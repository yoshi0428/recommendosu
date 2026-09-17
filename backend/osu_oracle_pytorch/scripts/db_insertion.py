from beatmap_mods import get_modded_stats, apply_bpm_mod, apply_length_mod

def insert_base_beatmap(
    conn,
    beatmap_data
):
    """
    Insert the base beatmap.

    beatmap_id is the PRIMARY KEY, so a map cannot accidentally
    become multiple independent beatmaps because of augmentation.
    """

    cursor = conn.cursor()

    cursor.execute("""
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
    """, (
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
    ))


def insert_vectors(
    conn,
    beatmap_id,
    vectors,
):
    """
    Insert the original vectors for a beatmap.
    """

    cursor = conn.cursor()

    cursor.executemany("""
        INSERT OR IGNORE INTO beatmap_vectors (
            beatmap_id,
            x_diff,
            y_diff,
            time_diff,
            length
        )
        VALUES (?, ?, ?, ?, ?)
    """, [
        (
            beatmap_id,
            vector[0],
            vector[1],
            vector[2],
            vector[3],
        )
        for vector in vectors
    ])


def insert_augmentation(
    conn,
    beatmap_id,
    augmentation,
):
    """
    Record that a particular augmentation exists.

    The augmented vectors themselves can be generated during
    training rather than permanently duplicated in the database.
    """

    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO beatmap_augmentations (
            beatmap_id,
            augmentation
        )
        VALUES (?, ?)
    """, (
        beatmap_id,
        augmentation,
    ))


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
    """

    cursor = conn.cursor()

    if not mods:
        mods_string = "NM"
    else:
        mods_string = "".join(sorted(mod.upper() for mod in mods))

    stats = get_modded_stats(base_data, difficulty_result, mods)

    effective_bpm, effective_min_bpm, effective_max_bpm = apply_bpm_mod(
        base_data["bpm"],
        base_data["min_bpm"],
        base_data["max_bpm"],
        mods
    )

    effective_length = apply_length_mod(
        base_data["length_seconds"],
        mods
    )

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
                object_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    
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
                object_count = excluded.object_count
    
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
        ),
    )

    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Failed to retrieve variant ID for {beatmap_id} + {mods_string}")

    return row[0], mods_string

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

    The tournament label determines both:
        1. Which prediction column is set to 1.
        2. Which mod variant the prediction belongs to.

    Examples:

        NM1 -> NM variant -> nm1 = 1
        HD2 -> HD variant -> hd2 = 1
        HR3 -> HR variant -> hr3 = 1
        DT3 -> DT variant -> dt2_and_3 = 1

    Returns True if the label matches this variant,
    otherwise False.
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
        required_mod_string = "".join(sorted(mod.upper() for mod in required_mods))

    # --------------------------------------------------------
    # Verify that this variant is the correct mod variant.
    #
    # We don't want NM1 to accidentally label the HD/HR/DT
    # variants.
    # --------------------------------------------------------

    if mods_string != required_mod_string:
        return False

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR IGNORE INTO tournament_predictions (
            variant_id
        )
        VALUES (?)
        """,
        (variant_id,),
    )

    cursor.execute(
        f"""
        UPDATE tournament_predictions
        SET {prediction_column} = 1
        WHERE variant_id = ?
        """,
        (variant_id,),
    )

    return True