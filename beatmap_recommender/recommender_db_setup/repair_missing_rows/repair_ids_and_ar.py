"""

    PASS 1

"""
import csv
import sqlite3
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DB_PATH = PROJECT_ROOT / "beatmap_recommender/dummy.db"
CSV_PATH = PROJECT_ROOT / "beatmap_recommender/recommender_db_setup/repair_missing_rows/unfetchable_beatmaps_rows.csv"


def migrate_beatmap_ids():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")

    cursor = conn.cursor()

    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=",")

        reader.fieldnames = [
            field.strip()
            for field in reader.fieldnames
        ]

        print("CSV fieldnames:")
        print([repr(field) for field in reader.fieldnames])

        corrections = list(reader)

    try:
        conn.execute("BEGIN")

        for row in corrections:
            old_beatmap_id = str(row["old_beatmap_id"]).strip()
            new_beatmap_id = str(row["beatmap_id"]).strip()
            new_beatmapset_id = str(row["beatmapset_id"]).strip() or None
            new_ar = float(row["ar"])

            print(
                f"old={old_beatmap_id!r}, "
                f"new={new_beatmap_id!r}, "
                f"set={new_beatmapset_id!r}, "
                f"ar={new_ar!r}"
            )

            # ------------------------------------------------
            # Verify old row exists.
            # ------------------------------------------------
            existing = cursor.execute("""
                SELECT
                    beatmap_id,
                    beatmapset_id,
                    ar
                FROM beatmaps
                WHERE beatmap_id = ?
            """, (old_beatmap_id,)).fetchone()

            if existing is None:
                raise RuntimeError(
                    f"Could not find old beatmap_id: "
                    f"{old_beatmap_id}"
                )

            # ------------------------------------------------
            # Make sure corrected ID doesn't already exist.
            # ------------------------------------------------
            collision = cursor.execute("""
                SELECT 1
                FROM beatmaps
                WHERE beatmap_id = ?
            """, (new_beatmap_id,)).fetchone()

            if collision:
                raise RuntimeError(
                    f"Corrected beatmap_id already exists: "
                    f"{new_beatmap_id}\n"
                    f"Existing row: {collision}"
                )

            # ------------------------------------------------
            # Sanity-check that this is one of the fallback rows we expect to repair.
            # ------------------------------------------------
            if existing[1] is not None:
                raise RuntimeError(
                    f"{old_beatmap_id}: expected NULL beatmapset_id, "
                    f"got {existing[1]}"
                )

            if existing[2] != new_ar:
                print(
                    f"  AR correction: {existing[2]} -> {new_ar}"
                )

            # ------------------------------------------------
            # Check for variant collisions.
            # ------------------------------------------------
            variant_collision = cursor.execute("""
                SELECT v.mods
                FROM beatmap_variants AS v
                WHERE v.beatmap_id = ?
                  AND EXISTS (
                      SELECT 1
                      FROM beatmap_variants AS existing
                      WHERE existing.beatmap_id = ?
                        AND existing.mods = v.mods
                  )
            """, (
                old_beatmap_id,
                new_beatmap_id,
            )).fetchall()

            if variant_collision:
                mods = [row[0] for row in variant_collision]

                raise RuntimeError(
                    f"{old_beatmap_id} -> {new_beatmap_id}: "
                    f"variant collision for mods {mods}"
                )

            # ------------------------------------------------
            # Temporary ID.
            # This preserves the foreign key while changing the primary key.
            # ------------------------------------------------
            temp_id = f"__migration__{uuid.uuid4().hex}"

            cursor.execute("""
                UPDATE beatmaps
                SET beatmap_id = ?
                WHERE beatmap_id = ?
            """, (
                temp_id,
                old_beatmap_id,
            ))

            cursor.execute("""
                UPDATE beatmap_variants
                SET beatmap_id = ?
                WHERE beatmap_id = ?
            """, (
                temp_id,
                old_beatmap_id,
            ))

            # ------------------------------------------------
            # Set corrected base beatmap information.
            # ------------------------------------------------
            cursor.execute("""
                UPDATE beatmaps
                SET
                    beatmap_id = ?,
                    beatmapset_id = ?,
                    ar = ?
                WHERE beatmap_id = ?
            """, (
                new_beatmap_id,
                new_beatmapset_id,
                new_ar,
                temp_id,
            ))

            # ------------------------------------------------
            # Move variants to corrected beatmap ID/set ID.
            # Their calculated statistics are deliberately untouched in this pass.
            # ------------------------------------------------
            cursor.execute("""
                UPDATE beatmap_variants
                SET
                    beatmap_id = ?,
                    beatmapset_id = ?
                WHERE beatmap_id = ?
            """, (
                new_beatmap_id,
                new_beatmapset_id,
                temp_id,
            ))

        # ----------------------------------------------------
        # Verify FK integrity.
        # ----------------------------------------------------
        violations = cursor.execute("""
            PRAGMA foreign_key_check
        """).fetchall()

        if violations:
            raise RuntimeError(
                "Foreign-key violations detected:\n"
                + "\n".join(map(str, violations[:20]))
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    migrate_beatmap_ids()