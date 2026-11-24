"""
The text of /changelog: the newest entries of the changelog of the site
(GET /api/v1/changelog, beatmap_recommender/changelog.json).

As in options.py, this file does not import discord. Thus the tests can
make sure that the text fits in a Discord embed.
"""

import datetime

# Discord embed limits.
FIELD_NAME_LIMIT = 256
FIELD_VALUE_LIMIT = 1024
EMBED_TOTAL_LIMIT = 6000

# The older entries are on the website.
MAX_ENTRIES = 5

CHANGELOG_URL = "https://recommendosu.com/changelog"


def _truncate(text, limit):
    """Cut text to limit characters. If the text is cut, end it with "…"."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_date(date):
    """Change "2026-11-01" to "November 1, 2026", as the website shows it."""
    day = datetime.date.fromisoformat(date)
    return f"{day:%B} {day.day}, {day.year}"


def changelog_embed_parts(entries):
    """
    Return (description, [(field name, field value), ...]) for the /changelog
    embed: one field for each entry, newest first, as many as fit (MAX_ENTRIES
    at most). The bot shows the text as written, so an entry can use Discord
    markdown.
    """
    if not entries:
        return "No changes posted yet.", []

    description = f"The latest changes. The full list is at {CHANGELOG_URL}."
    total = len(description)
    fields = []

    for entry in entries[:MAX_ENTRIES]:
        name = _truncate(f"{format_date(entry['date'])}: {entry['title']}", FIELD_NAME_LIMIT)
        value = _truncate("\n".join(f"• {change}" for change in entry["changes"]) or "-", FIELD_VALUE_LIMIT)

        if total + len(name) + len(value) > EMBED_TOTAL_LIMIT:
            break

        total += len(name) + len(value)
        fields.append((name, value))

    return description, fields
