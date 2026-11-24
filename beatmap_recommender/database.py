import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The path of the recommender database. A script that uses a different file
# (the benchmarks, the smoke test) sets this value before it connects.
DB_PATH = Path(
    os.getenv(
        "DB_PATH",
        PROJECT_ROOT / "beatmap_recommender/recommender.db",
    )
)

CONNECTION_TIMEOUT = 60


def connect_db(read_only: bool = False) -> sqlite3.Connection:
    """
    Connect to the database at DB_PATH.

    Each request queries the file directly. The SQL of a request is a few
    index lookups. The OS page cache makes them as fast as a copy in memory.
    The large variant data loads once into the variant table (variant_table.py).
    WAL mode lets these reads run while the code writes scores.
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
    """Return True if conn is connected to the file at DB_PATH."""
    for _, name, filename in conn.execute("PRAGMA database_list"):
        if name == "main":
            return bool(filename) and Path(filename).resolve() == Path(DB_PATH).resolve()

    return False
