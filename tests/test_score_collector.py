"""
Tests for the code that runs at the start of each recommendation request: it
fetches the scores of a player from osu! and saves them to the database.

    score_collector.update_player_scores
        -> fetch_player_scores        (osu! API, through OsuAPIClient)
        -> normalize_score            (API JSON -> database row)
        -> store_player_scores
            -> db_insertion.insert_score  (upsert into `scores`)

Fakes replace the osu! API at two different levels:

  * FakeOsuAPI replaces the full client. The tests of score_collector use it,
    because score_collector needs only *something* with a .get(endpoint,
    params) method.
  * Fake HTTP responses replace requests.Session.get. The tests of the retry,
    rate limit and 404 logic of OsuAPIClient use them.

The choice of the level to fake is an important testing skill. Fake the layer
just below the code that you test, so that the tested code runs for real.
"""

import json
import sqlite3

import pytest
import requests

from beatmap_recommender.api import osu_api_client
from beatmap_recommender.api.osu_api_client import OsuAPIClient, OsuAPINotFoundError
from beatmap_recommender.content_similarity.core_modules import score_collector
from beatmap_recommender.content_similarity.core_modules.score_collector import (
    PlayerNotFoundError,
    normalize_score,
    store_player_scores,
    update_player_scores,
)
from beatmap_recommender.recommender_db_setup.db_insertion import insert_score

PLAYER_ID = 100


def api_score(score_id, beatmap_id=1, mods=("HD", "DT"), pp=250.0, user_id=PLAYER_ID, **overrides):
    """
    A score in the shape of the osu! API v2 /users/{id}/scores/* response.

    It has only the fields that normalize_score reads. Real responses have
    many more fields. That is not a problem, because normalize_score ignores
    them.
    """
    score = {
        "id": score_id,
        "user_id": user_id,
        "beatmap": {"id": beatmap_id, "status": "ranked"},
        "score": 1_000_000,
        "max_combo": 700,
        "accuracy": 0.9812,
        "pp": pp,
        "rank": "S",
        "mods": list(mods) if mods is not None else None,
        "created_at": "2026-10-01T12:00:00Z",
    }
    score.update(overrides)
    return score


def read_scores(conn):
    """Return all the rows in `scores` as dicts, keyed by score_id, so that a test can find one directly."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM scores").fetchall()
    conn.row_factory = None
    return {row["score_id"]: dict(row) for row in rows}


# ---------------------------------------------------------------------------
# normalize_score: API JSON -> database row
# ---------------------------------------------------------------------------
def test_normalize_score_maps_api_fields():
    row = normalize_score(api_score(42, beatmap_id=10818), source="top")

    assert row == {
        "score_id": "42",          # The IDs become strings, as in the TEXT columns.
        "player_id": PLAYER_ID,
        "beatmap_id": "10818",
        "status": "ranked",
        "score": 1_000_000,
        "max_combo": 700,
        "accuracy": 0.9812,
        "pp": 250.0,
        "rank": "S",
        "mods": "HD,DT",           # The format that the rest of the app parses.
        "created_at": "2026-10-01T12:00:00Z",
        "source": "top",
    }


def test_normalize_score_no_mods_is_empty_string():
    # NM is stored as "" (as in the real scores table), and later
    # canonicalize_mods changes "" into "NM".
    assert normalize_score(api_score(1, mods=()), "top")["mods"] == ""
    assert normalize_score(api_score(1, mods=None), "top")["mods"] == ""


def test_normalize_score_reads_player_from_nested_user():
    score = api_score(1, user_id=None, user={"id": 555})
    assert normalize_score(score, "recent")["player_id"] == 555


def test_normalize_score_keeps_null_pp():
    # Failed or unranked plays have pp = null. It must stay NULL. It must not
    # cause a crash, and it must not become 0.
    assert normalize_score(api_score(1, pp=None), "recent")["pp"] is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"user_id": None}, "missing player_id"),
        ({"beatmap": {}}, "missing beatmap_id"),
        ({"beatmap": None}, "missing beatmap_id"),
    ],
)
def test_normalize_score_rejects_incomplete_scores(overrides, message):
    with pytest.raises(ValueError, match=message):
        normalize_score(api_score(1, **overrides), "top")


# ---------------------------------------------------------------------------
# insert_score: the upsert
# ---------------------------------------------------------------------------
@pytest.fixture
def db_with_map(recommender_db):
    recommender_db.add_beatmap(1)
    return recommender_db


def insert(conn, score_id, source, **overrides):
    insert_score(conn, normalize_score(api_score(score_id, **overrides), source))
    conn.commit()


def test_insert_score_adds_a_row(db_with_map):
    insert(db_with_map.conn, 1, "top")

    rows = read_scores(db_with_map.conn)
    assert rows["1"]["source"] == "top"
    assert rows["1"]["mods"] == "HD,DT"


# The source column records the API list (or lists) that a score came from.
# The ranking code treats "top,recent" as a top play, and the mod preferences
# must not count it twice. Thus these tests fix the merge rules of the column.
@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("top", "top", "top"),
        ("recent", "recent", "recent"),
        ("top", "recent", "top,recent"),
        ("recent", "top", "top,recent"),
        ("top,recent", "top", "top,recent"),
        ("top,recent", "recent", "top,recent"),
        ("top,recent", "top,recent", "top,recent"),
    ],
)
def test_insert_score_merges_sources(db_with_map, first, second, expected):
    insert(db_with_map.conn, 1, first)
    insert(db_with_map.conn, 1, second)

    rows = read_scores(db_with_map.conn)
    assert len(rows) == 1  # An upsert, not a second row.
    assert rows["1"]["source"] == expected


def test_insert_score_updates_changed_fields(db_with_map):
    # osu! calculates pp again from time to time. A new fetch must store the new value.
    insert(db_with_map.conn, 1, "top", pp=250.0)
    insert(db_with_map.conn, 1, "top", pp=263.5)

    assert read_scores(db_with_map.conn)["1"]["pp"] == 263.5


# ---------------------------------------------------------------------------
# store_player_scores
# ---------------------------------------------------------------------------
def test_store_skips_scores_on_unknown_beatmaps(recommender_db):
    # The recommender database has only ranked and loved maps. A play on a
    # graveyard map has no beatmap row to join, so the code skips it.
    recommender_db.add_beatmap(1)

    stored = store_player_scores(
        recommender_db.conn,
        top_scores=[api_score(1, beatmap_id=1), api_score(2, beatmap_id=999)],
        recent_scores=[],
    )

    assert stored == 1
    assert set(read_scores(recommender_db.conn)) == {"1"}


def test_store_marks_score_in_both_lists_as_top_recent(recommender_db):
    # A new personal best is in both /scores/best and /scores/recent in the
    # same fetch.
    recommender_db.add_beatmap(1)
    same_score = api_score(7, beatmap_id=1)

    store_player_scores(recommender_db.conn, top_scores=[same_score], recent_scores=[same_score])

    assert read_scores(recommender_db.conn)["7"]["source"] == "top,recent"


def test_store_keeps_older_history(recommender_db):
    # The code keeps the scores that leave the top and recent lists of the API.
    # Thus the history of the player grows over time.
    recommender_db.add_beatmap(1)
    recommender_db.add_beatmap(2)

    store_player_scores(recommender_db.conn, [api_score(1, beatmap_id=1)], [])
    store_player_scores(recommender_db.conn, [api_score(2, beatmap_id=2)], [])

    assert set(read_scores(recommender_db.conn)) == {"1", "2"}


# ---------------------------------------------------------------------------
# update_player_scores (with a fake API client)
# ---------------------------------------------------------------------------
class FakeOsuAPI:
    """
    A replacement for OsuAPIClient. It returns fixed responses for each
    endpoint, and records each request, so that the tests can check the
    requests.

    As the real API does, it obeys offset and limits limit to 100.
    """

    def __init__(self, top=(), recent=(), error=None):
        self.responses = {
            f"/users/{PLAYER_ID}/scores/best": list(top),
            f"/users/{PLAYER_ID}/scores/recent": list(recent),
        }
        self.error = error
        self.requests = []

    def get(self, endpoint, params=None):
        self.requests.append((endpoint, params))
        if self.error:
            raise self.error
        params = params or {}
        offset = params.get("offset", 0)
        limit = min(params.get("limit", 100), 100)
        return self.responses[endpoint][offset : offset + limit]


def by_endpoint(requests_made):
    """Return the requests grouped by endpoint (best, then recent), each group in request order."""
    return sorted(requests_made, key=lambda request: request[0])


def test_update_player_scores_fetches_and_stores(recommender_db):
    recommender_db.add_beatmap(1)
    recommender_db.add_beatmap(2)
    api = FakeOsuAPI(top=[api_score(1, beatmap_id=1)], recent=[api_score(2, beatmap_id=2, mods=())])

    stored = update_player_scores(recommender_db.conn, api, PLAYER_ID, limit=100)

    assert stored == 2
    rows = read_scores(recommender_db.conn)
    assert rows["1"]["source"] == "top"
    assert rows["2"]["source"] == "recent"

    # The request parameters are part of the contract with osu!. The code fetches
    # the two endpoints at the same time, so only the order in each one is fixed.
    assert by_endpoint(api.requests) == [
        (f"/users/{PLAYER_ID}/scores/best", {"limit": 100, "offset": 0, "include_fails": 1, "mode": "osu"}),
        (f"/users/{PLAYER_ID}/scores/recent", {"limit": 100, "offset": 0, "include_fails": 1, "mode": "osu"}),
    ]


def test_fetch_pages_past_the_100_score_api_limit():
    # osu! returns 100 scores for each request at most. Thus a top 200 needs two
    # requests: offset 0 and offset 100.
    top = [api_score(i) for i in range(200)]
    recent = [api_score(1000 + i) for i in range(150)]
    api = FakeOsuAPI(top=top, recent=recent)

    top_scores, recent_scores = score_collector.fetch_player_scores(api, PLAYER_ID, limit=200)

    assert [s["id"] for s in top_scores] == list(range(200))
    assert [s["id"] for s in recent_scores] == [1000 + i for i in range(150)]
    assert [(endpoint.rsplit("/", 1)[1], params["offset"], params["limit"]) for endpoint, params in by_endpoint(api.requests)] == [
        ("best", 0, 100),
        ("best", 100, 100),
        ("recent", 0, 100),
        ("recent", 100, 100),  # This returns 50, so the paging stops here.
    ]


def test_fetch_stops_after_a_short_page():
    # A player with only 30 top plays: one request, and no empty second request.
    api = FakeOsuAPI(top=[api_score(i) for i in range(30)])

    top_scores, recent_scores = score_collector.fetch_player_scores(api, PLAYER_ID, limit=200)

    assert len(top_scores) == 30
    assert recent_scores == []
    assert len(api.requests) == 2  # One for each endpoint.


def test_fetch_last_page_asks_only_for_the_remainder():
    api = FakeOsuAPI(top=[api_score(i) for i in range(200)])

    top_scores, _ = score_collector.fetch_player_scores(api, PLAYER_ID, limit=150)

    assert len(top_scores) == 150
    assert [params["limit"] for endpoint, params in api.requests if endpoint.endswith("best")] == [100, 50]


def test_stored_scores_feed_the_recommender(recommender_db):
    """
    An integration check across the boundary: the ranking code must be able to
    read the scores that the collector saved. If normalize_score changed the
    mods format, the unit tests above would still pass, but this test would
    fail.
    """
    from beatmap_recommender.content_similarity.core_modules.variant_ranking import (
        get_player_played_variants,
    )

    recommender_db.add_beatmap(1)
    recommender_db.add_beatmap(2)
    api = FakeOsuAPI(top=[api_score(1, beatmap_id=1, mods=("HD", "NC"))], recent=[api_score(2, beatmap_id=2, mods=())])

    update_player_scores(recommender_db.conn, api, PLAYER_ID)
    played = get_player_played_variants(recommender_db.conn, PLAYER_ID)

    assert {(v["beatmap_id"], v["mods"]) for v in played} == {("1", "HDDT"), ("2", "NM")}


# ---------------------------------------------------------------------------
# OsuAPIClient: retries, rate limits, errors
# ---------------------------------------------------------------------------
def http_response(status, body=None, headers=None):
    """
    A real requests.Response object with fixed content.

    Because it is the real class (not a homemade fake), raise_for_status()
    and .json() work exactly as in production.
    """
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body if body is not None else {}).encode()
    response.headers.update(headers or {})
    response.url = "https://osu.ppy.sh/api/v2/test"
    return response


@pytest.fixture
def fake_http(monkeypatch):
    """
    Make OsuAPIClient fast and offline.

    * A function that records the delay replaces time.sleep. It does not
      wait, so the retry tests take milliseconds, not minutes.
    * random.uniform returns 0, so the backoff delays are predictable.
    * The shared rate limiter never waits, so `fake.sleeps` holds only retry
      delays. (The rate limiter tests use their own clock.)
    * requests.Session.get returns the queued responses in order.

    The tests put responses (or exceptions) into `fake.queue`.
    """

    class Fake:
        queue = []
        sleeps = []
        calls = []

    fake = Fake()
    fake.queue, fake.sleeps, fake.calls = [], [], []

    def fake_get(session, url, headers=None, params=None, timeout=None):
        fake.calls.append({"url": url, "headers": headers, "params": params})
        item = fake.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(osu_api_client.time, "sleep", fake.sleeps.append)
    monkeypatch.setattr(osu_api_client.random, "uniform", lambda a, b: 0.0)
    monkeypatch.setattr(osu_api_client, "rate_limiter", osu_api_client.RateLimiter(burst=1, interval=0))
    monkeypatch.setattr(requests.Session, "get", fake_get)
    return fake


def test_client_sends_token_and_returns_json(fake_http):
    fake_http.queue.append(http_response(200, [{"id": 1}]))

    result = OsuAPIClient("secret-token").get("/users/1/scores/best", params={"limit": 5})

    assert result == [{"id": 1}]
    call = fake_http.calls[0]
    assert call["url"] == "https://osu.ppy.sh/api/v2/users/1/scores/best"
    assert call["headers"]["Authorization"] == "Bearer secret-token"
    assert call["params"] == {"limit": 5}


def test_client_retries_server_errors_with_backoff(fake_http):
    fake_http.queue += [http_response(502), http_response(503), http_response(200, ["ok"])]

    assert OsuAPIClient("t").get("/x") == ["ok"]
    # Exponential backoff: 2**0, 2**1 (the test sets the random jitter to 0).
    assert fake_http.sleeps == [1, 2]


def test_client_gives_up_after_max_retries(fake_http):
    fake_http.queue += [http_response(500)] * osu_api_client.MAX_RETRIES

    with pytest.raises(requests.HTTPError):
        OsuAPIClient("t").get("/x")
    assert len(fake_http.calls) == osu_api_client.MAX_RETRIES


def test_client_retries_network_errors(fake_http):
    fake_http.queue += [requests.ConnectionError("reset"), http_response(200, ["ok"])]
    assert OsuAPIClient("t").get("/x") == ["ok"]


def test_client_honours_retry_after_on_429(fake_http):
    fake_http.queue += [http_response(429, headers={"Retry-After": "7"}), http_response(200, ["ok"])]

    assert OsuAPIClient("t").get("/x") == ["ok"]
    assert 7.0 in fake_http.sleeps


def test_client_404_raises_not_found(fake_http):
    fake_http.queue.append(http_response(404))
    with pytest.raises(OsuAPINotFoundError):
        OsuAPIClient("t").get("/users/1/scores/best")


def test_client_401_is_not_retried(fake_http):
    fake_http.queue.append(http_response(401))
    with pytest.raises(RuntimeError, match="invalid or expired"):
        OsuAPIClient("t").get("/x")
    assert len(fake_http.calls) == 1


# fake_clock is in conftest.py.
def test_rate_limiter_allows_a_burst_then_paces(fake_clock):
    limiter = osu_api_client.RateLimiter(burst=4, interval=1.5)

    for _ in range(4):
        limiter.acquire()
    assert fake_clock.sleeps == []  # The 4 requests of a score refresh go out at once.

    limiter.acquire()
    limiter.acquire()
    assert fake_clock.sleeps == [pytest.approx(1.5), pytest.approx(1.5)]

    # Idle time fills the bucket again, up to the burst size.
    fake_clock.now += 60
    for _ in range(4):
        limiter.acquire()
    assert len(fake_clock.sleeps) == 2


def test_default_rate_limiter_stays_under_60_requests_per_minute(fake_clock):
    limiter = osu_api_client.RateLimiter(
        burst=osu_api_client.REQUEST_BURST,
        interval=60.0 / (osu_api_client.REQUESTS_PER_MINUTE - osu_api_client.REQUEST_BURST),
    )
    start = fake_clock.now
    times = []

    for _ in range(200):
        limiter.acquire()
        times.append(fake_clock.now - start)

    for first in range(len(times)):
        in_window = sum(1 for t in times[first:] if t - times[first] < 60.0)
        assert in_window <= osu_api_client.REQUESTS_PER_MINUTE


def test_rate_limit_is_shared_by_every_client(fake_http, fake_clock, monkeypatch):
    # Each recommendation makes its own client. With a limit for each client,
    # users at the same time could go past the limit together.
    monkeypatch.setattr(osu_api_client, "rate_limiter", osu_api_client.RateLimiter(burst=1, interval=1.5))
    fake_http.queue += [http_response(200, []), http_response(200, [])]

    OsuAPIClient("a").get("/a")
    OsuAPIClient("b").get("/b")

    assert fake_clock.sleeps == [pytest.approx(1.5)]


# ---------------------------------------------------------------------------
# Skipping a refresh that just happened
# ---------------------------------------------------------------------------
def test_successful_update_is_remembered(recommender_db, monkeypatch):
    now = [5000.0]
    monkeypatch.setattr(score_collector.time, "monotonic", lambda: now[0])

    assert not score_collector.scores_refreshed_recently(PLAYER_ID)
    update_player_scores(recommender_db.conn, FakeOsuAPI(), PLAYER_ID)
    assert score_collector.scores_refreshed_recently(PLAYER_ID)
    assert not score_collector.scores_refreshed_recently(PLAYER_ID + 1)

    now[0] += score_collector.SCORE_REFRESH_INTERVAL
    assert not score_collector.scores_refreshed_recently(PLAYER_ID)


def test_unknown_player_raises_player_not_found_and_is_not_remembered(recommender_db):
    # main.py changes PlayerNotFoundError into a 404 response.
    with pytest.raises(PlayerNotFoundError, match=str(PLAYER_ID)):
        update_player_scores(recommender_db.conn, FakeOsuAPI(error=OsuAPINotFoundError("404")), PLAYER_ID)

    assert not score_collector.scores_refreshed_recently(PLAYER_ID)


def test_recommend_player_skips_a_recent_refresh(recommender_db, monkeypatch):
    import asyncio

    from beatmap_recommender import recommender
    from beatmap_recommender.api.model import RecommendationSettings

    calls = []

    async def fake_get_access_token(session_id):
        calls.append("token")
        return "token"

    def fake_recommend_player_sync(settings, access_token, update_scores, cancel_event):
        calls.append(("sync", access_token, update_scores))
        return []

    monkeypatch.setattr(recommender, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(recommender, "recommend_player_sync", fake_recommend_player_sync)
    settings = RecommendationSettings(player_id=PLAYER_ID)

    asyncio.run(recommender.recommend_player(settings, "session", PLAYER_ID))
    update_player_scores(recommender_db.conn, FakeOsuAPI(), PLAYER_ID)
    asyncio.run(recommender.recommend_player(settings, "session", PLAYER_ID))

    assert calls == ["token", ("sync", "token", True), ("sync", None, False)]
