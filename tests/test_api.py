"""
API tests for main.py, with the TestClient of FastAPI.

TestClient sends real HTTP requests to the app *in the same process*: no
server, no port, no network. You call `client.get("/health")`, and you get a
normal response object with `.status_code`, `.json()`, `.headers` and
`.cookies`. These tests check the contract that the frontend needs: URLs,
status codes, auth rules, and response shapes.

Important: the code makes `TestClient(app)` *without* a `with` block on
purpose. `with TestClient(app)` runs the lifespan of the app, which loads all
the variants of the 583MB recommender database into memory. None of these
tests need it, so they skip it. A fake replaces all the code that would use
the database or osu!.
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
    # A new, empty result cache for each test (the cache is a global of the module).
    monkeypatch.setattr(result_cache, "_results", {})
    return TestClient(main.app)


@pytest.fixture
def logged_in_client(client):
    """A client with a valid session cookie for player 100."""
    session_id = session.create_session(PLAYER_ID)
    token_store.store_tokens(session_id, PLAYER_ID, "access", "refresh", expires_in=3600)
    client.cookies.set("session_id", session_id)
    client.session_id = session_id
    return client


def fake_recommendation(beatmap_id, final_score=0.5, beatmapset_id="set"):
    """One row in the shape of the rows that rank_variants returns."""
    return {
        "variant_id": int(beatmap_id), "beatmap_id": str(beatmap_id),
        "beatmapset_id": beatmapset_id, "mods": "NM", "status": "ranked",
        "title": "Title", "artist": "Artist", "creator": "Mapper", "version": "Insane",
        "hp_drain": 5.0, "circle_size": 4.0, "od": 8.0, "ar": 9.0,
        "star_rating": 5.0, "max_combo": 700, "bpm": 180.0,
        "length_seconds": 120.0, "object_count": 500,
        "pp": 250.0, "pp_aim": 100.0, "pp_speed": 90.0, "pp_acc": 60.0, "pp_flashlight": 0.0,
        "content_similarity": 0.9, "mod_preference": 1.0, "difficulty_score": 0.8,
        "classifier_score": 0.5, "final_score": final_score,
    }


@pytest.fixture
def fake_recommender(monkeypatch):
    """
    Replace main.recommend_player with a fake that returns fixed rows.

    The fake also records its arguments, so that the tests can check what
    the endpoint passed in. For example, that the player ID came from the
    session cookie.
    """
    state = {"rows": [fake_recommendation(i, final_score=1 - i / 10000) for i in range(2500)], "calls": []}

    async def fake_recommend_player(settings, session_id, session_player_id, cancel_event=None, **kwargs):
        state["calls"].append(
            {
                "settings": settings,
                "session_player_id": session_player_id,
                "sync_play_history": kwargs.get("sync_play_history"),
            }
        )
        if "raise" in state:
            # type: ignore
            raise state["raise"]
        return state["rows"]

    # main.py did `from beatmap_recommender.recommender import recommend_player`,
    # so the endpoint finds the name in `main`. Thus the patch must go there.
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
        ("post", f"{API}/recommend"),
        ("get", f"{API}/recommend/abc/page"),
        ("post", f"{API}/recommend/abc/cancel"),
    ],
)
def test_protected_endpoints_require_login(client, method, path):
    # With one parameter for each endpoint, a new endpoint is one line here, and
    # it is easy to see which endpoints are protected.
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

    # The server must accept the state in the URL exactly one time.
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

    # The player ID came from the session. The endpoint did not trust the body.
    assert fake_recommender["calls"][0]["settings"].player_id == PLAYER_ID


@pytest.mark.parametrize(("player_id", "synced"), [(None, True), (PLAYER_ID, True), (555, False)])
def test_post_recommend_syncs_only_the_logged_in_players_history(logged_in_client, fake_recommender, player_id, synced):
    # The full play history costs many osu! API requests, so the site keeps it
    # only for its own users. Another player ID in the body gets no sync.
    post_recommend(logged_in_client, body={"player_id": player_id})

    assert fake_recommender["calls"][0]["sync_play_history"] is synced


def test_post_recommend_requires_recommendation_id_header(logged_in_client, fake_recommender):
    response = post_recommend(logged_in_client, recommendation_id=None)
    assert response.status_code == 400
    assert fake_recommender["calls"] == []  # Rejected before any work started.


def test_settings_are_validated(logged_in_client, fake_recommender):
    # Before the endpoint runs, Pydantic rejects out-of-range values with 422.
    response = post_recommend(logged_in_client, {"min_year": 1999})
    assert response.status_code == 422


def test_paging_through_a_result(logged_in_client, fake_recommender):
    post_recommend(logged_in_client)

    response = logged_in_client.get(f"{API}/recommend/rec-1/page", params={"offset": 2000, "limit": 1000})

    body = response.json()
    assert body["total_count"] == 2500
    assert body["offset"] == 2000
    assert len(body["recommendations"]) == 500  # Only 500 rows remain after offset 2000.
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

    # Log in as a different player, and try to read the result of player 100.
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
# End-to-end: real endpoint -> real recommender -> tiny test database
# ---------------------------------------------------------------------------
def test_recommend_end_to_end_with_test_database(logged_in_client, seeded_db, monkeypatch):
    """
    The most realistic test in this file. Nothing in the recommendation
    pipeline is fake, except the two things that leave this machine:

      * the database connection goes to the small seeded test database, not
        to the 583MB recommender database, and
      * update_player_scores (which calls the osu! API) does nothing, so the
        code uses the scores in the test database as they are.

    This test finds problems that the unit tests cannot find: two parts that
    each work alone, but do not agree about a column name, a dict key, or a
    data type.
    """
    monkeypatch.setattr(recommender, "connect_db", lambda read_only=False: sqlite3.connect(seeded_db.path))
    monkeypatch.setattr(recommender, "update_player_scores", lambda conn, api, player_id: None)

    response = post_recommend(logged_in_client, {})

    assert response.status_code == 200, response.text
    body = response.json()
    recommended = {r["beatmap_id"] for r in body["recommendations"]}

    assert body["total_count"] > 0
    # By default, the played maps are excluded,
    assert recommended.isdisjoint({"1", "2", "3", "4"})
    # and the maps that are much too hard or too easy are outside the star window.
    assert recommended.isdisjoint({"13", "14"})

    scores = [r["final_score"] for r in body["recommendations"]]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Discord bot endpoints
# ---------------------------------------------------------------------------
BOT_KEY = "test-bot-key"
DISCORD_USER_ID = 900000000000000001


@pytest.fixture
def bot_client(client, monkeypatch):
    """A client that sends a valid X-Bot-Key and no session cookie."""
    monkeypatch.setattr(main, "BOT_API_KEY", BOT_KEY)
    client.headers["X-Bot-Key"] = BOT_KEY
    client.headers["X-Discord-User-Id"] = str(DISCORD_USER_ID)
    return client


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", f"{API}/bot/players/someone"),
        ("post", f"{API}/bot/recommend"),
        ("get", f"{API}/bot/recommend/abc/page"),
        ("get", f"{API}/bot/classify/1"),
    ],
)
@pytest.mark.parametrize("configured_key", [None, BOT_KEY])
def test_bot_endpoints_require_the_bot_key(client, monkeypatch, method, path, configured_key):
    # If BOT_API_KEY is not set, the endpoints are fully off.
    monkeypatch.setattr(main, "BOT_API_KEY", configured_key)
    kwargs = {"json": {"player_id": 1}} if method == "post" else {}
    client.headers["X-Discord-User-Id"] = "1"

    assert getattr(client, method)(path, **kwargs).status_code == 401
    assert getattr(client, method)(path, headers={"X-Bot-Key": "wrong"}, **kwargs).status_code == 401


def test_bot_recommend_uses_any_player_without_a_session(bot_client, fake_recommender):
    response = bot_client.post(f"{API}/bot/recommend", json={"player_id": 555, "min_stars": 5.0})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["player_id"] == 555
    assert body["total_count"] == 2500
    assert len(body["recommendations"]) == main.BOT_RECOMMENDATION_PAGE_SIZE

    call = fake_recommender["calls"][0]
    assert call["settings"].min_stars == 5.0
    # There is no session player, so the recommender uses the token of the app.
    assert call["session_player_id"] is None


@pytest.mark.parametrize(("headers", "synced"), [({}, False), ({"X-Linked-Player": "true"}, True)])
def test_bot_recommend_syncs_only_linked_accounts(bot_client, fake_recommender, headers, synced):
    # A /rec for any player that someone looks up must not fetch the full play
    # history of that player. Only a linked account (the bot sends the header) does.
    bot_client.post(f"{API}/bot/recommend", json={"player_id": 555}, headers=headers)

    assert fake_recommender["calls"][0]["sync_play_history"] is synced


def test_bot_recommend_requires_the_discord_user(bot_client, fake_recommender):
    del bot_client.headers["X-Discord-User-Id"]
    response = bot_client.post(f"{API}/bot/recommend", json={"player_id": 555})
    assert response.status_code == 422


def test_bot_pages_through_the_whole_result(bot_client, fake_recommender):
    recommendation_id = bot_client.post(f"{API}/bot/recommend", json={"player_id": 555}).json()["recommendation_id"]

    response = bot_client.get(
        f"{API}/bot/recommend/{recommendation_id}/page", params={"offset": 2450, "limit": 100}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_count"] == 2500
    # The last rows of the result: nothing after the end.
    assert [r["beatmap_id"] for r in body["recommendations"]] == [str(i) for i in range(2450, 2500)]


def test_bot_page_size_limit(bot_client, fake_recommender):
    recommendation_id = bot_client.post(f"{API}/bot/recommend", json={"player_id": 555}).json()["recommendation_id"]
    response = bot_client.get(
        f"{API}/bot/recommend/{recommendation_id}/page",
        params={"limit": main.MAX_BOT_RECOMMENDATION_PAGE_SIZE + 1},
    )
    assert response.status_code == 422


def test_bot_results_belong_to_one_discord_user(bot_client, fake_recommender):
    recommendation_id = bot_client.post(f"{API}/bot/recommend", json={"player_id": 555}).json()["recommendation_id"]

    response = bot_client.get(
        f"{API}/bot/recommend/{recommendation_id}/page", headers={"X-Discord-User-Id": "42"}
    )
    assert response.status_code == 404


def test_bot_results_do_not_replace_website_results(bot_client, logged_in_client, fake_recommender):
    """
    The result cache keeps one result for each owner. A Discord user who asks
    about a player must not delete the result that the player reads on the
    website.
    """
    post_recommend(logged_in_client, recommendation_id="web-1")
    bot_client.post(f"{API}/bot/recommend", json={"player_id": PLAYER_ID})

    response = logged_in_client.get(f"{API}/recommend/web-1/page")
    assert response.status_code == 200


def test_bot_recommend_requires_player_id(bot_client, fake_recommender):
    response = bot_client.post(f"{API}/bot/recommend", json={})
    assert response.status_code == 400


def test_bot_recommend_unknown_player_is_404(bot_client, fake_recommender):
    fake_recommender["raise"] = PlayerNotFoundError(555)
    response = bot_client.post(f"{API}/bot/recommend", json={"player_id": 555})
    assert response.status_code == 404


def test_bot_player_lookup(bot_client, monkeypatch):
    requests_made = []

    def fake_get(self, endpoint, params=None):
        requests_made.append((endpoint, params))
        if "nobody" in endpoint:
            raise main.OsuAPINotFoundError("404")
        return {"id": 42, "username": "Some One"}

    async def fake_token():
        return "app-token"

    monkeypatch.setattr(main, "get_application_access_token", fake_token)
    monkeypatch.setattr(main.OsuAPIClient, "get", fake_get)

    response = bot_client.get(f"{API}/bot/players/some%20one")
    assert response.json() == {"player_id": 42, "username": "Some One"}
    # The username is found as a name, never as an ID, and encoded again.
    assert requests_made[0] == ("/users/some%20one/osu", {"key": "username"})

    assert bot_client.get(f"{API}/bot/players/nobody").status_code == 404


def test_bot_classify(bot_client, seeded_db, monkeypatch):
    monkeypatch.setattr(main, "connect_db", lambda read_only=False: sqlite3.connect(seeded_db.path))
    seeded_db.add_beatmap(20, predictions=None)

    response = bot_client.get(f"{API}/bot/classify/10")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["beatmap_id"] == "10"
    assert body["predictions"] == pytest.approx({"NM1": 0.1, "NM2": 0.1, "NM3": 0.6, "NM4": 0.1, "NM5": 0.1})

    assert bot_client.get(f"{API}/bot/classify/999").status_code == 404
    # The map is in the database, but the classifier has no prediction for it.
    assert bot_client.get(f"{API}/bot/classify/20").status_code == 404
