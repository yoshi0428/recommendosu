import os
import sqlite3
from concurrent.futures import ProcessPoolExecutor

from osu_tools import OsuCalculator
from tqdm import tqdm

from db_table_creation import create_tables
from parser import parse_osu_file
from beatmap_mods import calculate_difficulty
from db_insertion import (
    insert_variant,
    insert_vectors,
    insert_base_beatmap,
    insert_tournament_prediction,
)


# ============================================================
# Configuration
# ============================================================

DATABASE_PATH = "../beatmaps.db"
ROOT_DIR = "../data"

NUM_WORKERS = 8
BATCH_SIZE = 2500


# ============================================================
# Mod variants
# ============================================================

MOD_VARIANTS = {
    "NM": [],
    "HD": ["HD"],
    "HR": ["HR"],
    "DT": ["DT"],
}

# ============================================================
# Tournament prediction labels
# ============================================================

# TOURNAMENT_LABELS = {
#     "aim": {
#         "column": "aim",
#         "mods": [],
#     },
#
#     "alt": {
#         "column": "alt",
#         "mods": [],
#     },
#
#     "stream": {
#         "column": "stream",
#         "mods": [],
#     },
#
#     "tech": {
#         "column": "tech",
#         "mods": [],
#     },
# }

TOURNAMENT_LABELS = {
    "nm1": {
        "column": "nm1",
        "mods": [],
    },

    "nm2": {
        "column": "nm2",
        "mods": [],
    },

    "nm3": {
        "column": "nm3",
        "mods": [],
    },

    "nm4": {
        "column": "nm4",
        "mods": [],
    },

    "nm5": {
        "column": "nm5",
        "mods": [],
    },

    "nm6": {
        "column": "nm6",
        "mods": [],
    },

    "dt1": {
        "column": "dt1",
        "mods": ["DT"],
    },

    "dt2_and_dt3": {
        "column": "dt2_and_dt3",
        "mods": ["DT"],
    },

    "dt4": {
        "column": "dt4",
        "mods": ["DT"],
    },

    "hr1": {
        "column": "hr1",
        "mods": ["HR"],
    },

    "hr2": {
        "column": "hr2",
        "mods": ["HR"],
    },

    "hr3": {
        "column": "hr3",
        "mods": ["HR"],
    },

    "hd1": {
        "column": "hd1",
        "mods": ["HD"],
    },

    "hd2": {
        "column": "hd2",
        "mods": ["HD"],
    },

    "hd3": {
        "column": "hd3",
        "mods": ["HD"],
    },

    "tiebreaker": {
        "column": "tiebreaker",
        "mods": [],
    },

    # Freemod intentionally omitted for now.
}

_worker_calculator = None

def init_worker():
    """
    Initialize one OsuCalculator per worker process.
    This avoids repeatedly constructing the calculator for every beatmap.
    """
    global _worker_calculator
    _worker_calculator = OsuCalculator()

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
            }

        variant_results[variant_name] = (mods, result)

    return {
        "success": True,
        "file_path": file_path,
        "variant_results": variant_results,
    }

def main():

    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = OFF") # Change to NORMAL for more safety if needed
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -200000")

    create_tables(conn)

    osu_files = []
    for dirpath, _, filenames in os.walk(ROOT_DIR):
        for filename in filenames:
            if filename.lower().endswith(".osu"):
                osu_files.append(os.path.join(dirpath, filename))
    print(f"Found {len(osu_files)} .osu files.")

    successful = 0
    skipped = 0
    failed_variants = 0

    print(f"Starting {NUM_WORKERS} difficulty workers...")

    with ProcessPoolExecutor(max_workers=NUM_WORKERS, initializer=init_worker) as executor:

        results = executor.map(process_difficulty, osu_files, chunksize=1)
        processed = 0

        for result in tqdm(results, total=len(osu_files), desc="Processing beatmaps"):
            processed += 1

            if not result["success"]:
                failed_variants += 1
                skipped += 1
                continue

            file_path = result["file_path"]
            variant_results = result["variant_results"]

            beatmap_data = parse_osu_file(file_path)

            if beatmap_data is None:
                skipped += 1
                continue

            beatmap_id = beatmap_data["beatmap_id"]

            if beatmap_id is None:
                skipped += 1
                continue

            # ------------------------------------------------
            # Tournament label
            #
            # Assumes the tournament label is the immediate
            # parent directory of the .osu file.
            #
            # Example:
            #
            # data/
            #   tournament_name/
            #       map.osu
            #
            # -> tournament_name
            # ------------------------------------------------

            tournament_label = os.path.basename(os.path.dirname(file_path))

            try:
                insert_base_beatmap(conn, beatmap_data)

                # --------------------------------------------
                # Raw vectors
                #
                # These should remain completely unmodified.
                # DT/HT transformation and normalization happen
                # later in the ML data pipeline.
                # --------------------------------------------
                insert_vectors(conn, beatmap_id, beatmap_data["vectors"])

                # --------------------------------------------
                # Mod variants
                # --------------------------------------------
                for (variant_name, (mods, difficulty_result)) in variant_results.items():
                    variant_id, mods_string = insert_variant(conn, beatmap_id, mods, beatmap_data, difficulty_result)
                    insert_tournament_prediction(conn, variant_id, mods_string, tournament_label, TOURNAMENT_LABELS)

                successful += 1

            except Exception as exc:
                conn.rollback()
                print(f"\nERROR processing: {file_path}")
                print(f"Error: {exc}")
                skipped += 1

            if processed % BATCH_SIZE == 0:
                conn.commit()
                print(f"\nProgress: {processed}/{len(osu_files)} | successful={successful} | skipped={skipped} | failed_variants={failed_variants}")

    conn.commit()
    conn.close()

    print()
    print("=" * 60)
    print("Processing complete")
    print("=" * 60)
    print(f"Total files:       {len(osu_files)}")
    print(f"Successful:        {successful}")
    print(f"Skipped:            {skipped}")
    print(f"Failed variants:   {failed_variants}")

if __name__ == "__main__":
    main()