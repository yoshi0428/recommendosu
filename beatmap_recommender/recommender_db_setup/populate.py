import os
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from osu_tools import OsuCalculator
from tqdm import tqdm

from beatmap_recommender.recommender_db_setup.db_table_creation import create_tables, create_recommender_tables
from beatmap_recommender.recommender_db_setup.osu_api_client import OsuAPIClient
from beatmap_recommender.recommender_db_setup.parser import parse_osu_file
from beatmap_recommender.recommender_db_setup.beatmap_mods import calculate_difficulty
from beatmap_recommender.recommender_db_setup.db_insertion import (
    insert_variant,
    insert_base_beatmap,
    insert_variant_prediction_labels,
)

import hashlib


# ============================================================
# Configuration
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "beatmap_recommender/dummy.db"
ROOT_DIR = PROJECT_ROOT / "beatmap_recommender/data"
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

VARIANT_LABELS = {
    "2007": {
        "column": '"2007"',
        "mods": [],
    },
    "2008": {
        "column": '"2008"',
        "mods": [],
    },
    "2009": {
        "column": '"2009"',
        "mods": [],
    },
    "2010": {
        "column": '"2010"',
        "mods": [],
    },
    "2011": {
        "column": '"2011"',
        "mods": [],
    },
    "2012": {
        "column": '"2012"',
        "mods": [],
    },
    "2013": {
        "column": '"2013"',
        "mods": [],
    },
    "2014": {
        "column": '"2014"',
        "mods": [],
    },
    "2015": {
        "column": '"2015"',
        "mods": [],
    },
    "2016": {
        "column": '"2016"',
        "mods": [],
    },
    "2017": {
        "column": '"2017"',
        "mods": [],
    },
    "2018": {
        "column": '"2018"',
        "mods": [],
    },
    "2019": {
        "column": '"2019"',
        "mods": [],
    },
    "2020": {
        "column": '"2020"',
        "mods": [],
    },
    "2021": {
        "column": '"2021"',
        "mods": [],
    },
    "2022": {
        "column": '"2022"',
        "mods": [],
    },
    "2023": {
        "column": '"2023"',
        "mods": [],
    },
    "2024": {
        "column": '"2024"',
        "mods": [],
    },
    "2025": {
        "column": '"2025"',
        "mods": [],
    },
    "2026": {
        "column": '"2026"',
        "mods": [],
    },
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

def get_file_content_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def main():

    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL") # Change to NORMAL for more safety if needed
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -200000")

    create_tables(conn)

    # Initialize the API client in the main process for legacy lookup
    api_client = None
    try:
        api_client = OsuAPIClient()
        api_client.authenticate()
    except Exception as e:
        print(f"Warning: Failed to initialize OsuAPIClient: {e}. Will rely on fallback defaults.")

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

            try:
                beatmap_data = parse_osu_file(file_path)
            except Exception as e:
                print(f"\nPARSER HANG/ERROR on file: {file_path} | Error: {e}")
                skipped += 1
                continue

            if beatmap_data is None:
                skipped += 1
                continue

            # Compute the file content MD5 hash for lookup/fallback
            file_hash = get_file_content_md5(file_path)

            # If beatmap_id or essential difficulty attributes are missing, try querying the API via checksum
            if (beatmap_data["beatmap_id"] is None or beatmap_data["ar"] is None) and api_client is not None:
                try:
                    response_data = api_client.get("/beatmaps/lookup", params={"checksum": file_hash})
                    if response_data and "id" in response_data:
                        beatmap_data["beatmap_id"] = str(response_data["id"])
                        beatmap_data["beatmapset_id"] = str(response_data["beatmapset_id"])
                        if beatmap_data["ar"] is None:
                            beatmap_data["ar"] = response_data.get("ar", 8.0)
                except Exception:
                    pass  # Fallback to local handling if API query fails or is rate-limited

            # Fallbacks if still missing after API lookup
            if beatmap_data["beatmap_id"] is None:
                beatmap_data["beatmap_id"] = file_hash
            else:
                beatmap_data["beatmap_id"] = str(beatmap_data["beatmap_id"])

            beatmap_id = beatmap_data["beatmap_id"]
            beatmapset_id = beatmap_data["beatmapset_id"]

            if beatmap_data["ar"] is None:
                beatmap_data["ar"] = 8.0

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

            variant_label = os.path.basename(os.path.dirname(file_path))

            try:
                insert_base_beatmap(conn, beatmap_data, file_hash)

                # NOTE: WE DON'T NEED THIS FOR THE RECSYS
                # insert_vectors(conn, beatmap_id, beatmap_data["vectors"])

                # --------------------------------------------
                # Mod variants
                # --------------------------------------------
                for (variant_name, (mods, difficulty_result)) in variant_results.items():
                    variant_id, mods_string = insert_variant(conn, beatmap_id, beatmapset_id, mods, beatmap_data, difficulty_result)
                    insert_variant_prediction_labels(conn, variant_id, mods_string, variant_label, VARIANT_LABELS)

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
    create_recommender_tables(conn)
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