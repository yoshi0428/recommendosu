import os
import sqlite3
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTH_DB_PATH = Path(
    os.getenv(
        "AUTH_DB_PATH",
        PROJECT_ROOT / "beatmap_recommender/auth.db",
    )
)


def get_connection():
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_token_store():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                session_id TEXT PRIMARY KEY,
                player_id INTEGER NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (session_id)
                    REFERENCES sessions(session_id)
                    ON DELETE CASCADE
            )
            """
        )

        conn.commit()

def store_tokens(
    session_id: str,
    player_id: int,
    access_token: str,
    refresh_token: str,
    expires_in: int,
):
    now = time.time()
    expires_at = now + expires_in

    with get_connection() as conn:
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

        conn.commit()

def get_tokens(session_id: str) -> dict | None:
    with get_connection() as conn:
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

def delete_tokens(player_id: int):
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM oauth_tokens
            WHERE player_id = ?
            """,
            (player_id,),
        )

        conn.commit()

def update_tokens(
    player_id: int,
    access_token: str,
    refresh_token: str,
    expires_in: int,
):
    now = time.time()
    expires_at = now + expires_in

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE oauth_tokens
            SET
                access_token = ?,
                refresh_token = ?,
                expires_at = ?,
                updated_at = ?
            WHERE player_id = ?
            """,
            (
                access_token,
                refresh_token,
                expires_at,
                now,
                player_id,
            ),
        )

        conn.commit()