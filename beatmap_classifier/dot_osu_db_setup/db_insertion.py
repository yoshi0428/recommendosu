from beatmap_mods import (
    get_modded_stats,
    apply_bpm_mod,
    apply_length_mod,
)


# ============================================================
# Base Beatmap
# ============================================================

def insert_base_beatmap(
    conn,
    beatmap_data,
):
    """
    Insert the base beatmap.

    beatmap_id is the PRIMARY KEY, so a map cannot accidentally
    become multiple independent beatmaps because of augmentation.

    The values stored here are BASE beatmap statistics.
    """

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR IGNORE INTO beatmaps (
            beatmap_id,
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
        VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?
        )
        """,
        (
            beatmap_data["beatmap_id"],
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
        ),
    )


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

    if not mods:
        mods_string = "NM"
    else:
        mods_string = "".join(
            sorted(
                mod.upper()
                for mod in mods
            )
        )

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
        raise RuntimeError(
            f"Failed to retrieve variant ID "
            f"for {beatmap_id} + {mods_string}"
        )

    return row[0], mods_string


# ============================================================
# Tournament Prediction
# ============================================================

def insert_tournament_prediction(
    conn,
    variant_id,
    mods_string,
    folder_name,
    tournament_labels,
):
    """
    Mark the appropriate beatmap variant as belonging to a
    tournament classification.

    The folder name is matched case-insensitively.

    The tournament label determines:

        1. Which prediction column is set to 1.
        2. Which mod variant the prediction belongs to.

    Examples:

        NM1 -> NM variant -> nm1 = 1
        HD2 -> HD variant -> hd2 = 1
        HR3 -> HR variant -> hr3 = 1
        DT3 -> DT variant -> dt2_and_dt3 = 1

    Returns:

        True
            If the label matches this variant.

        False
            If the label does not belong to this variant.
    """

    label = folder_name.strip().lower()

    tournament = tournament_labels.get(label)

    if tournament is None:
        return False

    prediction_column = tournament["column"]
    required_mods = tournament["mods"]

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
        INSERT OR IGNORE INTO tournament_predictions (
            variant_id
        )
        VALUES (?)
        """,
        (variant_id,),
    )

    # --------------------------------------------------------
    # Set tournament label
    #
    # prediction_column comes from your own trusted
    # tournament_labels configuration.
    # --------------------------------------------------------

    cursor.execute(
        f"""
        UPDATE tournament_predictions
        SET {prediction_column} = 1
        WHERE variant_id = ?
        """,
        (variant_id,),
    )

    return True
