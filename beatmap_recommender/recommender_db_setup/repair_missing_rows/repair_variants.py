"""

    PASS 2

"""
import csv
import hashlib
import os
import sqlite3
from pathlib import Path

from osu_tools import OsuCalculator
from tqdm import tqdm

from beatmap_recommender.recommender_db_setup.parser import parse_osu_file
from beatmap_recommender.recommender_db_setup.beatmap_mods import (
    calculate_difficulty,
    get_modded_stats,
    apply_bpm_mod,
    apply_length_mod,
)
from beatmap_recommender.content_similarity.core_modules.mod_preferences import (
    canonicalize_mods,
)


# ============================================================
# Configuration
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATABASE_PATH = PROJECT_ROOT / "beatmap_recommender/dummy.db"
ROOT_DIR = PROJECT_ROOT / "beatmap_recommender/data"
CSV_PATH = PROJECT_ROOT / "beatmap_recommender/recommender_db_setup/repair_missing_rows/unfetchable_beatmaps_rows.csv"


# Copy/import the same MOD_VARIANTS dictionary used by your original population script.
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


# ============================================================
# Helpers
# ============================================================
def get_file_content_md5(file_path):
    hash_md5 = hashlib.md5()

    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)

    return hash_md5.hexdigest()


def load_corrections():
    with open(
        CSV_PATH,
        newline="",
        encoding="utf-8-sig",
    ) as f:
        reader = csv.DictReader(f)

        reader.fieldnames = [
            field.strip()
            for field in reader.fieldnames
        ]

        rows = list(reader)

    return rows


def build_variant_lookup():
    """
    Map canonical database mod strings to the original mod lists.

    This ensures that combinations such as HDDT are interpreted
    exactly as they were during the original population.
    """

    lookup = {}

    for variant_name, mods in MOD_VARIANTS.items():
        mods_string = canonicalize_mods(mods)

        if mods_string in lookup:
            raise RuntimeError(
                f"Duplicate canonical mod combination: {mods_string}"
            )

        lookup[mods_string] = mods

    return lookup


def find_osu_files(target_md5s):
    """
    Scan the existing .osu collection and retain only files
    whose content MD5 matches one of the affected beatmaps.
    """

    files_by_md5 = {}

    for dirpath, _, filenames in os.walk(ROOT_DIR):
        for filename in filenames:
            if not filename.lower().endswith(".osu"):
                continue

            file_path = os.path.join(dirpath, filename)
            file_md5 = get_file_content_md5(file_path)

            if file_md5 not in target_md5s:
                continue

            if file_md5 in files_by_md5:
                raise RuntimeError(
                    f"Multiple files have MD5 {file_md5}:\n"
                    f"{files_by_md5[file_md5]}\n"
                    f"{file_path}"
                )

            files_by_md5[file_md5] = file_path

    missing = target_md5s - files_by_md5.keys()

    if missing:
        raise RuntimeError(
            "Could not locate .osu files for these MD5 hashes:\n"
            + "\n".join(sorted(missing))
        )

    return files_by_md5


# ============================================================
# Recalculate variants
# ============================================================
def recalculate_variant(
    conn,
    variant,
    base_data,
    file_path,
    mods,
    star_calculator,
):
    """
    Recalculate and update one existing variant.

    Keeps variant_id and all relationships intact.
    """

    result = calculate_difficulty(
        file_path=file_path,
        mods=mods,
        star_calculator=star_calculator,
    )

    if result is None:
        raise RuntimeError(
            f"Difficulty calculation failed for "
            f"{file_path}, mods={mods}"
        )

    stats = get_modded_stats(
        base_data,
        result,
        mods,
    )

    (
        effective_bpm,
        effective_min_bpm,
        effective_max_bpm,
    ) = apply_bpm_mod(
        base_data["bpm"],
        base_data["min_bpm"],
        base_data["max_bpm"],
        mods,
    )

    effective_length = apply_length_mod(
        base_data["length_seconds"],
        mods,
    )

    cursor = conn.execute("""
        UPDATE beatmap_variants
        SET
            hp_drain = ?,
            circle_size = ?,
            od = ?,
            ar = ?,

            star_rating = ?,
            max_combo = ?,

            bpm = ?,
            min_bpm = ?,
            max_bpm = ?,

            length_seconds = ?,
            object_count = ?,

            pp = ?,
            pp_aim = ?,
            pp_speed = ?,
            pp_acc = ?,
            pp_flashlight = ?

        WHERE variant_id = ?
    """, (
        stats["hp_drain"],
        stats["circle_size"],
        stats["od"],
        stats["ar"],

        stats["star_rating"],
        stats["max_combo"],

        effective_bpm,
        effective_min_bpm,
        effective_max_bpm,

        effective_length,
        base_data["object_count"],

        stats["pp"],
        stats["pp_aim"],
        stats["pp_speed"],
        stats["pp_acc"],
        stats["pp_flashlight"],

        variant["variant_id"],
    ))

    if cursor.rowcount != 1:
        raise RuntimeError(
            f"Expected to update variant_id "
            f"{variant['variant_id']}, updated {cursor.rowcount}"
        )


# ============================================================
# Main
# ============================================================
def main():
    corrections = load_corrections()

    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        # ----------------------------------------------------
        # Build target IDs and verify Pass 1 has completed.
        # ----------------------------------------------------
        corrected_ids = {
            str(row["beatmap_id"]).strip()
            for row in corrections
        }

        if len(corrected_ids) != len(corrections):
            raise RuntimeError(
                "CSV contains duplicate corrected beatmap IDs"
            )

        placeholders = ",".join("?" for _ in corrected_ids)

        beatmaps = conn.execute(f"""
            SELECT
                beatmap_id,
                beatmapset_id,
                md5,
                hp_drain,
                circle_size,
                od,
                ar,
                bpm,
                min_bpm,
                max_bpm,
                length_seconds,
                object_count
            FROM beatmaps
            WHERE beatmap_id IN ({placeholders})
        """, tuple(sorted(corrected_ids))).fetchall()

        beatmaps_by_id = {
            row[0]: {
                "beatmap_id": row[0],
                "beatmapset_id": row[1],
                "md5": row[2],
                "hp_drain": row[3],
                "circle_size": row[4],
                "od": row[5],
                "ar": row[6],
                "bpm": row[7],
                "min_bpm": row[8],
                "max_bpm": row[9],
                "length_seconds": row[10],
                "object_count": row[11],
            }
            for row in beatmaps
        }

        missing_ids = corrected_ids - beatmaps_by_id.keys()

        if missing_ids:
            raise RuntimeError(
                "These corrected IDs are missing from beatmaps. "
                "Run Pass 1 first:\n"
                + "\n".join(sorted(missing_ids))
            )

        # ----------------------------------------------------
        # Verify base ARs match the CSV.
        # ----------------------------------------------------
        for row in corrections:
            beatmap_id = str(row["beatmap_id"]).strip()
            expected_ar = float(row["ar"])
            actual_ar = beatmaps_by_id[beatmap_id]["ar"]

            if actual_ar is None or abs(actual_ar - expected_ar) > 1e-6:
                raise RuntimeError(
                    f"AR mismatch for {beatmap_id}: "
                    f"database={actual_ar}, CSV={expected_ar}"
                )

        # ----------------------------------------------------
        # Locate source files by the preserved MD5.
        # ----------------------------------------------------
        target_md5s = {
            beatmap["md5"]
            for beatmap in beatmaps_by_id.values()
        }

        if None in target_md5s:
            raise RuntimeError(
                "At least one affected beatmap has no stored MD5"
            )

        files_by_md5 = find_osu_files(target_md5s)

        # ----------------------------------------------------
        # Load existing variants.
        # ----------------------------------------------------
        variants_by_id = {}

        for beatmap_id in corrected_ids:
            variants = conn.execute("""
                SELECT
                    variant_id,
                    beatmap_id,
                    mods
                FROM beatmap_variants
                WHERE beatmap_id = ?
                ORDER BY variant_id
            """, (beatmap_id,)).fetchall()

            variants_by_id[beatmap_id] = [
                {
                    "variant_id": row[0],
                    "beatmap_id": row[1],
                    "mods": row[2],
                }
                for row in variants
            ]

        variant_lookup = build_variant_lookup()

        # Validate the full batch before making any changes.
        for beatmap_id, variants in variants_by_id.items():
            for variant in variants:
                mods_string = variant["mods"]

                if mods_string not in variant_lookup:
                    raise RuntimeError(
                        f"Unknown mods string {mods_string!r} "
                        f"for beatmap {beatmap_id}, "
                        f"variant_id={variant['variant_id']}"
                    )

        # ----------------------------------------------------
        # Recalculate everything in one transaction.
        # ----------------------------------------------------
        total_variants = sum(
            len(variants)
            for variants in variants_by_id.values()
        )

        updated = 0

        conn.execute("BEGIN")

        star_calculator = OsuCalculator()

        for beatmap_id in tqdm(
            sorted(corrected_ids),
            desc="Recalculating beatmaps",
        ):
            base_data = beatmaps_by_id[beatmap_id]

            file_path = files_by_md5[base_data["md5"]]

            # Use the corrected database base AR and the existing base stats as the input to fallbacks.
            # Parse the file to validate that it is readable and corresponds to a usable beatmap.
            parsed_data = parse_osu_file(file_path)

            if parsed_data is None:
                raise RuntimeError(
                    f"Failed to parse {file_path}"
                )

            # Verify the file content still matches the checksum stored in the database.
            if get_file_content_md5(file_path) != base_data["md5"]:
                raise RuntimeError(
                    f"MD5 mismatch for {file_path}"
                )

            for variant in variants_by_id[beatmap_id]:
                mods = variant_lookup[variant["mods"]]

                recalculate_variant(
                    conn=conn,
                    variant=variant,
                    base_data=base_data,
                    file_path=file_path,
                    mods=mods,
                    star_calculator=star_calculator,
                )

                updated += 1

        # ----------------------------------------------------
        # Final integrity checks.
        # ----------------------------------------------------
        violations = conn.execute("""
            PRAGMA foreign_key_check
        """).fetchall()

        if violations:
            raise RuntimeError(
                "Foreign-key violations detected:\n"
                + "\n".join(map(str, violations[:20]))
            )

        conn.commit()

        print()
        print("=" * 60)
        print("Variant recalculation complete")
        print("=" * 60)
        print(f"Beatmaps processed: {len(corrected_ids)}")
        print(f"Variants updated:  {updated}/{total_variants}")

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()