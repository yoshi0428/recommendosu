import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from beatmap_recommender.api.osu_api_client import OsuAPINotFoundError
from beatmap_recommender.recommender_db_setup.db_insertion import insert_score

logger = logging.getLogger(__name__)

# The maximum number of scores that osu! returns for one /users/{id}/scores/* request.
API_PAGE_SIZE = 100

# If the scores of a player were refreshed within this many seconds, the code
# does not refresh them again. For example, the player changes a setting and
# runs the recommender again. This saves 4 osu! API requests.
SCORE_REFRESH_INTERVAL = 120.0

# player_id -> time.monotonic() of the last successful refresh of the player.
_last_refreshed = {}
_last_refreshed_lock = threading.Lock()


def scores_refreshed_recently(player_id):
    """Return True if update_player_scores() succeeded for player_id in the last SCORE_REFRESH_INTERVAL."""
    with _last_refreshed_lock:
        refreshed_at = _last_refreshed.get(player_id)

    return refreshed_at is not None and time.monotonic() - refreshed_at < SCORE_REFRESH_INTERVAL


def _mark_refreshed(player_id):
    with _last_refreshed_lock:
        now = time.monotonic()
        _last_refreshed[player_id] = now

        # Delete the expired entries, so that the dict does not grow with each new player.
        for stale in [key for key, value in _last_refreshed.items() if now - value >= SCORE_REFRESH_INTERVAL]:
            del _last_refreshed[stale]


class PlayerNotFoundError(LookupError):
    """The osu! API has no public profile for this player ID."""

    def __init__(self, player_id):
        self.player_id = player_id
        super().__init__(
            f"osu! player {player_id} was not found. "
            "The ID may be wrong, or the account may be restricted."
        )


def fetch_player_scores(api, player_id, limit=200):
    """
    Fetch the top scores and the recent scores of a player from the osu! API.

    Returns:
        tuple[list, list]: top_scores, recent_scores

    Raises:
        PlayerNotFoundError: if osu! returns 404 for the player.
    """
    # The two lists do not depend on each other, so fetch them at the same
    # time. The shared rate limiter of the client still controls the requests.
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            top = executor.submit(_fetch_paginated, api, f"/users/{player_id}/scores/best", limit)
            recent = executor.submit(_fetch_paginated, api, f"/users/{player_id}/scores/recent", limit)
            return top.result(), recent.result()
    except OsuAPINotFoundError as exc:
        raise PlayerNotFoundError(player_id) from exc


def _fetch_paginated(api, endpoint, limit):
    """
    Fetch up to `limit` scores from a /users/{id}/scores/* endpoint.

    osu! returns API_PAGE_SIZE scores for each request at most. It lowers a
    larger limit without an error. Thus the code gets more scores page by
    page, with offset. The list of best scores stops at 200.

    Without a mode, osu! returns the scores of the default mode of the
    profile (for example mania). The database has only osu!standard maps,
    so each request asks for mode "osu".
    """
    scores = []
    while len(scores) < limit:
        page_size = min(API_PAGE_SIZE, limit - len(scores))
        page = api.get(
            endpoint,
            params={"limit": page_size, "offset": len(scores), "include_fails": 1, "mode": "osu"},
        )
        scores.extend(page)

        # A short page means that the list ended.
        if len(page) < page_size:
            break

    return scores


def normalize_score(score, source):
    """
    Change a score from the osu! API into the format of our database.

    Args:
        score: The score dict that the osu! API returned.
        source: "top" or "recent".

    Returns:
        A dict for insert_score().
    """
    beatmap = score.get("beatmap") or {}
    player_id = score.get("user_id")

    if player_id is None:
        player_id = (score.get("user") or {}).get("id")

    if player_id is None:
        raise ValueError(f"Score {score.get('id')} is missing player_id")

    beatmap_id = beatmap.get("id")
    if beatmap_id is None:
        raise ValueError(f"Score {score.get('id')} is missing beatmap_id")

    return {
        "score_id": str(score["id"]),
        "player_id": int(player_id),
        "beatmap_id": str(beatmap_id),
        "status": beatmap.get("status"),
        "score": score.get("score"),
        "max_combo": score.get("max_combo"),
        "accuracy": score.get("accuracy"),
        "pp": score.get("pp"),
        "rank": score.get("rank"),
        "mods": ",".join(score.get("mods") or []),
        "created_at": score.get("created_at"),
        "source": source,
    }


def store_player_scores(conn, top_scores, recent_scores):
    """
    Store the scores in the connected database. Skip a score if its beatmap
    is not in the beatmaps table. Return the number of stored scores.
    """
    all_scores = [(score, "top") for score in top_scores] + [(score, "recent") for score in recent_scores]
    to_insert = []

    for score, source in all_scores:
        normalized = normalize_score(score, source)

        exists = conn.execute("SELECT 1 FROM beatmaps WHERE beatmap_id = ?", (normalized["beatmap_id"],)).fetchone()

        if exists is None:
            logger.debug(
                "Skipping score %s: beatmap %s not found in beatmaps",
                normalized["score_id"],
                normalized["beatmap_id"],
            )
            continue

        to_insert.append(normalized)

    with conn:
        for normalized in to_insert:
            insert_score(conn, normalized)

    stored = len(to_insert)
    logger.info("Stored: %d, Skipped: %d", stored, len(all_scores) - stored)
    return stored


def update_player_scores(conn, api, player_id, limit=200):
    """
    Fetch and store the top scores and the recent scores of a player.

    The scores from earlier updates stay in the database. Thus each update
    adds to the score history of the player.

    The code remembers a successful update (see scores_refreshed_recently()).

    Returns:
        The number of stored score records.
    """

    top_scores, recent_scores = fetch_player_scores(api, player_id, limit=limit)
    stored = store_player_scores(conn, top_scores, recent_scores)
    _mark_refreshed(player_id)
    logger.info(
        "Player %s: %d top scores, %d recent scores, %d records processed.",
        player_id,
        len(top_scores),
        len(recent_scores),
        stored,
    )
    return stored
