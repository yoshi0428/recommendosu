"""
The full lists of played beatmaps (beatmap_recommender/content_similarity/core_modules/played_maps.py):
the fetch of most_played, its store and refresh, its use to exclude played
maps, and the background worker and low-priority rate limit that it uses.
"""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from beatmap_recommender.api import osu_api_client
from beatmap_recommender.content_similarity.core_modules import played_maps
from beatmap_recommender.content_similarity.core_modules.content_similarity import get_maps
from tests.conftest import PLAYER_ID

NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


class FakeMostPlayedAPI:
    """Serve a most_played list in pages, as /users/{id}/beatmapsets/most_played does."""

    def __init__(self, entries):
        self.entries = entries
        self.calls = []

    def get(self, endpoint, params=None):
        self.calls.append((endpoint, dict(params)))
        offset, limit = params["offset"], params["limit"]
        return self.entries[offset : offset + limit]


def entry(beatmap_id, count=1, mode="osu"):
    return {"beatmap_id": beatmap_id, "count": count, "beatmap": {"id": beatmap_id, "mode": mode}}


# ---------------------------------------------------------------------------
# Fetching and storing
# ---------------------------------------------------------------------------
def test_fetch_pages_until_a_short_page_and_keeps_only_standard():
    entries = [entry(i, count=i) for i in range(1, 251)] + [entry(9001, mode="mania")]
    api = FakeMostPlayedAPI(entries)

    played = played_maps.fetch_played_beatmaps(api, PLAYER_ID)

    assert len(played) == 250 and "9001" not in played
    assert played["7"] == 7
    assert [params["offset"] for _, params in api.calls] == [0, 100, 200]
    assert api.calls[0][0] == f"/users/{PLAYER_ID}/beatmapsets/most_played"


def test_fetch_stops_after_an_exactly_full_last_page():
    api = FakeMostPlayedAPI([entry(i) for i in range(1, 101)])
    assert len(played_maps.fetch_played_beatmaps(api, PLAYER_ID)) == 100
    assert len(api.calls) == 2  # The second, empty page ends the list.


def test_store_replaces_the_players_rows(recommender_db):
    conn = recommender_db.conn
    played_maps.store_played_beatmaps(conn, PLAYER_ID, {"1": 3, "2": 1}, NOW)
    played_maps.store_played_beatmaps(conn, PLAYER_ID + 1, {"1": 5}, NOW)
    played_maps.store_played_beatmaps(conn, PLAYER_ID, {"3": 2}, NOW + timedelta(days=8))

    rows = conn.execute("SELECT player_id, beatmap_id, play_count FROM played_beatmaps ORDER BY 1, 2").fetchall()
    assert rows == [(PLAYER_ID, "3", 2), (PLAYER_ID + 1, "1", 5)]
    assert played_maps.synced_at(conn, PLAYER_ID) == NOW + timedelta(days=8)


def test_sync_skips_a_fresh_list_and_refetches_a_stale_one(recommender_db):
    conn = recommender_db.conn
    api = FakeMostPlayedAPI([entry(1), entry(2)])

    assert played_maps.sync_player(conn, api, PLAYER_ID, now=NOW) == 2
    just_before = NOW + played_maps.RESYNC_INTERVAL - timedelta(minutes=1)
    assert played_maps.sync_player(conn, api, PLAYER_ID, now=just_before) is None
    assert len(api.calls) == 1

    api.entries.append(entry(3))
    later = NOW + played_maps.RESYNC_INTERVAL
    assert played_maps.sync_player(conn, api, PLAYER_ID, now=later) == 3


def test_resync_interval_covers_the_recent_scores_gap():
    # /scores/recent returns only the plays of the last 24 hours. A play that
    # no score refresh saw is excluded only after the next most_played sync.
    # With a longer interval, a map played a few days ago could still show
    # as unplayed for up to a week.
    assert played_maps.RESYNC_INTERVAL <= timedelta(days=1)


@pytest.mark.parametrize("sync", [True, False])
def test_recommend_player_syncs_only_when_asked(monkeypatch, sync):
    import asyncio

    from beatmap_recommender import recommender
    from beatmap_recommender.api.model import RecommendationSettings

    requested = []
    monkeypatch.setattr(recommender, "request_sync", requested.append)
    monkeypatch.setattr(recommender, "recommend_player_sync", lambda *args: [])
    settings = RecommendationSettings(player_id=PLAYER_ID)

    asyncio.run(
        recommender.recommend_player(settings, None, None, update_scores=False, sync_play_history=sync)
    )

    assert requested == ([PLAYER_ID] if sync else [])


# ---------------------------------------------------------------------------
# Excluding played maps
# ---------------------------------------------------------------------------
def test_played_ids_combine_scores_and_the_fetched_list(seeded_db):
    conn = seeded_db.conn
    # The test schema has no played_beatmaps table, as in an older read-only copy.
    assert played_maps.get_played_beatmap_ids(conn, PLAYER_ID) == {"1", "2", "3", "4"}

    played_maps.store_played_beatmaps(conn, PLAYER_ID, {"10": 4, "999": 1}, NOW)
    assert played_maps.get_played_beatmap_ids(conn, PLAYER_ID) == {"1", "2", "3", "4", "10", "999"}
    assert played_maps.get_played_beatmap_ids(conn, PLAYER_ID + 1) == set()


def test_get_maps_excludes_maps_only_in_the_fetched_list(seeded_db):
    conn = seeded_db.conn
    before, _ = get_maps(conn, mods="NM", player_id=PLAYER_ID)
    assert "10" in set(before)

    # 999 is not in the database (for example, a graveyard map). The code ignores it.
    played_maps.store_played_beatmaps(conn, PLAYER_ID, {"10": 4, "999": 1}, NOW)
    after, matrix = get_maps(conn, mods="NM", player_id=PLAYER_ID)

    assert set(after) == set(before) - {"10"}
    assert len(matrix) == len(after)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------
def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_worker_syncs_queued_players_and_ignores_duplicates(recommender_db):
    path = recommender_db.path
    release = threading.Event()

    class SlowAPI(FakeMostPlayedAPI):
        def get(self, endpoint, params=None):
            release.wait(5)
            return super().get(endpoint, params)

    api = SlowAPI([entry(1), entry(2)])
    import sqlite3

    worker = played_maps.SyncWorker(connect=lambda: sqlite3.connect(path), make_api=lambda: api)
    worker.request(PLAYER_ID)
    worker.request(PLAYER_ID)  # Already in the queue, so ignored.
    release.set()

    assert wait_for(lambda: played_maps.synced_at(recommender_db.conn, PLAYER_ID) is not None)
    assert len(api.calls) == 1
    assert played_maps.get_played_beatmap_ids(recommender_db.conn, PLAYER_ID) >= {"1", "2"}


def test_worker_survives_a_failing_player(recommender_db):
    import sqlite3

    class FailingThenWorkingAPI(FakeMostPlayedAPI):
        def get(self, endpoint, params=None):
            if f"/users/{PLAYER_ID}/" in endpoint:
                raise osu_api_client.OsuAPINotFoundError("404")
            return super().get(endpoint, params)

    api = FailingThenWorkingAPI([entry(1)])
    worker = played_maps.SyncWorker(connect=lambda: sqlite3.connect(recommender_db.path), make_api=lambda: api)
    worker.request(PLAYER_ID)
    worker.request(PLAYER_ID + 1)

    assert wait_for(lambda: played_maps.synced_at(recommender_db.conn, PLAYER_ID + 1) is not None)
    assert played_maps.synced_at(recommender_db.conn, PLAYER_ID) is None


def test_request_sync_does_nothing_until_the_worker_starts(monkeypatch):
    monkeypatch.setattr(played_maps, "_worker", None)
    played_maps.request_sync(PLAYER_ID)  # No error, and no thread.


# ---------------------------------------------------------------------------
# Low-priority rate limiting
# ---------------------------------------------------------------------------
# fake_clock is in conftest.py.
def test_background_waits_for_a_full_bucket_and_idle_live_traffic(fake_clock):
    limiter = osu_api_client.RateLimiter(burst=4, interval=1.0, background_idle=2.0)
    limiter.acquire()  # A live request. The bucket has 3 left.
    start = fake_clock.now

    limiter.acquire_background()

    # It waited until the bucket was full again (1 s) and there was no live traffic for 2 s.
    assert fake_clock.now - start >= 2.0


def test_background_leaves_live_requests_their_burst(fake_clock):
    limiter = osu_api_client.RateLimiter(burst=4, interval=1.0, background_idle=2.0)
    fake_clock.now += 10
    limiter.acquire_background()  # The server is idle, so the request goes out at once.
    assert fake_clock.sleeps == []

    sleeps_before = len(fake_clock.sleeps)
    for _ in range(3):
        limiter.acquire()  # A live refresh just after still gets 3 requests at once.
    assert len(fake_clock.sleeps) == sleeps_before


def test_low_priority_client_uses_the_background_slot(monkeypatch):
    used = []

    class RecordingLimiter:
        def acquire(self):
            used.append("live")

        def acquire_background(self):
            used.append("background")

    class OK:
        status_code = 200

        def json(self):
            return []

        def raise_for_status(self):
            pass

    monkeypatch.setattr(osu_api_client, "rate_limiter", RecordingLimiter())
    client = osu_api_client.OsuAPIClient("t")
    monkeypatch.setattr(client.session, "get", lambda *a, **k: OK())
    client.get("/x")
    client.low_priority = True
    client.get("/x")

    assert used == ["live", "background"]
