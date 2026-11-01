import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The recommender database. Scripts that use another file (the benchmarks,
# the smoke test) reassign it before connecting.
DB_PATH = Path(
    os.getenv(
        "DB_PATH",
        PROJECT_ROOT / "beatmap_recommender/recommender.db",
    )
)

CONNECTION_TIMEOUT = 60


def connect_db(read_only: bool = False) -> sqlite3.Connection:
    """
    Connect to DB_PATH.

    Requests query it directly: the per-request SQL is a few indexed
    lookups, which the OS page cache makes as fast as an in-memory copy,
    and the bulk variant data is read once into the variant table
    (variant_table.py). WAL lets those reads run while scores are written.
    """
    path = Path(DB_PATH).resolve()

    if read_only:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=CONNECTION_TIMEOUT)
    else:
        conn = sqlite3.connect(path, timeout=CONNECTION_TIMEOUT)
        conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def is_db_path(conn: sqlite3.Connection) -> bool:
    """Whether conn is connected to the file at DB_PATH."""
    for _, name, filename in conn.execute("PRAGMA database_list"):
        if name == "main":
            return bool(filename) and Path(filename).resolve() == Path(DB_PATH).resolve()

    return False
