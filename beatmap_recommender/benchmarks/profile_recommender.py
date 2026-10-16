"""
Time or profile one recommendation without calling the osu! API.

The default request is the worst case: no star-rating bounds and every mod
combination, so all ~3 million variants are scored. It uses the player's
scores already stored in the database (update_scores=False).

    # per-stage timings from the logs, 2 runs
    PYTHONPATH=. python beatmap_recommender/benchmarks/profile_recommender.py

    # cProfile, sorted by cumulative and by own time
    PYTHONPATH=. python beatmap_recommender/benchmarks/profile_recommender.py --cprofile

    # a typical request (the default settings) instead of the worst case
    PYTHONPATH=. python beatmap_recommender/benchmarks/profile_recommender.py --typical

cProfile adds a lot of overhead to code that makes millions of small calls,
so use it to find where the time goes and the plain timings to measure it.
"""

import argparse
import cProfile
import gc
import logging
import os
import pstats
import sys
import time
from pathlib import Path

# The recommender imports the OAuth module, which refuses to load without
# these. Scores aren't fetched here, so placeholders are enough.
for name in ("OSU_CLIENT_ID", "OSU_CLIENT_SECRET", "OSU_REDIRECT_URI"):
    os.environ.setdefault(name, "unused")

from beatmap_recommender.api.model import RecommendationSettings
from beatmap_recommender.content_similarity.core_modules.variant_table import load_variant_table
from beatmap_recommender.database import load_memory_db
from beatmap_recommender.recommender import recommend_player_sync

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Loaded into memory read-only, so the file itself is never modified.
DEFAULT_DB_PATH = PROJECT_ROOT / "beatmap_recommender/recommender.local.db"
DEFAULT_PLAYER_ID = 10961031

WORST_CASE_SETTINGS = {
    "min_stars": 0.0,
    "max_stars": float("inf"),
    "mods": None,
    "excluded_mods": None,
    "beatmap_status": "all",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--player-id", type=int, default=DEFAULT_PLAYER_ID)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--cprofile", action="store_true", help="profile one run with cProfile")
    parser.add_argument("--typical", action="store_true", help="use the default settings instead of the worst case")
    parser.add_argument(
        "--no-gc",
        action="store_true",
        help="disable the cyclic garbage collector, to measure how much time it takes",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    start = time.perf_counter()
    load_memory_db(args.db)
    print(f"load_memory_db: {time.perf_counter() - start:.2f}s")

    # The server builds this at startup, so it isn't part of a request.
    start = time.perf_counter()
    load_variant_table()
    print(f"load_variant_table: {time.perf_counter() - start:.2f}s")

    settings = RecommendationSettings(
        player_id=args.player_id,
        **({} if args.typical else WORST_CASE_SETTINGS),
    )

    if args.no_gc:
        gc.disable()

    if args.cprofile:
        profiler = cProfile.Profile()
        start = time.perf_counter()
        profiler.enable()
        rows = recommend_player_sync(settings, update_scores=False)
        profiler.disable()
        print(f"recommend_player_sync: {time.perf_counter() - start:.2f}s ({len(rows)} rows)")

        stats = pstats.Stats(profiler, stream=sys.stdout)
        stats.sort_stats("cumulative").print_stats(35)
        stats.sort_stats("tottime").print_stats(25)
        return

    for run in range(args.runs):
        start = time.perf_counter()
        rows = recommend_player_sync(settings, update_scores=False)
        print(f"run {run}: {time.perf_counter() - start:.2f}s ({len(rows)} rows)")

        # Free this run's result before the next one, like the server does
        # once a result expires, so runs don't slow each other down.
        del rows


if __name__ == "__main__":
    main()
