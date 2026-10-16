"""
Check that a change to the recommender doesn't change its output.

Runs several recommendation requests offline and saves a hash of each full
result (every row, in order, with its keys in order). Save a snapshot before
the change, save another after it, then compare them:

    git stash
    PYTHONPATH=. python beatmap_recommender/benchmarks/snapshot_recommender.py save before.pkl
    git stash pop
    PYTHONPATH=. python beatmap_recommender/benchmarks/snapshot_recommender.py save after.pkl
    PYTHONPATH=. python beatmap_recommender/benchmarks/snapshot_recommender.py compare before.pkl after.pkl

Scores lose weight with age (see ability.py), so the clock is frozen at
FROZEN_NOW; otherwise two runs minutes apart would give slightly different
scores. Floats are compared by value, so a numpy float64 and a Python float
holding the same number count as equal.
"""

import argparse
import hashlib
import os
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# The recommender imports the OAuth module, which refuses to load without
# these. Scores aren't fetched here, so placeholders are enough.
for name in ("OSU_CLIENT_ID", "OSU_CLIENT_SECRET", "OSU_REDIRECT_URI"):
    os.environ.setdefault(name, "unused")

import beatmap_recommender.content_similarity.core_modules.ability as ability
from beatmap_recommender.api.model import RecommendationSettings
from beatmap_recommender.database import load_memory_db
from beatmap_recommender.recommender import recommend_player_sync

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Loaded into memory read-only, so the file itself is never modified.
DEFAULT_DB_PATH = PROJECT_ROOT / "beatmap_recommender/recommender.local.db"
DEFAULT_PLAYER_ID = 10961031

FROZEN_NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)

CASES = {
    # No star bounds and every mod: all ~3 million variants.
    "worst_balanced": {"min_stars": 0.0, "max_stars": float("inf")},
    # Same, through the pp_potential goal and its per-variant pp scoring.
    "worst_pp": {"min_stars": 0.0, "max_stars": float("inf"), "goal": "pp_potential"},
    "default": {},
    "filtered": {
        "mods": ["HD", "DT"],
        "excluded_mods": ["FL"],
        "beatmap_status": "ranked",
        "limit": 500,
    },
}


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW


def hash_rows(rows):
    # repr rather than pickle: pickle encodes a repeated object (such as one
    # shared "HDDT" string) differently from equal copies of it. repr of a
    # float is exact, so equal hashes still mean identical values.
    digest = hashlib.sha256()

    for row in rows:
        normalized = tuple(
            (key, float(value) if isinstance(value, float) else value) for key, value in row.items()
        )
        digest.update(repr(normalized).encode())

    return digest.hexdigest()


def save(path, db_path, player_id):
    ability.datetime = FrozenDatetime
    load_memory_db(db_path)
    snapshot = {}

    for name, overrides in CASES.items():
        start = time.perf_counter()
        rows = recommend_player_sync(
            RecommendationSettings(player_id=player_id, **overrides),
            update_scores=False,
        )
        elapsed = time.perf_counter() - start

        snapshot[name] = (len(rows), hash_rows(rows))
        print(f"{name}: {elapsed:.2f}s, {len(rows)} rows, sha256 {snapshot[name][1][:16]}")

    with open(path, "wb") as file:
        pickle.dump(snapshot, file)


def compare(before_path, after_path):
    with open(before_path, "rb") as file:
        before = pickle.load(file)
    with open(after_path, "rb") as file:
        after = pickle.load(file)

    identical = True

    for name in before.keys() | after.keys():
        if before.get(name) == after.get(name):
            print(f"{name}: identical")
        else:
            print(f"{name}: DIFFERENT ({before.get(name)} vs {after.get(name)})")
            identical = False

    return identical


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    save_parser = commands.add_parser("save", help="run every case and save the result hashes")
    save_parser.add_argument("path", type=Path)
    save_parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    save_parser.add_argument("--player-id", type=int, default=DEFAULT_PLAYER_ID)

    compare_parser = commands.add_parser("compare", help="compare two saved snapshots")
    compare_parser.add_argument("before", type=Path)
    compare_parser.add_argument("after", type=Path)

    args = parser.parse_args()

    if args.command == "save":
        save(args.path, args.db, args.player_id)
    elif not compare(args.before, args.after):
        sys.exit(1)


if __name__ == "__main__":
    main()
