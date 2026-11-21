"""
Every beatmap a player has ever played, so "exclude already played" covers
more than the top/recent plays in the scores table.

A player's full list comes from /users/{id}/beatmapsets/most_played (every
beatmap they have a play count on, 100 per request). Fetching it takes one
request per 100 beatmaps, minutes for a long-time player, so it runs in a
background thread instead of in the request:

    recommend_player() -> request_sync(player_id)   queue the player, return at once
    worker thread      -> sync_player()             fetch, replace their played_beatmaps rows

The worker only takes a request slot when no live request is waiting (see
RateLimiter.acquire_background()), so it never delays a score refresh by more
than one request. A player is fetched again after RESYNC_INTERVAL; plays
since the last fetch reach the scores table through the normal score refresh,
and get_played_beatmap_ids() combines the two.

The worker only runs once start_sync_worker() is called (main.py's lifespan),
so scripts, benchmarks and tests that call the recommender never touch the API.
"""

import logging
import queue
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from beatmap_recommender.api.osu_api_client import OsuAPINotFoundError

logger = logging.getLogger(__name__)

# The most entries osu! returns from one most_played request.
PAGE_SIZE = 100

# A player's list is fetched again when it's older than this.
RESYNC_INTERVAL = timedelta(days=7)

CREATE_TABLES = """
    CREATE TABLE IF NOT EXISTS played_beatmaps (
        player_id INTEGER NOT NULL,
        beatmap_id TEXT NOT NULL,
        play_count INTEGER NOT NULL,
        PRIMARY KEY (player_id, beatmap_id)
    ) WITHOUT ROWID;

    CREATE TABLE IF NOT EXISTS played_beatmaps_sync (
        player_id INTEGER PRIMARY KEY,
        synced_at TEXT NOT NULL,
        beatmap_count INTEGER NOT NULL
    );
"""


def create_played_tables(conn):
    conn.executescript(CREATE_TABLES)


# ============================================================
# Reading
# ============================================================
def get_played_beatmap_ids(conn, player_id):
    """
    Every beatmap ID the player has played: their stored scores, plus their
    full most_played list if it has been fetched. A database without the
    played_beatmaps table (an older copy, opened read-only) has only the scores.
    """
    played = {beatmap_id for (beatmap_id,) in conn.execute(
        "SELECT DISTINCT beatmap_id FROM scores WHERE player_id = ?", (player_id,)
    )}
    try:
        played.update(beatmap_id for (beatmap_id,) in conn.execute(
            "SELECT beatmap_id FROM played_beatmaps WHERE player_id = ?", (player_id,)
        ))
    except sqlite3.OperationalError:  # no such table
        pass
    return played


def synced_at(conn, player_id):
    """When the player's most_played list was last stored, or None."""
    try:
        row = conn.execute("SELECT synced_at FROM played_beatmaps_sync WHERE player_id = ?", (player_id,)).fetchone()
    except sqlite3.OperationalError:  # no such table
        return None
    return datetime.fromisoformat(row[0]) if row else None


# ============================================================
# Fetching and storing
# ============================================================
def fetch_played_beatmaps(api, player_id):
    """{beatmap_id: play count} of the player's osu!standard beatmaps, from most_played."""
    played, offset = {}, 0
    while True:
        page = api.get(
            f"/users/{player_id}/beatmapsets/most_played",
            params={"limit": PAGE_SIZE, "offset": offset},
        )
        for entry in page:
            beatmap = entry.get("beatmap") or {}
            if beatmap.get("mode", "osu") == "osu":
                played[str(entry["beatmap_id"])] = int(entry.get("count") or 0)
        offset += len(page)
        if len(page) < PAGE_SIZE:  # a short page means the list has run out
            return played


def store_played_beatmaps(conn, player_id, played, now=None):
    """Replace the player's played_beatmaps rows with `played` and record the sync time."""
    now = now or datetime.now(timezone.utc)
    create_played_tables(conn)
    with conn:
        conn.execute("DELETE FROM played_beatmaps WHERE player_id = ?", (player_id,))
        conn.executemany(
            "INSERT INTO played_beatmaps (player_id, beatmap_id, play_count) VALUES (?, ?, ?)",
            [(player_id, beatmap_id, count) for beatmap_id, count in played.items()],
        )
        conn.execute(
            """
            INSERT INTO played_beatmaps_sync (player_id, synced_at, beatmap_count) VALUES (?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                synced_at = excluded.synced_at,
                beatmap_count = excluded.beatmap_count
            """,
            (player_id, now.isoformat(), len(played)),
        )


def sync_player(conn, api, player_id, now=None):
    """
    Fetch and store the player's list unless it's younger than RESYNC_INTERVAL.
    Returns the number of beatmaps stored, or None if the stored list was still fresh.
    """
    now = now or datetime.now(timezone.utc)
    last = synced_at(conn, player_id)
    if last is not None and now - last < RESYNC_INTERVAL:
        return None

    played = fetch_played_beatmaps(api, player_id)
    store_played_beatmaps(conn, player_id, played, now)
    logger.info("Player %s: stored %s played beatmaps.", player_id, f"{len(played):,}")
    return len(played)


# ============================================================
# Background worker
# ============================================================
class SyncWorker:
    """One daemon thread that syncs queued players one at a time."""

    def __init__(self, connect, make_api):
        self._connect = connect  # () -> a read-write sqlite3 connection
        self._make_api = make_api  # () -> an OsuAPIClient with low_priority = True
        self._queue = queue.Queue()
        self._queued = set()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="played-maps-sync", daemon=True)
        self._thread.start()

    def request(self, player_id):
        """Queue the player unless they're already queued."""
        with self._lock:
            if player_id in self._queued:
                return
            self._queued.add(player_id)
        self._queue.put(player_id)

    def _run(self):
        api = None
        while True:
            player_id = self._queue.get()
            try:
                api = api or self._make_api()
                conn = self._connect()
                try:
                    sync_player(conn, api, player_id)
                finally:
                    conn.close()
            except OsuAPINotFoundError:
                logger.info("Player %s: not found on osu!, played beatmaps not fetched.", player_id)
            except Exception:
                logger.exception("Player %s: fetching played beatmaps failed.", player_id)
            finally:
                with self._lock:
                    self._queued.discard(player_id)


_worker = None


def start_sync_worker(connect, make_api):
    """Start the background worker (once). Until then request_sync() does nothing."""
    global _worker
    if _worker is None:
        _worker = SyncWorker(connect, make_api)
    return _worker


def request_sync(player_id):
    """Queue a background fetch of the player's played beatmaps, if the worker is running."""
    if _worker is not None and player_id is not None:
        _worker.request(player_id)
