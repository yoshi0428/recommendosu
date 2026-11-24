"""
The auth database (auth.db). It holds the login sessions, the osu! OAuth
tokens of each session, and the OAuth states that wait for a login to finish.
session.py, token_store.py and oauth_state.py use it.
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

# The sessions table comes first because oauth_tokens refers to it.
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
    Open a connection to the auth database as one transaction.

    If the block succeeds, the transaction commits. If the block raises, the
    transaction rolls back. The connection closes in both cases. The plain
    sqlite3 `with conn:` commits or rolls back, but it does not close.
    """
    conn = sqlite3.connect(AUTH_DB_PATH, timeout=CONNECTION_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # SQLite ignores foreign keys unless this setting is on. Logout needs
    # ON DELETE CASCADE to delete the tokens of the session.
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize_auth_db():
    """Create the auth tables if they do not exist."""
    with auth_db() as conn:
        conn.executescript(SCHEMA)
