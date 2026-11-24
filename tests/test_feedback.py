"""Tests for beatmap_recommender/feedback.py and POST /feedback."""

import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main
from beatmap_recommender import feedback
from beatmap_recommender.auth import session

PLAYER = 100
CLICK = datetime(2026, 11, 20, 12, tzinfo=timezone.utc).timestamp()
HOUR = 3600


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def db(recommender_db, tmp_path, monkeypatch):
    monkeypatch.setattr(feedback, "FEEDBACK_DB_PATH", tmp_path / "feedback.db")
    feedback.initialize_feedback_db()
    recommender_db.add_beatmap(1)
    recommender_db.add_beatmap(2)
    return recommender_db


def variant(db, beatmap_id=1, mods="HD"):
    return db.conn.execute(
        "SELECT variant_id FROM beatmap_variants WHERE beatmap_id = ? AND mods = ?", (str(beatmap_id), mods)
    ).fetchone()[0]


def click(db, at=CLICK, beatmap_id=1):
    event = {
        "event_type": "open", "variant_id": variant(db, beatmap_id), "recommendation_id": "rec",
        "position": 3, "for_player_id": PLAYER, "final_score": 0.8,
    }
    feedback.log_event(db.conn, PLAYER, event, now=at)


def events():
    with feedback.feedback_db() as conn:
        return conn.execute("SELECT * FROM feedback_events ORDER BY event_id").fetchall()


class FakeAPI:
    def __init__(self, scores=()):
        self.scores, self.calls = list(scores), []

    def get(self, endpoint, params=None):
        self.calls.append(endpoint)
        return self.scores[params["offset"]:params["offset"] + params["limit"]]


def run(db, api, now):
    feedback.check_plays(lambda: sqlite3.connect(db.path), lambda: api, now)


def test_log_takes_the_map_from_the_database(db):
    click(db)
    (event,) = events()
    assert (event["beatmap_id"], event["mods"], event["position"]) == ("1", "HD", 3)


@pytest.mark.parametrize(
    "offset, played",
    [(-60, False), (0, False), (60, True), (feedback.PLAY_WINDOW, True), (feedback.PLAY_WINDOW + 60, False)],
)
def test_only_a_score_in_the_window_counts(db, offset, played):
    click(db)
    db.add_score(PLAYER, 1, created_at=iso(CLICK + offset))
    run(db, FakeAPI(), CLICK + feedback.PLAY_WINDOW + HOUR)
    assert (events()[0]["played_at"] is not None) is played


def test_the_first_play_counts_even_if_it_failed(db):
    click(db)
    db.add_score(PLAYER, 1, mods="HD", rank="S", created_at=iso(CLICK + 900))
    db.add_score(PLAYER, 1, mods="", rank="F", created_at=iso(CLICK + 600))
    db.add_score(PLAYER, 2, created_at=iso(CLICK + 60))
    db.add_score(PLAYER + 1, 1, created_at=iso(CLICK + 60))
    run(db, FakeAPI(), CLICK + HOUR)
    event = events()[0]
    assert (event["played_at"], event["played_mods"], event["played_rank"]) == (CLICK + 600, "NM", "F")


@pytest.mark.parametrize("age, fetched", [(19, False), (20, True), (23.9, True), (24, False)])
def test_fetch_is_in_the_recent_scores_window(db, age, fetched):
    click(db)
    api = FakeAPI()
    run(db, api, CLICK + age * HOUR)
    assert bool(api.calls) is fetched
    assert (events()[0]["checked_at"] is not None) is fetched


def test_fetch_finds_the_play_of_a_player_who_did_not_come_back(db):
    click(db)
    click(db, beatmap_id=2)
    click(db, at=CLICK + 10 * HOUR)
    api = FakeAPI([{
        "id": 9, "user_id": PLAYER, "beatmap": {"id": 1, "status": "ranked"}, "mods": ["HD"],
        "rank": "A", "created_at": iso(CLICK + HOUR),
    }])
    now = CLICK + 20 * HOUR
    run(db, api, now)
    run(db, api, now)

    assert api.calls == [f"/users/{PLAYER}/scores/recent"]
    first, second, third = events()
    assert (first["played_at"], first["checked_at"]) == (CLICK + HOUR, now)
    assert (second["played_at"], second["checked_at"]) == (None, now)
    # The thread checks the new event later.
    assert third["checked_at"] is None


def test_a_failed_fetch_does_not_stop_the_run(db):
    class BrokenAPI:
        def get(self, *args, **kwargs):
            raise RuntimeError("down")

    click(db)
    db.add_score(PLAYER, 1, created_at=iso(CLICK + HOUR))
    run(db, BrokenAPI(), CLICK + 20 * HOUR)
    assert events()[0]["checked_at"] is None
    assert events()[0]["played_at"] == CLICK + HOUR


# ---------------------------------------------------------------------------
# POST /feedback
# ---------------------------------------------------------------------------
@pytest.fixture
def client(db, auth_db, monkeypatch):
    monkeypatch.setattr(main, "connect_db", lambda read_only=False: sqlite3.connect(db.path))
    return TestClient(main.app)


def body(db, **changes):
    return {
        "event_type": "preview", "recommendation_id": "rec", "variant_id": variant(db), "position": 0,
        "for_player_id": 7, "final_score": 0.5, **changes,
    }


def test_endpoint_needs_a_login(client, db):
    assert client.post("/api/v1/feedback", json=body(db)).status_code == 401
    assert events() == []


def test_endpoint_stores_the_session_player(client, db):
    client.cookies.set("session_id", session.create_session(PLAYER))
    assert client.post("/api/v1/feedback", json=body(db)).status_code == 204
    (event,) = events()
    assert (event["player_id"], event["for_player_id"], event["event_type"]) == (PLAYER, 7, "preview")


@pytest.mark.parametrize(
    "changes, status",
    [({"event_type": "hack"}, 422), ({"position": -1}, 422), ({"variant_id": 2**64}, 422), ({"variant_id": 10**9}, 404)],
)
def test_endpoint_rejects_bad_events(client, db, changes, status):
    client.cookies.set("session_id", session.create_session(PLAYER))
    assert client.post("/api/v1/feedback", json=body(db, **changes)).status_code == status
    assert events() == []
