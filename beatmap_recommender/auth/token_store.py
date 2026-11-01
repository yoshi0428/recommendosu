import time

from beatmap_recommender.auth.db import auth_db


def store_tokens(
    session_id: str,
    player_id: int,
    access_token: str,
    refresh_token: str,
    expires_in: int,
):
    now = time.time()
    expires_at = now + expires_in

    with auth_db() as conn:
        conn.execute(
            """
            INSERT INTO oauth_tokens (
                session_id,
                player_id,
                access_token,
                refresh_token,
                expires_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                player_id,
                access_token,
                refresh_token,
                expires_at,
                now,
                now,
            ),
        )


def get_tokens(session_id: str) -> dict | None:
    with auth_db() as conn:
        row = conn.execute(
            """
            SELECT
                session_id,
                player_id,
                access_token,
                refresh_token,
                expires_at
            FROM oauth_tokens
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def delete_tokens(session_id: str):
    with auth_db() as conn:
        conn.execute(
            """
            DELETE FROM oauth_tokens
            WHERE session_id = ?
            """,
            (session_id,),
        )


def update_tokens(
    session_id: str,
    access_token: str,
    refresh_token: str,
    expires_in: int,
):
    now = time.time()
    expires_at = now + expires_in

    with auth_db() as conn:
        conn.execute(
            """
            UPDATE oauth_tokens
            SET
                access_token = ?,
                refresh_token = ?,
                expires_at = ?,
                updated_at = ?
            WHERE session_id = ?
            """,
            (
                access_token,
                refresh_token,
                expires_at,
                now,
                session_id,
            ),
        )
