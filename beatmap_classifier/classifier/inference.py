"""
Running the trained CNN-XGBoost classifier on one beatmap.

Used by beatmap_recommender/recommender_db_setup/precompute_nm1-5.py (every
NM variant in the recommender database) and beatmap_classifier/test_model.py
(one map at a time). Its inputs must match how train_full.ipynb built the
training data; tests/test_classifier_features.py checks that they do.
"""

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from beatmap_classifier.classifier.augment_faster import extract_movement_features_from_X
from beatmap_classifier.classifier.cnn_model import CNNModel
from beatmap_classifier.classifier.utils_training import (
    load_pytorch_models,
    load_vector_normalization,
    normalize_beatmap_vectors,
    pad_sequences_pt,
)
from beatmap_classifier.classifier_db_setup.parser import parse_osu_file

MODEL_DIR = Path(__file__).resolve().parents[1] / "models/full"

# train_full.ipynb pads and cuts every map to this many vectors.
MAX_SEQUENCE_LENGTH = 4096
# Longer sliders are dropped by the parser, as when the training data was built.
MAX_SLIDER_LENGTH = 500.0
NUM_CLASSES = 5

# The meta-model's input after the 5 CNN probabilities, in training order:
# the variant's stats (get_additional_features()), then the movement features
# (extract_movement_features_from_X()).
SQL_FEATURE_NAMES = [
    "ar",
    "od",
    "circle_size",
    "star_rating",
    "bpm",
    "max_combo",
    "length_seconds",
    "object_count",
    "pp",
    "pp_aim",
    "pp_speed",
    "pp_acc",
]

MOVEMENT_FEATURE_NAMES = [
    "slider_ratio",
    "slider_length_std",
    "speed_std",
    "speed_change_std",
    "speed_change_max",
    "angle_std",
    "angle_mean",
    "rhythm_variance",
    "distance_mean",
    "speed_change_95th",
    "angle_90th",
    "sharp_turn_ratio",
]

ADDITIONAL_FEATURE_NAMES = SQL_FEATURE_NAMES + MOVEMENT_FEATURE_NAMES


class UnclassifiableBeatmap(Exception):
    """Map parsed fine but has no usable hit objects (empty, all spinners, all filtered sliders)."""


@dataclass
class Classifier:
    cnn_models: list
    label_encoder: object
    meta_model: object
    # The scales training divided time_diff / slider length by (see get_data()).
    vector_normalization: dict
    device: torch.device


def load_classifier(model_dir=MODEL_DIR, device=None):
    """Load the bagged CNNs, the XGBoost meta-model and what they need from model_dir."""
    model_dir = Path(model_dir)
    device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")

    with open(model_dir / "label_encoder.pkl", "rb") as f:
        label_encoder = pickle.load(f)

    with open(model_dir / "meta_model.pkl", "rb") as f:
        meta_model = pickle.load(f)

    model_kwargs = {
        "input_channels": 8,
        "num_classes": NUM_CLASSES,
        "max_length": MAX_SEQUENCE_LENGTH,
        "dropout_rate": 0.5,
    }
    cnn_models = load_pytorch_models(model_dir / "bagged_models", CNNModel, model_kwargs, device)

    return Classifier(
        cnn_models=cnn_models,
        label_encoder=label_encoder,
        meta_model=meta_model,
        vector_normalization=load_vector_normalization(model_dir / "vector_normalization.json"),
        device=device,
    )


def read_vectors(file_path):
    """The raw hit-object vectors of a .osu file, as the classifier database stores them."""
    beatmap_data = parse_osu_file(file_path, max_slider_length=MAX_SLIDER_LENGTH)

    if beatmap_data is None:
        raise ValueError("parse_osu_file returned None")

    return beatmap_data["vectors"]


def predict_cnn(vectors, classifier):
    """The bagged CNNs' mean NM1-NM5 probabilities for one map's (normalized) vectors."""
    padded = pad_sequences_pt([vectors], dtype=torch.float32, maxlen=MAX_SEQUENCE_LENGTH)

    # [batch, sequence, channels] -> [batch, channels, sequence]
    padded = padded.permute(0, 2, 1).to(classifier.device)

    with torch.no_grad():
        predictions = [torch.softmax(model.eval()(padded), dim=1).cpu() for model in classifier.cnn_models]

    return torch.stack(predictions).mean(dim=0)[0].numpy()


def classify(classifier, vectors, stats):
    """
    Classify one beatmap.

    vectors: its raw hit-object vectors (read_vectors()).
    stats: {name: value} for every SQL_FEATURE_NAMES entry, e.g. its NM
        variant's row in beatmap_variants.

    Returns {"label": "NM3", "probabilities": {"NM1": ..., ...},
    "cnn_probabilities": array in label_encoder order}.
    """
    if len(vectors) == 0:
        raise UnclassifiableBeatmap("No usable hit objects (empty / spinners only / sliders over length cap)")

    # The parser returns raw milliseconds / slider lengths, but the model was
    # trained on vectors scaled by get_data(). And training cut every map to
    # MAX_SEQUENCE_LENGTH vectors before computing the movement features too.
    vectors = normalize_beatmap_vectors(vectors, classifier.vector_normalization)[:MAX_SEQUENCE_LENGTH]

    cnn_probabilities = predict_cnn(vectors, classifier)
    sql_features = np.array([stats[name] for name in SQL_FEATURE_NAMES], dtype=np.float32)
    movement_features = np.asarray(extract_movement_features_from_X(vectors), dtype=np.float32)

    meta_features = np.hstack([cnn_probabilities, sql_features, movement_features]).reshape(1, -1)
    probabilities = classifier.meta_model.predict_proba(meta_features)[0]

    labels = classifier.label_encoder.classes_
    return {
        "label": str(labels[int(np.argmax(probabilities))]).upper(),
        "probabilities": {str(label).upper(): float(p) for label, p in zip(labels, probabilities)},
        "cnn_probabilities": cnn_probabilities,
    }
