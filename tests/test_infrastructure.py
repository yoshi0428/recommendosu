"""
Tests for the plumbing around the recommender: cancellation, the in-memory
result cache, and the SQLite-backed auth stores (OAuth state, sessions,
tokens).

New techniques in this file:
    * Faking time. Code with expiry logic (TTLs, sessions) calls
      time.time() / time.monotonic(). Rather than sleeping for 30 minutes in a
      test, we replace the clock with one we control.
    * Testing async functions without extra plugins: asyncio.run(...) runs a
      coroutine to completion inside a normal test.
    * Mocking a network call so a test never talks to osu!.
"""

import asyncio

import pytest

from beatmap_recommender import cancellation, result_cache
from beatmap_recommender.auth import oauth_state, session, token_manager, token_store


class FakeClock:
    """
    A clock that only moves when the test says so.

    Pass `clock.now` wherever the code expects time.time or time.monotonic,
    then call `clock.advance(seconds)` to jump forward instantly.

    Caveat: the app modules do `import time`, so `module.time` *is* the
    global time module and patching it affects everything for the duration
    of the test. That's fine for these short synchronous tests (monkeypatch
    restores it afterwards), but don't combine it with asyncio.run, since the
    event loop reads time.monotonic too.
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

    cancellation.check_cancelled(None)  # Must not raise.
    cancellation.check_cancelled(threading.Event())


# ---------------------------------------------------------------------------
# result_cache.py
# ---------------------------------------------------------------------------
@pytest.fixture
def cache_clock(monkeypatch):
    """
    Give result_cache a fake clock and an empty cache.

    result_cache keeps its data in a module-level dict, which persists across
    tests in the same process. Without resetting it, a result stored by one
    test could be visible to the next: a common cause of tests that pass
    alone but fail when run together (or vice versa).
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
    assert page == ROWS[1:3]  # Dicts come back intact, in order.


def test_page_past_the_end_is_empty(cache_clock):
    result_cache.store_result("rec1", 1, ROWS)
    assert result_cache.get_result_page("rec1", 1, offset=100, limit=10) == (5, [])


def test_other_players_cannot_read_a_result(cache_clock):
    # Security-relevant: recommendation IDs come from the client, so the
    # player check is what stops one user reading another's result.
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
    assert result_cache.get_result_page("rec1", 1, 0, 1) is not None  # Access refreshes the TTL...

    cache_clock.advance(result_cache.RESULT_TTL_SECONDS - 1)
    assert result_cache.get_result_page("rec1", 1, 0, 1) is not None  # ...so it's still alive.

    cache_clock.advance(result_cache.RESULT_TTL_SECONDS + 1)
    assert result_cache.get_result_page("rec1", 1, 0, 1) is None


def test_empty_result_can_be_stored(cache_clock):
    result_cache.store_result("rec1", 1, [])
    assert result_cache.get_result_page("rec1", 1, 0, 10) == (0, [])


# ---------------------------------------------------------------------------
# auth/oauth_state.py
# ---------------------------------------------------------------------------
# These use the `auth_db` fixture from conftest.py, which points the modules
# at a temporary auth.db. Your real one is never touched.
def test_state_can_only_be_used_once(auth_db):
    # One-time use is what protects the OAuth login against CSRF/replay.
    oauth_state.store_state("xyz")

    assert oauth_state.consume_state("xyz") is True
    assert oauth_state.consume_state("xyz") is False


def test_unknown_state_is_rejected(auth_db):
    assert oauth_state.consume_state("forged") is False


def test_state_expires(auth_db, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(oauth_state.time, "time", clock.now)

    oauth_state.store_state("xyz")
    clock.advance(601)  # States live for 600 seconds.

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
    # oauth_tokens has ON DELETE CASCADE on sessions. This only works because
    # get_connection() enables PRAGMA foreign_keys=ON; SQLite ignores foreign
    # keys by default. The test guards that easy-to-lose detail: logging out
    # should not leave tokens behind.
    session_id = session.create_session(42)
    token_store.store_tokens(session_id, 42, "access", "refresh", 3600)

    session.delete_session(session_id)

    assert token_store.get_tokens(session_id) is None


# ---------------------------------------------------------------------------
# auth/token_manager.py
# ---------------------------------------------------------------------------
def test_valid_access_token_is_returned_without_refresh(auth_db, monkeypatch):
    session_id = session.create_session(42)
    token_store.store_tokens(session_id, 42, "still-good", "refresh", expires_in=3600)

    async def must_not_be_called(refresh_token):
        raise AssertionError("refresh should not happen for a valid token")

    monkeypatch.setattr(token_manager, "refresh_access_token", must_not_be_called)

    assert asyncio.run(token_manager.get_access_token(session_id)) == "still-good"


def test_expiring_access_token_is_refreshed(auth_db, monkeypatch):
    session_id = session.create_session(42)
    # Expires in 30s, inside the 60s safety buffer, so it should be refreshed.
    token_store.store_tokens(session_id, 42, "old-access", "old-refresh", expires_in=30)

    calls = []

    # A *fake* replacing the real HTTP call to osu!. It records how it was
    # called so we can assert on that too.
    async def fake_refresh(refresh_token):
        calls.append(refresh_token)
        return {"access_token": "new-access", "expires_in": 86400}  # No new refresh token.

    # Patch the name *where it is looked up*: token_manager did
    # `from ... import refresh_access_token`, so it has its own reference, and
    # patching osu_oauth.refresh_access_token would have no effect here.
    monkeypatch.setattr(token_manager, "refresh_access_token", fake_refresh)

    assert asyncio.run(token_manager.get_access_token(session_id)) == "new-access"
    assert calls == ["old-refresh"]

    stored = token_store.get_tokens(session_id)
    assert stored["access_token"] == "new-access"
    assert stored["refresh_token"] == "old-refresh"  # Kept when osu! doesn't rotate it.


def test_missing_tokens_raise(auth_db):
    with pytest.raises(ValueError, match="No OAuth tokens"):
        asyncio.run(token_manager.get_access_token("no-such-session"))
