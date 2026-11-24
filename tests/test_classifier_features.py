"""
Training/prediction consistency for the fusion classifier.

beatmap_classifier/train_fusion.py trains the model. It builds its inputs
from a classifier database (get_data() vectors, beatmap_variants rows) and
the .osu files of the maps. Later, beatmap_recommender/recommender_db_setup/
precompute_nm1-5.py makes the predictions for the website. It builds the same
inputs again with beatmap_classifier/classifier/inference.py, from the
recommender database and its own copies of the .osu files.

If the two do not agree (a different order, scale, stats...), the model gets
inputs that are unlike its training data. Nothing crashes, and the training
accuracy still looks good, because training never runs inference. The only
sign is worse NM1-NM5 probabilities on the site, without an error. This is
called *training/serving skew*, and a test like this one is the usual way to
find it.

How the test works, for one tournament map from each of NM1-NM5:
  * Training side: the functions of train_fusion.py on
    beatmap_classifier/curated_collection.db and beatmap_classifier/data.
  * Prediction side: inference.model_inputs() on the copy of the .osu file
    in the recommender and its beatmap_variants rows, as precompute does.
  * Compare the two.

Needs beatmap_classifier/curated_collection.db, beatmap_recommender/dummy.db,
the .osu files in beatmap_classifier/data and beatmap_recommender/data, and
torch. It is marked slow (the classifier database takes about 6s to load).
Run it with `pytest -m slow`.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")

import torch  # noqa: E402

from beatmap_classifier import train_fusion  # noqa: E402
from beatmap_classifier.classifier import fusion, inference  # noqa: E402
from beatmap_classifier.classifier.training_data import get_data, get_vector_normalization  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER_DB = PROJECT_ROOT / "beatmap_classifier" / "curated_collection.db"
CLASSIFIER_DATA = PROJECT_ROOT / "beatmap_classifier" / "data"
RECOMMENDER_DB = PROJECT_ROOT / "beatmap_recommender" / "dummy.db"
DATA = PROJECT_ROOT / "beatmap_recommender" / "data"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not (CLASSIFIER_DB.exists() and RECOMMENDER_DB.exists()),
        reason="beatmap_classifier/curated_collection.db or beatmap_recommender/dummy.db not found",
    ),
]

# One tournament map for each category, with the .osu file of the recommender and the MD5 of that file.
BEATMAPS = {
    "NM1": ("1001573", "64ac315bc3b8764cf0408acb8b10b2a3",
            "Ranked/2016/Cocoa, Chino, Rize, Chiya, Syaro, Maya, Megu - Honjitsu wa Makoto ni Rarirurein (Momochikun) [Extrarirurein].osu"),
    "NM2": ("1008079", "26afc4f44088aa14a5f1c6e502140a1e",
            "Ranked/2016/Kalmah - Swamphell (Mazzerin) [Possession].osu"),
    "NM3": ("1049018", "84850d4ae1540266da89324e0c1abd37",
            "Ranked/2016/Meramipop - Sanae-san (EvilElvis) [Behind you!].osu"),
    "NM4": ("1137171", "f1c0e50d0e5fea0b8f8ce1c7fc26b85d",
            "Loved/2018/SYUNN - Megalara Garuda (Callionet) [fanzhen0019].osu"),
    "NM5": ("1245365", "cca7413a6a826541c28c2a13e271d947",
            "Ranked/2017/xi - Glorious Crown (Monstrata) [NiNo's Extra].osu"),
}


# ---------------------------------------------------------------------------
# Loading both sides
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def training():
    """The data that train_fusion.load_dataset() builds the inputs of each map from. scope="module", because it takes seconds."""
    X, _, beatmap_ids = get_data(str(CLASSIFIER_DB))
    with sqlite3.connect(f"{CLASSIFIER_DB.as_uri()}?mode=ro", uri=True) as conn:
        vector_normalization = get_vector_normalization(conn.cursor())
    return {
        "vectors": dict(zip(map(str, beatmap_ids), X)),
        "stats": train_fusion.variant_stats(CLASSIFIER_DB, [b for b, _, _ in BEATMAPS.values()]),
        "files": {p.stem: p for p in CLASSIFIER_DATA.rglob("*.osu")},
        "vector_normalization": vector_normalization,
    }


@pytest.fixture(scope="module", params=list(BEATMAPS), ids=list(BEATMAPS))
def pair(request, training):
    """Return, for one beatmap, the inputs that training builds and the inputs that inference builds."""
    label = request.param
    beatmap_id, md5, relative_path = BEATMAPS[label]
    path = DATA / relative_path
    if not path.exists():
        pytest.skip(f"{relative_path} not found")
    assert hashlib.md5(path.read_bytes()).hexdigest() == md5, f"{relative_path} changed on disk"
    training_file = training["files"].get(beatmap_id)
    if training_file is None:
        pytest.skip(f"{beatmap_id}.osu not in beatmap_classifier/data")

    # Prediction side: the beatmap_variants rows that precompute passes.
    with sqlite3.connect(f"{RECOMMENDER_DB.as_uri()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        stats_by_mod = {
            row["mods"]: dict(row)
            for row in conn.execute("SELECT * FROM beatmap_variants WHERE beatmap_id = ?", (beatmap_id,))
            if row["mods"] in inference.STAT_MODS
        }
    classifier = inference.Classifier(
        models=[], classes=[], normalization={},
        vector_normalization=training["vector_normalization"], device=torch.device("cpu"),
    )
    pred_sequence, pred_tabular = inference.model_inputs(classifier, str(path), stats_by_mod)

    return {
        "label": label,
        "mods": set(stats_by_mod),
        "train_sequence": fusion.rich_sequence(training_file),
        "pred_sequence": pred_sequence,
        "train_tabular": fusion.tabular_row(training["stats"].get(beatmap_id, {}), training["vectors"][beatmap_id]),
        "pred_tabular": pred_tabular,
    }


def describe(names, train, pred, mismatched):
    return "\n".join(
        f"  {names[j]:30s} training={train[j]:.6g}  prediction={pred[j]:.6g}" for j in mismatched
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_saved_vector_normalization_matches_training():
    # get_data() calculates its scales from the training database. The copy that
    # is saved with the model must be the same. If not, inference scales the
    # vectors of the movement features differently from the training data.
    config_path = inference.MODEL_DIR / "fusion_config.json"
    if not config_path.exists():
        pytest.skip("no trained model in models/fusion")
    config = json.loads(config_path.read_text())
    db = Path(config["info"].get("db", ""))
    if not db.is_absolute():
        db = PROJECT_ROOT / db
    if not db.exists():
        pytest.skip(f"training database {db} not found")
    with sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True) as conn:
        assert config["vector_normalization"] == get_vector_normalization(conn.cursor())


def test_recommender_has_every_mod(pair):
    assert pair["mods"] == set(inference.STAT_MODS)


def test_rich_sequence_matches(pair):
    train, pred = pair["train_sequence"], pair["pred_sequence"]
    assert pred.shape == train.shape
    bad = [name for c, name in enumerate(fusion.RICH_CHANNELS) if not np.allclose(train[:, c], pred[:, c], rtol=1e-5, atol=1e-6)]
    assert not bad, f"{pair['label']}: rich channels differ: {bad}"


def test_tabular_features_match(pair):
    train, pred = pair["train_tabular"], pair["pred_tabular"]
    mismatched = np.flatnonzero(~np.isclose(train, pred, rtol=1e-4, atol=1e-6))
    assert not mismatched.size, "\n" + describe(fusion.TABULAR_FEATURES, train, pred, mismatched)
