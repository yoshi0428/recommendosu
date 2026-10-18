import logging
import time

import numpy as np
from tqdm import tqdm

from beatmap_recommender.content_similarity.core_modules.variant_table import (
    get_variant_table,
)

logger = logging.getLogger(__name__)

# Upper bound on seed x candidate distances held in memory per batch
# (float64, so 8_000_000 is about 64MB).
MAX_BATCH_DISTANCES = 8_000_000

SIMILARITY_FEATURES = [
    "star_rating",
    "bpm",
    "length_seconds",
    "object_count",
    "ar",
    "od",
    "circle_size",
    "pp_aim",
    "pp_speed",
    "pp_acc",
]


def _fetch_maps_as_numpy(conn, query, params=()):
    """Helper to fetch DB rows directly into NumPy arrays without DataFrame overhead."""
    cursor = conn.execute(query, params)
    rows = cursor.fetchall()

    if not rows:
        return np.array([], dtype=object), np.empty(
            (0, len(SIMILARITY_FEATURES)), dtype=np.float32
        )

    # Fast unpacking
    beatmap_ids = np.array([str(r[0]) for r in rows], dtype=object)

    # Extract feature matrix and replace None/nulls with 0.0 directly
    matrix_data = [[0.0 if val is None else val for val in r[1:]] for r in rows]
    matrix = np.array(matrix_data, dtype=np.float32)

    # Some loved gimmick maps store inf BPM; a single inf turns every
    # mean/std into NaN and wipes out all similarities.
    np.nan_to_num(matrix, copy=False, nan=0.0, posinf=0.0, neginf=0.0)

    return beatmap_ids, matrix


def get_player_seed_maps(conn, player_id):
    query = """
        SELECT DISTINCT
            bv.beatmap_id,
            COALESCE(bv.star_rating, 0.0),
            COALESCE(bv.bpm, 0.0),
            COALESCE(bv.length_seconds, 0.0),
            COALESCE(bv.object_count, 0.0),
            COALESCE(bv.ar, 0.0),
            COALESCE(bv.od, 0.0),
            COALESCE(bv.circle_size, 0.0),
            COALESCE(bv.pp_aim, 0.0),
            COALESCE(bv.pp_speed, 0.0),
            COALESCE(bv.pp_acc, 0.0)
        FROM scores AS s
        JOIN beatmap_variants AS bv
            ON bv.beatmap_id = s.beatmap_id
            AND bv.mods = 'NM'
        WHERE s.player_id = ?
    """
    return _fetch_maps_as_numpy(conn, query, (player_id,))


def get_maps(conn, mods="NM", player_id=None, status=None):
    """
    Every variant with these mods (and status), minus the beatmaps player_id
    has scores on, as (beatmap_ids, feature matrix) like get_player_seed_maps().

    Read from the in-memory variant table, in rowid order (the order a scan
    of beatmap_variants returns), instead of from SQLite on every request.
    """
    table = get_variant_table(conn)
    beatmap_categories = table.categories["beatmap_id"]

    mask = table.category_mask("mods", lambda value: value == mods)[table.columns["mods"]]

    if status is not None:
        mask &= table.category_mask("status", lambda value: value == status)[table.columns["status"]]

    if player_id is not None:
        played_beatmap_ids = [
            beatmap_id
            for (beatmap_id,) in conn.execute(
                "SELECT DISTINCT beatmap_id FROM scores WHERE player_id = ?",
                (player_id,),
            )
        ]
        played = np.zeros(len(beatmap_categories), dtype=bool)
        played[table.codes_of("beatmap_id", played_beatmap_ids)] = True
        mask &= ~played[table.columns["beatmap_id"]]

    rows = np.flatnonzero(mask)

    if len(rows) == 0:
        return np.array([], dtype=object), np.empty((0, len(SIMILARITY_FEATURES)), dtype=np.float32)

    beatmap_ids = np.array(beatmap_categories, dtype=object)[table.columns["beatmap_id"][rows]]

    # NULL is NaN in float_columns; COALESCE(..., 0.0) made it 0.0. Values
    # too large for float32 become inf, which is zeroed below.
    with np.errstate(over="ignore"):
        matrix = np.column_stack(
            [np.nan_to_num(table.float_columns[feature][rows], nan=0.0) for feature in SIMILARITY_FEATURES]
        ).astype(np.float32)

    # Some loved gimmick maps store inf BPM; a single inf turns every
    # mean/std into NaN and wipes out all similarities.
    np.nan_to_num(matrix, copy=False, nan=0.0, posinf=0.0, neginf=0.0)

    return beatmap_ids, matrix


def calculate_seed_similarity(
    seed_beatmap_ids,
    seed_matrix,
    candidate_beatmap_ids,
    candidate_matrix,
    top_k=50,
    batch_size=8192,
    similarity_feature_weights=None,
):
    """
    Find each seed's top_k nearest candidates and keep, per candidate,
    the best similarity to any seed.

    Returns:
        dict[str, float]: candidate beatmap_id -> best similarity, for
        every candidate that is within top_k of at least one seed.
    """
    if len(seed_beatmap_ids) == 0 or len(candidate_beatmap_ids) == 0:
        return {}

    means = candidate_matrix.mean(axis=0)
    stds = candidate_matrix.std(axis=0)
    stds[stds == 0] = 1.0

    seed_matrix = (seed_matrix - means) / stds
    candidate_matrix = (candidate_matrix - means) / stds

    if similarity_feature_weights:
        weights = np.asarray(
            [similarity_feature_weights[feature] for feature in SIMILARITY_FEATURES],
            dtype=np.float32,
        )
        seed_matrix *= weights
        candidate_matrix *= weights

    # float64 because the |s|^2 + |c|^2 - 2 s.c expansion loses precision
    # in float32 (sklearn upcasts for the same reason).
    seed_matrix = seed_matrix.astype(np.float64)
    candidate_matrix = candidate_matrix.astype(np.float64)

    n_candidates = len(candidate_beatmap_ids)
    query_k = min(top_k, n_candidates)

    # Cap each batch's seed x candidate distance matrix to bound memory.
    batch_size = max(1, min(batch_size, MAX_BATCH_DISTANCES // n_candidates))

    candidate_sq_norms = np.einsum("ij,ij->i", candidate_matrix, candidate_matrix)
    best_similarity = np.full(n_candidates, -1.0)
    n_seeds = len(seed_beatmap_ids)

    for start in tqdm(
        range(0, n_seeds, batch_size),
        desc="Calculating seed similarities",
        unit="batch",
        # Hidden when stderr isn't a terminal, e.g. in the server container.
        disable=None,
    ):
        batch_seeds = seed_matrix[start : start + batch_size]

        # Squared euclidean distance: |s|^2 + |c|^2 - 2 s.c
        distances = (
            np.einsum("ij,ij->i", batch_seeds, batch_seeds)[:, None]
            + candidate_sq_norms[None, :]
            - 2.0 * (batch_seeds @ candidate_matrix.T)
        )
        np.maximum(distances, 0.0, out=distances)

        if query_k < n_candidates:
            np.sqrt(distances, out=distances)
            indices = np.argpartition(distances, query_k - 1, axis=1)[:, :query_k]
            sim_scores = 1.0 / (1.0 + np.take_along_axis(distances, indices, axis=1))
            np.maximum.at(best_similarity, indices.ravel(), sim_scores.ravel())
        else:
            # sqrt preserves order, so the square root of the smallest squared
            # distance is the smallest distance, without a sqrt per pair.
            sim_scores = 1.0 / (1.0 + np.sqrt(distances.min(axis=0)))
            np.maximum(best_similarity, sim_scores, out=best_similarity)

    matched = best_similarity >= 0.0
    return dict(
        zip(
            candidate_beatmap_ids[matched].tolist(),
            best_similarity[matched].tolist(),
        )
    )


def build_seed_similarity_index(
    conn,
    player_id,
    top_k=50,
    batch_size=8192,
    similarity_feature_weights=None,
    exclude_already_played=True,
    status=None,
):
    start = time.perf_counter()
    seed_beatmap_ids, seed_matrix = get_player_seed_maps(conn, player_id)
    if len(seed_beatmap_ids) == 0:
        logger.info("Player %s: no NM seed maps found.", player_id)
        return {}

    logger.info(
        "Player %s: %s seed maps: %.4fs", player_id, f"{len(seed_beatmap_ids):,}", time.perf_counter() - start
    )

    start = time.perf_counter()

    # excludes already played beatmaps within your scores, if True
    if exclude_already_played:
        candidate_beatmap_ids, candidate_matrix = get_maps(
            conn, mods="NM", player_id=player_id, status=status
        )
    else:
        candidate_beatmap_ids, candidate_matrix = get_maps(
            conn, mods="NM", player_id=None, status=status
        )

    if len(candidate_beatmap_ids) == 0:
        logger.info("No unplayed NM candidate maps remain.")
        return {}

    logger.info(
        "NM candidate pool (%s): %s maps: %.4fs",
        status or "all",
        f"{len(candidate_beatmap_ids):,}",
        time.perf_counter() - start,
    )

    start = time.perf_counter()
    similarity_index = calculate_seed_similarity(
        seed_beatmap_ids=seed_beatmap_ids,
        seed_matrix=seed_matrix,
        candidate_beatmap_ids=candidate_beatmap_ids,
        candidate_matrix=candidate_matrix,
        top_k=top_k,
        batch_size=batch_size,
        similarity_feature_weights=similarity_feature_weights,
    )

    logger.info("Seed similarity: %.4fs (%s matched)", time.perf_counter() - start, f"{len(similarity_index):,}")
    return similarity_index
