"""
Train the fusion classifier (classifier/fusion.py) that inference.py and
precompute_nm1-5.py use.

    python -m beatmap_classifier.train_fusion

By default, it reads beatmap_classifier/expanded_collection.db and the .osu
files in beatmap_classifier/data/<SLOT>/. populate.py builds the database
from these files:

    python beatmap_classifier/classifier_db_setup/populate.py --keep-multicategory

(--keep-multicategory keeps the maps that are pooled in several slots. Without
it, these maps are deleted.) --db and --osu-dir select a different database
and its .osu files (searched recursively, named <beatmap_id>.osu). A map
without an NM1-NM5 slot is left out. A map in several of these slots gets
each slot as a label.

The script trains one model for each fold (5 folds, grouped by beatmapset).
It reports the out-of-fold top-1 accuracy (the top prediction is one of the
slots of the map), and saves all 5 models to --out. Inference averages them.
"""

import argparse
import re
import sqlite3
from pathlib import Path

import numpy as np
import torch
from sklearn.model_selection import GroupKFold

from beatmap_classifier.classifier import fusion
from beatmap_classifier.classifier.training_data import get_data, get_vector_normalization

CLASSIFIER_DIR = Path(__file__).resolve().parent
DEFAULT_DB = CLASSIFIER_DIR / "expanded_collection.db"
DEFAULT_OSU_DIR = CLASSIFIER_DIR / "data"
DEFAULT_OUT = CLASSIFIER_DIR / "models/fusion"
CLASSES = ["nm1", "nm2", "nm3", "nm4", "nm5"]
FOLDS = 5


def variant_stats(db_path, beatmap_ids):
    """Return {beatmap_id: {mod: {stat: value}}} for fusion.STAT_MODS."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    wanted = set(map(str, beatmap_ids))
    stats = {}
    for row in conn.execute("SELECT * FROM beatmap_variants"):
        if row["mods"] in fusion.STAT_MODS and str(row["beatmap_id"]) in wanted:
            stats.setdefault(str(row["beatmap_id"]), {})[row["mods"]] = dict(row)
    conn.close()
    return stats


def beatmapset_id(path):
    """Return the BeatmapSetID of the file, so that the difficulties of one mapset stay in one fold."""
    match = re.search(r"^BeatmapSetID\s*:\s*(-?\d+)", fusion._read_text(path), re.M)
    return match.group(1) if match and int(match.group(1)) > 0 else f"map-{Path(path).stem}"


def load_dataset(db_path, osu_dir, classes=CLASSES):
    """
    Return (rich sequences, tabular rows, multi-hot labels Y, beatmapset groups,
    beatmap IDs) for the maps with a slot in classes and a readable .osu file.
    """
    X, label_sets, beatmap_ids = get_data(str(db_path))
    files = {p.stem: p for p in Path(osu_dir).expanduser().rglob("*.osu")}
    stats = variant_stats(db_path, beatmap_ids)

    sequences, tabular, labels, groups, ids = [], [], [], [], []
    skipped = {"no slot in classes": 0, "no .osu file": 0, "unparseable": 0}
    for vectors, label_set, beatmap_id in zip(X, label_sets, beatmap_ids):
        y = [c for c in classes if c in label_set]
        path = files.get(str(beatmap_id))
        if not y:
            skipped["no slot in classes"] += 1
            continue
        if path is None:
            skipped["no .osu file"] += 1
            continue
        sequence = fusion.rich_sequence(path)
        if sequence is None or len(vectors) == 0:
            skipped["unparseable"] += 1
            continue
        sequences.append(sequence)
        tabular.append(fusion.tabular_row(stats.get(str(beatmap_id), {}), vectors))
        labels.append(y)
        groups.append(beatmapset_id(path))
        ids.append(str(beatmap_id))

    Y = np.zeros((len(ids), len(classes)), np.float32)
    for i, y in enumerate(labels):
        Y[i, [classes.index(c) for c in y]] = 1
    print(f"{len(ids):,} maps from {len(set(groups)):,} mapsets; skipped {skipped}")
    print(f"maps per slot: {dict(zip(classes, Y.sum(0).astype(int).tolist()))}; "
          f"in several slots: {(Y.sum(1) > 1).mean():.1%}")
    return sequences, np.array(tabular), Y, np.array(groups), ids


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="classifier database (default expanded_collection.db)")
    parser.add_argument("--osu-dir", type=Path, default=DEFAULT_OSU_DIR, help="its .osu files (default data/)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    np.random.seed(0)
    torch.manual_seed(0)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    sequences, tabular, Y, groups, ids = load_dataset(args.db, args.osu_dir)
    normalization = fusion.fit_normalization(sequences, tabular)
    batcher = fusion.Batcher(sequences, tabular, normalization, device)

    models, oof = [], np.zeros_like(Y)
    for k, (train_rows, val_rows) in enumerate(GroupKFold(n_splits=FOLDS).split(ids, groups=groups)):
        model = fusion.train(batcher, Y, train_rows, val_rows, log=f"fold {k + 1}/{FOLDS}")
        oof[val_rows] = fusion.predict([model], batcher, val_rows)
        models.append(model)

    hit = Y[np.arange(len(Y)), oof.argmax(1)] > 0
    single = Y.sum(1) == 1
    single_acc = float((oof[single].argmax(1) == Y[single].argmax(1)).mean())
    print(f"\nout-of-fold top-1 (top slot is one of the map's): {hit.mean():.4f}; "
          f"accuracy on single-slot maps: {single_acc:.4f}")
    for j, c in enumerate(CLASSES):
        rows = Y[:, j] > 0
        print(f"  {c.upper():5s} {rows.sum():6,d} maps  top-1 {hit[rows].mean():.4f}")

    with sqlite3.connect(f"file:{args.db}?mode=ro", uri=True) as conn:
        vector_normalization = get_vector_normalization(conn.cursor())
    fusion.save(
        args.out, models, [c.upper() for c in CLASSES], normalization, vector_normalization,
        info={"db": str(args.db), "maps": len(ids), "oof_top1": float(hit.mean()),
              "oof_single_slot_accuracy": single_acc},
    )
    np.savez(args.out / "oof_predictions.npz", beatmap_ids=np.array(ids), Y=Y, oof=oof)
    print(f"saved {len(models)} models to {args.out}")


if __name__ == "__main__":
    main()
