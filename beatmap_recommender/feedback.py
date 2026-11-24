"""
The feedback log of the website: what a player does with a recommendation.

Each event is one row of feedback_events in feedback.db:

    details   the player clicked the row
    preview   the audio preview started
    open      the player opened the osu! page of the map

feedback.db is a separate file, because a rebuild replaces recommender.db.

A background thread then finds out if the player played the map. It reads the
scores that the app stored. A player who does not come back has no new scores.
Thus the thread also fetches the recent scores of the player one time, about
20 hours after the event. The osu! API returns the recent scores of the last
24 hours, so this fetch covers all the time since the event.

    played_at is set                          the player played the map
    played_at is NULL, checked_at is set      no play before checked_at
    played_at is NULL, checked_at is NULL     not known
"""

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from beatmap_recommender.content_similarity.core_modules.score_collector import (
    _fetch_paginated,
    store_player_scores,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_DB_PATH = Path(os.getenv("FEEDBACK_DB_PATH", PROJECT_ROOT / "beatmap_recommender/feedback.db"))
CONNECTION_TIMEOUT = 30

HOUR = 3600
# A play counts if it is at most this long after the event.
PLAY_WINDOW = 7 * 24 * HOUR
# The thread fetches the recent scores when an event is this old.
CHECK_DELAY = 20 * HOUR
# The osu! API returns the recent scores of this period.
RECENT_SCORES_WINDOW = 24 * HOUR
RECENT_SCORES_LIMIT = 1000
# The thread runs at this interval.
CHECK_INTERVAL = HOUR

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback_events (
    event_id INTEGER PRIMARY KEY,
    created_at REAL NOT NULL,           -- Unix time, as for all times in this table
    event_type TEXT NOT NULL,
    player_id INTEGER NOT NULL,         -- the logged-in player
    for_player_id INTEGER NOT NULL,     -- the player of the recommendations
    recommendation_id TEXT NOT NULL,
    position INTEGER NOT NULL,          -- 0 is the top recommendation
    beatmap_id TEXT NOT NULL,
    variant_id INTEGER NOT NULL,
    mods TEXT NOT NULL,
    final_score REAL,
    played_at REAL,
    played_mods TEXT,
    played_rank TEXT,                   -- F is a failed play
    checked_at REAL
);
"""


@contextmanager
def feedback_db():
    """Open a connection to feedback.db as one transaction, as auth_db() does."""
    conn = sqlite3.connect(FEEDBACK_DB_PATH, timeout=CONNECTION_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize_feedback_db():
    """Create the feedback table if it does not exist."""
    with feedback_db() as conn:
        conn.executescript(SCHEMA)


def log_event(recommender_conn, player_id, event, now=None):
    """
    Store one event (a FeedbackEvent dict of main.py). The map and the mods
    come from the database, not from the browser. Raise LookupError if the
    variant does not exist.
    """
    variant = recommender_conn.execute(
        "SELECT beatmap_id, mods FROM beatmap_variants WHERE variant_id = ?", (event["variant_id"],)
    ).fetchone()
    if variant is None:
        raise LookupError(f"Variant {event['variant_id']} was not found.")

    beatmap_id, mods = variant
    with feedback_db() as conn:
        conn.execute(
            """
            INSERT INTO feedback_events (
                created_at, event_type, player_id, for_player_id, recommendation_id,
                position, beatmap_id, variant_id, mods, final_score
            ) VALUES (
                :now, :event_type, :player_id, :for_player_id, :recommendation_id,
                :position, :beatmap_id, :variant_id, :mods, :final_score
            )
            """,
            {**event, "now": now or time.time(), "player_id": player_id, "beatmap_id": beatmap_id, "mods": mods},
        )


def fetch_recent_scores(recommender_conn, make_api, now):
    """Fetch the recent scores of each player who has an event of CHECK_DELAY or older."""
    # If an event is older than the window, the recent scores do not cover it.
    due = "checked_at IS NULL AND created_at > ? AND created_at <= ?"
    period = (now - RECENT_SCORES_WINDOW, now - CHECK_DELAY)

    with feedback_db() as conn:
        rows = conn.execute(f"SELECT DISTINCT player_id FROM feedback_events WHERE {due}", period).fetchall()

    api = make_api() if rows else None
    for (player_id,) in rows:
        try:
            scores = _fetch_paginated(api, f"/users/{player_id}/scores/recent", RECENT_SCORES_LIMIT)
            store_player_scores(recommender_conn, [], scores)
        except Exception:
            logger.exception("Player %s: the fetch of the recent scores failed.", player_id)
            continue

        with feedback_db() as conn:
            conn.execute(
                f"UPDATE feedback_events SET checked_at = ? WHERE player_id = ? AND {due}", (now, player_id, *period)
            )


def update_plays(recommender_conn, now):
    """Store the first play of the map after each event, if there is one."""

    def iso(timestamp):  # the format of scores.created_at
        return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with feedback_db() as conn:
        events = conn.execute(
            "SELECT * FROM feedback_events WHERE played_at IS NULL AND created_at > ?",
            # One more day, for the scores that arrive late.
            (now - PLAY_WINDOW - 24 * HOUR,),
        ).fetchall()

        for event in events:
            play = recommender_conn.execute(
                """
                SELECT CAST(strftime('%s', created_at) AS REAL), COALESCE(NULLIF(mods, ''), 'NM'), rank
                FROM scores
                WHERE player_id = ? AND beatmap_id = ? AND created_at > ? AND created_at <= ?
                ORDER BY created_at
                LIMIT 1
                """,
                (
                    event["player_id"],
                    event["beatmap_id"],
                    iso(event["created_at"]),
                    iso(event["created_at"] + PLAY_WINDOW),
                ),
            ).fetchone()
            if play is not None:
                conn.execute(
                    "UPDATE feedback_events SET played_at = ?, played_mods = ?, played_rank = ? WHERE event_id = ?",
                    (*play, event["event_id"]),
                )


def check_plays(connect, make_api, now=None):
    """Do one run of the background thread."""
    now = now or time.time()
    conn = connect()
    try:
        fetch_recent_scores(conn, make_api, now)
        update_plays(conn, now)
    finally:
        conn.close()


def start_feedback_thread(connect, make_api):
    """
    Start the background thread.

    connect: returns a read-write connection to the recommender database.
    make_api: returns an OsuAPIClient with low priority.
    """

    def run():
        while True:
            try:
                check_plays(connect, make_api)
            except Exception:
                logger.exception("The check of the feedback events failed.")
            time.sleep(CHECK_INTERVAL)

    threading.Thread(target=run, name="feedback", daemon=True).start()
