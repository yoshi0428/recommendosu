"""
Time or profile one recommendation without calling the osu! API.

The default request is the worst case: no star-rating bounds and every mod
combination, so all ~3 million variants are scored. It uses the player's
scores already stored in the database (update_scores=False).

    # the time of each stage, from the logs, 2 runs
    PYTHONPATH=. python beatmap_recommender/benchmarks/profile_recommender.py

    # cProfile, sorted by cumulative time and by own time
    PYTHONPATH=. python beatmap_recommender/benchmarks/profile_recommender.py --cprofile

    # a typical request (the default settings), not the worst case
    PYTHONPATH=. python beatmap_recommender/benchmarks/profile_recommender.py --typical

cProfile adds a lot of overhead to code that makes millions of small calls,
so use it to find where the time goes and the plain timings to measure it.
"""

import argparse
import cProfile
import gc
import logging
import pstats
import sys
import time
from pathlib import Path

# common sets the placeholder credentials, so it must come before the recommender imports.
from beatmap_recommender.benchmarks.common import DEFAULT_DB_PATH, DEFAULT_PLAYER_ID  # isort: skip

from beatmap_recommender.api.model import RecommendationSettings
from beatmap_recommender.content_similarity.core_modules.variant_table import load_variant_table
from beatmap_recommender import database
from beatmap_recommender.recommender import recommend_player_sync

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

    database.DB_PATH = args.db

    # The server builds this at startup, so it is not part of a request.
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

        # Free the result of this run before the next one, as the server does
        # when a result expires. Thus one run does not slow down the next.
        del rows


if __name__ == "__main__":
    main()
