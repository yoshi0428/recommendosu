"""
Unit tests for the numeric scoring helpers: ability.py, pp_potential.py and
the classifier score in cnn_xgboost_influence.py.

Testing math code well mostly comes down to:
    * Work out a few results by hand and check the code agrees.
    * Check the boundaries: zero, negative, missing, exactly-on-the-edge.
    * Check *relationships* (e.g. "older scores weigh less") rather than only
      magic numbers, so the test explains *why* the value matters.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from beatmap_recommender.content_similarity.core_modules.ability import (
    get_ability_score_weight,
    get_recency_weight,
)
from beatmap_recommender.content_similarity.core_modules.cnn_xgboost_influence import (
    calculate_classifier_score,
)
from beatmap_recommender.content_similarity.core_modules.pp_potential import (
    calculate_pp_potential,
    weighted_mean_and_std,
)


def days_ago(days):
    """An osu!-API-style timestamp (e.g. 2026-10-01T12:00:00Z) `days` ago."""
    played_at = datetime.now(timezone.utc) - timedelta(days=days)
    return played_at.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# ability.get_recency_weight
# ---------------------------------------------------------------------------
# get_recency_weight compares against datetime.now(). Tests that depend on the
# current time are a classic source of flaky tests (tests that pass or fail at
# random). Here we avoid that by building the timestamps relative to "now" and
# comparing with a tolerance, since a few milliseconds pass between creating
# the timestamp and the function reading the clock.
@pytest.mark.parametrize(
    ("age_days", "expected"),
    [(0, 1.0), (30, 0.5), (60, 0.25), (90, 0.125)],
)
def test_recency_weight_halves_every_half_life(age_days, expected):
    weight = get_recency_weight(days_ago(age_days), recency_half_life_days=30)
    assert weight == pytest.approx(expected, rel=1e-3)


@pytest.mark.parametrize("bad_timestamp", [None, "", "not-a-date"])
def test_recency_weight_keeps_scores_with_unusable_timestamps(bad_timestamp):
    assert get_recency_weight(bad_timestamp, 30) == 1.0


def test_future_timestamps_are_not_boosted():
    # max(0, age) means clock skew can't produce a weight above 1.
    assert get_recency_weight(days_ago(-10), 30) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# ability.get_ability_score_weight
# ---------------------------------------------------------------------------
def ability_weight(source, pp=None, created_at=None):
    # A small wrapper with the default settings from api/model.py, so each
    # test only spells out the arguments it is actually about.
    return get_ability_score_weight(
        source, pp, created_at,
        recency_half_life_days=30.0,
        ability_top_weight=1.0,
        ability_recent_weight=2.0,
        ability_pp_weight=0.05,
    )


def test_recent_scores_count_more_for_current_ability():
    # This is the opposite of mod preferences, where top plays count more.
    assert ability_weight("recent") == 2.0
    assert ability_weight("top") == 1.0
    assert ability_weight("top,recent") == 1.0


def test_old_high_pp_play_can_weigh_less_than_new_one():
    old = ability_weight("top", pp=400, created_at=days_ago(120))
    new = ability_weight("top", pp=400, created_at=days_ago(0))
    assert old < new


# ---------------------------------------------------------------------------
# pp_potential.weighted_mean_and_std
# ---------------------------------------------------------------------------
def test_weighted_mean_and_std_matches_numpy():
    values = [1.0, 2.0, 3.0, 10.0]
    weights = [1.0, 1.0, 1.0, 3.0]

    mean, std = weighted_mean_and_std(values, weights)

    # Cross-check against an independent implementation (numpy).
    expected_mean = np.average(values, weights=weights)
    expected_std = np.sqrt(np.average((np.array(values) - expected_mean) ** 2, weights=weights))
    assert mean == pytest.approx(expected_mean)
    assert std == pytest.approx(expected_std)


def test_weighted_mean_and_std_with_zero_weights_falls_back_to_unweighted():
    mean, std = weighted_mean_and_std([2.0, 4.0], [0.0, 0.0])
    assert (mean, std) == (3.0, 1.0)


# ---------------------------------------------------------------------------
# pp_potential.calculate_pp_potential
# ---------------------------------------------------------------------------
PROFILE = {
    "pp_mean": 200.0, "pp_std": 20.0,
    "star_rating_mean": 5.0, "star_rating_std": 0.5,
}
FLOORS = {"star_rating": 0.35}
WEIGHTS = {"star_rating": 1.0}


def pp_potential(pp, stars=5.0, **kwargs):
    variant = {"pp": pp, "star_rating": stars}
    kwargs.setdefault("pp_min", 250.0)
    kwargs.setdefault("pp_max", 300.0)
    return calculate_pp_potential(variant, PROFILE, FLOORS, WEIGHTS, **kwargs)


@pytest.mark.parametrize(
    ("pp", "expected"),
    [
        (249.9, 0.0),  # Below the push window: filtered out.
        (250.0, 0.0),  # Exactly the entry level maps to 0.
        (275.0, 0.5),  # Halfway through the window.
        (300.0, 1.0),  # Top of the window.
        (300.1, 0.0),  # Above the window: filtered out, not clamped to 1.
        (0, 0.0),
        ("garbage", 0.0),
    ],
)
def test_pp_potential_is_linear_inside_the_push_window(pp, expected):
    assert pp_potential(pp) == pytest.approx(expected)


def test_pp_potential_penalizes_maps_that_are_much_too_hard():
    comfortable = pp_potential(290, stars=5.4)  # z = 0.8, inside the comfort zone.
    too_hard = pp_potential(290, stars=7.0)     # z = 4.0, well past feature_max_z.

    assert comfortable == pytest.approx(0.8)
    assert 0.0 < too_hard < comfortable


def test_pp_potential_without_profile_is_zero():
    assert calculate_pp_potential({"pp": 280}, {}, FLOORS, WEIGHTS) == 0.0


def test_pp_potential_falls_back_to_profile_bounds():
    # Without explicit pp_min/pp_max, the window is
    # [mean + 2.5 std, mean + 7.5 std] = [250, 350] using the defaults.
    assert pp_potential(300, pp_min=None, pp_max=None) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# cnn_xgboost_influence.calculate_classifier_score
# ---------------------------------------------------------------------------
def test_classifier_score_rewards_matching_category():
    preferences = {"NM1": 0.0, "NM2": 0.0, "NM3": 1.0, "NM4": 0.0, "NM5": 0.0}
    matching = {"NM1": 0.0, "NM2": 0.0, "NM3": 1.0, "NM4": 0.0, "NM5": 0.0}
    other = {"NM1": 1.0, "NM2": 0.0, "NM3": 0.0, "NM4": 0.0, "NM5": 0.0}

    assert calculate_classifier_score(matching, preferences) == 1.0
    assert calculate_classifier_score(other, preferences) == 0.0


def test_classifier_score_missing_data_is_zero():
    assert calculate_classifier_score(None, {"NM1": 1.0}) == 0.0
    assert calculate_classifier_score({"NM1": 1.0}, {}) == 0.0
