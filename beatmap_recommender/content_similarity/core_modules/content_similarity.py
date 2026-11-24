import logging
import time

import numpy as np
from tqdm import tqdm

from beatmap_recommender.content_similarity.core_modules.played_maps import get_played_beatmap_ids
from beatmap_recommender.content_similarity.core_modules.variant_table import get_variant_table

logger = logging.getLogger(__name__)

# The maximum number of seed x candidate distances in memory for each batch.
# The values are float64, so 8_000_000 is about 64MB.
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


def _no_maps():
    """The (beatmap_ids, feature matrix) pair for zero maps."""
    return np.array([], dtype=object), np.empty((0, len(SIMILARITY_FEATURES)), dtype=np.float32)


def _clean_features(matrix):
    """
    Change NaN and inf to 0.0, in place. Some loved gimmick maps store an inf
    BPM. One inf makes every mean and std NaN, and then all similarities fail.
    """
    np.nan_to_num(matrix, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    return matrix


def get_player_seed_maps(conn, player_id):
    """
    Return (beatmap_ids, feature matrix) for the NM variants of the maps that
    the player has scores on. These maps are the seeds of the similarity search.
    """
    rows = conn.execute(
        """
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
          -- A failed play (rank F) does not show what the player can do.
          -- It still counts as played.
          AND COALESCE(s.rank, '') != 'F'
        """,
        (player_id,),
    ).fetchall()

    if not rows:
        return _no_maps()

    beatmap_ids = np.array([str(row[0]) for row in rows], dtype=object)
    # The query changes NULL to 0.0 with COALESCE, so each value is a number.
    matrix = np.array([row[1:] for row in rows], dtype=np.float32)
    return beatmap_ids, _clean_features(matrix)


def get_maps(conn, mods="NM", player_id=None, status=None):
    """
    Return all the variants with these mods (and this status), without the
    beatmaps that player_id played (played_maps.get_played_beatmap_ids()).
    The result is (beatmap_ids, feature matrix), as in get_player_seed_maps().

    The data comes from the variant table in memory, not from SQLite on each
    request. The order is the rowid order, which is the order of a scan of
    beatmap_variants.
    """
    table = get_variant_table(conn)
    beatmap_categories = table.categories["beatmap_id"]

    mask = table.category_mask("mods", lambda value: value == mods)[table.columns["mods"]]

    if status is not None:
        mask &= table.category_mask("status", lambda value: value == status)[table.columns["status"]]

    if player_id is not None:
        played_beatmap_ids = list(get_played_beatmap_ids(conn, player_id))
        played = np.zeros(len(beatmap_categories), dtype=bool)
        played[table.codes_of("beatmap_id", played_beatmap_ids)] = True
        mask &= ~played[table.columns["beatmap_id"]]

    rows = np.flatnonzero(mask)

    if len(rows) == 0:
        return _no_maps()

    beatmap_ids = np.array(beatmap_categories, dtype=object)[table.columns["beatmap_id"][rows]]

    # In float_columns, NULL is NaN. A value too large for float32 becomes inf.
    # _clean_features() changes both to 0.0, the same as COALESCE(..., 0.0).
    with np.errstate(over="ignore"):
        matrix = np.column_stack([table.float_columns[feature][rows] for feature in SIMILARITY_FEATURES]).astype(
            np.float32
        )

    return beatmap_ids, _clean_features(matrix)


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
    Find the top_k nearest candidates of each seed. For each candidate, keep
    the best similarity to any seed.

    Returns:
        dict[str, float]: candidate beatmap_id -> best similarity, for each
        candidate that is in the top_k of one or more seeds.
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

    # Use float64, because the |s|^2 + |c|^2 - 2 s.c expansion loses precision
    # in float32. sklearn changes to float64 for the same reason.
    seed_matrix = seed_matrix.astype(np.float64)
    candidate_matrix = candidate_matrix.astype(np.float64)

    n_candidates = len(candidate_beatmap_ids)
    query_k = min(top_k, n_candidates)

    # Limit the size of the seed x candidate distance matrix of each batch, to limit memory.
    batch_size = max(1, min(batch_size, MAX_BATCH_DISTANCES // n_candidates))

    candidate_sq_norms = np.einsum("ij,ij->i", candidate_matrix, candidate_matrix)
    best_similarity = np.full(n_candidates, -1.0)
    n_seeds = len(seed_beatmap_ids)

    for start in tqdm(
        range(0, n_seeds, batch_size),
        desc="Calculating seed similarities",
        unit="batch",
        # The bar does not show when stderr is not a terminal, for example in the server container.
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
            # sqrt keeps the order. Thus the square root of the smallest squared
            # distance is the smallest distance, without a sqrt for each pair.
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

    # With player_id, get_maps() leaves out the beatmaps that the player played.
    candidate_beatmap_ids, candidate_matrix = get_maps(
        conn, mods="NM", player_id=player_id if exclude_already_played else None, status=status
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
