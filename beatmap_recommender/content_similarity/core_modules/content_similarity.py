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

# Canonical order used when converting API mod lists into the concatenated representation used by the DB.
MOD_ORDER = [
    "EZ",
    "NF",
    "HT",
    "HD",
    "HR",
    "DT",
    "NC",
    "FL",
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
    if not maps:
        return [], np.empty((0, len(FEATURES)), dtype=np.float32)

    beatmap_ids = []

    for i, beatmap in enumerate(maps):
        beatmap_id = beatmap.get("beatmap_id")

        if beatmap_id is None:
            raise ValueError(
                f"Beatmap at index {i} has no beatmap_id: {beatmap}"
            )

        for feature in FEATURES:
            value = beatmap.get(feature)

            if value is not None:
                try:
                    float(value)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"Invalid numeric feature for beatmap "
                        f"{beatmap_id}: {feature}={value!r}"
                    )

        beatmap_ids.append(str(beatmap_id))

    matrix = np.array(
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
    batch_size=1024,
    feature_weights=None,
):
    """
    Calculate top-K content similarity for player seed maps against the candidate pool.
    Similarity is based on weighted Euclidean distance after z-score standardization using the candidate distribution.

    similarity = 1 / (1 + distance)

    A cKDTree is used because the resulting metric is ordinary Euclidean distance after feature weighting.
    The seed's own base beatmap is excluded.
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

    stds[stds == 0] = 1.0

    seed_matrix = (
            (seed_matrix - means) / stds
    ).astype(np.float32)

    candidate_matrix = (
        (candidate_matrix - means) / stds
    ).astype(np.float32)

    # ---------------------------------------------------------
    # Apply feature weights.
    #
    # Weighted Euclidean distance:
    #
    # sqrt(sum((x_i - y_i)^2 * weight_i^2))
    #
    # Multiplying each feature by its weight converts this
    # into ordinary Euclidean distance.
    # ---------------------------------------------------------
    weights = np.array(
        [
            feature_weights[feature]
            for feature in FEATURES
        ],
        dtype=np.float32,
    )

    seed_matrix *= weights
    candidate_matrix *= weights

    # ---------------------------------------------------------
    # Number of neighbors.
    #
    # Query one extra neighbor because the seed itself may be
    # present in the candidate pool.
    # ---------------------------------------------------------
    n_candidates = len(candidate_beatmap_ids)
    if n_candidates < 2:
        return {}

    query_k = min(top_k + 1, n_candidates)

    # ---------------------------------------------------------
    # Build nearest-neighbor index.
    # ---------------------------------------------------------
    tree = KDTree(candidate_matrix)
    candidate_beatmap_ids_array = np.asarray(candidate_beatmap_ids, dtype=object)

    # Map beatmap ID -> candidate index.
    #
    # This avoids doing:
    #
    #     np.flatnonzero(candidate_ids == seed_id)
    #
    # for every seed.
    # ---------------------------------------------------------
    candidate_index_by_id = {
        str(beatmap_id): index
        for index, beatmap_id
        in enumerate(candidate_beatmap_ids)
    }

    similarities = {}

    # ---------------------------------------------------------
    # Query seeds in batches.
    # ---------------------------------------------------------
    for start in tqdm(
        range(0, len(seed_beatmap_ids), batch_size),
        desc="Calculating seed similarities",
        unit="batch",
    ):
        end = min(start + batch_size, len(seed_beatmap_ids))
        seed_batch = seed_matrix[start:end]

        # -----------------------------------------------------
        # Find nearest candidates.
        #
        # distances:
        #     shape = (batch_size, query_k)
        #
        # indices:
        #     shape = (batch_size, query_k)
        # -----------------------------------------------------

        distances, indices = tree.query(seed_batch, k=query_k)

        # cKDTree returns 1D arrays when k=1.
        # Our query_k should normally be >1, but keeping this
        # robust costs almost nothing.
        if query_k == 1:
            distances = distances[:, None]
            indices = indices[:, None]

        # -----------------------------------------------------
        # Process each seed.
        # -----------------------------------------------------

        for local_i in range(end - start):

            global_i = start + local_i

            seed_beatmap_id = str(seed_beatmap_ids[global_i])

            candidate_indices = indices[local_i]
            candidate_distances = distances[local_i]

            results = []

            own_candidate_index = (candidate_index_by_id.get(seed_beatmap_id))

            for candidate_index, distance in zip(candidate_indices, candidate_distances):
                candidate_index = int(candidate_index)

                if own_candidate_index is not None and candidate_index == own_candidate_index:
                    continue

                if not np.isfinite(distance):
                    continue

                similarity = 1.0 / (1.0 + float(distance))

                results.append(
                    (candidate_beatmap_ids_array[candidate_index], similarity)
                )

                if len(results) >= top_k:
                    break

            if results:
                similarities[seed_beatmap_ids[global_i]] = results

    return similarities

def build_seed_similarity_index(
    conn,
    player_id,
    top_k=50,
    batch_size=1024,
    feature_weights=None,
):
    seed_maps = get_player_seed_maps(conn, player_id)

    if not seed_maps:
        print(f"Player {player_id}: no NM seed maps found.")
        return {}

    print(f"Player {player_id}: {len(seed_maps):,} seed maps.")

    candidate_maps = get_maps(conn, mods="NM", player_id=player_id)
    if len(candidate_maps) < 1:
        print("No unplayed NM candidate maps remain.")
        return {}

    print(f"NM candidate pool: {len(candidate_maps):,} maps.")

    return calculate_seed_similarity(
        seed_maps=seed_maps,
        candidate_maps=candidate_maps,
        top_k=top_k,
        batch_size=batch_size,
        feature_weights=feature_weights,
    )