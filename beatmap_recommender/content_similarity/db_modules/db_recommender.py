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

    conn.commit()

