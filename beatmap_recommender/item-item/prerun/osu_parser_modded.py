import os
import sqlite3
from osu_tools import OsuCalculator
from tqdm import tqdm
from .parser import parse_osu_file
from .beatmap_mods import calculate_difficulty
from .db_insertion import insert_tournament_prediction, insert_variant, insert_base_beatmap
from .db_table_creation import create_tables

# ============================================================
# Configuration
# ============================================================

DATABASE_PATH = "../../recommender.db"
ROOT_DIR = "../../data/<YEAR>"

MAX_SEQUENCE_LENGTH = 3502
MAX_SLIDER_LENGTH = 500.0
MAX_TIME_DIFF = 1000.0

# Variants we want available for recommendation.
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
    "dt2": {
        "column": "dt2_and_3",
        "mods": ["DT"],
    },
    "dt3": {
        "column": "dt2_and_3",
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

# Initialize once.
# This is important because OsuCalculator loads the .NET
# runtime and osu! difficulty calculation code.
star_calculator = OsuCalculator()

def main():

    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
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

    # --------------------------------------------------------
    # Processing
    # --------------------------------------------------------
    successful = 0
    skipped = 0
    failed_variants = 0

    for file_path in tqdm(osu_files, desc="Processing beatmaps"):

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

        variant_results = {}
        failed = False

        for variant_name, mods in MOD_VARIANTS.items():
            result = calculate_difficulty(file_path, mods, star_calculator)
            if result is None:
                failed_variants += 1
                failed = True
                break

            variant_results[variant_name] = (mods, result)

        if failed:
            skipped += 1
            continue

        try:
            with conn:
                insert_base_beatmap(conn, beatmap_data)

                # Mod variants
                for variant_name, (mods, result) in variant_results.items():
                    variant_id = insert_variant(conn, beatmap_id, mods, beatmap_data, result)
                    insert_tournament_prediction(conn, variant_id)

            successful += 1

        except Exception as exc:
            print(f"\nDATABASE ERROR: {file_path}")
            print(f"Beatmap ID: {beatmap_id}")
            print(f"Error: {exc}")
            skipped += 1

    conn.close()


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    main()