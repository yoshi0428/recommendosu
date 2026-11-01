"""
Fast checks of beatmap_classifier/classifier/inference.py with fake models.
(tests/test_classifier_features.py compares it against the real training
data, but needs the databases and is marked slow.)
"""

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from beatmap_classifier.classifier import inference  # noqa: E402
from beatmap_classifier.classifier.augment_faster import extract_movement_features_from_X  # noqa: E402


class RecordingCNN:
    def __init__(self):
        self.inputs = []

    def eval(self):
        return self

    def __call__(self, batch):
        self.inputs.append(batch)
        return torch.zeros((batch.shape[0], 5))


class RecordingMetaModel:
    def __init__(self):
        self.inputs = []

    def predict_proba(self, features):
        self.inputs.append(features)
        return np.array([[0.1, 0.2, 0.4, 0.2, 0.1]])


class FakeLabelEncoder:
    classes_ = np.array(["nm1", "nm2", "nm3", "nm4", "nm5"])


def make_classifier():
    return inference.Classifier(
        cnn_models=[RecordingCNN()],
        label_encoder=FakeLabelEncoder(),
        meta_model=RecordingMetaModel(),
        vector_normalization={"max_time_diff": 100.0, "max_vector_length": 500.0},
        device=torch.device("cpu"),
    )


STATS = {name: float(i) for i, name in enumerate(inference.SQL_FEATURE_NAMES)}


def random_vectors(count, seed=0):
    vectors = np.random.default_rng(seed).uniform(0.1, 1.0, size=(count, 8)).astype(np.float32)
    vectors[:, 2] *= 100  # Raw milliseconds, as the parser returns them.
    return vectors


def test_classify_returns_uppercase_labels_and_probabilities():
    prediction = inference.classify(make_classifier(), random_vectors(50), STATS)

    assert prediction["label"] == "NM3"
    assert prediction["probabilities"] == pytest.approx({"NM1": 0.1, "NM2": 0.2, "NM3": 0.4, "NM4": 0.2, "NM5": 0.1})
    assert prediction["cnn_probabilities"] == pytest.approx([0.2] * 5)


def test_meta_model_input_is_cnn_then_stats_then_movement():
    classifier = make_classifier()
    vectors = random_vectors(50)
    inference.classify(classifier, vectors, STATS)

    row = classifier.meta_model.inputs[0][0]
    normalized = inference.normalize_beatmap_vectors(vectors, classifier.vector_normalization)

    assert row.shape == (5 + 24,)
    np.testing.assert_allclose(row[5:17], [STATS[name] for name in inference.SQL_FEATURE_NAMES])
    np.testing.assert_allclose(row[17:], extract_movement_features_from_X(normalized), rtol=1e-6)


def test_long_maps_are_cut_like_training():
    # train_full.ipynb cuts maps to MAX_SEQUENCE_LENGTH vectors before
    # computing the movement features; inference has to do the same.
    classifier = make_classifier()
    vectors = random_vectors(inference.MAX_SEQUENCE_LENGTH + 500)
    vectors[inference.MAX_SEQUENCE_LENGTH:, 0] *= 50  # Make the cut-off part different.
    inference.classify(classifier, vectors, STATS)

    normalized = inference.normalize_beatmap_vectors(vectors, classifier.vector_normalization)
    expected = extract_movement_features_from_X(normalized[: inference.MAX_SEQUENCE_LENGTH])
    full = extract_movement_features_from_X(normalized)

    movement = classifier.meta_model.inputs[0][0][17:]
    np.testing.assert_allclose(movement, expected, rtol=1e-6)
    assert not np.allclose(movement, full, rtol=1e-6)
    assert classifier.cnn_models[0].inputs[0].shape == (1, 8, inference.MAX_SEQUENCE_LENGTH)


def test_map_without_vectors_is_unclassifiable():
    with pytest.raises(inference.UnclassifiableBeatmap):
        inference.classify(make_classifier(), [], STATS)
