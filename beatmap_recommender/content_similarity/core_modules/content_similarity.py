import numpy as np
from scipy.spatial import KDTree
from tqdm import tqdm

FEATURES = [
    "star_rating",
    "bpm",
    "length_seconds",
    "object_count",
    "ar",
    "od",
    "circle_size",
]

MAP_COLUMNS = [
    "beatmap_id",
    *FEATURES,
]


def get_player_seed_maps(conn, player_id):
    """
    Get the player's played base beatmaps and resolve them to their NM variants.
    """

    rows = conn.execute("""
        SELECT DISTINCT
            bv.beatmap_id,
            bv.star_rating,
            bv.bpm,
            bv.length_seconds,
            bv.object_count,
            bv.ar,
            bv.od,
            bv.circle_size
        FROM scores AS s
        JOIN beatmap_variants AS bv
            ON bv.beatmap_id = s.beatmap_id
            AND bv.mods = 'NM'
        WHERE s.player_id = ?
    """, (player_id,)).fetchall()

    return [dict(zip(MAP_COLUMNS, row)) for row in rows]

def get_maps(conn, mods="NM", player_id=None):
    params = [mods]

    query = """
        SELECT
            bv.beatmap_id,
            bv.star_rating,
            bv.bpm,
            bv.length_seconds,
            bv.object_count,
            bv.ar,
            bv.od,
            bv.circle_size
        FROM beatmap_variants AS bv
        WHERE bv.mods = ?
    """

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

    rows = conn.execute(query, params).fetchall()

    return [dict(zip(MAP_COLUMNS, row))for row in rows]

def build_feature_matrix(maps):
    """
    Convert beatmap dictionaries into:

        beatmap_ids
        float32 feature matrix

    Missing numeric values are represented as 0.0.
    """

    if not maps:
        return [], np.empty((0, len(FEATURES)), dtype=np.float32)

    beatmap_ids = [str(beatmap["beatmap_id"])for beatmap in maps]
    matrix = np.asarray(
        [
            [
                float(beatmap[feature])
                if beatmap[feature] is not None else 0.0
                for feature in FEATURES
            ]
            for beatmap in maps
        ],
        dtype=np.float32,
    )

    return beatmap_ids, matrix

def calculate_seed_similarity(
    seed_maps,
    candidate_maps,
    top_k=50,
    batch_size=8192,
    feature_weights=None,
    workers=-1,
):
    """
    Calculate top-K content similarity for player seed maps
    against the candidate pool.

    Similarity is based on weighted Euclidean distance after
    z-score standardization using the candidate distribution.

        similarity = 1 / (1 + distance)

    KDTree is used because feature weighting converts the
    weighted Euclidean metric into ordinary Euclidean distance.

    The candidate pool is expected to already exclude maps
    played by the player, so seed maps cannot occur in the
    candidate results.
    """

    if not seed_maps or not candidate_maps:
        return {}

    # ---------------------------------------------------------
    # Build feature matrices.
    # ---------------------------------------------------------
    seed_beatmap_ids, seed_matrix = build_feature_matrix(seed_maps)
    candidate_beatmap_ids, candidate_matrix = build_feature_matrix(candidate_maps)
    if not seed_beatmap_ids or not candidate_beatmap_ids:
        return {}

    # ---------------------------------------------------------
    # Standardize using candidate distribution.
    # ---------------------------------------------------------
    means = candidate_matrix.mean(axis=0)
    stds = candidate_matrix.std(axis=0)

    # Avoid division by zero for constant features.
    stds[stds == 0] = 1.0

    seed_matrix = ((seed_matrix - means) / stds).astype(np.float32, copy=False)
    candidate_matrix = ((candidate_matrix - means) / stds).astype(np.float32, copy=False)

    # ---------------------------------------------------------
    # Apply feature weights.
    #
    # Weighted Euclidean distance:
    #
    # sqrt(sum((x_i - y_i)^2 * weight_i^2))
    #
    # Scaling each feature by its weight turns this into ordinary Euclidean distance.
    # ---------------------------------------------------------
    weights = np.asarray(
        [feature_weights[feature] for feature in FEATURES],
        dtype=np.float32,
    )

    seed_matrix *= weights
    candidate_matrix *= weights

    # ---------------------------------------------------------
    # Number of neighbors.
    #
    # The candidate pool already excludes the player's played
    # maps, so the seed itself cannot appear here.
    # ---------------------------------------------------------
    n_candidates = len(candidate_beatmap_ids)
    if n_candidates == 0:
        return {}

    query_k = min(top_k, n_candidates)

    # ---------------------------------------------------------
    # Build nearest-neighbor index.
    # ---------------------------------------------------------
    tree = KDTree(candidate_matrix)
    candidate_beatmap_ids_array = np.asarray(candidate_beatmap_ids, dtype=object)

    # ---------------------------------------------------------
    # Query seeds in batches.
    # ---------------------------------------------------------
    similarities = {}
    for start in tqdm(
        range(0, len(seed_beatmap_ids), batch_size),
        desc="Calculating seed similarities",
        unit="batch",
    ):
        end = min(start + batch_size, len(seed_beatmap_ids))
        seed_batch = seed_matrix[start:end]
        distances, indices = tree.query(seed_batch, k=query_k, workers=workers)

        # cKDTree/KDTree returns 1D arrays when k == 1.
        if query_k == 1:
            distances = distances[:, None]
            indices = indices[:, None]

        # -----------------------------------------------------
        # Convert nearest-neighbor results into similarities.
        # -----------------------------------------------------
        for local_i in range(end - start):
            global_i = start + local_i
            seed_beatmap_id = seed_beatmap_ids[global_i]

            candidate_indices = indices[local_i]
            candidate_distances = distances[local_i]

            results = []

            for candidate_index, distance in zip(candidate_indices, candidate_distances):
                if not np.isfinite(distance):
                    continue

                candidate_index = int(candidate_index)
                similarity = 1.0 / (1.0 + float(distance))

                results.append(
                    (candidate_beatmap_ids_array[candidate_index], similarity)
                )

            if results:
                similarities[seed_beatmap_id] = results

    return similarities


def build_seed_similarity_index(
    conn,
    player_id,
    top_k=50,
    batch_size=8192,
    feature_weights=None,
    workers=-1,
    already_played=True,
):
    seed_maps = get_player_seed_maps(conn, player_id)
    if not seed_maps:
        print(f"Player {player_id}: no NM seed maps found.")
        return {}

    print(f"Player {player_id}: {len(seed_maps):,} seed maps.")

    # excludes already played beatmaps within your scores, if True
    if already_played:
        candidate_maps = get_maps(conn, mods="NM", player_id=player_id)
    else:
        candidate_maps = get_maps(conn, mods="NM", player_id=None)

    if not candidate_maps:
        print("No unplayed NM candidate maps remain.")
        return {}

    print(f"\nNM candidate pool: {len(candidate_maps):,} maps.\n")

    return calculate_seed_similarity(
        seed_maps=seed_maps,
        candidate_maps=candidate_maps,
        top_k=top_k,
        batch_size=batch_size,
        feature_weights=feature_weights,
        workers=workers,
    )