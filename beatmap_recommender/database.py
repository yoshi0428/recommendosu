import os
import sqlite3
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DB_PATH = Path(
    os.getenv(
        "DB_PATH",
        PROJECT_ROOT / "beatmap_recommender/recommender.db",
    )
)

# A named memdb database is shared by every connection in this process,
# so the on-disk database only needs to be loaded into memory once.
MEMORY_DB_URI = "file:/recommender?vfs=memdb"

CONNECTION_TIMEOUT = 60

_memory_anchor: sqlite3.Connection | None = None
_memory_lock = threading.Lock()


def load_memory_db() -> None:
    """
    Copy the on-disk database into the shared in-memory database.

    The anchor connection is kept open for the lifetime of the process,
    otherwise SQLite frees the in-memory database when the last
    connection to it closes.
    """
    global _memory_anchor

    with _memory_lock:
        if _memory_anchor is not None:
            return

        anchor = sqlite3.connect(
            MEMORY_DB_URI,
            uri=True,
            check_same_thread=False,
        )
        # The source must be opened as a URI for VACUUM INTO to treat
        # MEMORY_DB_URI as a URI rather than a file name.
        disk_conn = sqlite3.connect(
            f"{DB_PATH.resolve().as_uri()}?mode=ro",
            uri=True,
        )

        # VACUUM INTO rather than backup(): backup copies the on-disk WAL
        # flag into the header, and memdb cannot open WAL databases.
        try:
            disk_conn.execute("VACUUM INTO ?", (MEMORY_DB_URI,))
        except BaseException:
            anchor.close()
            raise
        finally:
            disk_conn.close()

        _memory_anchor = anchor
        print(f"Loaded {DB_PATH} into memory.")


def connect_memory_db() -> sqlite3.Connection:
    load_memory_db()
    conn = sqlite3.connect(MEMORY_DB_URI, uri=True, timeout=CONNECTION_TIMEOUT)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def connect_disk_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=CONNECTION_TIMEOUT)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def is_memory_db(conn: sqlite3.Connection) -> bool:
    # In-memory databases report an empty filename.
    _, _, filename = conn.execute("PRAGMA database_list").fetchone()
    return not filename
