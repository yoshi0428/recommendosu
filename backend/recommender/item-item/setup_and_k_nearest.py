import numpy as np
from sklearn.preprocessing import RobustScaler
from sklearn.neighbors import NearestNeighbors

FEATURE_COLUMNS = [
    "star_rating",
    "aim_difficulty",
    "speed_difficulty",
    "flashlight_difficulty",
    "ar",
    "cs",
    "od",
    "hp",
    "bpm",
    "bpm_min",
    "bpm_max",
    "effective_bpm",
    "length",
    "object_count",
    "objects_per_second",
    "circle_ratio",
    "slider_ratio",
    "spinner_ratio",
    "delta_mean",
    "delta_median",
    "delta_std",
    "delta_p25",
    "delta_p75",
    "delta_min",
    "delta_max",
    "spacing_mean",
    "spacing_median",
    "spacing_std",
    "spacing_p25",
    "spacing_p75",
    "spacing_max",
    "movement_speed_mean",
    "movement_speed_median",
    "movement_speed_std",
    "movement_speed_p75",
    "rhythm_ratio_mean",
    "rhythm_ratio_std",
    "rhythm_ratio_p25",
    "rhythm_ratio_p75",
]

def load_feature_matrix(conn):
    query = f"""
        SELECT
            variant_id,
            {",".join(FEATURE_COLUMNS)}
        FROM variant_features
        ORDER BY variant_id
    """

    rows = conn.execute(query).fetchall()

    if not rows:
        return [], np.empty((0, len(FEATURE_COLUMNS)), dtype=np.float32)

    variant_ids = [row[0] for row in rows]
    X = np.asarray([row[1:] for row in rows], dtype=np.float32)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    return variant_ids, X


def scale_features(X):
    """
    RobustScaler prevents large-scale features such as
    object_count and length from dominating cosine similarity.
    """
    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(X)
    X_scaled = np.nan_to_num(X_scaled, nan=0.0, posinf=0.0, neginf=0.0)

    return X_scaled, scaler


def build_neighbors(
    conn,
    variant_ids,
    X_scaled,
    k=50
):
    """
    Calculate nearest neighbors for every variant.
    """

    if len(variant_ids) <= 1:
        print("Not enough variants to build neighbors.")
        return

    k = min(k, len(variant_ids) - 1)
    print(f"Building {k} neighbors for {len(variant_ids):,} variants...")

    # --------------------------------------------------------
    # Cosine nearest neighbors
    # --------------------------------------------------------

    nn = NearestNeighbors(
        n_neighbors=k + 1,
        metric="cosine",
        algorithm="brute",
        n_jobs=-1
    )

    nn.fit(X_scaled)
    distances, indices = nn.kneighbors(X_scaled)

    cursor = conn.cursor()
    cursor.execute("DELETE FROM variant_neighbors")

    batch = []

    for i, variant_id in enumerate(variant_ids):

        # index 0 is the map itself.
        for rank in range(
            1,
            k + 1
        ):

            neighbor_index = indices[
                i
            ][rank]

            distance = distances[
                i
            ][rank]

            neighbor_id = variant_ids[
                neighbor_index
            ]

            similarity = (
                1.0 -
                float(distance)
            )

            batch.append((
                variant_id,
                neighbor_id,
                similarity,
                rank
            ))

        if len(batch) >= 10_000:

            cursor.executemany(
                """
                INSERT OR REPLACE INTO
                variant_neighbors
                (
                    variant_id,
                    neighbor_variant_id,
                    similarity,
                    rank
                )
                VALUES (?, ?, ?, ?)
                """,
                batch
            )

            conn.commit()

            batch.clear()

    if batch:

        cursor.executemany(
            """
            INSERT OR REPLACE INTO
            variant_neighbors
            (
                variant_id,
                neighbor_variant_id,
                similarity,
                rank
            )
            VALUES (?, ?, ?, ?)
            """,
            batch
        )

    conn.commit()

    print(
        "Neighbor table complete."
    )
