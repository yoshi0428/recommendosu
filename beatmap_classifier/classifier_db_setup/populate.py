import argparse
import os
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from tqdm import tqdm

from beatmap_classifier.classifier_db_setup.db_insertion import (
    insert_base_beatmap,
    insert_tournament_prediction,
    insert_variant,
    insert_vectors,
)
from beatmap_classifier.classifier_db_setup.db_table_creation import create_tables
from beatmap_classifier.classifier_db_setup.parser import parse_osu_file
from beatmap_recommender.recommender_db_setup.beatmap_mods import calculate_difficulty
from beatmap_recommender.recommender_db_setup.star_calculator import VersionAwareOsuCalculator

CLASSIFIER_DIR = Path(__file__).resolve().parents[1]
DATABASE_PATH = CLASSIFIER_DIR / "expanded_collection.db"
ROOT_DIR = CLASSIFIER_DIR / "data"
VIEW_MULTICATEGORY_SQL = CLASSIFIER_DIR / "view_multicategory_maps.sql"
CLEAN_MULTICATEGORY_SQL = CLASSIFIER_DIR / "clean_multicategory_maps.sql"

NUM_WORKERS = 8
BATCH_SIZE = 2500


# The variants to store for each map: variant name -> mods.
MOD_VARIANTS = {
    "NM": [],
    "HD": ["HD"],
    "HR": ["HR"],
    "DT": ["DT"],
}

_worker_calculator = None


def init_worker():
    """
    Make one OsuCalculator for each worker process, so that the worker does
    not make a new calculator for each beatmap.
    """
    global _worker_calculator
    _worker_calculator = VersionAwareOsuCalculator()


def process_difficulty(file_path):
    """
    Calculate the difficulty of all the MOD_VARIANTS of one .osu file. This
    function runs in the worker processes. It does NOT use the database.
    """
    variant_results = {}
    for variant_name, mods in MOD_VARIANTS.items():
        result = calculate_difficulty(file_path, mods, _worker_calculator)

        if result is None:
            return {"success": False, "file_path": file_path}

        variant_results[variant_name] = (mods, result)

    return {
        "success": True,
        "file_path": file_path,
        "variant_results": variant_results,
    }


def main(database_path=DATABASE_PATH, root_dir=ROOT_DIR, keep_multicategory=False):
    """
    Parse all the .osu files under root_dir and store each map, its vectors,
    its MOD_VARIANTS and its tournament slot (the name of its folder).
    """
    conn = sqlite3.connect(database_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -200000")

    create_tables(conn)

    osu_files = [
        os.path.join(dirpath, filename)
        for dirpath, _, filenames in os.walk(root_dir)
        for filename in filenames
        if filename.lower().endswith(".osu")
    ]
    print(f"Found {len(osu_files)} .osu files.")

    successful = 0
    skipped = 0
    failed_variants = 0

    print(f"Starting {NUM_WORKERS} difficulty workers...")

    with ProcessPoolExecutor(max_workers=NUM_WORKERS, initializer=init_worker) as executor:
        results = executor.map(process_difficulty, osu_files, chunksize=1)

        for processed, result in enumerate(tqdm(results, total=len(osu_files), desc="Processing beatmaps"), 1):
            if not result["success"]:
                failed_variants += 1
                skipped += 1
                continue

            file_path = result["file_path"]
            variant_results = result["variant_results"]

            try:
                beatmap_data = parse_osu_file(file_path)
            except Exception as e:
                print(f"\nPARSER HANG/ERROR on file: {file_path} | Error: {e}")
                skipped += 1
                continue

            if beatmap_data is None:
                skipped += 1
                continue

            # downloader_backoff.py saves each map as <beatmap_id>.osu. Use that
            # ID, not the BeatmapID in the file: old maps do not have one, and
            # some maps set it to 0 (two NM5 maps once both had beatmap_id "0").
            beatmap_data["beatmap_id"] = Path(file_path).stem
            beatmap_id = beatmap_data["beatmap_id"]

            # The tournament label is the name of the directory that holds the
            # .osu file: data/NM1/map.osu -> NM1.

            tournament_label = os.path.basename(os.path.dirname(file_path))

            # One SAVEPOINT for each file. Thus a failed file rolls back only its
            # own rows, not all the files since the last commit.
            if not conn.in_transaction:
                conn.execute("BEGIN")

            conn.execute("SAVEPOINT beatmap")

            try:
                insert_base_beatmap(conn, beatmap_data)

                # The raw vectors, with no changes. The DT/HT change and the
                # normalization happen later, in training_data.get_data().
                insert_vectors(conn, beatmap_id, beatmap_data["vectors"])

                for mods, difficulty_result in variant_results.values():
                    variant_id, mods_string = insert_variant(
                        conn, beatmap_id, mods, beatmap_data, difficulty_result
                    )
                    insert_tournament_prediction(conn, variant_id, mods_string, tournament_label)

            except Exception as exc:
                conn.execute("ROLLBACK TO beatmap")
                conn.execute("RELEASE beatmap")
                print(f"\nERROR processing: {file_path}")
                print(f"Error: {exc}")
                skipped += 1
            else:
                conn.execute("RELEASE beatmap")
                successful += 1

            if processed % BATCH_SIZE == 0:
                conn.commit()
                print(
                    f"\nProgress: {processed}/{len(osu_files)} | successful={successful} | "
                    f"skipped={skipped} | failed_variants={failed_variants}"
                )

    conn.commit()

    # Delete the maps that are in more than one tournament slot (their label is not clear).
    view_sql = VIEW_MULTICATEGORY_SQL.read_text().strip().rstrip(";")
    multicategory_count = conn.execute(f"SELECT COUNT(*) FROM ({view_sql})").fetchone()[0]
    if not keep_multicategory:
        conn.executescript(CLEAN_MULTICATEGORY_SQL.read_text())
    conn.close()

    print()
    print("=" * 60)
    print("Processing complete")
    print("=" * 60)
    print(f"Total files:       {len(osu_files)}")
    print(f"Successful:        {successful}")
    print(f"Skipped:            {skipped}")
    print(f"Failed variants:   {failed_variants}")
    print(f"Multi-category:    {multicategory_count} ({'kept' if keep_multicategory else 'removed'})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a classifier database from .osu files in slot-named folders.")
    parser.add_argument("--db", type=Path, default=DATABASE_PATH, help=f"database to create/extend (default {DATABASE_PATH.name})")
    parser.add_argument(
        "--data-dir", type=Path, default=ROOT_DIR, help="root holding one folder per slot, e.g. NM1/123.osu (default data/)"
    )
    parser.add_argument(
        "--keep-multicategory",
        action="store_true",
        help="keep the maps pooled in several slots (train_fusion.py gives them each slot as a label). By default, they are removed.",
    )
    args = parser.parse_args()
    main(args.db.expanduser(), args.data_dir.expanduser(), args.keep_multicategory)
