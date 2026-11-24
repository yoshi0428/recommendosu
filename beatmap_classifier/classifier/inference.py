"""
Run the trained fusion classifier (classifier/fusion.py) on one beatmap.

beatmap_recommender/recommender_db_setup/precompute_nm1-5.py uses it (for all
the NM variants in the recommender database), and so does
beatmap_classifier/test_model.py (one map at a time). Its inputs must match
the training data from train_fusion.py. tests/test_classifier_features.py
makes sure that they match.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from beatmap_classifier.classifier import fusion
from beatmap_classifier.classifier.training_data import normalize_beatmap_vectors
from beatmap_classifier.classifier_db_setup.parser import parse_osu_file

MODEL_DIR = Path(__file__).resolve().parents[1] / "models/fusion"

# The parser limits slider lengths to this value, as for the training data.
MAX_SLIDER_LENGTH = 500.0

# The mods of the beatmap_variants rows that classify() needs.
STAT_MODS = fusion.STAT_MODS


class UnclassifiableBeatmap(Exception):
    """The map parsed, but it has no hit objects that the classifier can use (empty, or only spinners)."""


@dataclass
class Classifier:
    models: list  # One model for each training fold. Their probabilities are averaged.
    classes: list  # "NM1", ... in output order
    normalization: dict  # fusion.fit_normalization() of the training maps
    # The scales that training divided time_diff / slider length by (see get_data()).
    vector_normalization: dict
    device: torch.device


def load_classifier(model_dir=MODEL_DIR, device=None):
    """Load the fusion models that train_fusion.py saved."""
    device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
    models, config = fusion.load(model_dir, device)
    return Classifier(
        models=models,
        classes=config["classes"],
        normalization=config["normalization"],
        vector_normalization=config["vector_normalization"],
        device=device,
    )


def read_vectors(file_path):
    """Return the raw hit-object vectors of a .osu file, as the classifier database stores them."""
    beatmap_data = parse_osu_file(file_path, max_slider_length=MAX_SLIDER_LENGTH)

    if beatmap_data is None:
        raise ValueError("parse_osu_file returned None")

    return beatmap_data["vectors"]


def model_inputs(classifier, file_path, stats_by_mod):
    """Return (rich sequence, tabular row) of one map, as train_fusion.py builds them."""
    vectors = read_vectors(file_path)
    if len(vectors) == 0:
        raise UnclassifiableBeatmap("No usable hit objects (empty / spinners only / sliders over length cap)")

    sequence = fusion.rich_sequence(file_path)
    if sequence is None:
        raise UnclassifiableBeatmap("Not an osu!standard map with at least 4 objects and a timing point")

    # The parser returns raw milliseconds and slider lengths. Training used the scaled vectors of get_data().
    vectors = normalize_beatmap_vectors(vectors, classifier.vector_normalization)
    return sequence, fusion.tabular_row(stats_by_mod, vectors)


def classify(classifier, file_path, stats_by_mod):
    """
    Classify one beatmap.

    file_path: its .osu file.
    stats_by_mod: {"NM": {stat: value}, "HD": ..., "HR": ..., "DT": ...},
        e.g. its beatmap_variants rows for STAT_MODS.

    Return {"label": "NM3", "probabilities": {"NM1": ..., ...},
    "slot_probabilities": {"NM1": ..., ...}}. Each slot gets a separate
    probability (slot_probabilities, because a map can fit several slots).
    probabilities are these values scaled to a sum of 1, as the recommender
    expects.
    """
    sequence, tabular = model_inputs(classifier, file_path, stats_by_mod)
    batcher = fusion.Batcher([sequence], [tabular], classifier.normalization, classifier.device)
    slot_probabilities = fusion.predict(classifier.models, batcher, [0])[0]
    probabilities = slot_probabilities / slot_probabilities.sum()

    return {
        "label": classifier.classes[int(np.argmax(slot_probabilities))],
        "probabilities": {label: float(p) for label, p in zip(classifier.classes, probabilities)},
        "slot_probabilities": {label: float(p) for label, p in zip(classifier.classes, slot_probabilities)},
    }
