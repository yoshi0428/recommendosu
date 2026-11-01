"""
Tests for the changelog: beatmap_recommender/changelog.py, GET
/api/v1/changelog, and the Discord bot's /changelog text (bot/changelog.py).
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
    EMBED_TOTAL_LIMIT,
    FIELD_NAME_LIMIT,
    FIELD_VALUE_LIMIT,
    MAX_ENTRIES,
    changelog_embed_parts,
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

    # Edited without a restart.
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


def test_embed_lists_the_newest_entries():
    description, fields = changelog_embed_parts([ENTRIES[1], ENTRIES[0]])

    assert "recommendosu.com/changelog" in description
    assert fields == [
        ("November 1, 2026: Fixes", "• Cancelling no longer shows an error."),
        ("October 19, 2026: Discord bot", "• Added /rec.\n• Added /classify."),
    ]


def test_empty_changelog():
    assert changelog_embed_parts([]) == ("No changes posted yet.", [])


def test_embed_fits_discord_limits_however_long_the_changelog():
    entries = [
        {"date": "2026-01-01", "title": "t" * 400, "changes": ["c" * 300] * 10}
        for _ in range(MAX_ENTRIES + 3)
    ]
    description, fields = changelog_embed_parts(entries)

    assert 0 < len(fields) <= MAX_ENTRIES
    for name, value in fields:
        assert len(name) <= FIELD_NAME_LIMIT
        assert len(value) <= FIELD_VALUE_LIMIT
    assert len("Changelog") + len(description) + sum(len(n) + len(v) for n, v in fields) <= EMBED_TOTAL_LIMIT
