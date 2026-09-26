def create_tables(conn):
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS beatmaps (
            beatmap_id TEXT PRIMARY KEY,
            beatmapset_id TEXT,
            md5 TEXT,
            
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            creator TEXT NOT NULL,
            version TEXT NOT NULL,
            preview_time REAL NOT NULL,
            
            year INTEGER NOT NULL DEFAULT 0,

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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS beatmap_variants (
            variant_id INTEGER PRIMARY KEY AUTOINCREMENT,

            beatmap_id TEXT NOT NULL,
            beatmapset_id TEXT,
            mods TEXT NOT NULL,
            
            year INTEGER NOT NULL DEFAULT 0,

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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS variant_predictions (
            variant_id INTEGER PRIMARY KEY,

            "2007" REAL,
            "2008" REAL,
            "2009" REAL,
            "2010" REAL,
            "2011" REAL,
            "2012" REAL,
            "2013" REAL,
            "2014" REAL,
            "2015" REAL,
            "2016" REAL,
            "2017" REAL,
            "2018" REAL,
            "2019" REAL,
            "2020" REAL,
            "2021" REAL,
            "2022" REAL,
            "2023" REAL,
            "2024" REAL,
            "2025" REAL,
            "2026" REAL,
            
            nm1 REAL,
            nm2 REAL,
            nm3 REAL,
            nm4 REAL,
            nm5 REAL,

            FOREIGN KEY (variant_id)
                REFERENCES beatmap_variants(variant_id)
                ON DELETE CASCADE
        )
    """)

    conn.commit()


def create_recommender_tables(conn):
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            score_id TEXT PRIMARY KEY,
            player_id INTEGER NOT NULL,
            beatmap_id TEXT NOT NULL,
            status TEXT,

            score INTEGER,
            max_combo INTEGER,
            accuracy REAL,

            pp REAL,

            rank TEXT,
            mods TEXT,

            created_at TEXT,

            source TEXT,

            FOREIGN KEY (beatmap_id)
                REFERENCES beatmaps(beatmap_id)
                ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS classifier_prediction_status (
            variant_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            error TEXT,
            FOREIGN KEY (variant_id)
                REFERENCES beatmap_variants(variant_id)
                ON DELETE CASCADE
        );
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scores_player
        ON scores(player_id);
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scores_beatmap
        ON scores(beatmap_id);
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scores_player_beatmap
        ON scores(player_id, beatmap_id);
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scores_player_created
        ON scores(player_id, created_at);
    """)

    conn.commit()