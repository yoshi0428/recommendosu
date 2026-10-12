import threading
import time
from dataclasses import dataclass

# Ranked results can hold millions of variants, so each player keeps at most
# one cached result and it expires after RESULT_TTL_SECONDS without access.
RESULT_TTL_SECONDS = 30 * 60


@dataclass
class CachedResult:
    player_id: int
    columns: list[str]
    # Rows are stored as tuples instead of dicts; at millions of rows the
    # per-dict overhead alone would be several GB.
    rows: list[tuple]
    last_access: float


_results: dict[str, CachedResult] = {}
_results_lock = threading.Lock()


def _evict_expired(now: float) -> None:
    expired = [
        recommendation_id
        for recommendation_id, result in _results.items()
        if now - result.last_access > RESULT_TTL_SECONDS
    ]

    for recommendation_id in expired:
        del _results[recommendation_id]


def store_result(
    recommendation_id: str,
    player_id: int,
    recommendations: list[dict],
) -> None:
    """Cache a ranked result, replacing any earlier result for the player."""
    columns = list(recommendations[0]) if recommendations else []

    # Every recommendation dict is built the same way, so values() follows columns.
    rows = [tuple(recommendation.values()) for recommendation in recommendations]

    now = time.monotonic()

    with _results_lock:
        _evict_expired(now)

        previous = [
            existing_id
            for existing_id, result in _results.items()
            if result.player_id == player_id
        ]

        for existing_id in previous:
            del _results[existing_id]

        _results[recommendation_id] = CachedResult(
            player_id=player_id,
            columns=columns,
            rows=rows,
            last_access=now,
        )


def get_result_page(
    recommendation_id: str,
    player_id: int,
    offset: int,
    limit: int,
) -> tuple[int, list[dict]] | None:
    """
    Return (total_count, recommendations) for one page of a cached result.

    Returns None if the result does not exist, has expired, or belongs to
    another player.
    """
    now = time.monotonic()

    with _results_lock:
        _evict_expired(now)

        result = _results.get(recommendation_id)

        if result is None or result.player_id != player_id:
            return None

        result.last_access = now
        columns = result.columns
        total_count = len(result.rows)
        page_rows = result.rows[offset : offset + limit]

    return total_count, [dict(zip(columns, row)) for row in page_rows]
