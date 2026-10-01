import numpy as np
import polars as pl
from sklearn.neighbors import NearestNeighbors
from tqdm import tqdm

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


def get_player_seed_maps(conn, player_id):
    """
    Fetch seed maps directly into a Polars DataFrame and extract zero-copy
    NumPy arrays for beatmap IDs and feature matrices.
    """
    query = """
        SELECT DISTINCT
            bv.beatmap_id,
            bv.star_rating, bv.bpm, bv.length_seconds, bv.object_count,
            bv.ar, bv.od, bv.circle_size, bv.pp_aim, bv.pp_acc, bv.pp_speed
        FROM scores AS s
        JOIN beatmap_variants AS bv
            ON bv.beatmap_id = s.beatmap_id
            AND bv.mods = 'NM'
        WHERE s.player_id = ?
    """
    df = pl.read_database(query=query, connection=conn, execute_options={"parameters": [player_id]})

    if df.is_empty():
        return np.array([], dtype=object), np.empty((0, len(SIMILARITY_FEATURES)), dtype=np.float32)

    beatmap_ids = df["beatmap_id"].cast(pl.Utf8).to_numpy()

    # Fill nulls with 0.0 and convert feature columns directly to a contiguous float32 C-array
    matrix = (
        df.select(SIMILARITY_FEATURES)
        .fill_null(0.0)
        .to_numpy()
        .astype(np.float32, copy=False)
    )

    return beatmap_ids, matrix


def get_maps(conn, mods="NM", player_id=None):
    """
    Fetch candidate map pool directly into a Polars DataFrame.
    """
    query = """
        SELECT
            bv.beatmap_id,
            bv.star_rating, bv.bpm, bv.length_seconds, bv.object_count,
            bv.ar, bv.od, bv.circle_size, bv.pp_aim, bv.pp_acc, bv.pp_speed
        FROM beatmap_variants AS bv
        WHERE bv.mods = ?
    """
    params = [mods]

    if player_id is not None:
        query += """
            AND NOT EXISTS (
                SELECT 1
                FROM scores AS s
                WHERE s.player_id = ?
                  AND s.beatmap_id = bv.beatmap_id
            )
        """
        params.append(player_id)

    df = pl.read_database(query=query, connection=conn, execute_options={"parameters": params})

    if df.is_empty():
        return np.array([], dtype=object), np.empty((0, len(SIMILARITY_FEATURES)), dtype=np.float32)

    beatmap_ids = df["beatmap_id"].cast(pl.Utf8).to_numpy()

    matrix = (
        df.select(SIMILARITY_FEATURES)
        .fill_null(0.0)
        .to_numpy()
        .astype(np.float32, copy=False)
    )

    return beatmap_ids, matrix


def calculate_seed_similarity(
        seed_beatmap_ids,
        seed_matrix,
        candidate_beatmap_ids,
        candidate_matrix,
        top_k=50,
        batch_size=8192,
        similarity_feature_weights=None,
        n_jobs=-1,
):
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

    n_candidates = len(candidate_beatmap_ids)
    query_k = min(top_k, n_candidates)

    nn = NearestNeighbors(n_neighbors=query_k, algorithm="brute", metric="euclidean", n_jobs=n_jobs)
    nn.fit(candidate_matrix)

    similarities = {}
    n_seeds = len(seed_beatmap_ids)

    for start in tqdm(
            range(0, n_seeds, batch_size),
            desc="Calculating seed similarities",
            unit="batch",
    ):
        end = min(start + batch_size, n_seeds)
        batch_seeds = seed_matrix[start:end]

        distances, indices = nn.kneighbors(batch_seeds)

        # Vectorized conversion: similarity = 1 / (1 + distance)
        sim_scores = 1.0 / (1.0 + distances)
        matched_ids = candidate_beatmap_ids[indices]

        for local_i in range(end - start):
            global_i = start + local_i
            seed_id = seed_beatmap_ids[global_i]
            similarities[seed_id] = list(zip(matched_ids[local_i], sim_scores[local_i]))

    return similarities


def build_seed_similarity_index(
        conn,
        player_id,
        top_k=50,
        batch_size=8192,
        similarity_feature_weights=None,
        workers=-1,
        exclude_already_played=True,
):
    seed_beatmap_ids, seed_matrix = get_player_seed_maps(conn, player_id)
    if len(seed_beatmap_ids) == 0:
        print(f"Player {player_id}: no NM seed maps found.")
        return {}

    print(f"Player {player_id}: {len(seed_beatmap_ids):,} seed maps.")

    # excludes already played beatmaps within your scores, if True
    if exclude_already_played:
        candidate_beatmap_ids, candidate_matrix = get_maps(conn, mods="NM", player_id=player_id)
    else:
        candidate_beatmap_ids, candidate_matrix = get_maps(conn, mods="NM", player_id=None)

    if len(candidate_beatmap_ids) == 0:
        print("No unplayed NM candidate maps remain.")
        return {}

    print(f"\nNM candidate pool: {len(candidate_beatmap_ids):,} maps.\n")

    return calculate_seed_similarity(
        seed_beatmap_ids=seed_beatmap_ids,
        seed_matrix=seed_matrix,
        candidate_beatmap_ids=candidate_beatmap_ids,
        candidate_matrix=candidate_matrix,
        top_k=top_k,
        batch_size=batch_size,
        similarity_feature_weights=similarity_feature_weights,
        n_jobs=workers,
    )