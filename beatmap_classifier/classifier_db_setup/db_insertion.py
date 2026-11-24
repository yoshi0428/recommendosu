from beatmap_classifier.classifier.training_data import TOURNAMENT_MODS
from beatmap_recommender.content_similarity.core_modules.mod_preferences import canonicalize_mods
from beatmap_recommender.recommender_db_setup.beatmap_mods import (
    apply_bpm_mod,
    apply_length_mod,
    get_modded_stats,
)

# The beatmaps columns. parse_osu_file() returns a value with the same key for each.
BEATMAP_COLUMNS = (
    "beatmap_id",
    "hp_drain",
    "circle_size",
    "od",
    "ar",
    "slider_multiplier",
    "slider_tick",
    "bpm",
    "min_bpm",
    "max_bpm",
    "length_seconds",
    "object_count",
)


def insert_base_beatmap(conn, beatmap_data):
    """
    Insert the base beatmap, with its BASE statistics (no mods).

    beatmap_id is the PRIMARY KEY. Thus augmentation cannot make one map into
    several separate beatmaps.
    """
    conn.execute(
        f"""
        INSERT OR IGNORE INTO beatmaps ({", ".join(BEATMAP_COLUMNS)})
        VALUES ({", ".join("?" for _ in BEATMAP_COLUMNS)})
        """,
        tuple(beatmap_data[column] for column in BEATMAP_COLUMNS),
    )


def insert_vectors(conn, beatmap_id, vectors):
    """Insert the raw vectors of a beatmap, and keep their order (vector_index)."""
    if not vectors:
        return

    conn.executemany(
        """
        INSERT OR REPLACE INTO beatmap_vectors (
            beatmap_id,
            vector_index,
            x_diff,
            y_diff,
            time_diff,
            length,
            distance,
            speed,
            speed_change,
            time_diff_change
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(beatmap_id, index, *vector[:8]) for index, vector in enumerate(vectors)],
    )


def insert_variant(conn, beatmap_id, mods, base_data, difficulty_result):
    """
    Insert one beatmap + mod combination, or update it if it exists.

    Example:

        beatmap_id = 12345
        mods = ["DT"]

    becomes:

        variant_id = ...
        beatmap_id = 12345
        mods = "DT"

    The statistics in beatmap_variants are the EFFECTIVE statistics for this
    mod combination. Return (variant_id, canonical mods string).
    """
    cursor = conn.cursor()
    mods_string = canonicalize_mods(mods)

    stats = get_modded_stats(base_data, difficulty_result, mods)
    effective_bpm, effective_min_bpm, effective_max_bpm = apply_bpm_mod(
        base_data["bpm"], base_data["min_bpm"], base_data["max_bpm"], mods
    )
    effective_length = apply_length_mod(base_data["length_seconds"], mods)

    cursor.execute(
        """
        INSERT INTO beatmap_variants (
            beatmap_id,
            mods,
            hp_drain,
            circle_size,
            od,
            ar,
            star_rating,
            max_combo,
            bpm,
            min_bpm,
            max_bpm,
            length_seconds,
            object_count,
            pp,
            pp_aim,
            pp_speed,
            pp_acc,
            pp_flashlight
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?
        )

        ON CONFLICT(beatmap_id, mods)
        DO UPDATE SET
            hp_drain = excluded.hp_drain,
            circle_size = excluded.circle_size,
            od = excluded.od,
            ar = excluded.ar,
            star_rating = excluded.star_rating,
            max_combo = excluded.max_combo,
            bpm = excluded.bpm,
            min_bpm = excluded.min_bpm,
            max_bpm = excluded.max_bpm,
            length_seconds = excluded.length_seconds,
            object_count = excluded.object_count,
            pp = excluded.pp,
            pp_aim = excluded.pp_aim,
            pp_speed = excluded.pp_speed,
            pp_acc = excluded.pp_acc,
            pp_flashlight = excluded.pp_flashlight

        RETURNING variant_id
        """,
        (
            beatmap_id,
            mods_string,
            stats["hp_drain"],
            stats["circle_size"],
            stats["od"],
            stats["ar"],
            stats["star_rating"],
            stats["max_combo"],
            effective_bpm,
            effective_min_bpm,
            effective_max_bpm,
            effective_length,
            base_data["object_count"],
            stats["pp"],
            stats["pp_aim"],
            stats["pp_speed"],
            stats["pp_acc"],
            stats["pp_flashlight"],
        ),
    )

    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(f"Failed to retrieve variant ID for {beatmap_id} + {mods_string}")

    return row[0], mods_string


def insert_tournament_prediction(conn, variant_id, mods_string, folder_name):
    """
    Mark the variant as part of the tournament slot that the folder of the map
    names (matched against TOURNAMENT_MODS, without regard to case). Do this
    only if the slot is played with the mods of this variant.

    Examples:

        NM1 -> NM variant -> nm1 = 1
        HD2 -> HD variant -> hd2 = 1
        DT2_AND_DT3 -> DT variant -> dt2_and_dt3 = 1

    Return True if the label was set. Return False if the label is not for
    this variant (or if the folder is not a tournament slot).
    """
    prediction_column = folder_name.strip().lower()

    # NM1 must not be inserted into the DT variant.
    if TOURNAMENT_MODS.get(prediction_column) != mods_string:
        return False

    cursor = conn.cursor()

    # Make sure that the prediction row exists.
    cursor.execute("INSERT OR IGNORE INTO tournament_predictions (variant_id) VALUES (?)", (variant_id,))

    # Set the tournament label. prediction_column is a TOURNAMENT_MODS key, so
    # it is a known column name, not user input.
    cursor.execute(
        f"""
        UPDATE tournament_predictions
        SET {prediction_column} = 1
        WHERE variant_id = ?
        """,
        (variant_id,),
    )

    return True
