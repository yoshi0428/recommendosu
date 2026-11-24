"""
Tests for the support code around the recommender: cancellation, the result
cache in memory, and the auth stores in SQLite (OAuth state, sessions, tokens).

New techniques in this file:
    * A fake time. Code with expiry logic (TTLs, sessions) calls
      time.time() / time.monotonic(). The test does not sleep for 30 minutes.
      It replaces the clock with one that it controls.
    * Tests of async functions without extra plugins: asyncio.run(...) runs a
      coroutine to its end inside a normal test.
    * A mock of a network call, so that a test never talks to osu!.
"""

import asyncio

import httpx
import pytest

from beatmap_recommender import cancellation, result_cache
from beatmap_recommender.auth import oauth_state, osu_oauth, session, token_store


class FakeClock:
    """
    A clock that moves only when the test tells it to.

    Pass `clock.now` where the code expects time.time or time.monotonic. Then
    call `clock.advance(seconds)` to jump forward at once.

    Caution: the app modules do `import time`, so `module.time` *is* the
    global time module. A patch on it affects everything for the time of the
    test. That is not a problem for these short synchronous tests (monkeypatch
    puts it back after the test). But do not use it with asyncio.run, because
    the event loop also reads time.monotonic.
    """

    def __init__(self, start=1_000_000.0):
        self.current = start

    def now(self):
        return self.current

    def advance(self, seconds):
        self.current += seconds


# ---------------------------------------------------------------------------
# cancellation.py
# ---------------------------------------------------------------------------
def test_cancel_sets_the_event():
    recommendation_id, event = cancellation.create_cancellation_event("abc")

    assert cancellation.cancel_recommendation("abc") is True
    assert event.is_set()
    with pytest.raises(cancellation.RecommendationCancelled):
        cancellation.check_cancelled(event)

    cancellation.remove_cancellation_event(recommendation_id)


def test_cancelling_unknown_or_finished_request_returns_false():
    assert cancellation.cancel_recommendation("never-existed") is False

    _, _ = cancellation.create_cancellation_event("done")
    cancellation.remove_cancellation_event("done")
    assert cancellation.cancel_recommendation("done") is False


def test_generated_ids_are_unique():
    first, _ = cancellation.create_cancellation_event()
    second, _ = cancellation.create_cancellation_event()
    assert first != second
    cancellation.remove_cancellation_event(first)
    cancellation.remove_cancellation_event(second)


def test_check_cancelled_ignores_missing_or_unset_event():
    import threading

    cancellation.check_cancelled(None)  # This must not raise an error.
    cancellation.check_cancelled(threading.Event())


# ---------------------------------------------------------------------------
# result_cache.py
# ---------------------------------------------------------------------------
@pytest.fixture
def cache_clock(monkeypatch):
    """
    Give result_cache a fake clock and an empty cache.

    result_cache keeps its data in a dict of the module, which stays between
    tests in the same process. Without a reset, the next test could see a
    result that the previous test stored. This is a usual cause of tests that
    pass alone but fail together (or the opposite).
    """
    clock = FakeClock()
    monkeypatch.setattr(result_cache.time, "monotonic", clock.now)
    monkeypatch.setattr(result_cache, "_results", {})
    return clock


ROWS = [{"beatmap_id": str(i), "final_score": 1 - i / 10} for i in range(5)]


def test_pages_are_slices_of_the_stored_result(cache_clock):
    result_cache.store_result("rec1", player_id=1, recommendations=ROWS)

    total, page = result_cache.get_result_page("rec1", player_id=1, offset=1, limit=2)

    assert total == 5
    assert page == ROWS[1:3]  # The dicts come back with no changes, in order.


def test_page_past_the_end_is_empty(cache_clock):
    result_cache.store_result("rec1", 1, ROWS)
    assert result_cache.get_result_page("rec1", 1, offset=100, limit=10) == (5, [])


def test_other_players_cannot_read_a_result(cache_clock):
    # Important for security: the recommendation IDs come from the client. Thus
    # the player check is what stops one user from reading the result of another.
    result_cache.store_result("rec1", player_id=1, recommendations=ROWS)
    assert result_cache.get_result_page("rec1", player_id=2, offset=0, limit=10) is None


def test_new_result_replaces_players_previous_result(cache_clock):
    result_cache.store_result("old", 1, ROWS)
    result_cache.store_result("new", 1, ROWS[:2])

    assert result_cache.get_result_page("old", 1, 0, 10) is None
    assert result_cache.get_result_page("new", 1, 0, 10)[0] == 2


def test_results_expire_after_ttl_without_access(cache_clock):
    result_cache.store_result("rec1", 1, ROWS)

    cache_clock.advance(result_cache.RESULT_TTL_SECONDS - 1)
    assert result_cache.get_result_page("rec1", 1, 0, 1) is not None  # An access resets the TTL,

    cache_clock.advance(result_cache.RESULT_TTL_SECONDS - 1)
    assert result_cache.get_result_page("rec1", 1, 0, 1) is not None  # so the result is still there.

    cache_clock.advance(result_cache.RESULT_TTL_SECONDS + 1)
    assert result_cache.get_result_page("rec1", 1, 0, 1) is None


def test_empty_result_can_be_stored(cache_clock):
    result_cache.store_result("rec1", 1, [])
    assert result_cache.get_result_page("rec1", 1, 0, 10) == (0, [])


# ---------------------------------------------------------------------------
# auth/oauth_state.py
# ---------------------------------------------------------------------------
# These tests use the `auth_db` fixture from conftest.py, which points the
# modules at a temporary auth.db. The tests never touch your real auth.db.
def test_state_can_only_be_used_once(auth_db):
    # One-time use is what protects the OAuth login against CSRF and replay attacks.
    oauth_state.store_state("xyz")

    assert oauth_state.consume_state("xyz") is True
    assert oauth_state.consume_state("xyz") is False


def test_unknown_state_is_rejected(auth_db):
    assert oauth_state.consume_state("forged") is False


def test_state_expires(auth_db, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(oauth_state.time, "time", clock.now)

    oauth_state.store_state("xyz")
    clock.advance(601)  # A state lasts 600 seconds.

    assert oauth_state.consume_state("xyz") is False


# ---------------------------------------------------------------------------
# auth/session.py
# ---------------------------------------------------------------------------
def test_session_round_trip(auth_db):
    session_id = session.create_session(player_id=42)

    assert session.get_current_player(session_id) == 42

    session.delete_session(session_id)
    with pytest.raises(ValueError, match="expired or invalid"):
        session.get_current_player(session_id)


def test_missing_session_cookie(auth_db):
    with pytest.raises(ValueError, match="Not authenticated"):
        session.get_current_player(None)


def test_expired_session_is_rejected_and_deleted(auth_db, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(session.time, "time", clock.now)

    session_id = session.create_session(42)
    clock.advance(session.SESSION_EXPIRATION_SECONDS)

    assert session.get_session(session_id) is None


def test_session_ids_are_random(auth_db):
    assert session.create_session(1) != session.create_session(1)


# ---------------------------------------------------------------------------
# auth/token_store.py
# ---------------------------------------------------------------------------
def test_store_tokens_upserts(auth_db):
    session_id = session.create_session(42)

    token_store.store_tokens(session_id, 42, "access-1", "refresh-1", expires_in=3600)
    token_store.store_tokens(session_id, 42, "access-2", "refresh-2", expires_in=3600)

    tokens = token_store.get_tokens(session_id)
    assert tokens["access_token"] == "access-2"
    assert tokens["refresh_token"] == "refresh-2"


def test_tokens_are_deleted_with_their_session(auth_db):
    # oauth_tokens has ON DELETE CASCADE on sessions. This works only because
    # auth_db() sets PRAGMA foreign_keys=ON. By default, SQLite ignores foreign
    # keys. This test protects that detail, which is easy to lose: a logout must
    # not leave tokens behind.
    session_id = session.create_session(42)
    token_store.store_tokens(session_id, 42, "access", "refresh", 3600)

    session.delete_session(session_id)

    assert token_store.get_tokens(session_id) is None


# ---------------------------------------------------------------------------
# auth/osu_oauth.py
# ---------------------------------------------------------------------------
def test_valid_access_token_is_returned_without_refresh(auth_db, monkeypatch):
    session_id = session.create_session(42)
    token_store.store_tokens(session_id, 42, "still-good", "refresh", expires_in=3600)

    async def must_not_be_called(refresh_token):
        raise AssertionError("refresh should not happen for a valid token")

    monkeypatch.setattr(osu_oauth, "refresh_access_token", must_not_be_called)

    assert asyncio.run(osu_oauth.get_access_token(session_id)) == "still-good"


def test_expiring_access_token_is_refreshed(auth_db, monkeypatch):
    session_id = session.create_session(42)
    # The token expires in 30s, inside the 60s safety buffer, so it must be refreshed.
    token_store.store_tokens(session_id, 42, "old-access", "old-refresh", expires_in=30)

    calls = []

    # A *fake* that replaces the real HTTP call to osu!. It records its calls,
    # so that the test can also check them.
    async def fake_refresh(refresh_token):
        calls.append(refresh_token)
        return {"access_token": "new-access", "expires_in": 86400}  # There is no new refresh token.

    # Patch the name *where the code finds it*. get_access_token calls the
    # refresh_access_token of the osu_oauth module, so replace that one. (A
    # module that did `from osu_oauth import refresh_access_token` would have
    # its own reference, and this patch would not change it.)
    monkeypatch.setattr(osu_oauth, "refresh_access_token", fake_refresh)

    assert asyncio.run(osu_oauth.get_access_token(session_id)) == "new-access"
    assert calls == ["old-refresh"]

    stored = token_store.get_tokens(session_id)
    assert stored["access_token"] == "new-access"
    assert stored["refresh_token"] == "old-refresh"  # Kept when osu! does not send a new one.


def _http_status_error(status_code):
    request = httpx.Request("POST", osu_oauth.OSU_TOKEN_URL)
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("token request failed", request=request, response=response)


@pytest.mark.parametrize("status_code", [400, 401])
def test_rejected_refresh_token_ends_the_session(auth_db, monkeypatch, status_code):
    # For example, the user revoked this app in the osu! settings.
    session_id = session.create_session(42)
    token_store.store_tokens(session_id, 42, "old-access", "revoked-refresh", expires_in=30)

    async def fake_refresh(refresh_token):
        raise _http_status_error(status_code)

    monkeypatch.setattr(osu_oauth, "refresh_access_token", fake_refresh)

    with pytest.raises(osu_oauth.OsuAuthorizationRevoked):
        asyncio.run(osu_oauth.get_access_token(session_id))

    assert session.get_session(session_id) is None
    assert token_store.get_tokens(session_id) is None


def test_osu_outage_during_refresh_keeps_the_session(auth_db, monkeypatch):
    session_id = session.create_session(42)
    token_store.store_tokens(session_id, 42, "old-access", "old-refresh", expires_in=30)

    async def fake_refresh(refresh_token):
        raise _http_status_error(503)

    monkeypatch.setattr(osu_oauth, "refresh_access_token", fake_refresh)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(osu_oauth.get_access_token(session_id))

    assert session.get_session(session_id) is not None


def test_refresh_lost_to_a_concurrent_refresh_uses_the_new_token(auth_db, monkeypatch):
    # Two tabs refresh with the same refresh token. osu! accepts the first and
    # rejects the second. The second must use the new tokens of the first, and
    # must not log out the user.
    session_id = session.create_session(42)
    token_store.store_tokens(session_id, 42, "old-access", "old-refresh", expires_in=30)

    async def fake_refresh(refresh_token):
        # The other tab refreshed first, just before osu! answered this request.
        token_store.update_tokens(session_id, "other-tab-access", "other-tab-refresh", 86400)
        raise _http_status_error(400)

    monkeypatch.setattr(osu_oauth, "refresh_access_token", fake_refresh)

    assert asyncio.run(osu_oauth.get_access_token(session_id)) == "other-tab-access"
    assert session.get_session(session_id) is not None


def test_missing_tokens_raise(auth_db):
    with pytest.raises(ValueError, match="No OAuth tokens"):
        asyncio.run(osu_oauth.get_access_token("no-such-session"))


def test_application_token_is_cached_until_it_expires(monkeypatch):
    clock = FakeClock()
    requests = []

    async def fake_request_token(grant):
        requests.append(grant["grant_type"])
        return {"access_token": f"app-token-{len(requests)}", "expires_in": 86400}

    monkeypatch.setattr(osu_oauth, "_request_token", fake_request_token)
    monkeypatch.setattr(osu_oauth.time, "time", clock.now)
    monkeypatch.setattr(osu_oauth, "_application_token", None)
    monkeypatch.setattr(osu_oauth, "_application_token_expires_at", 0.0)

    assert asyncio.run(osu_oauth.get_application_access_token()) == "app-token-1"
    assert asyncio.run(osu_oauth.get_application_access_token()) == "app-token-1"

    # The token is refreshed TOKEN_EXPIRY_BUFFER seconds before osu! expires it.
    clock.advance(86400 - osu_oauth.TOKEN_EXPIRY_BUFFER)
    assert asyncio.run(osu_oauth.get_application_access_token()) == "app-token-2"
    assert requests == ["client_credentials", "client_credentials"]
