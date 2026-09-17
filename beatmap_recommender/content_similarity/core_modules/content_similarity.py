import numpy as np
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
    A player may have played a map with HD, DT, HR, etc.
    We still use that map as a content seed, but similarity is calculated using the map's NM stats.

    Returns:
        List[dict]
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

    columns = [
        "beatmap_id",
        "star_rating",
        "bpm",
        "length_seconds",
        "object_count",
        "ar",
        "od",
        "circle_size",
    ]

    return [dict(zip(columns, row)) for row in rows]


def get_maps(conn, mods="NM"):
    """
    Load beatmaps from the database using a specific mod variant.
    For the current content-based recommender, this is normally called with mods="NM".

    Returns:
        List[dict]
    """

    rows = conn.execute("""
        SELECT
            beatmap_id,
            star_rating,
            bpm,
            length_seconds,
            object_count,
            ar,
            od,
            circle_size
        FROM beatmap_variants
        WHERE mods = ?
    """, (mods,)).fetchall()

    columns = [
        "beatmap_id",
        "star_rating",
        "bpm",
        "length_seconds",
        "object_count",
        "ar",
        "od",
        "circle_size",
    ]

    return [dict(zip(columns, row)) for row in rows]


def build_feature_matrix(maps):
    """
    Build a NumPy feature matrix from base beatmaps.

    Args:
        maps:
            List of beatmap dictionaries.

    Returns:
        beatmap_ids:
            List of base beatmap IDs.

        matrix:
            NumPy array with shape
            (n_maps, n_features).
    """

    if not maps:
        return [], np.empty((0, len(FEATURES)), dtype=np.float32)

    beatmap_ids = [beatmap["beatmap_id"] for beatmap in maps]

    matrix = np.array(
        [
            [
                float(beatmap[feature])
                if beatmap[feature] is not None
                else 0.0
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
    Calculate top-K content similarity for the player's seed beatmaps against all candidate beatmaps.
    Both seed and candidate maps should normally be represented using their NM variants.

    Similarity is based on weighted Euclidean distance after z-score standardization using the candidate distribution.
    Similarity is calculated as:
        similarity = 1 / (1 + distance)

    The seed's own base beatmap is excluded from its results.

    Returns:
        {
            seed_beatmap_id: [
                (candidate_beatmap_id, similarity),
                ...
            ]
        }
    """
    if not seed_maps or not candidate_maps:
        return {}

    # ---------------------------------------------------------
    # Build feature matrices.
    # ---------------------------------------------------------
    seed_beatmap_ids, seed_matrix = build_feature_matrix(seed_maps)
    candidate_beatmap_ids, candidate_matrix = build_feature_matrix(candidate_maps)

    if len(seed_beatmap_ids) == 0:
        return {}

    if len(candidate_beatmap_ids) == 0:
        return {}

    # ---------------------------------------------------------
    # Standardize using the candidate distribution.
    #
    # This keeps the feature scale consistent between the
    # seed maps and the candidate pool.
    # ---------------------------------------------------------
    means = candidate_matrix.mean(axis=0)
    stds = candidate_matrix.std(axis=0)

    # Avoid division by zero for constant features.
    stds[stds == 0] = 1.0

    seed_matrix = (seed_matrix - means) / stds
    candidate_matrix = (candidate_matrix - means) / stds

    # ---------------------------------------------------------
    # Apply feature weights.
    # ---------------------------------------------------------
    weights = np.array(
        [feature_weights[feature] for feature in FEATURES],
        dtype=np.float32,
    )

    seed_matrix *= weights
    candidate_matrix *= weights

    # ---------------------------------------------------------
    # Determine how many candidates to keep.
    #
    # We need at least one candidate to exclude the seed
    # itself, hence n_candidates - 1.
    # ---------------------------------------------------------
    n_candidates = len(candidate_beatmap_ids)
    k = min(top_k, n_candidates - 1,)
    if k <= 0:
        return {}

    # ---------------------------------------------------------
    # Precompute values used by the Euclidean distance.
    # ||a - b||² = ||a||² + ||b||² - 2(a · b)
    # ---------------------------------------------------------
    candidate_squared_norms = np.sum(candidate_matrix ** 2, axis=1,)
    candidate_beatmap_ids_array = np.asarray(candidate_beatmap_ids)
    similarities = {}

    # ---------------------------------------------------------
    # Process seed maps in batches to avoid constructing
    # one enormous seed × candidate matrix.
    # ---------------------------------------------------------

    for start in tqdm(
        range(0, len(seed_beatmap_ids), batch_size,),
        desc="Calculating seed similarities",
        unit="batch",
    ):
        end = min(start + batch_size, len(seed_beatmap_ids),)
        seed_batch = seed_matrix[start:end]

        # -----------------------------------------------------
        # ||seed||²
        # -----------------------------------------------------
        seed_squared_norms = np.sum(seed_batch ** 2, axis=1, keepdims=True,)

        # -----------------------------------------------------
        # seed · candidate
        # -----------------------------------------------------
        dot_products = (seed_batch @ candidate_matrix.T)

        # -----------------------------------------------------
        # Squared Euclidean distance.
        # -----------------------------------------------------
        distance_squared = (seed_squared_norms + candidate_squared_norms[None, :] - 2.0 * dot_products)

        # Floating-point errors can produce tiny negative
        # values such as -1e-7.
        distance_squared = np.maximum(distance_squared, 0.0,)
        distances = np.sqrt(distance_squared)

        # -----------------------------------------------------
        # Convert distance into similarity.
        # -----------------------------------------------------
        similarity_batch = 1.0 / (1.0 + distances)

        # -----------------------------------------------------
        # Process each seed in this batch.
        # -----------------------------------------------------
        for local_i in range(end - start):

            global_i = start + local_i
            row = similarity_batch[local_i]
            seed_beatmap_id = seed_beatmap_ids[global_i]

            # -------------------------------------------------
            # Do not recommend the seed's own base beatmap.
            #
            # Since the candidate pool may contain only one
            # NM variant per base beatmap, this removes the
            # played map regardless of which mod the player
            # originally used.
            # -------------------------------------------------

            matching_indices = np.flatnonzero(candidate_beatmap_ids_array == seed_beatmap_id)
            if len(matching_indices) > 0:
                row[matching_indices] = -np.inf

            # -------------------------------------------------
            # Get top-K candidates.
            # -------------------------------------------------
            top_indices = np.argpartition(row, -k,)[-k:]

            # Sort those K candidates by similarity.
            top_indices = top_indices[
                np.argsort(row[top_indices])[::-1]
            ]

            similarities[seed_beatmap_id] = [
                (candidate_beatmap_ids[j], float(row[j]),)
                for j in top_indices
                if np.isfinite(row[j])
            ]

    return similarities


def build_seed_similarity_index(
    conn,
    player_id,
    top_k=50,
    batch_size=1024,
    feature_weights=None,
):
    """
    Build a content-similarity index using the player's played base beatmaps as seeds.
    All seeds and candidates are represented by their NM variants.

    Returns:
        {
            seed_beatmap_id: [
                (candidate_beatmap_id, similarity),
                ...
            ]
        }
    """

    # ---------------------------------------------------------
    # Get the player's played maps.
    #
    # Each distinct base beatmap is resolved to its NM variant
    # for content similarity.
    # ---------------------------------------------------------

    seed_maps = get_player_seed_maps(conn, player_id,)

    if not seed_maps:
        print(f"Player {player_id}: no NM seed maps found.")
        return {}

    print(f"Player {player_id}: {len(seed_maps):,} seed maps.")

    # ---------------------------------------------------------
    # Load the entire NM candidate pool.
    # ---------------------------------------------------------
    candidate_maps = get_maps(conn, mods="NM",)

    if len(candidate_maps) < 2:
        print("Not enough NM candidate maps to calculate similarity.")
        return {}

    print(f"NM candidate pool: {len(candidate_maps):,} maps.")

    # ---------------------------------------------------------
    # Calculate similarities.
    # ---------------------------------------------------------

    similarity_index = calculate_seed_similarity(
        seed_maps=seed_maps,
        candidate_maps=candidate_maps,
        top_k=top_k,
        batch_size=batch_size,
        feature_weights=feature_weights,
    )

    return similarity_index