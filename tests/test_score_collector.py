"""
Tests for the code that runs at the start of every recommendation request:
fetching a player's scores from osu! and saving them to the database.

    score_collector.update_player_scores
        -> fetch_player_scores        (osu! API, through OsuAPIClient)
        -> normalize_score            (API JSON -> database row)
        -> store_player_scores
            -> db_insertion.insert_score  (upsert into `scores`)

The osu! API is replaced with fakes at two different levels:

  * FakeOsuAPI replaces the whole client. It's used to test score_collector,
    which only needs *something* with a .get(endpoint, params) method.
  * Fake HTTP responses replace requests.Session.get. They're used to test
    OsuAPIClient's own retry, rate-limit and 404 logic.

Choosing the level to fake is a key testing skill: fake the layer just below
the code you're testing, so the code under test runs for real.
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
from beatmap_recommender.database import is_memory_db
from beatmap_recommender.recommender_db_setup.db_insertion import insert_score

PLAYER_ID = 100


def api_score(score_id, beatmap_id=1, mods=("HD", "DT"), pp=250.0, user_id=PLAYER_ID, **overrides):
    """
    A score shaped like the osu! API v2 /users/{id}/scores/* response.

    Only the fields normalize_score reads are included. Real responses have
    many more, which is fine because normalize_score ignores them.
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
    """All rows in `scores` as dicts, keyed by score_id, so tests can look one up directly."""
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
        "score_id": "42",          # IDs become strings, matching the TEXT columns.
        "player_id": PLAYER_ID,
        "beatmap_id": "10818",
        "status": "ranked",
        "score": 1_000_000,
        "max_combo": 700,
        "accuracy": 0.9812,
        "pp": 250.0,
        "rank": "S",
        "mods": "HD,DT",           # The format the rest of the app parses.
        "created_at": "2026-10-01T12:00:00Z",
        "source": "top",
    }


def test_normalize_score_no_mods_is_empty_string():
    # NM is stored as "" (that's what the real scores table contains), and
    # canonicalize_mods turns "" into "NM" later.
    assert normalize_score(api_score(1, mods=()), "top")["mods"] == ""
    assert normalize_score(api_score(1, mods=None), "top")["mods"] == ""


def test_normalize_score_reads_player_from_nested_user():
    score = api_score(1, user_id=None, user={"id": 555})
    assert normalize_score(score, "recent")["player_id"] == 555


def test_normalize_score_keeps_null_pp():
    # Failed or unranked plays have pp = null. That must survive as NULL,
    # not crash and not become 0.
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


# The source column records which API list(s) a score came from. The ranking
# code treats "top,recent" as a top play, and mod preferences rely on not
# counting it twice, so this column's merge rules are worth pinning down.
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
    assert len(rows) == 1  # Upsert, not a duplicate row.
    assert rows["1"]["source"] == expected


def test_insert_score_updates_changed_fields(db_with_map):
    # osu! recalculates pp from time to time; re-fetching must store the new value.
    insert(db_with_map.conn, 1, "top", pp=250.0)
    insert(db_with_map.conn, 1, "top", pp=263.5)

    assert read_scores(db_with_map.conn)["1"]["pp"] == 263.5


# ---------------------------------------------------------------------------
# store_player_scores
# ---------------------------------------------------------------------------
def test_store_skips_scores_on_unknown_beatmaps(recommender_db):
    # The recommender DB only contains ranked/loved maps. A play on a
    # graveyard map has nothing to join against, so it's skipped.
    recommender_db.add_beatmap(1)

    stored = store_player_scores(
        recommender_db.conn,
        top_scores=[api_score(1, beatmap_id=1), api_score(2, beatmap_id=999)],
        recent_scores=[],
    )

    assert stored == 1
    assert set(read_scores(recommender_db.conn)) == {"1"}


def test_store_marks_score_in_both_lists_as_top_recent(recommender_db):
    # A fresh personal best shows up in both /scores/best and /scores/recent
    # in the same fetch.
    recommender_db.add_beatmap(1)
    same_score = api_score(7, beatmap_id=1)

    store_player_scores(recommender_db.conn, top_scores=[same_score], recent_scores=[same_score])

    assert read_scores(recommender_db.conn)["7"]["source"] == "top,recent"


def test_store_keeps_older_history(recommender_db):
    # Scores that drop out of the API's top/recent lists are kept, so the
    # player's history grows over time.
    recommender_db.add_beatmap(1)
    recommender_db.add_beatmap(2)

    store_player_scores(recommender_db.conn, [api_score(1, beatmap_id=1)], [])
    store_player_scores(recommender_db.conn, [api_score(2, beatmap_id=2)], [])

    assert set(read_scores(recommender_db.conn)) == {"1", "2"}


def test_store_writes_through_to_disk_when_using_memory_db(recommender_db, disk_recommender_db, monkeypatch):
    """
    In production `conn` is the shared in-memory database, and scores must
    also be written to the on-disk file so they survive a restart.

    Here recommender_db plays the in-memory database and disk_recommender_db
    plays the file. We tell score_collector "this connection is the memory DB"
    and "here's the disk DB" by patching the two names it imported.
    """
    for db in (recommender_db, disk_recommender_db):
        db.add_beatmap(1)

    monkeypatch.setattr(score_collector, "is_memory_db", lambda conn: True)
    monkeypatch.setattr(score_collector, "connect_disk_db", lambda: sqlite3.connect(disk_recommender_db.path))

    store_player_scores(recommender_db.conn, [api_score(1, beatmap_id=1)], [])

    assert set(read_scores(recommender_db.conn)) == {"1"}
    assert set(read_scores(disk_recommender_db.conn)) == {"1"}


def test_store_does_not_touch_disk_for_a_normal_connection(recommender_db, monkeypatch):
    recommender_db.add_beatmap(1)

    def fail():
        raise AssertionError("connect_disk_db should not be called for a file connection")

    monkeypatch.setattr(score_collector, "connect_disk_db", fail)

    store_player_scores(recommender_db.conn, [api_score(1, beatmap_id=1)], [])


def test_is_memory_db():
    memory = sqlite3.connect(":memory:")
    assert is_memory_db(memory) is True
    memory.close()


def test_is_memory_db_false_for_a_file(recommender_db):
    assert is_memory_db(recommender_db.conn) is False


# ---------------------------------------------------------------------------
# update_player_scores (with a fake API client)
# ---------------------------------------------------------------------------
class FakeOsuAPI:
    """
    Stands in for OsuAPIClient. Returns canned responses per endpoint and
    records every request, so tests can check what was asked for.
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
        return self.responses[endpoint]


def test_update_player_scores_fetches_and_stores(recommender_db):
    recommender_db.add_beatmap(1)
    recommender_db.add_beatmap(2)
    api = FakeOsuAPI(top=[api_score(1, beatmap_id=1)], recent=[api_score(2, beatmap_id=2, mods=())])

    stored = update_player_scores(recommender_db.conn, api, PLAYER_ID, limit=100)

    assert stored == 2
    rows = read_scores(recommender_db.conn)
    assert rows["1"]["source"] == "top"
    assert rows["2"]["source"] == "recent"

    # The request parameters are part of the contract with osu!.
    assert api.requests == [
        (f"/users/{PLAYER_ID}/scores/best", {"limit": 100, "include_fails": 1}),
        (f"/users/{PLAYER_ID}/scores/recent", {"limit": 100, "include_fails": 1}),
    ]


def test_unknown_player_raises_player_not_found(recommender_db):
    api = FakeOsuAPI(error=OsuAPINotFoundError("404"))

    # PlayerNotFoundError is what main.py turns into a 404 response.
    with pytest.raises(PlayerNotFoundError, match=str(PLAYER_ID)):
        update_player_scores(recommender_db.conn, api, PLAYER_ID)


def test_stored_scores_feed_the_recommender(recommender_db):
    """
    Integration check across the boundary: scores saved by the collector
    must be readable by the ranking code. If normalize_score ever changed
    the mods format, the unit tests above would still pass, but this would
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
    A real requests.Response object with canned content.

    Using the real class (instead of a homemade fake) means
    raise_for_status() and .json() behave exactly like in production.
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

    * time.sleep is replaced with a function that records the delay instead
      of waiting, so retry tests take milliseconds instead of minutes.
    * random.uniform returns 0, so backoff delays are predictable.
    * MIN_REQUEST_INTERVAL is 0, so the client's request pacing never sleeps
      and `fake.sleeps` contains only retry delays. (The pacing test turns it
      back on.)
    * requests.Session.get returns the queued responses in order.

    Tests put responses (or exceptions) into `fake.queue`.
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
    monkeypatch.setattr(osu_api_client, "MIN_REQUEST_INTERVAL", 0)
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
    # Exponential backoff: 2**0, 2**1 (the random jitter is patched to 0).
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


def test_client_spaces_out_requests(fake_http, monkeypatch):
    # Two requests back to back: the second must wait so they're at least
    # MIN_REQUEST_INTERVAL apart. A frozen clock makes "elapsed" exactly 0.
    monkeypatch.setattr(osu_api_client, "MIN_REQUEST_INTERVAL", 1.1)
    monkeypatch.setattr(osu_api_client.time, "time", lambda: 1000.0)
    fake_http.queue += [http_response(200, []), http_response(200, [])]
    client = OsuAPIClient("t")

    client.get("/a")
    client.get("/b")

    assert fake_http.sleeps == [pytest.approx(1.1)]
