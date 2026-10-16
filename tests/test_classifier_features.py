"""
Training/prediction consistency for the CNN-XGBoost classifier.

The model is trained in beatmap_classifier/train_full.ipynb, which builds its
inputs with get_data() and get_additional_features() from
beatmap_classifier/classifier/utils_training.py. Predictions for the website
are made later by beatmap_recommender/recommender_db_setup/precompute_nm1-5.py,
which builds the same inputs again with its own code.

If the two disagree (different order, scaling, padding...) the model gets
inputs unlike anything it was trained on. Nothing crashes and the notebook's
accuracy still looks fine, because the notebook never runs precompute. The
only symptom is quietly worse NM1-NM5 probabilities on the site. This is
called *training/serving skew*, and a test like this is the standard way to
catch it.

How the test works:
  * Training side: run the real get_data() / get_additional_features() on
    beatmap_classifier/unexpanded_beatmaps.db, exactly like the notebook does.
  * Prediction side: run the real predict_beatmap() from precompute on the
    same map's .osu file, but with fake models that *record* the inputs they
    receive instead of predicting. That captures precisely what the real
    models would be fed.
  * Compare the two, for one tournament map from each of NM1-NM5.

Needs beatmap_classifier/unexpanded_beatmaps.db, beatmap_recommender/dummy.db, the .osu
files in beatmap_recommender/data, torch and osu-tools-py. Marked slow
(loading the classifier database takes ~6s); run with `pytest -m slow`.
"""

import hashlib
import importlib.util
import sqlite3
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("osu_tools")  # precompute imports the star calculator.

import torch  # noqa: E402

from beatmap_classifier.classifier.augment_faster import extract_movement_features_from_X  # noqa: E402
from beatmap_classifier.classifier.utils_training import (  # noqa: E402
    get_additional_features,
    get_data,
    get_vector_normalization,
    load_vector_normalization,
    pad_sequences_pt,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER_DB = PROJECT_ROOT / "beatmap_classifier" / "unexpanded_beatmaps.db"
RECOMMENDER_DB = PROJECT_ROOT / "beatmap_recommender" / "dummy.db"
PRECOMPUTE = PROJECT_ROOT / "beatmap_recommender" / "recommender_db_setup" / "precompute_nm1-5.py"
DATA = PROJECT_ROOT / "beatmap_recommender" / "data"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not (CLASSIFIER_DB.exists() and RECOMMENDER_DB.exists()),
        reason="beatmap_classifier/unexpanded_beatmaps.db or beatmap_recommender/dummy.db not found",
    ),
]

# One tournament map per category, with its .osu file and that file's MD5.
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

CNN_CHANNELS = [
    "x_diff", "y_diff", "time_diff", "length",
    "distance", "speed", "speed_change", "time_diff_change",
]


# ---------------------------------------------------------------------------
# Loading both sides
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def training():
    """
    Training inputs for every tournament map, built exactly like cells 6-10
    of train_full.ipynb. scope="module" because this takes several seconds
    and is the same for every test in the file.
    """
    X, y, beatmap_ids = get_data(str(CLASSIFIER_DB))
    raw_additional, _ = get_additional_features(str(CLASSIFIER_DB), y, beatmap_ids)

    # Cell 8: pad to the 99th-percentile length, rounded up to a power of 2.
    lengths = np.array([len(sequence) for sequence in X])
    max_length = int(np.percentile(lengths, 99))
    max_length = min(2 ** int(np.ceil(np.log2(max_length))), 4096)
    X_padded = pad_sequences_pt(X, maxlen=max_length, dtype=torch.float32)

    return {
        "index": {beatmap_id: i for i, beatmap_id in enumerate(beatmap_ids)},
        "X": X,
        "X_padded": X_padded,
        "max_length": max_length,
        "raw_additional": raw_additional,
    }


class RecordingCNN:
    """Stands in for one bagged CNN: records its input, returns flat logits."""

    def __init__(self):
        self.inputs = []

    def eval(self):
        return self

    def __call__(self, batch):
        self.inputs.append(batch.detach().cpu())
        return torch.zeros((batch.shape[0], 5))


class RecordingMetaModel:
    """Stands in for the XGBoost meta-model: records its input row."""

    def __init__(self):
        self.inputs = []

    def predict_proba(self, features):
        self.inputs.append(np.asarray(features))
        return np.full((1, 5), 0.2)


class FakeLabelEncoder:
    classes_ = np.array(["nm1", "nm2", "nm3", "nm4", "nm5"])

    def inverse_transform(self, indices):
        return self.classes_[indices]


@pytest.fixture(scope="module")
def precompute():
    # The file name contains a hyphen, so it can't be imported with a normal
    # `import` statement. importlib loads it from its path instead.
    spec = importlib.util.spec_from_file_location("precompute_nm1_5", PRECOMPUTE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module", params=list(BEATMAPS), ids=list(BEATMAPS))
def pair(request, training, precompute):
    """
    For one beatmap: what training fed the models, and what precompute
    feeds them. Parametrized fixture: every test using it runs once per map.
    """
    label = request.param
    beatmap_id, md5, relative_path = BEATMAPS[label]
    path = DATA / relative_path
    if not path.exists():
        pytest.skip(f"{relative_path} not found")
    assert hashlib.md5(path.read_bytes()).hexdigest() == md5, f"{relative_path} changed on disk"

    # Prediction side: the NM variant row as precompute's main() builds it.
    with sqlite3.connect(f"{RECOMMENDER_DB.as_uri()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        variant = dict(conn.execute(
            "SELECT * FROM beatmap_variants WHERE beatmap_id = ? AND mods = 'NM'", (beatmap_id,)
        ).fetchone())

    cnn, meta = RecordingCNN(), RecordingMetaModel()
    precompute.predict_beatmap(
        str(path), variant, [cnn], FakeLabelEncoder(), meta,
        load_vector_normalization(precompute.VECTOR_NORMALIZATION_PATH),
    )

    i = training["index"][beatmap_id]
    n = len(training["X"][i])
    cnn_input = cnn.inputs[0][0].T.numpy()  # [channels, length] -> [length, channels]

    return {
        "label": label,
        "n": n,
        "train_cnn": training["X_padded"][i].numpy(),
        "pred_cnn": cnn_input,
        "train_additional": np.hstack([
            np.asarray(training["raw_additional"][(beatmap_id, "NM")], dtype=np.float32),
            extract_movement_features_from_X(training["X_padded"][i]),
        ]),
        # Meta-model row = 5 CNN probabilities, then the additional features.
        "pred_additional": meta.inputs[0][0, 5:],
    }


def describe(names, train, pred, mismatched):
    return "\n".join(
        f"  {names[j]:20s} training={train[j]:.6g}  prediction={pred[j]:.6g}" for j in mismatched
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_saved_vector_normalization_matches_training(precompute):
    # get_data() computes its scales from unexpanded_beatmaps.db at training time.
    # The copy saved next to the model must be the same, or precompute
    # scales differently from the data the model learned on. (It would
    # drift if unexpanded_beatmaps.db changed without retraining and re-saving.)
    with sqlite3.connect(f"{CLASSIFIER_DB.as_uri()}?mode=ro", uri=True) as conn:
        expected = get_vector_normalization(conn.cursor())

    assert load_vector_normalization(precompute.VECTOR_NORMALIZATION_PATH) == expected


def test_sequence_length_matches(training, precompute):
    assert precompute.MAX_SEQUENCE_LENGTH == training["max_length"]


def test_feature_order_matches(precompute):
    # get_metadata's docstring says the order "MUST remain"; this checks it
    # against the order get_additional_features() returns.
    assert precompute.sql_feature_names == [
        "ar", "od", "circle_size", "star_rating", "bpm", "max_combo",
        "length_seconds", "object_count", "pp", "pp_aim", "pp_speed", "pp_acc",
    ]
    assert precompute.indices == list(range(24)), "precompute excludes features the model was trained with"


def test_metadata_features_match(pair, precompute):
    train, pred = pair["train_additional"][:12], pair["pred_additional"][:12]
    mismatched = np.flatnonzero(~np.isclose(train, pred, rtol=1e-5))
    names = precompute.additional_feature_names[:12]
    assert not mismatched.size, "\n" + describe(names, train, pred, mismatched)


def test_cnn_input_matches(pair):
    # Regression test: precompute used to feed the CNN raw milliseconds and
    # slider lengths, while training divided them by 86087 and 500.
    n = pair["n"]
    train, pred = pair["train_cnn"][:n], pair["pred_cnn"][:n]
    assert pred.shape == train.shape

    channel_ok = [np.allclose(train[:, c], pred[:, c], rtol=1e-4, atol=1e-6) for c in range(8)]
    bad = [CNN_CHANNELS[c] for c, ok in enumerate(channel_ok) if not ok]
    assert not bad, f"{pair['label']}: CNN channels differ: {bad}"


def test_movement_features_match(pair, precompute):
    train, pred = pair["train_additional"][12:], pair["pred_additional"][12:]
    mismatched = np.flatnonzero(~np.isclose(train, pred, rtol=1e-4, atol=1e-6))
    names = precompute.additional_feature_names[12:]
    assert not mismatched.size, "\n" + describe(names, train, pred, mismatched)
