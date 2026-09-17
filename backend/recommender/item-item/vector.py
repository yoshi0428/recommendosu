from utils import safe_stats
import numpy as np

def extract_vector_features(
    vectors,
    clock_rate=1.0
):
    """
    Extract fixed-length recommender features from hit-object
    vectors.

    Expected vector format:

        (
            x_diff,
            y_diff,
            time_diff,
            slider_length
        )

    IMPORTANT:

    time_diff should ideally be the original millisecond
    difference between objects.

    If your current beatmap_vectors stores normalized time_diff,
    modify this function/parser so the recommender receives
    the original timing information.
    """

    if not vectors:
        return {}

    vectors = np.asarray(
        vectors,
        dtype=np.float32
    )

    if vectors.ndim != 2 or vectors.shape[1] < 3:
        return {}

    x_diff = vectors[:, 0]
    y_diff = vectors[:, 1]

    raw_delta = vectors[:, 2].copy()

    # --------------------------------------------------------
    # Apply clock-rate transformation
    # --------------------------------------------------------

    if clock_rate != 1.0:
        raw_delta /= clock_rate

    # Prevent invalid values.
    raw_delta = np.nan_to_num(
        raw_delta,
        nan=0.0,
        posinf=0.0,
        neginf=0.0
    )

    # --------------------------------------------------------
    # Timing statistics
    # --------------------------------------------------------

    delta_stats = safe_stats(
        raw_delta
    )

    # --------------------------------------------------------
    # Cursor movement distance
    # --------------------------------------------------------

    spacing = np.sqrt(
        x_diff ** 2 +
        y_diff ** 2
    )

    spacing = np.nan_to_num(
        spacing,
        nan=0.0,
        posinf=0.0,
        neginf=0.0
    )

    spacing_stats = safe_stats(
        spacing
    )

    # --------------------------------------------------------
    # Movement speed
    #
    # distance / milliseconds
    # --------------------------------------------------------

    valid = raw_delta > 0

    if np.any(valid):
        movement_speed = (
            spacing[valid] /
            raw_delta[valid]
        )
    else:
        movement_speed = np.array(
            [],
            dtype=np.float32
        )

    movement_speed_stats = safe_stats(
        movement_speed
    )

    # --------------------------------------------------------
    # Rhythm ratios
    #
    # For consecutive timing intervals:
    #
    # 100ms / 200ms -> 2.0
    # 200ms / 100ms -> 2.0
    #
    # Using the larger/smaller ratio makes it symmetric.
    # --------------------------------------------------------

    if len(raw_delta) >= 3:

        d1 = raw_delta[:-1]
        d2 = raw_delta[1:]

        valid = (
            (d1 > 0) &
            (d2 > 0)
        )

        if np.any(valid):

            rhythm_ratios = np.maximum(
                d1[valid] / d2[valid],
                d2[valid] / d1[valid]
            )

            # Prevent pathological timing values from
            # completely dominating similarity.
            rhythm_ratios = np.clip(
                rhythm_ratios,
                1.0,
                8.0
            )

        else:

            rhythm_ratios = np.array(
                [],
                dtype=np.float32
            )

    else:

        rhythm_ratios = np.array(
            [],
            dtype=np.float32
        )

    rhythm_stats = safe_stats(
        rhythm_ratios
    )

    # --------------------------------------------------------
    # Object density
    # --------------------------------------------------------

    object_count = len(vectors)

    duration_seconds = (
        np.sum(raw_delta) / 1000.0
    )

    if duration_seconds > 0:

        objects_per_second = (
            object_count /
            duration_seconds
        )

    else:

        objects_per_second = 0.0

    return {

        # Timing
        "delta_mean":
            delta_stats["mean"],

        "delta_median":
            delta_stats["median"],

        "delta_std":
            delta_stats["std"],

        "delta_p25":
            delta_stats["p25"],

        "delta_p75":
            delta_stats["p75"],

        "delta_min":
            delta_stats["min"],

        "delta_max":
            delta_stats["max"],

        # Movement
        "spacing_mean":
            spacing_stats["mean"],

        "spacing_median":
            spacing_stats["median"],

        "spacing_std":
            spacing_stats["std"],

        "spacing_p25":
            spacing_stats["p25"],

        "spacing_p75":
            spacing_stats["p75"],

        "spacing_max":
            spacing_stats["max"],

        # Movement speed
        "movement_speed_mean":
            movement_speed_stats["mean"],

        "movement_speed_median":
            movement_speed_stats["median"],

        "movement_speed_std":
            movement_speed_stats["std"],

        "movement_speed_p75":
            movement_speed_stats["p75"],

        # Rhythm
        "rhythm_ratio_mean":
            rhythm_stats["mean"],

        "rhythm_ratio_std":
            rhythm_stats["std"],

        "rhythm_ratio_p25":
            rhythm_stats["p25"],

        "rhythm_ratio_p75":
            rhythm_stats["p75"],

        # Density
        "object_count":
            float(object_count),

        "objects_per_second":
            float(objects_per_second),
    }

def get_beatmap_vectors(
    conn,
    beatmap_id
):
    """
    Retrieve the stored vectors for a beatmap.

    Adjust object_index if your table uses a different
    ordering column.
    """

    rows = conn.execute(
        """
        SELECT
            x_diff,
            y_diff,
            time_diff,
            slider_length

        FROM beatmap_vectors

        WHERE beatmap_id = ?

        ORDER BY object_index
        """,
        (beatmap_id,)
    ).fetchall()

    return [
        tuple(row)
        for row in rows
    ]