"""
The site's changelog, shown at recommendosu.com/changelog and by the Discord
bot's /changelog.

Entries live in changelog.json next to this file, newest first:

    [
      {
        "date": "2026-11-01",
        "title": "Discord bot",
        "changes": ["Added /changelog.", "Fixed the help text."]
      }
    ]

The file is read on every request, so in production (where beatmap_recommender/
is mounted into the backend container) an edit shows up without a restart.
"""

import datetime
import json
from pathlib import Path

from pydantic import BaseModel, Field, TypeAdapter

CHANGELOG_PATH = Path(__file__).resolve().parent / "changelog.json"


class ChangelogEntry(BaseModel):
    date: datetime.date = Field(examples=["2026-11-01"])
    title: str = Field(examples=["Discord bot"])
    changes: list[str] = Field(examples=[["Added /changelog."]])


_entries = TypeAdapter(list[ChangelogEntry])


def read_changelog(path=None) -> list[ChangelogEntry]:
    """Every entry, newest first (sorted by date, so the file's order doesn't matter)."""
    entries = _entries.validate_python(json.loads(Path(path or CHANGELOG_PATH).read_text(encoding="utf-8")))
    return sorted(entries, key=lambda entry: entry.date, reverse=True)
