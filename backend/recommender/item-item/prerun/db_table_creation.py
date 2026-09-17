def create_tables(conn):
    """
    Create the normalized database schema.

    beatmaps:
        One row per actual osu! difficulty.

    beatmap_vectors:
        CNN input vectors belonging to the base beatmap.

    beatmap_augmentations:
        Records which geometric augmentations are available.

    beatmap_variants:
        One row per beatmap + mod combination.

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
    # Mod variants
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
    #
    # These columns are placeholders for your classifier.
    # They can be populated by a separate inference script.
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
            dt2_and_3 REAL,
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