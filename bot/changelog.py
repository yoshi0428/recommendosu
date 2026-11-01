"""
The text of /changelog: the newest entries of the site's changelog
(GET /api/v1/changelog, beatmap_recommender/changelog.json).

Kept free of discord imports like options.py, so tests can check it fits in
a Discord embed.
"""

import datetime

# Discord embed limits.
FIELD_NAME_LIMIT = 256
FIELD_VALUE_LIMIT = 1024
EMBED_TOTAL_LIMIT = 6000

# Older entries are on the website.
MAX_ENTRIES = 5

CHANGELOG_URL = "https://recommendosu.com/changelog"


def _truncate(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_date(date):
    """ "2026-11-01" -> "November 1, 2026", like the website."""
    day = datetime.date.fromisoformat(date)
    return f"{day:%B} {day.day}, {day.year}"


def changelog_embed_parts(entries):
    """
    (description, [(field name, field value), ...]) for the /changelog embed:
    one field per entry, newest first, as many as fit (up to MAX_ENTRIES).
    The text is shown as written, so entries can use Discord markdown.
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
