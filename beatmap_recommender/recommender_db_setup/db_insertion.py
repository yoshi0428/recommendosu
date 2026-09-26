from beatmap_recommender.recommender_db_setup.beatmap_mods import (
    get_modded_stats,
    apply_bpm_mod,
    apply_length_mod,
)
from beatmap_recommender.content_similarity.core_modules.mod_preferences import (
    canonicalize_mods,
)

# ============================================================
# Base Beatmap
# ============================================================

def insert_base_beatmap(conn, beatmap_data, md5, year):
    """
    Insert the base beatmap.

    beatmap_id is the PRIMARY KEY, so a map cannot accidentally
    become multiple independent beatmaps because of augmentation.

    The values stored here are BASE beatmap statistics.
    """
    conn.execute("""
        INSERT INTO beatmaps (
            beatmap_id,
            beatmapset_id,
            md5,
            title,
            artist,
            creator,
            version,
            preview_time,
            year,
            hp_drain,
            circle_size,
            od,
            ar,
            slider_multiplier,
            slider_tick,
            bpm,
            min_bpm,
            max_bpm,
            length_seconds,
            object_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(beatmap_id) DO UPDATE SET
            beatmapset_id = excluded.beatmapset_id,
            md5 = excluded.md5,
            title = excluded.title,
            artist = excluded.artist,
            creator = excluded.creator,
            version = excluded.version,
            preview_time = excluded.preview_time,
            year = excluded.year,
            hp_drain = excluded.hp_drain,
            circle_size = excluded.circle_size,
            od = excluded.od,
            ar = excluded.ar,
            slider_multiplier = excluded.slider_multiplier,
            slider_tick = excluded.slider_tick,
            bpm = excluded.bpm,
            min_bpm = excluded.min_bpm,
            max_bpm = excluded.max_bpm,
            length_seconds = excluded.length_seconds,
            object_count = excluded.object_count
    """, (
        str(beatmap_data["beatmap_id"]),
        beatmap_data["beatmapset_id"],
        md5,
        beatmap_data["title"],
        beatmap_data["artist"],
        beatmap_data["creator"],
        beatmap_data["version"],
        beatmap_data["preview_time"],
        year,
        beatmap_data["hp_drain"],
        beatmap_data["circle_size"],
        beatmap_data["od"],
        beatmap_data["ar"],
        beatmap_data["slider_multiplier"],
        beatmap_data["slider_tick"],
        beatmap_data["bpm"],
        beatmap_data["min_bpm"],
        beatmap_data["max_bpm"],
        beatmap_data["length_seconds"],
        beatmap_data["object_count"],
    ))


# ============================================================
# Base Vectors
# ============================================================

def insert_vectors(conn, beatmap_id, vectors):
    """
    Insert raw beatmap vectors while preserving their order.
    """

    if not vectors:
        return

    cursor = conn.cursor()

    cursor.executemany(
        """
        INSERT OR IGNORE INTO beatmap_vectors (
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
        [
            (
                beatmap_id,
                index,
                vector[0],
                vector[1],
                vector[2],
                vector[3],
                vector[4],
                vector[5],
                vector[6],
                vector[7],
            )
            for index, vector in enumerate(vectors)
        ],
    )

# ============================================================
# Beatmap Variants
# ============================================================

def insert_variant(
    conn,
    beatmap_id,
    beatmapset_id,
    year,
    mods,
    base_data,
    difficulty_result,
):
    """
    Insert one beatmap + mod combination.

    Example:

        beatmap_id = 12345
        mods = ["DT"]

    becomes:

        variant_id = ...
        beatmap_id = 12345
        mods = "DT"

    The statistics stored in beatmap_variants are the EFFECTIVE
    statistics for this particular mod combination.
    """

    cursor = conn.cursor()

    # --------------------------------------------------------
    # Canonical mod string
    # --------------------------------------------------------
    mods_string = canonicalize_mods(mods)

    # --------------------------------------------------------
    # Calculate modded difficulty statistics
    # --------------------------------------------------------

    stats = get_modded_stats(
        base_data,
        difficulty_result,
        mods,
    )

    # --------------------------------------------------------
    # Calculate effective BPM
    # --------------------------------------------------------

    (
        effective_bpm,
        effective_min_bpm,
        effective_max_bpm,
    ) = apply_bpm_mod(
        base_data["bpm"],
        base_data["min_bpm"],
        base_data["max_bpm"],
        mods,
    )

    # --------------------------------------------------------
    # Calculate effective length
    # --------------------------------------------------------

    effective_length = apply_length_mod(
        base_data["length_seconds"],
        mods,
    )

    # --------------------------------------------------------
    # Insert / update variant
    # --------------------------------------------------------

    cursor.execute(
        """
        INSERT INTO beatmap_variants (
            beatmap_id,
            beatmapset_id,
            mods,
            year,
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
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )

        ON CONFLICT(beatmap_id, mods)
        DO UPDATE SET
            beatmapset_id = excluded.beatmapset_id,
            year = excluded.year,
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
            beatmapset_id,
            mods_string,

            year,

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
        raise RuntimeError(
            f"Failed to retrieve variant ID "
            f"for {beatmap_id} + {mods_string}"
        )

    return row[0], mods_string


def insert_variant_prediction_labels(
    conn,
    variant_id,
    mods_string,
    folder_name,
    variant_predictions_labels,
):
    """
    Mark the appropriate beatmap variant as belonging to a
    variant_predictions classification.

    The folder name is matched case-insensitively.
    """

    label = folder_name.strip().lower()

    variant_predictions = variant_predictions_labels.get(label)

    if variant_predictions is None:
        return False

    prediction_column = variant_predictions["column"]
    required_mods = variant_predictions["mods"]

    # --------------------------------------------------------
    # Determine canonical mod string
    # --------------------------------------------------------

    if not required_mods:
        required_mod_string = "NM"
    else:
        required_mod_string = "".join(
            sorted(
                mod.upper()
                for mod in required_mods
            )
        )

    # --------------------------------------------------------
    # Make sure this prediction belongs to this variant.
    #
    # Example:
    #
    # NM1 must not be inserted into the DT variant.
    # --------------------------------------------------------

    if mods_string != required_mod_string:
        return False

    cursor = conn.cursor()

    # --------------------------------------------------------
    # Ensure prediction row exists
    # --------------------------------------------------------

    cursor.execute(
        """
        INSERT OR IGNORE INTO variant_predictions (
            variant_id
        )
        VALUES (?)
        """,
        (variant_id,),
    )

    cursor.execute(
        f"""
        UPDATE variant_predictions
        SET {prediction_column} = 1
        WHERE variant_id = ?
        """,
        (variant_id,),
    )

    return True

def insert_score(conn, score):
    conn.execute("""
        INSERT INTO scores (
            score_id,
            player_id,
            beatmap_id,
            status,
            score,
            max_combo,
            accuracy,
            pp,
            rank,
            mods,
            created_at,
            source
        )
        VALUES (
            :score_id,
            :player_id,
            :beatmap_id,
            :status,
            :score,
            :max_combo,
            :accuracy,
            :pp,
            :rank,
            :mods,
            :created_at,
            :source
        )
        ON CONFLICT(score_id) DO UPDATE SET
            player_id = excluded.player_id,
            beatmap_id = excluded.beatmap_id,
            status = excluded.status,
            score = excluded.score,
            max_combo = excluded.max_combo,
            accuracy = excluded.accuracy,
            pp = excluded.pp,
            rank = excluded.rank,
            mods = excluded.mods,
            created_at = excluded.created_at,
            source = CASE
                WHEN scores.source = excluded.source
                    THEN scores.source
                ELSE 'top,recent'
            END
    """, score)
