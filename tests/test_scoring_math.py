"""
Unit tests for the numeric scoring helpers: ability.py and the classifier
score in classifier_influence.py.

Good tests of math code mostly do these things:
    * Calculate a few results by hand, and check that the code agrees.
    * Check the boundaries: zero, negative, missing, exactly on the edge.
    * Check *relationships* (for example, "older scores weigh less"), not
      only magic numbers. Thus the test explains *why* the value matters.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from beatmap_recommender.content_similarity.core_modules.ability import (
    get_ability_score_weight,
    get_recency_weight,
    weighted_mean_and_std,
)
from beatmap_recommender.content_similarity.core_modules.classifier_influence import (
    NM_LABELS,
    calculate_classifier_scores,
)


def days_ago(days):
    """Return a timestamp in the osu! API format (for example 2026-10-01T12:00:00Z), `days` ago."""
    played_at = datetime.now(timezone.utc) - timedelta(days=days)
    return played_at.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# ability.get_recency_weight
# ---------------------------------------------------------------------------
# get_recency_weight compares with datetime.now(). Tests that depend on the
# current time are a usual source of flaky tests (tests that pass or fail at
# random). These tests prevent that: they build the timestamps relative to
# "now" and compare with a tolerance, because a few milliseconds pass between
# the timestamp and the moment that the function reads the clock.
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
    # Because of max(0, age), a clock difference cannot give a weight above 1.
    assert get_recency_weight(days_ago(-10), 30) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# ability.get_ability_score_weight
# ---------------------------------------------------------------------------
def ability_weight(source, pp=None, created_at=None):
    # A small wrapper with the default settings from api/model.py, so that
    # each test writes only the arguments that it checks.
    return get_ability_score_weight(
        source, pp, created_at,
        recency_half_life_days=30.0,
        ability_top_weight=1.0,
        ability_recent_weight=2.0,
        ability_pp_weight=0.05,
    )


def test_recent_scores_count_more_for_current_ability():
    # This is the opposite of the mod preferences, where top plays count more.
    assert ability_weight("recent") == 2.0
    assert ability_weight("top") == 1.0
    assert ability_weight("top,recent") == 1.0


def test_old_high_pp_play_can_weigh_less_than_new_one():
    old = ability_weight("top", pp=400, created_at=days_ago(120))
    new = ability_weight("top", pp=400, created_at=days_ago(0))
    assert old < new


# ---------------------------------------------------------------------------
# ability.weighted_mean_and_std
# ---------------------------------------------------------------------------
def test_weighted_mean_and_std_matches_numpy():
    values = [1.0, 2.0, 3.0, 10.0]
    weights = [1.0, 1.0, 1.0, 3.0]

    mean, std = weighted_mean_and_std(values, weights)

    # Compare with a separate implementation (numpy).
    expected_mean = np.average(values, weights=weights)
    expected_std = np.sqrt(np.average((np.array(values) - expected_mean) ** 2, weights=weights))
    assert mean == pytest.approx(expected_mean)
    assert std == pytest.approx(expected_std)


def test_weighted_mean_and_std_with_zero_weights_falls_back_to_unweighted():
    mean, std = weighted_mean_and_std([2.0, 4.0], [0.0, 0.0])
    assert (mean, std) == (3.0, 1.0)


# ---------------------------------------------------------------------------
# classifier_influence.calculate_classifier_scores
# ---------------------------------------------------------------------------
def calculate_classifier_score(probabilities, preferences):
    """Call calculate_classifier_scores() for one {label: probability} dict. Missing data scores 0."""
    if not probabilities or not preferences:
        return 0.0

    row = [probabilities.get(label) or 0.0 for label in NM_LABELS]
    return float(calculate_classifier_scores([row], preferences)[0])


def test_classifier_score_rewards_matching_category():
    preferences = {"NM1": 0.0, "NM2": 0.0, "NM3": 1.0, "NM4": 0.0, "NM5": 0.0}
    matching = {"NM1": 0.0, "NM2": 0.0, "NM3": 1.0, "NM4": 0.0, "NM5": 0.0}
    other = {"NM1": 1.0, "NM2": 0.0, "NM3": 0.0, "NM4": 0.0, "NM5": 0.0}

    assert calculate_classifier_score(matching, preferences) == 1.0
    assert calculate_classifier_score(other, preferences) == 0.0


def test_classifier_score_missing_data_is_zero():
    assert calculate_classifier_score(None, {"NM1": 1.0}) == 0.0
    assert calculate_classifier_score({"NM1": 1.0}, {}) == 0.0
