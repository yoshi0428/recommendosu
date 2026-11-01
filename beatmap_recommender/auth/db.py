"""
The auth database (auth.db): login sessions, their osu! OAuth tokens, and
pending OAuth states. Used by session.py, token_store.py and oauth_state.py.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

AUTH_DB_PATH = Path(
    os.getenv(
        "AUTH_DB_PATH",
        PROJECT_ROOT / "beatmap_recommender/auth.db",
    )
)

CONNECTION_TIMEOUT = 30

# sessions comes before oauth_tokens, which references it.
SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    player_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

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
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
"""


@contextmanager
def auth_db():
    """
    A connection to the auth database, as one transaction: committed if the
    block succeeds, rolled back if it raises, and closed either way.

    (sqlite3's own `with conn:` commits or rolls back, but never closes.)
    """
    conn = sqlite3.connect(AUTH_DB_PATH, timeout=CONNECTION_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # SQLite ignores foreign keys unless this is on, and logging out relies
    # on ON DELETE CASCADE to delete the session's tokens.
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize_auth_db():
    """Create the auth tables if they don't exist."""
    with auth_db() as conn:
        conn.executescript(SCHEMA)
