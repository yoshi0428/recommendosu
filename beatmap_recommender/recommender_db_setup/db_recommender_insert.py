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