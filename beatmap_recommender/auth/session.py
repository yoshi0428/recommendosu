import secrets
import sqlite3
import time
from pathlib import Path


SESSION_EXPIRATION_SECONDS = 86400

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTH_DB_PATH = PROJECT_ROOT / "beatmap_recommender/auth.db"


def get_connection():
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_session_store():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                player_id INTEGER NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )

        conn.commit()


def create_session(player_id: int) -> str:
    session_id = secrets.token_urlsafe(32)
    now = time.time()
    expires_at = now + SESSION_EXPIRATION_SECONDS

    with get_connection() as conn:
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

        conn.commit()

    return session_id


def get_session(session_id: str) -> dict | None:
    with get_connection() as conn:
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
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM sessions
            WHERE session_id = ?
            """,
            (session_id,),
        )

        conn.commit()


def get_current_player(session_id: str | None) -> int:
    if not session_id:
        raise ValueError("Not authenticated.")

    session = get_session(session_id)
    if session is None:
        raise ValueError("Session expired or invalid.")

    return session["player_id"]