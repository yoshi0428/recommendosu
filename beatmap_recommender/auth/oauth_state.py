import sqlite3
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTH_DB_PATH = PROJECT_ROOT / "beatmap_recommender/auth.db"
_STATE_EXPIRATION_SECONDS = 600


def get_connection():
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_state_store():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                created_at REAL NOT NULL
            )
            """
        )
        conn.commit()


def store_state(state: str):
    created_at = time.time()
    expiration_time = created_at - _STATE_EXPIRATION_SECONDS

    with get_connection() as conn:
        # Remove expired states so they do not accumulate.
        conn.execute(
            """
            DELETE FROM oauth_states
            WHERE created_at < ?
            """,
            (expiration_time,),
        )

        conn.execute(
            """
            INSERT INTO oauth_states (
                state,
                created_at
            )
            VALUES (?, ?)
            """,
            (
                state,
                created_at,
            ),
        )

        conn.commit()


def consume_state(state: str) -> bool:
    """
    Atomically validate and consume an OAuth state.

    Returns True only if the state exists and has not expired.
    A valid state is deleted as part of the same atomic operation.
    """
    expiration_time = time.time() - _STATE_EXPIRATION_SECONDS

    with get_connection() as conn:
        cursor = conn.execute(
            """
            DELETE FROM oauth_states
            WHERE state = ?
              AND created_at >= ?
            """,
            (
                state,
                expiration_time,
            ),
        )

        conn.commit()

        return cursor.rowcount == 1