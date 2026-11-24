"""
The text of /changelog: the newest entries of the changelog of the site
(GET /api/v1/changelog, beatmap_recommender/changelog.json).

As in options.py, this file does not import discord. Thus the tests can
make sure that the text fits in a Discord embed.
"""

import datetime

# Discord limits. EMBED_TOTAL_LIMIT is for all the embeds of one message.
TITLE_LIMIT = 256
DESCRIPTION_LIMIT = 4096
EMBED_TOTAL_LIMIT = 6000
# The older entries are on the website. Discord permits 10 embeds.
MAX_ENTRIES = 5

CHANGELOG_URL = "https://recommendosu.com/changelog"


def format_date(date):
    """Change "2026-11-01" to "November 1, 2026", as the website shows it."""
    day = datetime.date.fromisoformat(date)
    return f"{day:%B} {day.day}, {day.year}"


def changelog_parts(entries):
    """
    Return (message, [(title, description), ...]) for /changelog: one embed
    for each entry, newest first, as many as fit (MAX_ENTRIES at most).

    The code never cuts an entry. An entry that does not fit is left out. The
    text is in the description of the embed, because a field holds only 1024
    characters, and a second field adds a gap. The bot shows the text as
    written, so an entry can use Discord markdown.
    """
    if not entries:
        return "No changes posted yet.", []

    embeds = []
    total = 0

    for entry in entries[:MAX_ENTRIES]:
        title = f"{format_date(entry['date'])}: {entry['title']}"
        text = "\n".join(f"• {change}" for change in entry["changes"]) or "-"

        if len(title) > TITLE_LIMIT:
            title, text = format_date(entry["date"]), f"{entry['title']}\n{text}"

        total += len(title) + len(text)
        if len(text) > DESCRIPTION_LIMIT or total > EMBED_TOTAL_LIMIT:
            break

        embeds.append((title, text))

    # Discord shows no link preview for a URL in <>.
    if not embeds:
        return f"The newest entry is too long for Discord. Read it at <{CHANGELOG_URL}>.", []
    return f"The latest changes. The full list is at <{CHANGELOG_URL}>.", embeds
