"""

This file was needed to fix a database populated by the non-version aware OsuCalculator.
There shouldn't be a need to run this anymore, since the rest of the codebase uses VersionAwareOsuCalculator.

Recalculate calculator outputs (star rating, max combo, pp) for every beatmap whose .osu file is not format v14.

osu-tools-py used to decode every file as v14, so old maps (mostly 2007-2012) got modern stacking and inflated aim / star ratings.
See star_calculator.VersionAwareOsuCalculator.

Base stats (hp/cs/od/ar), bpm and length are not touched.

"""

import re
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from tqdm import tqdm

from beatmap_recommender.content_similarity.core_modules.mod_preferences import (
    canonicalize_mods,
)
from beatmap_recommender.recommender_db_setup.beatmap_mods import (
    calculate_difficulty,
    get_result_attribute,
)
from beatmap_recommender.recommender_db_setup.dot_osu_indexer import build_osu_file_index
from beatmap_recommender.recommender_db_setup.populate import MOD_VARIANTS
from beatmap_recommender.recommender_db_setup.star_calculator import VersionAwareOsuCalculator

# ============================================================
# Configuration
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATABASE_PATH = PROJECT_ROOT / "beatmap_recommender/dummy.db"
ROOT_DIR = PROJECT_ROOT / "beatmap_recommender/data"
NUM_WORKERS = 8
LATEST_FORMAT_VERSION = 14

FORMAT_VERSION_PATTERN = re.compile(rb"osu file format v(\d+)")

_worker_calculator = None


# ============================================================
# Helpers
# ============================================================
def get_format_version(file_path):
    """
    Read the "osu file format vN" header. Returns None if it can't be found
    (e.g. UTF-16 files), in which case the map is recalculated anyway.
    """
    with open(file_path, "rb") as f:
        head = f.read(256)

    match = FORMAT_VERSION_PATTERN.search(head)
    return int(match.group(1)) if match else None


def init_worker():
    global _worker_calculator
    _worker_calculator = VersionAwareOsuCalculator()


def process_beatmap(task):
    beatmap_id, file_path, variants = task
    rows = []

    for variant_id, mods in variants:
        result = calculate_difficulty(file_path, mods, _worker_calculator)

        if result is None:
            return beatmap_id, None

        rows.append(
            (
                get_result_attribute(result, "stars", "star_rating"),
                get_result_attribute(result, "max_combo"),
                get_result_attribute(result, "pp"),
                get_result_attribute(result, "pp_aim"),
                get_result_attribute(result, "pp_speed"),
                get_result_attribute(result, "pp_acc"),
                get_result_attribute(result, "pp_flashlight"),
                variant_id,
            )
        )

    return beatmap_id, rows


# ============================================================
# Main
# ============================================================
def main():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        by_beatmap_id, _ = build_osu_file_index(ROOT_DIR, conn)

        targets = {
            beatmap_id: file_path
            for beatmap_id, file_path in by_beatmap_id.items()
            if get_format_version(file_path) != LATEST_FORMAT_VERSION
        }

        print(f"Beatmaps with pre-v{LATEST_FORMAT_VERSION} files: {len(targets):,}")

        mods_by_string = {canonicalize_mods(mods): mods for mods in MOD_VARIANTS.values()}

        variants_by_beatmap = {}
        for variant_id, beatmap_id, mods_string in conn.execute(
            "SELECT variant_id, beatmap_id, mods FROM beatmap_variants"
        ):
            if beatmap_id not in targets:
                continue

            if mods_string not in mods_by_string:
                raise RuntimeError(f"Unknown mods string {mods_string!r} for variant_id={variant_id}")

            variants_by_beatmap.setdefault(beatmap_id, []).append((variant_id, mods_by_string[mods_string]))

        old_stars = dict(
            conn.execute(
                "SELECT variant_id, star_rating FROM beatmap_variants WHERE mods = 'NM'"
            ).fetchall()
        )

        tasks = [
            (beatmap_id, targets[beatmap_id], variants)
            for beatmap_id, variants in sorted(variants_by_beatmap.items())
        ]

        updated = 0
        changed_beatmaps = []
        failed = []

        conn.execute("BEGIN")

        with ProcessPoolExecutor(max_workers=NUM_WORKERS, initializer=init_worker) as executor:
            results = executor.map(process_beatmap, tasks, chunksize=16)

            for (beatmap_id, rows), (_, _, variants) in tqdm(
                zip(results, tasks), total=len(tasks), desc="Recalculating beatmaps"
            ):
                if rows is None:
                    failed.append(beatmap_id)
                    continue

                nm_variant_id = next(variant_id for variant_id, mods in variants if not mods)
                new_nm_stars = next(row[0] for row in rows if row[-1] == nm_variant_id)
                if abs(new_nm_stars - old_stars[nm_variant_id]) > 1e-6:
                    changed_beatmaps.append((beatmap_id, old_stars[nm_variant_id], new_nm_stars))

                conn.executemany(
                    """
                    UPDATE beatmap_variants
                    SET
                        star_rating = ?,
                        max_combo = ?,
                        pp = ?,
                        pp_aim = ?,
                        pp_speed = ?,
                        pp_acc = ?,
                        pp_flashlight = ?
                    WHERE variant_id = ?
                """,
                    rows,
                )
                updated += len(rows)

        conn.commit()

        print()
        print("=" * 60)
        print("Legacy format recalculation complete")
        print("=" * 60)
        print(f"Beatmaps processed:     {len(tasks):,}")
        print(f"Variants updated:       {updated:,}")
        print(f"Beatmaps with NM change: {len(changed_beatmaps):,}")
        print(f"Failed beatmaps:        {len(failed):,}")

        for beatmap_id, old, new in sorted(changed_beatmaps, key=lambda c: -abs(c[2] - c[1]))[:20]:
            print(f"  {beatmap_id}: {old:.3f} -> {new:.3f}")

        if failed:
            print("Failed:", ", ".join(failed[:50]))

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()
