"""
API tests for main.py, using FastAPI's TestClient.

TestClient sends real HTTP requests to the app *in-process*: no server, no
port, no network. You call `client.get("/health")` and get back a normal
response object with `.status_code`, `.json()`, `.headers` and `.cookies`.
These tests check the contract the frontend relies on: URLs, status codes,
auth rules, and response shapes.

Important detail: `TestClient(app)` is created *without* a `with` block on
purpose. Entering `with TestClient(app)` runs the app's lifespan, which
loads the 583MB recommender database into memory. None of these tests need
it, so they skip it, and anything that would touch the database or osu! is
replaced with a fake.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

import main
from beatmap_recommender import recommender, result_cache
from beatmap_recommender.auth import oauth_state, session, token_store
from beatmap_recommender.cancellation import RecommendationCancelled
from beatmap_recommender.content_similarity.core_modules.score_collector import (
    PlayerNotFoundError,
)

API = main.API_PREFIX
PLAYER_ID = 100


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client(auth_db, monkeypatch):
    # Fresh, empty result cache per test (it's a module-level global).
    monkeypatch.setattr(result_cache, "_results", {})
    return TestClient(main.app)


@pytest.fixture
def logged_in_client(client):
    """A client carrying a valid session cookie for player 100."""
    session_id = session.create_session(PLAYER_ID)
    token_store.store_tokens(session_id, PLAYER_ID, "access", "refresh", expires_in=3600)
    client.cookies.set("session_id", session_id)
    client.session_id = session_id
    return client


def fake_recommendation(beatmap_id, final_score=0.5, beatmapset_id="set"):
    """One row shaped like what rank_variants returns."""
    return {
        "variant_id": int(beatmap_id), "beatmap_id": str(beatmap_id),
        "beatmapset_id": beatmapset_id, "mods": "NM", "status": "ranked",
        "title": "Title", "artist": "Artist", "creator": "Mapper", "version": "Insane",
        "hp_drain": 5.0, "circle_size": 4.0, "od": 8.0, "ar": 9.0,
        "star_rating": 5.0, "max_combo": 700, "bpm": 180.0,
        "length_seconds": 120.0, "object_count": 500,
        "pp": 250.0, "pp_aim": 100.0, "pp_speed": 90.0, "pp_acc": 60.0, "pp_flashlight": 0.0,
        "content_similarity": 0.9, "mod_preference": 1.0, "difficulty_score": 0.8,
        "classifier_score": 0.5, "pp_potential": 0.0, "final_score": final_score,
    }


@pytest.fixture
def fake_recommender(monkeypatch):
    """
    Replace main.recommend_player with a fake that returns canned rows.

    The fake also records the arguments it received, so tests can check
    what the endpoint passed in, e.g. that the player ID came from the
    session cookie.
    """
    state = {"rows": [fake_recommendation(i, final_score=1 - i / 10000) for i in range(2500)], "calls": []}

    async def fake_recommend_player(settings, session_id, session_player_id, cancel_event=None, **kwargs):
        state["calls"].append({"settings": settings, "session_player_id": session_player_id})
        if "raise" in state:
            # type: ignore
            raise state["raise"]
        return state["rows"]

    # main.py did `from beatmap_recommender.recommender import recommend_player`,
    # so the endpoint looks the name up in `main`. That's where it must be patched.
    monkeypatch.setattr(main, "recommend_player", fake_recommend_player)
    return state


# ---------------------------------------------------------------------------
# Health / auth basics
# ---------------------------------------------------------------------------
def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", f"{API}/auth/me"),
        ("get", f"{API}/recommend"),
        ("post", f"{API}/recommend"),
        ("get", f"{API}/recommend/abc/page"),
        ("post", f"{API}/recommend/abc/cancel"),
    ],
)
def test_protected_endpoints_require_login(client, method, path):
    # Parametrizing over endpoints means a newly added endpoint is one line
    # here, and it's obvious at a glance which endpoints are protected.
    kwargs = {"json": {}} if method == "post" else {}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 401


def test_invalid_session_cookie_is_rejected(client):
    client.cookies.set("session_id", "made-up")
    response = client.get(f"{API}/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Session expired or invalid."


def test_auth_me(logged_in_client):
    response = logged_in_client.get(f"{API}/auth/me")
    assert response.json() == {"player_id": PLAYER_ID}


def test_logout_ends_the_session(logged_in_client):
    response = logged_in_client.post(f"{API}/auth/logout")
    assert response.status_code == 200

    assert session.get_session(logged_in_client.session_id) is None


# ---------------------------------------------------------------------------
# OAuth login flow
# ---------------------------------------------------------------------------
def test_login_redirects_to_osu_with_a_stored_state(client):
    response = client.get(f"{API}/auth/osu", follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://osu.ppy.sh/oauth/authorize?")

    # The state in the URL must be one the server will accept exactly once.
    state = location.split("state=")[1].split("&")[0]
    assert oauth_state.consume_state(state) is True


def test_oauth_callback_creates_session(client, monkeypatch):
    oauth_state.store_state("good-state")

    async def fake_exchange(code):
        assert code == "the-code"
        return {"access_token": "acc", "refresh_token": "ref", "expires_in": 86400}

    async def fake_user(access_token):
        return {"id": 777}

    monkeypatch.setattr(main, "exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(main, "get_authenticated_user", fake_user)

    response = client.get(
        f"{API}/auth/osu/callback",
        params={"code": "the-code", "state": "good-state"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    session_id = response.cookies["session_id"]
    assert session.get_current_player(session_id) == 777
    assert token_store.get_tokens(session_id)["access_token"] == "acc"


@pytest.mark.parametrize(
    ("params", "detail"),
    [
        ({"error": "access_denied"}, "osu! authorization failed: access_denied"),
        ({"state": "s"}, "Missing authorization code."),
        ({"code": "c"}, "Missing OAuth state."),
        ({"code": "c", "state": "never-issued"}, "Invalid or expired OAuth state."),
    ],
)
def test_oauth_callback_rejects_bad_requests(client, params, detail):
    response = client.get(f"{API}/auth/osu/callback", params=params, follow_redirects=False)
    assert response.status_code == 400
    assert response.json()["detail"] == detail


# ---------------------------------------------------------------------------
# POST /recommend + paging + cancel (recommender faked)
# ---------------------------------------------------------------------------
def post_recommend(client, body=None, recommendation_id="rec-1"):
    headers = {"X-Recommendation-Id": recommendation_id} if recommendation_id else {}
    return client.post(f"{API}/recommend", json=body or {}, headers=headers)


def test_post_recommend_returns_first_page(logged_in_client, fake_recommender):
    response = post_recommend(logged_in_client)

    assert response.status_code == 200
    body = response.json()
    assert body["recommendation_id"] == "rec-1"
    assert body["player_id"] == PLAYER_ID
    assert body["total_count"] == 2500
    assert len(body["recommendations"]) == main.RECOMMENDATION_PAGE_SIZE

    # The player ID was filled in from the session, not trusted from the body.
    assert fake_recommender["calls"][0]["settings"].player_id == PLAYER_ID


def test_post_recommend_requires_recommendation_id_header(logged_in_client, fake_recommender):
    response = post_recommend(logged_in_client, recommendation_id=None)
    assert response.status_code == 400
    assert fake_recommender["calls"] == []  # Rejected before any work happened.


def test_settings_are_validated(logged_in_client, fake_recommender):
    # Pydantic rejects out-of-range values with 422 before the endpoint runs.
    response = post_recommend(logged_in_client, {"min_year": 1999})
    assert response.status_code == 422


def test_rows_without_beatmapset_id_are_dropped(logged_in_client, fake_recommender):
    fake_recommender["rows"] = [fake_recommendation(1), fake_recommendation(2, beatmapset_id=None)]
    body = post_recommend(logged_in_client).json()
    assert [r["beatmap_id"] for r in body["recommendations"]] == ["1"]


def test_paging_through_a_result(logged_in_client, fake_recommender):
    post_recommend(logged_in_client)

    response = logged_in_client.get(f"{API}/recommend/rec-1/page", params={"offset": 2000, "limit": 1000})

    body = response.json()
    assert body["total_count"] == 2500
    assert body["offset"] == 2000
    assert len(body["recommendations"]) == 500  # Only 500 rows left after offset 2000.
    assert body["recommendations"][0]["beatmap_id"] == "2000"


def test_page_size_limit(logged_in_client, fake_recommender):
    post_recommend(logged_in_client)
    response = logged_in_client.get(
        f"{API}/recommend/rec-1/page", params={"limit": main.MAX_RECOMMENDATION_PAGE_SIZE + 1}
    )
    assert response.status_code == 422


def test_unknown_page_is_404(logged_in_client):
    response = logged_in_client.get(f"{API}/recommend/nope/page")
    assert response.status_code == 404


def test_another_player_cannot_page_your_result(logged_in_client, fake_recommender):
    post_recommend(logged_in_client)

    # Log in as a different player and try to read player 100's result.
    other_session = session.create_session(200)
    logged_in_client.cookies.set("session_id", other_session)

    response = logged_in_client.get(f"{API}/recommend/rec-1/page")
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PlayerNotFoundError(123), 404),
        (ValueError("min_bpm (200) cannot be greater than max_bpm (100)"), 400),
    ],
)
def test_recommender_errors_become_http_errors(logged_in_client, fake_recommender, error, status):
    fake_recommender["raise"] = error
    response = post_recommend(logged_in_client)
    assert response.status_code == status
    assert response.json()["detail"] == str(error)


def test_cancelled_recommendation_returns_204(logged_in_client, fake_recommender):
    fake_recommender["raise"] = RecommendationCancelled()

    response = post_recommend(logged_in_client)

    assert response.status_code == 204
    assert response.headers["X-Recommendation-Cancelled"] == "true"


def test_cancel_endpoint_for_unknown_request(logged_in_client):
    response = logged_in_client.post(f"{API}/recommend/not-running/cancel")
    assert response.json() == {"recommendation_id": "not-running", "cancelled": False}


# ---------------------------------------------------------------------------
# Music preview
# ---------------------------------------------------------------------------
def test_music_preview_unknown_song_is_404(client, monkeypatch):
    monkeypatch.setattr(main, "AUDIO_INDEX", {})
    response = client.get(
        f"{API}/music/preview", params={"artist": "a", "title": "t", "creator": "c"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# End-to-end: real endpoint -> real recommender -> tiny test database
# ---------------------------------------------------------------------------
def test_recommend_end_to_end_with_test_database(logged_in_client, seeded_db, monkeypatch):
    """
    The most realistic test in this file: nothing in the recommendation
    pipeline is faked except the two things that leave this machine:

      * the database connection is pointed at the tiny seeded test DB
        instead of the 583MB in-memory one, and
      * update_player_scores (which calls the osu! API) is a no-op, so the
        scores already in the test DB are used as-is.

    This catches problems the unit tests can't: two pieces that each work
    alone but disagree about a column name, a dict key, or a data type.
    """
    monkeypatch.setattr(recommender, "connect_memory_db", lambda: sqlite3.connect(seeded_db.path))
    monkeypatch.setattr(recommender, "update_player_scores", lambda conn, api, player_id: None)

    response = post_recommend(logged_in_client, {"goal": "pp_potential"})

    assert response.status_code == 200, response.text
    body = response.json()
    recommended = {r["beatmap_id"] for r in body["recommendations"]}

    assert body["total_count"] > 0
    # Played maps are excluded by default...
    assert recommended.isdisjoint({"1", "2", "3", "4"})
    # ...and the far-too-hard / far-too-easy maps fall outside the star window.
    assert recommended.isdisjoint({"13", "14"})

    scores = [r["final_score"] for r in body["recommendations"]]
    assert scores == sorted(scores, reverse=True)
