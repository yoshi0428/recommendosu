"""
Tests for the changelog: beatmap_recommender/changelog.py, GET
/api/v1/changelog, and the /changelog text of the Discord bot (bot/changelog.py).
"""

import asyncio
import json

import httpx
import pydantic
import pytest
from fastapi.testclient import TestClient

import main
from beatmap_recommender import changelog
from bot.api import BackendClient
from bot.changelog import (
    DESCRIPTION_LIMIT,
    EMBED_TOTAL_LIMIT,
    MAX_ENTRIES,
    TITLE_LIMIT,
    changelog_parts,
    format_date,
)

ENTRIES = [
    {"date": "2026-10-19", "title": "Discord bot", "changes": ["Added /rec.", "Added /classify."]},
    {"date": "2026-11-01", "title": "Fixes", "changes": ["Cancelling no longer shows an error."]},
]


@pytest.fixture
def changelog_file(tmp_path, monkeypatch):
    def write(entries):
        path = tmp_path / "changelog.json"
        path.write_text(json.dumps(entries))
        monkeypatch.setattr(changelog, "CHANGELOG_PATH", path)
        return path

    return write


def test_the_repository_changelog_is_valid():
    # A typo in changelog.json would break the page and /changelog.
    changelog.read_changelog()


def test_entries_come_newest_first(changelog_file):
    changelog_file(ENTRIES)
    assert [entry.title for entry in changelog.read_changelog()] == ["Fixes", "Discord bot"]


def test_a_bad_entry_is_rejected(changelog_file):
    changelog_file([{"date": "yesterday", "title": "x", "changes": []}])
    with pytest.raises(pydantic.ValidationError):
        changelog.read_changelog()


def test_endpoint_is_public_and_reads_the_file_each_time(changelog_file):
    client = TestClient(main.app)  # No session cookie.

    changelog_file(ENTRIES)
    response = client.get("/api/v1/changelog")
    assert response.status_code == 200
    assert response.json() == [ENTRIES[1], ENTRIES[0]]

    # The edit shows without a restart.
    changelog_file([])
    assert client.get("/api/v1/changelog").json() == []


# ---------------------------------------------------------------------------
# Discord bot
# ---------------------------------------------------------------------------
def test_bot_fetches_the_public_changelog():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=ENTRIES)

    async def go():
        backend = BackendClient("http://backend:8000/", "secret", transport=httpx.MockTransport(handler))
        try:
            return await backend.changelog()
        finally:
            await backend.aclose()

    assert asyncio.run(go()) == ENTRIES
    assert seen[0].url == "http://backend:8000/api/v1/changelog"


def test_format_date_matches_the_website():
    assert format_date("2026-11-01") == "November 1, 2026"


def test_each_entry_is_one_embed():
    message, embeds = changelog_parts([ENTRIES[1], ENTRIES[0]])

    assert "recommendosu.com/changelog" in message
    assert embeds == [
        ("November 1, 2026: Fixes", "• Cancelling no longer shows an error."),
        ("October 19, 2026: Discord bot", "• Added /rec.\n• Added /classify."),
    ]


def test_empty_changelog():
    assert changelog_parts([]) == ("No changes posted yet.", [])


def entry(changes, title="Title"):
    return {"date": "2026-01-01", "title": title, "changes": changes}


def check_limits(embeds):
    assert len(embeds) <= MAX_ENTRIES
    for title, text in embeds:
        assert 0 < len(title) <= TITLE_LIMIT
        assert 0 < len(text) <= DESCRIPTION_LIMIT
    assert sum(len(title) + len(text) for title, text in embeds) <= EMBED_TOTAL_LIMIT


def test_a_long_entry_stays_one_text_without_gaps():
    changes = ["c" * 300] * 12
    _, embeds = changelog_parts([entry(changes)])

    check_limits(embeds)
    assert embeds == [("January 1, 2026: Title", "\n".join(f"• {change}" for change in changes))]


def test_a_long_title_moves_into_the_text():
    _, embeds = changelog_parts([entry(["Change."], title="t" * 400)])

    check_limits(embeds)
    assert embeds == [("January 1, 2026", "t" * 400 + "\n• Change.")]


def test_entries_that_do_not_fit_are_left_out_whole():
    entries = [entry(["c" * 300] * 12) for _ in range(MAX_ENTRIES + 3)]
    _, embeds = changelog_parts(entries)

    check_limits(embeds)
    assert embeds == changelog_parts(entries[:1])[1]


def test_at_most_max_entries_show():
    assert len(changelog_parts([entry(["Change."])] * (MAX_ENTRIES + 3))[1]) == MAX_ENTRIES


def test_a_newest_entry_that_never_fits_points_to_the_website():
    message, embeds = changelog_parts([entry(["c" * 5000])])
    assert embeds == []
    assert "too long" in message and "recommendosu.com/changelog" in message


def test_the_newest_entry_of_the_repository_shows_in_full():
    entries = [e.model_dump(mode="json") for e in changelog.read_changelog()]
    _, embeds = changelog_parts(entries)

    check_limits(embeds)
    assert all(f"• {change}" in embeds[0][1] for change in entries[0]["changes"])
