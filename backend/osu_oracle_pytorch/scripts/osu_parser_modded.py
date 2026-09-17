import os
import sqlite3
from concurrent.futures import ProcessPoolExecutor

from osu_tools import OsuCalculator
from tqdm import tqdm

from db_table_creation import create_tables
from parser import parse_osu_file
from beatmap_mods import calculate_difficulty
from db_insertion import insert_variant, insert_augmentation, insert_vectors, insert_base_beatmap, insert_tournament_prediction


# ============================================================
# Configuration
# ============================================================

DATABASE_PATH = "../beatmaps.db"
ROOT_DIR = "../data"

MAX_SEQUENCE_LENGTH = 3502
MAX_SLIDER_LENGTH = 500.0
MAX_TIME_DIFF = 1000.0

# Number of worker processes.
# Start with something like 4 or 6.
# If your CPU has plenty of cores, try increasing this.
NUM_WORKERS = 8

# Number of beatmaps per SQLite transaction.
BATCH_SIZE = 2500

# Variants we want available for recommendation.
# The tournament labels themselves are NOT mods.
# Additional combinations can be added later if required.
MOD_VARIANTS = {
    "NM": [],
    "HD": ["HD"],
    "HR": ["HR"],
    "DT": ["DT"],
}

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

    # freemod is freaking weird, don't touch it for now
}

# ============================================================
# Worker State
# ============================================================
_worker_calculator = None

def init_worker():
    """
    Initialize one OsuCalculator per worker process.

    This prevents every individual calculation from having to
    initialize the .NET/osu! difficulty runtime.
    """
    global _worker_calculator
    _worker_calculator = OsuCalculator()

def process_difficulty(file_path):
    """
    Calculate all requested difficulty variants for one beatmap.
    This function runs inside a worker process.
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
    conn.execute("PRAGMA synchronous = OFF") # OFF instead of NORMAL because we can regenerate the data after a crash
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -200000")

    create_tables(conn)

    # --------------------------------------------------------
    # Collect .osu files
    # --------------------------------------------------------
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

    with ProcessPoolExecutor(
        max_workers=NUM_WORKERS,
        initializer=init_worker,
    ) as executor:

        # ----------------------------------------------------
        # Submit work to workers
        # executor.map() preserves input ordering, which makes
        # this relatively simple to reason about.
        # ----------------------------------------------------
        results = executor.map(process_difficulty, osu_files, chunksize=1)

        # ----------------------------------------------------
        # Process results
        # ----------------------------------------------------
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

            if beatmap_data["beatmap_id"] is None:
                skipped += 1
                continue

            if len(beatmap_data["vectors"]) > MAX_SEQUENCE_LENGTH:
                skipped += 1
                continue

            beatmap_id = beatmap_data["beatmap_id"]

            # specific to our setup here
            tournament_label = os.path.basename(os.path.dirname(file_path))

            # ------------------------------------------------
            # IMPORTANT:
            # We commit once per BATCH_SIZE maps.
            # ------------------------------------------------
            try:
                insert_base_beatmap(conn, beatmap_data)

                # --------------------------------------------
                # CNN vectors
                # --------------------------------------------
                insert_vectors(conn, beatmap_id, beatmap_data["vectors"])
                insert_augmentation(conn, beatmap_id, "original")
                insert_augmentation(conn, beatmap_id, "horizontal")
                insert_augmentation(conn, beatmap_id, "vertical")
                insert_augmentation(conn, beatmap_id, "horizontal_vertical")

                # --------------------------------------------
                # Mod variants
                # --------------------------------------------
                for variant_name, (mods, difficulty_result) in variant_results.items():
                    variant_id, mods_string = insert_variant(conn, beatmap_id, mods, beatmap_data, difficulty_result)
                    insert_tournament_prediction(conn, variant_id, mods_string, tournament_label, TOURNAMENT_LABELS)

                successful += 1

            except Exception as exc:
                print(f"\nDATABASE ERROR: {file_path}")
                print(f"Beatmap ID: {beatmap_id}")
                print(f"Error: {exc}")
                skipped += 1

            # ------------------------------------------------
            # Batch commit
            # ------------------------------------------------
            if processed % BATCH_SIZE == 0:
                conn.commit()

    # Final commit and close DB
    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()