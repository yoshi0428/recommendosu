def create_tables(conn):
    """
    Create the tables of the classifier database.

    beatmaps:
        One row for each osu! difficulty.

    beatmap_vectors:
        The raw vectors from one hit object to the next, for the base beatmap.
        They are NOT normalized for a mod variant.

    beatmap_variants:
        One row for each beatmap + mod combination, with the effective
        difficulty statistics of that variant.

    tournament_predictions:
        The tournament slot labels of each variant: 1 in the column of each
        slot that the map was pooled in. (The name is older than this use.)
    """

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS beatmaps (
            beatmap_id TEXT PRIMARY KEY,

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

    # The vectors hold RAW values: time_diff is the base time difference, and
    # length is the original slider length. Do NOT normalize them here.

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS beatmap_vectors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
        
            beatmap_id TEXT NOT NULL,
        
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

    # Each variant row holds the EFFECTIVE statistics of the variant. For
    # example, 12345 + NM, 12345 + DT and 12345 + HR are separate rows.

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS beatmap_variants (
            variant_id INTEGER PRIMARY KEY AUTOINCREMENT,

            beatmap_id TEXT NOT NULL,
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

            pp REAL,
            pp_aim REAL,
            pp_speed REAL,
            pp_acc REAL,
            pp_flashlight REAL,

            FOREIGN KEY (beatmap_id)
                REFERENCES beatmaps(beatmap_id)
                ON DELETE CASCADE,

            UNIQUE (
                beatmap_id,
                mods
            )
        )
    """)

    # The tournament slot labels. The columns are the keys of
    # training_data.TOURNAMENT_MODS (without the columns of older databases).

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tournament_predictions (
            variant_id INTEGER PRIMARY KEY,
            
            nm1 REAL,
            nm2 REAL,
            nm3 REAL,
            nm4 REAL,
            nm5 REAL,
            nm6 REAL,
            nm7 REAL,
            nm8 REAL,
            
            dt1 REAL,
            dt2 REAL,
            dt3 REAL,
            dt4 REAL,
            dt5 REAL,
            
            hr1 REAL,
            hr2 REAL,
            hr3 REAL,
            hr4 REAL,
            
            hd1 REAL,
            hd2 REAL,
            hd3 REAL,
            hd4 REAL,

            fm1 REAL,
            fm2 REAL,
            fm3 REAL,
            fm4 REAL,
            
            tb REAL,
            
            FOREIGN KEY (variant_id)
                REFERENCES beatmap_variants(variant_id)
                ON DELETE CASCADE
        )
    """)

    conn.commit()
