def create_tables(conn):
    """
    Create the normalized database schema.

    beatmaps:
        One row per actual osu! difficulty.

    beatmap_vectors:
        Raw object-to-object vectors belonging to the base beatmap.
        These are NOT normalized for a particular mod variant.

    beatmap_augmentations:
        Records which geometric augmentations are available.

    beatmap_variants:
        One row per beatmap + mod combination.
        Contains the effective difficulty/statistics for that variant.

    tournament_predictions:
        Classifier probabilities for each variant.
    """

    cursor = conn.cursor()

    # --------------------------------------------------------
    # Base beatmaps
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS beatmaps (
            beatmap_id INTEGER PRIMARY KEY,

            hp_drain REAL NOT NULL,
            circle_size REAL NOT NULL,
            od REAL NOT NULL,
            ar REAL NOT NULL,

            slider_multiplier REAL,
            slider_tick REAL,

            bpm REAL,
            min_bpm REAL,
            max_bpm REAL,

            length_seconds REAL NOT NULL,
            object_count INTEGER NOT NULL
        )
    """)

    # --------------------------------------------------------
    # Base beatmap vectors
    #
    # IMPORTANT:
    # These are RAW values.
    #
    # time_diff = original/base timing difference
    # length    = original slider length
    #
    # Do NOT normalize these here.
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS beatmap_vectors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
        
            beatmap_id INTEGER NOT NULL,
        
            vector_index INTEGER NOT NULL,
        
            x_diff REAL NOT NULL,
            y_diff REAL NOT NULL,
            time_diff REAL NOT NULL,
            length REAL NOT NULL,
            distance REAL NOT NULL,
            speed REAL NOT NULL,
            speed_change REAL NOT NULL,
            time_diff_change REAL NOT NULL,
        
            FOREIGN KEY (beatmap_id)
                REFERENCES beatmaps(beatmap_id)
                ON DELETE CASCADE,
        
            UNIQUE (beatmap_id, vector_index)
        );
    """)

    # --------------------------------------------------------
    # Mod variants
    #
    # Contains the EFFECTIVE statistics for the variant.
    #
    # Example:
    #
    # 12345 + NM
    # 12345 + DT
    # 12345 + HR
    #
    # are separate rows.
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS beatmap_variants (
            variant_id INTEGER PRIMARY KEY AUTOINCREMENT,

            beatmap_id INTEGER NOT NULL,
            mods TEXT NOT NULL,

            hp_drain REAL NOT NULL,
            circle_size REAL NOT NULL,
            od REAL NOT NULL,
            ar REAL NOT NULL,

            star_rating REAL NOT NULL,
            max_combo INTEGER,

            bpm REAL,
            min_bpm REAL,
            max_bpm REAL,

            length_seconds REAL NOT NULL,
            object_count INTEGER NOT NULL,

            FOREIGN KEY (beatmap_id)
                REFERENCES beatmaps(beatmap_id)
                ON DELETE CASCADE,

            UNIQUE (
                beatmap_id,
                mods
            )
        )
    """)

    # --------------------------------------------------------
    # Tournament classifier predictions
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tournament_predictions (
            variant_id INTEGER PRIMARY KEY,
            
            nm1 REAL,
            nm2 REAL,
            nm3 REAL,
            nm4 REAL,
            nm5 REAL,
            nm6 REAL,
            
            dt1 REAL,
            dt2_and_dt3 REAL,
            dt4 REAL,
            
            hr1 REAL,
            hr2 REAL,
            hr3 REAL,
            
            hd1 REAL,
            hd2 REAL,
            hd3 REAL,
            
            tiebreaker REAL,
            
            FOREIGN KEY (variant_id)
                REFERENCES beatmap_variants(variant_id)
                ON DELETE CASCADE
        )
    """)

    conn.commit()
