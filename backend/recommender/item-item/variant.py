from utils import *
from vector import extract_vector_features
from vector import get_beatmap_vectors

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

def build_variant_features(
    vectors,
    variant_stats,
    mods
):
    """
    Combine vector-derived features with your existing
    OsuCalculator/modded difficulty statistics.
    """

    clock_rate = get_clock_rate(mods)

    features = extract_vector_features(
        vectors,
        clock_rate=clock_rate
    )

    # --------------------------------------------------------
    # Difficulty
    # --------------------------------------------------------

    features.update({

        "star_rating":
            safe_float(
                variant_stats.get("star_rating")
            ),

        "aim_difficulty":
            safe_float(
                variant_stats.get("aim_difficulty")
            ),

        "speed_difficulty":
            safe_float(
                variant_stats.get("speed_difficulty")
            ),

        "flashlight_difficulty":
            safe_float(
                variant_stats.get("flashlight_difficulty")
            ),

        "ar":
            safe_float(
                variant_stats.get("ar")
            ),

        "cs":
            safe_float(
                variant_stats.get("cs")
            ),

        "od":
            safe_float(
                variant_stats.get("od")
            ),

        "hp":
            safe_float(
                variant_stats.get("hp")
            ),

        # ----------------------------------------------------
        # BPM
        # ----------------------------------------------------

        "bpm":
            safe_float(
                variant_stats.get("bpm")
            ),

        "bpm_min":
            safe_float(
                variant_stats.get("bpm_min")
            ),

        "bpm_max":
            safe_float(
                variant_stats.get("bpm_max")
            ),

        "effective_bpm":
            safe_float(
                variant_stats.get("effective_bpm")
            ),

        # ----------------------------------------------------
        # Length
        # ----------------------------------------------------

        "length":
            safe_float(
                variant_stats.get("length")
            ),
    })

    return features


def insert_variant_features(
    conn,
    variant_id,
    features
):
    columns = [
        "variant_id"
    ] + FEATURE_COLUMNS

    values = [
        variant_id
    ]

    for column in FEATURE_COLUMNS:
        values.append(
            safe_float(
                features.get(column)
            )
        )

    placeholders = ",".join(
        ["?"] * len(values)
    )

    conn.execute(
        f"""
        INSERT OR REPLACE INTO variant_features
        (
            {",".join(columns)}
        )
        VALUES (
            {placeholders}
        )
        """,
        values
    )

def get_variant_id(
    conn,
    beatmap_id,
    mods
):
    """
    Find the variant ID associated with a beatmap/mod
    combination.
    """

    mod_string = normalize_mods(
        mods
    )

    row = conn.execute(
        """
        SELECT variant_id
        FROM beatmap_variants
        WHERE beatmap_id = ?
          AND mods = ?
        """,
        (
            beatmap_id,
            mod_string
        )
    ).fetchone()

    if row is None:
        return None

    return row[0]


def get_variant_stats(
    conn,
    variant_id
):
    """
    Retrieve variant difficulty information.

    IMPORTANT:

    Adjust this query to match your existing
    beatmap_variants columns.

    The returned dictionary should contain whatever fields
    your build_variant_features() expects.
    """

    row = conn.execute(
        """
        SELECT
            star_rating,
            aim_difficulty,
            speed_difficulty,
            flashlight_difficulty,

            ar,
            cs,
            od,
            hp,

            bpm,
            bpm_min,
            bpm_max,
            effective_bpm,

            length

        FROM beatmap_variants
        WHERE variant_id = ?
        """,
        (variant_id,)
    ).fetchone()

    if row is None:
        return {}

    return {
        "star_rating": row[0],
        "aim_difficulty": row[1],
        "speed_difficulty": row[2],
        "flashlight_difficulty": row[3],

        "ar": row[4],
        "cs": row[5],
        "od": row[6],
        "hp": row[7],

        "bpm": row[8],
        "bpm_min": row[9],
        "bpm_max": row[10],
        "effective_bpm": row[11],

        "length": row[12],
    }

def build_variant_feature_database(
    conn
):
    """
    Generate recommender features for every beatmap variant.
    """

    variants = conn.execute(
        """
        SELECT
            variant_id,
            beatmap_id,
            mods
        FROM beatmap_variants
        """
    ).fetchall()

    print(
        f"Found {len(variants):,} variants."
    )

    processed = 0

    for variant_id, beatmap_id, mods_string in variants:

        # ----------------------------------------------------
        # Convert stored mod representation into a list.
        #
        # If your DB stores JSON or another format, change this.
        # ----------------------------------------------------

        if mods_string == "NM":
            mods = []

        else:
            mods = []

            if "HD" in mods_string:
                mods.append("HD")

            if "HR" in mods_string:
                mods.append("HR")

            if "DT" in mods_string:
                mods.append("DT")

            if "HT" in mods_string:
                mods.append("HT")

        # ----------------------------------------------------
        # Get vectors
        # ----------------------------------------------------

        vectors = get_beatmap_vectors(
            conn,
            beatmap_id
        )

        if not vectors:
            continue

        # ----------------------------------------------------
        # Get variant difficulty information
        # ----------------------------------------------------

        variant_stats = get_variant_stats(
            conn,
            variant_id
        )

        if not variant_stats:
            continue

        # ----------------------------------------------------
        # Extract features
        # ----------------------------------------------------

        features = build_variant_features(
            vectors,
            variant_stats,
            mods
        )

        # ----------------------------------------------------
        # Insert
        # ----------------------------------------------------

        insert_variant_features(
            conn,
            variant_id,
            features
        )

        processed += 1

        if processed % 1000 == 0:

            conn.commit()

            print(
                f"Processed "
                f"{processed:,}/"
                f"{len(variants):,}"
            )

    conn.commit()

    print(
        f"Feature generation complete: "
        f"{processed:,} variants."
    )

def convert_plays_to_variants(
    conn,
    plays
):
    """
    Convert API play objects into variant IDs.

    Expected play:

        {
            "beatmap_id": 123456,
            "mods": ["HD", "DT"],
            "pp": 250.0
        }

    Returns:

        [
            {
                "variant_id": 123,
                "pp": 250.0
            }
        ]
    """

    result = []

    for play in plays:

        beatmap_id = play[
            "beatmap_id"
        ]

        mods = play.get(
            "mods",
            []
        )

        variant_id = get_variant_id(
            conn,
            beatmap_id,
            mods
        )

        if variant_id is None:
            continue

        result.append({

            "variant_id":
                variant_id,

            "pp":
                safe_float(
                    play.get("pp")
                ),

            "beatmap_id":
                beatmap_id,

            "mods":
                mods,
        })

    return result