"""
Store the CNN-XGBoost classifier's NM1-NM5 probabilities for every NM variant
in the recommender database (variant_predictions), and the outcome of each
attempt (classifier_prediction_status).

The classifier reads the hit objects from the variant's local .osu file
(found by its MD5) and its stats from the beatmap_variants row.
"""

import hashlib
import sqlite3
from pathlib import Path

from beatmap_classifier.classifier.inference import (
    UnclassifiableBeatmap,
    classify,
    load_classifier,
    read_vectors,
)

# ============================================================
# Configuration
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "beatmap_recommender/dummy.db"
DATA_ROOT = PROJECT_ROOT / "beatmap_recommender/data"

COMMIT_INTERVAL = 500

# Which NM variants to classify:
#     "pending" -> only variants with no status row yet
#     "failed"  -> pending + variants whose last attempt failed
#     "all"     -> every NM variant, overwriting existing predictions
#                  (use after training a new model)
SELECTION_MODE = "all"

VARIANT_FILTERS = {
    "pending": "s.variant_id IS NULL",
    "failed": "(s.variant_id IS NULL OR s.status = 'failed')",
    "all": "1 = 1",
}


# ============================================================
# Local files
# ============================================================
def index_osu_files(root_dir):
    """
    {MD5 of the file contents: path} for every .osu file under root_dir,
    the same files populate.py scans (including downloaders' *_1.osu
    copies), so every beatmap it inserted can be found by its md5.
    """
    index = {}
    paths = sorted(p for p in Path(root_dir).rglob("*") if p.suffix.lower() == ".osu")

    for i, path in enumerate(paths, start=1):
        index.setdefault(hashlib.md5(path.read_bytes()).hexdigest(), str(path))

        if i % 5000 == 0:
            print(f"Indexed {i:,}/{len(paths):,} files")

    print(f"Indexed {len(paths):,} .osu files ({len(index):,} distinct).")
    return index


# ============================================================
# Database
# ============================================================
def get_nm_variants(conn, mode):
    """NM variants to classify, filtered by `mode` (see SELECTION_MODE), with their beatmap's md5."""
    if mode not in VARIANT_FILTERS:
        raise ValueError(f"Unknown selection mode {mode!r}; expected one of {list(VARIANT_FILTERS)}")

    return conn.execute(
        f"""
        SELECT v.*, b.md5
        FROM beatmap_variants v
        JOIN beatmaps b
            ON b.beatmap_id = v.beatmap_id
        LEFT JOIN classifier_prediction_status s
            ON s.variant_id = v.variant_id
        WHERE v.mods = 'NM'
          AND {VARIANT_FILTERS[mode]}
        ORDER BY v.variant_id
        """
    ).fetchall()


def save_prediction(conn, variant_id, probabilities):
    """Save NM1-NM5 classifier probabilities."""
    conn.execute(
        """
        INSERT INTO variant_predictions (variant_id, nm1, nm2, nm3, nm4, nm5)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(variant_id) DO UPDATE SET
            nm1 = excluded.nm1,
            nm2 = excluded.nm2,
            nm3 = excluded.nm3,
            nm4 = excluded.nm4,
            nm5 = excluded.nm5
        """,
        (variant_id, *(probabilities.get(label, 0.0) for label in ("NM1", "NM2", "NM3", "NM4", "NM5"))),
    )


def clear_prediction(conn, variant_id):
    """
    Remove NM1-NM5 probabilities left over from a previous model,
    so a variant that now fails doesn't keep a stale prediction.
    """
    conn.execute(
        """
        UPDATE variant_predictions
        SET nm1 = NULL, nm2 = NULL, nm3 = NULL, nm4 = NULL, nm5 = NULL
        WHERE variant_id = ?
        """,
        (variant_id,),
    )


def save_status(conn, variant_id, status, error=None):
    """Insert or update classifier processing status."""
    conn.execute(
        """
        INSERT INTO classifier_prediction_status (variant_id, status, error)
        VALUES (?, ?, ?)
        ON CONFLICT(variant_id) DO UPDATE SET
            status = excluded.status,
            error = excluded.error
        """,
        (variant_id, status, error),
    )


# ============================================================
# Main precomputation
# ============================================================
def main():
    print(f"Selection mode: {SELECTION_MODE}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        variants = get_nm_variants(conn, SELECTION_MODE)
        total = len(variants)

        if total == 0:
            print("No NM variants require classifier prediction.")
            return

        print("Indexing local .osu files...")
        files_by_md5 = index_osu_files(DATA_ROOT)

        print("Loading classifier...")
        classifier = load_classifier()
        print(f"Loaded {len(classifier.cnn_models)} CNN models on {classifier.device}")

        successful = skipped = failed = 0

        for i, variant in enumerate(variants, start=1):
            variant_id = variant["variant_id"]
            print(f"[{i:,}/{total:,}] variant={variant_id} beatmap={variant['beatmap_id']}")
            file_path = files_by_md5.get(variant["md5"])

            try:
                if file_path is None:
                    raise FileNotFoundError(f"Local .osu file not found for md5 {variant['md5']}")

                print(f"  -> {file_path}")
                prediction = classify(classifier, read_vectors(file_path), variant)

                save_prediction(conn, variant_id, prediction["probabilities"])
                save_status(conn, variant_id, "success")
                successful += 1

                print(
                    f"  -> {prediction['label']} ("
                    + ", ".join(f"{label}={p:.3f}" for label, p in prediction["probabilities"].items())
                    + ")"
                )

            except UnclassifiableBeatmap as e:
                skipped += 1
                clear_prediction(conn, variant_id)
                save_status(conn, variant_id, "skipped", str(e))
                print(f"  -> SKIPPED: {e}")

            except Exception as e:
                failed += 1
                clear_prediction(conn, variant_id)
                error_message = f"{type(e).__name__}: {e}"
                save_status(conn, variant_id, "failed", error_message)
                print(f"  -> ERROR: {error_message}")

            if i % COMMIT_INTERVAL == 0:
                conn.commit()
                print(f"  -> Committed at {i:,}/{total:,}")

        conn.commit()
        print()
        print("=" * 60)
        print("Precomputation complete")
        print("=" * 60)
        print(f"Successful: {successful:,}")
        print(f"Skipped:    {skipped:,}")
        print(f"Failed:     {failed:,}")
        print(f"Total:      {total:,}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
