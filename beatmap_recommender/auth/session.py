import secrets
import time

from beatmap_recommender.auth.db import auth_db

SESSION_EXPIRATION_SECONDS = 86400


def create_session(player_id: int) -> str:
    session_id = secrets.token_urlsafe(32)
    now = time.time()
    expires_at = now + SESSION_EXPIRATION_SECONDS

    with auth_db() as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id,
                player_id,
                created_at,
                expires_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                session_id,
                player_id,
                now,
                expires_at,
            ),
        )

    return session_id


def get_session(session_id: str) -> dict | None:
    with auth_db() as conn:
        row = conn.execute(
            """
            SELECT
                session_id,
                player_id,
                created_at,
                expires_at
            FROM sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

    if row is None:
        return None

    session = dict(row)
    if session["expires_at"] <= time.time():
        delete_session(session_id)
        return None

    return session


def delete_session(session_id: str):
    with auth_db() as conn:
        conn.execute(
            """
            DELETE FROM sessions
            WHERE session_id = ?
            """,
            (session_id,),
        )


def get_current_player(session_id: str | None) -> int:
    if not session_id:
        raise ValueError("Not authenticated.")

    session = get_session(session_id)
    if session is None:
        raise ValueError("Session expired or invalid.")

    return session["player_id"]
