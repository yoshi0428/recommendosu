"""
Populate the recommender database from the .osu files under data/<Status>/<Year>/.

Single pass:

    1. Scan every .osu file (md5, mode, BeatmapID). Non-osu!standard files are
       dropped here, before any difficulty calculation.
    2. Resolve each file's real beatmap ID (see beatmap_id_resolution.py):
       files with a missing, 0/-1 or shared BeatmapID go through the manual
       overrides CSV, then a seed DB, then the osu! API checksum lookup.
       Files that can't be resolved are logged and not inserted.
    3. Calculate all mod variants in worker processes and insert each file in
       its own SAVEPOINT, so one bad file can't roll back the rest of a batch.

Every file that needed resolution, was skipped, or failed is written to
populate_logs/populate_<timestamp>.csv.

Usage (from the project root):

    # check the ID resolution first; nothing is written to a database
    python -m beatmap_recommender.recommender_db_setup.populate --resolve-only --seed-db beatmap_recommender/dummy.db

    # repopulate into a fresh file, reusing dummy.db's already-resolved IDs
    python -m beatmap_recommender.recommender_db_setup.populate --db beatmap_recommender/fresh.db --seed-db beatmap_recommender/dummy.db

"""

import argparse
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from beatmap_recommender.recommender_db_setup.beatmap_id_resolution import (
    DEFAULT_OVERRIDES_PATH,
    LOG_FIELDS,
    ChecksumLookup,
    load_overrides,
    load_seed,
    resolve_beatmap_ids,
    scan_osu_files,
    write_log,
)
from beatmap_recommender.recommender_db_setup.beatmap_mods import calculate_difficulty
from beatmap_recommender.recommender_db_setup.db_insertion import (
    insert_base_beatmap,
    insert_variant,
)
from beatmap_recommender.recommender_db_setup.db_table_creation import (
    create_recommender_tables,
    create_tables,
)
from beatmap_recommender.recommender_db_setup.parser import parse_osu_file
from beatmap_recommender.recommender_db_setup.star_calculator import VersionAwareOsuCalculator

# ============================================================
# Configuration
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "beatmap_recommender/dummy.db"
ROOT_DIR = PROJECT_ROOT / "beatmap_recommender/data"
LOG_DIR = Path(__file__).resolve().parent / "populate_logs"
API_CACHE_PATH = LOG_DIR / "api_lookup_cache.json"
NUM_WORKERS = 8
BATCH_SIZE = 2500

MOD_VARIANTS = {
    "NM": [],
    "HD": ["HD"],
    "HR": ["HR"],
    "DT": ["DT"],
    "EZ": ["EZ"],
    "HT": ["HT"],
    "FL": ["FL"],
    "HDHR": ["HD", "HR"],
    "HDDT": ["HD", "DT"],
    "HDHRDT": ["HD", "HR", "DT"],
    "HRDT": ["HR", "DT"],
    "EZDT": ["EZ", "DT"],
    "EZHD": ["EZ", "HD"],
    "EZHT": ["EZ", "HT"],
    "HDHT": ["HD", "HT"],
    "HRHT": ["HR", "HT"],
    "HDHRFL": ["HD", "HR", "FL"],
    "HDFL": ["HD", "FL"],
    "HRFL": ["HR", "FL"],
    "DTFL": ["DT", "FL"],
}

_worker_calculator = None


def init_worker():
    """
    Initialize one OsuCalculator per worker process.
    This avoids repeatedly constructing the calculator for every beatmap.
    """
    global _worker_calculator
    _worker_calculator = VersionAwareOsuCalculator()


def process_difficulty(file_path):
    """
    Calculate all requested mod variants for one .osu file.
    This function runs inside worker processes.
    The database is NOT touched here.
    """
    global _worker_calculator
    variant_results = {}
    for variant_name, mods in MOD_VARIANTS.items():
        result = calculate_difficulty(file_path, mods, _worker_calculator)

        if result is None:
            return {
                "success": False,
                "file_path": file_path,
                "failed_variant": variant_name,
            }

        variant_results[variant_name] = (mods, result)

    return {
        "success": True,
        "file_path": file_path,
        "variant_results": variant_results,
    }


def make_api_client():
    # Imported lazily: osu_api_client requires credentials in .env at import time.
    from beatmap_recommender.recommender_db_setup.osu_api_client import OsuAPIClient

    client = OsuAPIClient()
    client.authenticate()
    return client


def insert_file(conn, file_path, result, resolution):
    """
    Insert one file and its variants inside a SAVEPOINT. Returns the outcome string.
    """
    if not result["success"]:
        return f"failed: difficulty calculation ({result['failed_variant']})"

    try:
        beatmap_data = parse_osu_file(file_path)
    except Exception as exc:
        return f"failed: parser error {type(exc).__name__}: {exc}"

    if beatmap_data is None:
        return "skipped: parser rejected file (not osu!standard)"

    beatmap_id = str(resolution["beatmap_id"])
    beatmapset_id = resolution["beatmapset_id"] or beatmap_data["beatmapset_id"]
    beatmap_data["beatmap_id"] = beatmap_id
    beatmap_data["beatmapset_id"] = beatmapset_id

    if beatmap_data["ar"] is None:
        # Pre-AR file formats: osu! uses OD as AR.
        beatmap_data["ar"] = resolution["ar"] if resolution["ar"] is not None else beatmap_data["od"]

    path = Path(file_path)
    year = int(path.parent.name.split()[0])
    status = path.parent.parent.name.lower()

    if not conn.in_transaction:
        conn.execute("BEGIN")

    conn.execute("SAVEPOINT beatmap")

    try:
        insert_base_beatmap(conn, beatmap_data, resolution["md5"], year, status)
        for mods, difficulty_result in result["variant_results"].values():
            insert_variant(conn, beatmap_id, beatmapset_id, year, status, mods, beatmap_data, difficulty_result)
    except Exception as exc:
        conn.execute("ROLLBACK TO beatmap")
        conn.execute("RELEASE beatmap")
        return f"failed: insert {type(exc).__name__}: {exc}"

    conn.execute("RELEASE beatmap")

    return "inserted"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DATABASE_PATH, help="database to populate")
    parser.add_argument("--data", type=Path, default=ROOT_DIR, help="root of the <Status>/<Year>/ .osu folders")
    parser.add_argument(
        "--seed-db",
        type=Path,
        default=None,
        help="existing DB to reuse resolved IDs from (opened read-only); saves API lookups",
    )
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES_PATH, help="manual md5 -> ID CSV")
    parser.add_argument("--api-cache", type=Path, default=API_CACHE_PATH)
    parser.add_argument("--resolve-only", action="store_true", help="scan + resolve + log, don't touch --db")
    parser.add_argument("--workers", type=int, default=NUM_WORKERS)
    args = parser.parse_args()

    log_path = LOG_DIR / f"populate_{datetime.now():%Y%m%d-%H%M%S}{'_resolve_only' if args.resolve_only else ''}.csv"

    # --------------------------------------------------------
    # 1. Scan
    # --------------------------------------------------------
    headers = scan_osu_files(args.data)
    standard = [h for h in headers if h["mode"] == 0]
    print(f"Found {len(headers):,} .osu files, {len(standard):,} osu!standard.")

    # --------------------------------------------------------
    # 2. Resolve IDs
    # --------------------------------------------------------
    seed = {}
    if args.seed_db is not None:
        seed_conn = sqlite3.connect(f"file:{args.seed_db}?mode=ro", uri=True)
        seed = load_seed(seed_conn)
        seed_conn.close()
        print(f"Seed DB: {len(seed):,} known md5s from {args.seed_db}")

    overrides = load_overrides(args.overrides)
    lookup = ChecksumLookup(args.api_cache, make_api_client)
    resolutions, log_rows = resolve_beatmap_ids(standard, lookup, overrides, seed)
    for md5, resolution in resolutions.items():
        resolution["md5"] = md5

    tasks = [h for h in standard if h["md5"] in resolutions]
    rejected = [h for h in standard if h["md5"] not in resolutions]
    print(f"Resolved {len(tasks):,} files, rejected {len(rejected):,} (see log).")

    def log_row(header, outcome):
        base = log_rows.get(header["md5"])
        row = dict(base) if base else {field: "" for field in LOG_FIELDS}
        resolution = resolutions.get(header["md5"], {})
        row.update(
            file=header["path"],
            md5=header["md5"],
            file_beatmap_id=header["file_beatmap_id"] or "",
            beatmap_id=row["beatmap_id"] or resolution.get("beatmap_id", ""),
            outcome=outcome or row["outcome"],
        )
        if not row["source"] and resolution:
            row["source"] = "file"
        return row

    final_rows = [log_row(h, None) for h in rejected]

    if args.resolve_only:
        final_rows += [log_row(h, "resolved") for h in tasks if h["md5"] in log_rows]
        write_log(final_rows, log_path)
        print(f"\nLog: {log_path}")
        return

    # --------------------------------------------------------
    # 3. Calculate + insert
    # --------------------------------------------------------
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -200000")

    create_tables(conn)

    inserted = 0
    failed = 0

    print(f"Starting {args.workers} difficulty workers...")

    try:
        with ProcessPoolExecutor(max_workers=args.workers, initializer=init_worker) as executor:
            results = executor.map(process_difficulty, [h["path"] for h in tasks], chunksize=1)

            for processed, (header, result) in enumerate(
                tqdm(zip(tasks, results), total=len(tasks), desc="Processing beatmaps"), start=1
            ):
                outcome = insert_file(conn, header["path"], result, resolutions[header["md5"]])

                if outcome == "inserted":
                    inserted += 1
                    if header["md5"] in log_rows:
                        final_rows.append(log_row(header, outcome))
                else:
                    failed += 1
                    final_rows.append(log_row(header, outcome))
                    print(f"\n{outcome}: {header['path']}")

                if processed % BATCH_SIZE == 0:
                    conn.commit()
                    print(f"\nProgress: {processed:,}/{len(tasks):,} | inserted={inserted:,} | failed={failed:,}")

        conn.commit()
        create_recommender_tables(conn)

    finally:
        conn.close()
        write_log(final_rows, log_path)

    print()
    print("=" * 60)
    print("Processing complete")
    print("=" * 60)
    print(f"osu!standard files: {len(standard):,}")
    print(f"Rejected (ID):      {len(rejected):,}")
    print(f"Inserted:           {inserted:,}")
    print(f"Failed:             {failed:,}")
    print(f"\nLog: {log_path}")


if __name__ == "__main__":
    main()
