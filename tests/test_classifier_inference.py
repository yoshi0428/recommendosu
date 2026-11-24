"""
Fast checks of beatmap_classifier/classifier/inference.py and fusion.py, with
a small synthetic .osu file and fake models. (tests/test_classifier_features.py
compares inference with the real training data. It needs the databases, so it
is marked slow.)
"""

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from beatmap_classifier.classifier import fusion, inference  # noqa: E402
from beatmap_classifier.classifier.training_data import normalize_beatmap_vectors  # noqa: E402

CLASSES = ["NM1", "NM2", "NM3", "NM4", "NM5"]
VECTOR_NORMALIZATION = {"max_time_diff": 100.0, "max_vector_length": 500.0}


def osu_file(tmp_path, objects, mode=0):
    """A minimal .osu file: 120 BPM, SV 1.4, the given [HitObjects] lines."""
    path = tmp_path / "map.osu"
    path.write_text(
        "osu file format v14\n\n[General]\nMode: " + str(mode) + "\n\n"
        "[Metadata]\nBeatmapID:1\nBeatmapSetID:2\n\n"
        "[Difficulty]\nHPDrainRate:5\nCircleSize:4\nOverallDifficulty:8\nApproachRate:9\n"
        "SliderMultiplier:1.4\nSliderTickRate:1\n\n"
        "[TimingPoints]\n0,500,4,2,0,50,1,0\n\n"
        "[HitObjects]\n" + "\n".join(objects) + "\n"
    )
    return path


CIRCLES = [f"{100 + 50 * (i % 4)},{100 + 30 * (i % 3)},{1000 + 250 * i},{5 if i == 0 else 1},0,0:0:0:0:" for i in range(20)]
SLIDER = "300,200,6500,2,0,L|400:200,1,100,0|0,0:0|0:0,0:0:0:0:"


class RecordingModel(torch.nn.Module):
    """A replacement for a fusion model. It records (x, mask, tab) and returns fixed logits."""

    def __init__(self, logits):
        super().__init__()
        self.logits = torch.tensor([logits], dtype=torch.float32)
        self.head = torch.nn.Sequential(torch.nn.Linear(1, len(logits)))  # predict_logits reads out_features.
        self.inputs = []

    def forward(self, x, mask, tab):
        self.inputs.append((x.cpu(), mask.cpu(), tab.cpu()))
        return self.logits.expand(x.shape[0], -1)


def identity_normalization():
    return {
        "seq_mean": [0.0] * len(fusion.RICH_CHANNELS),
        "seq_std": [1.0] * len(fusion.RICH_CHANNELS),
        "tab_mean": [0.0] * len(fusion.TABULAR_FEATURES),
        "tab_std": [1.0] * len(fusion.TABULAR_FEATURES),
    }


def make_classifier(models):
    return inference.Classifier(
        models=models,
        classes=CLASSES,
        normalization=identity_normalization(),
        vector_normalization=VECTOR_NORMALIZATION,
        device=torch.device("cpu"),
    )


def stats_by_mod():
    return {
        mod: {name: (10 * m + i) / 10 for i, name in enumerate(fusion.VARIANT_STATS)}
        for m, mod in enumerate(fusion.STAT_MODS)
    }


def test_rich_sequence_channels(tmp_path):
    sequence = fusion.rich_sequence(osu_file(tmp_path, CIRCLES + [SLIDER]))

    assert sequence.shape == (20, len(fusion.RICH_CHANNELS))  # One row for each object after the first.
    channel = {name: i for i, name in enumerate(fusion.RICH_CHANNELS)}
    last = sequence[-1]  # The slider.
    assert last[channel["is_slider"]] == 1
    assert last[channel["slider_path_dx"]] == pytest.approx(100 / 512)
    assert last[channel["slider_beats"]] == pytest.approx(100 / 140)  # length / (SV * 100) beats.
    assert last[channel["bpm"]] == pytest.approx(120 / 200)
    assert sequence[:-1, channel["is_slider"]].sum() == 0
    assert sequence[0, channel["dx"]] == pytest.approx(50 / 512)


def test_rich_sequence_rejects_other_modes_and_tiny_maps(tmp_path):
    assert fusion.rich_sequence(osu_file(tmp_path, CIRCLES, mode=1)) is None
    assert fusion.rich_sequence(osu_file(tmp_path, CIRCLES[:3])) is None


def test_classify_scales_probabilities_to_sum_to_one(tmp_path):
    logits = [-2.0, 0.0, 1.5, 0.5, -1.0]
    prediction = inference.classify(make_classifier([RecordingModel(logits)]), osu_file(tmp_path, CIRCLES), stats_by_mod())

    sigmoid = 1 / (1 + np.exp(-np.array(logits)))
    assert prediction["label"] == "NM3"
    assert list(prediction["slot_probabilities"].values()) == pytest.approx(sigmoid.tolist(), rel=1e-5)
    assert list(prediction["probabilities"].values()) == pytest.approx((sigmoid / sigmoid.sum()).tolist(), rel=1e-5)


def test_bagged_models_are_averaged(tmp_path):
    models = [RecordingModel([0.0] * 5), RecordingModel([2.0] * 5)]
    prediction = inference.classify(make_classifier(models), osu_file(tmp_path, CIRCLES), stats_by_mod())

    expected = (0.5 + 1 / (1 + np.exp(-2.0))) / 2
    assert prediction["slot_probabilities"]["NM1"] == pytest.approx(expected, rel=1e-5)


def test_model_inputs_are_the_rich_sequence_and_tabular_row(tmp_path):
    path = osu_file(tmp_path, CIRCLES + [SLIDER])
    model = RecordingModel([0.0] * 5)
    inference.classify(make_classifier([model]), path, stats_by_mod())
    x, mask, tab = model.inputs[0]

    np.testing.assert_allclose(x[0].numpy(), fusion.rich_sequence(path), rtol=1e-6)
    assert mask.sum() == len(fusion.rich_sequence(path))

    vectors = normalize_beatmap_vectors(inference.read_vectors(str(path)), VECTOR_NORMALIZATION)
    np.testing.assert_allclose(tab[0].numpy(), fusion.tabular_row(stats_by_mod(), vectors), rtol=1e-6)
    # The stats come first, mod by mod, in TABULAR_FEATURES order (small values: the inputs are clipped to +-10).
    names = fusion.TABULAR_FEATURES
    assert tab[0, names.index("NM_ar")] == 0
    assert tab[0, names.index("HD_od")] == pytest.approx(1.1)
    assert tab[0, names.index("DT_pp_acc")] == pytest.approx(4.1)


def test_missing_mod_stats_are_zero(tmp_path):
    path = osu_file(tmp_path, CIRCLES)
    stats = stats_by_mod()
    del stats["DT"]
    stats["HR"]["pp"] = None
    model = RecordingModel([0.0] * 5)
    inference.classify(make_classifier([model]), path, stats)
    tab = model.inputs[0][2][0].numpy()

    names = fusion.TABULAR_FEATURES
    assert not tab[[i for i, n in enumerate(names) if n.startswith("DT_")]].any()
    assert tab[names.index("HR_pp")] == 0


def test_long_maps_are_cut(tmp_path):
    many = [f"{100 + 7 * (i % 50)},{100 + 3 * (i % 40)},{1000 + 50 * i},1,0,0:0:0:0:" for i in range(fusion.MAX_SEQUENCE_LENGTH + 300)]
    model = RecordingModel([0.0] * 5)
    inference.classify(make_classifier([model]), osu_file(tmp_path, many), stats_by_mod())

    assert model.inputs[0][0].shape[1] == fusion.MAX_SEQUENCE_LENGTH


def test_map_without_objects_is_unclassifiable(tmp_path):
    with pytest.raises(inference.UnclassifiableBeatmap):
        inference.classify(make_classifier([RecordingModel([0.0] * 5)]), osu_file(tmp_path, []), stats_by_mod())


def test_save_and_load_round_trip(tmp_path):
    torch.manual_seed(0)
    models = [fusion.new_model(len(CLASSES)).eval() for _ in range(2)]
    fusion.save(tmp_path, models, CLASSES, identity_normalization(), VECTOR_NORMALIZATION)
    classifier = inference.load_classifier(tmp_path, device=torch.device("cpu"))

    assert classifier.classes == CLASSES
    assert classifier.vector_normalization == VECTOR_NORMALIZATION
    assert len(classifier.models) == 2
    for saved, loaded in zip(models, classifier.models):
        for a, b in zip(saved.state_dict().values(), loaded.state_dict().values()):
            assert torch.equal(a, b)


def test_real_model_runs_on_cpu(tmp_path):
    torch.manual_seed(0)
    fusion.save(tmp_path / "model", [fusion.new_model(len(CLASSES))], CLASSES, identity_normalization(), VECTOR_NORMALIZATION)
    classifier = inference.load_classifier(tmp_path / "model", device=torch.device("cpu"))
    prediction = inference.classify(classifier, osu_file(tmp_path, CIRCLES + [SLIDER]), stats_by_mod())

    assert sum(prediction["probabilities"].values()) == pytest.approx(1.0)
    assert prediction["label"] in CLASSES


def test_load_rejects_a_model_with_other_inputs(tmp_path):
    fusion.save(tmp_path, [fusion.new_model(len(CLASSES))], CLASSES, identity_normalization(), VECTOR_NORMALIZATION)
    config = (tmp_path / "fusion_config.json").read_text().replace('"NM_ar"', '"NM_hp"')
    (tmp_path / "fusion_config.json").write_text(config)

    with pytest.raises(ValueError, match="different inputs"):
        inference.load_classifier(tmp_path, device=torch.device("cpu"))

