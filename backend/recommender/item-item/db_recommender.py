def create_recommender_tables(conn):
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS variant_features (
            variant_id INTEGER PRIMARY KEY,

            star_rating REAL,
            aim_difficulty REAL,
            speed_difficulty REAL,
            flashlight_difficulty REAL,

            ar REAL,
            cs REAL,
            od REAL,
            hp REAL,

            bpm REAL,
            bpm_min REAL,
            bpm_max REAL,
            effective_bpm REAL,

            length REAL,
            object_count REAL,
            objects_per_second REAL,

            circle_ratio REAL,
            slider_ratio REAL,
            spinner_ratio REAL,

            delta_mean REAL,
            delta_median REAL,
            delta_std REAL,
            delta_p25 REAL,
            delta_p75 REAL,
            delta_min REAL,
            delta_max REAL,

            spacing_mean REAL,
            spacing_median REAL,
            spacing_std REAL,
            spacing_p25 REAL,
            spacing_p75 REAL,
            spacing_max REAL,

            movement_speed_mean REAL,
            movement_speed_median REAL,
            movement_speed_std REAL,
            movement_speed_p75 REAL,

            rhythm_ratio_mean REAL,
            rhythm_ratio_std REAL,
            rhythm_ratio_p25 REAL,
            rhythm_ratio_p75 REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS variant_neighbors (
            variant_id INTEGER NOT NULL,
            neighbor_variant_id INTEGER NOT NULL,
            similarity REAL NOT NULL,
            rank INTEGER NOT NULL,

            PRIMARY KEY (
                variant_id,
                neighbor_variant_id
            )
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_variant_neighbors_variant
        ON variant_neighbors(variant_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_variant_neighbors_neighbor
        ON variant_neighbors(neighbor_variant_id)
    """)

    conn.commit()

