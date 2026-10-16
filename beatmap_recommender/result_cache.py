import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass

# Ranked results can hold millions of variants, so each player keeps at most
# one cached result and it expires after RESULT_TTL_SECONDS without access.
RESULT_TTL_SECONDS = 30 * 60


@dataclass
class CachedResult:
    player_id: int
    # Usually a VariantRows from rank_variants, which only builds the dicts
    # of the page being read; a result of millions of rows is then a few
    # numpy arrays rather than millions of dicts.
    rows: Sequence[dict]
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
    recommendations: Sequence[dict],
) -> None:
    """Cache a ranked result, replacing any earlier result for the player."""
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
            rows=recommendations,
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
        rows = result.rows

    return len(rows), list(rows[offset : offset + limit])
