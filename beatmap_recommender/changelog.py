"""
The changelog of the site. recommendosu.com/changelog and the /changelog
command of the Discord bot show it.

The entries are in changelog.json, in the same directory as this file, with
the newest entry first:

    [
      {
        "date": "2026-11-01",
        "title": "Discord bot",
        "changes": ["Added /changelog.", "Fixed the help text."]
      }
    ]

The code reads the file on each request. In production, beatmap_recommender/
is mounted into the backend container. Thus an edit shows without a restart.
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
    """Return all the entries, newest first. The sort uses the date, so the order in the file has no effect."""
    entries = _entries.validate_python(json.loads(Path(path or CHANGELOG_PATH).read_text(encoding="utf-8")))
    return sorted(entries, key=lambda entry: entry.date, reverse=True)
