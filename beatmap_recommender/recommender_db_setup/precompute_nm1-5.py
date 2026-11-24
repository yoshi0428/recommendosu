"""
Store the NM1-NM5 probabilities of the fusion classifier for each NM variant
in the recommender database (variant_predictions), and the outcome of each
attempt (classifier_prediction_status).

The classifier reads the hit objects from the local .osu file of the variant
(found by its MD5), and the stats from the NM/HD/HR/DT beatmap_variants rows
of the beatmap.
"""

import hashlib
import sqlite3
from pathlib import Path

from beatmap_classifier.classifier.inference import (
    STAT_MODS,
    UnclassifiableBeatmap,
    classify,
    load_classifier,
)
from beatmap_recommender.content_similarity.core_modules.classifier_influence import NM_LABELS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "beatmap_recommender/recommender.local.db"
DATA_ROOT = PROJECT_ROOT / "beatmap_recommender/data"

COMMIT_INTERVAL = 500

# The NM variants to classify:
#     "pending" -> only the variants with no status row yet
#     "failed"  -> pending + the variants whose last attempt failed
#     "all"     -> all the NM variants. This overwrites the existing
#                  predictions (use it after you train a new model).
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
    Return {MD5 of the file contents: path} for each .osu file under root_dir.
    These are the same files that populate.py scans (also the *_1.osu copies
    from the downloaders), so the code can find each inserted beatmap by its md5.
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
    """Return the NM variants to classify, filtered by `mode` (see SELECTION_MODE), with the md5 of their beatmap."""
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


def get_stats_by_mod(conn, beatmap_id):
    """Return {mod: beatmap_variants row} of the beatmap, for the mods that the classifier reads."""
    rows = conn.execute(
        f"""
        SELECT *
        FROM beatmap_variants
        WHERE beatmap_id = ?
          AND mods IN ({", ".join("?" * len(STAT_MODS))})
        """,
        (beatmap_id, *STAT_MODS),
    ).fetchall()
    return {row["mods"]: dict(row) for row in rows}


def save_prediction(conn, variant_id, probabilities):
    """Save the NM1-NM5 probabilities of the classifier."""
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
        (variant_id, *(probabilities.get(label, 0.0) for label in NM_LABELS)),
    )


def clear_prediction(conn, variant_id):
    """
    Remove the NM1-NM5 probabilities of a previous model, so that a variant
    that fails now does not keep an old prediction.
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
    """Insert or update the classifier status of the variant."""
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


def main():
    """Classify the selected NM variants, and store each result and status."""
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
        print(f"Loaded {len(classifier.models)} fusion models on {classifier.device}")

        successful = skipped = failed = 0

        for i, variant in enumerate(variants, start=1):
            variant_id = variant["variant_id"]
            print(f"[{i:,}/{total:,}] variant={variant_id} beatmap={variant['beatmap_id']}")
            file_path = files_by_md5.get(variant["md5"])

            try:
                if file_path is None:
                    raise FileNotFoundError(f"Local .osu file not found for md5 {variant['md5']}")

                print(f"  -> {file_path}")
                prediction = classify(classifier, file_path, get_stats_by_mod(conn, variant["beatmap_id"]))

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
