"""
Unit tests for recommender_db_setup/beatmap_mods.py: the formulas that change
the base stats of a map into modded stats.

These formulas encode the rules of osu!, so the expected values come from the
game, not from the code. This is important: a test with an expected value
copied from the output of the code only shows that the code does what it
does. The HR circle-size bug, fixed in commit 8c7e9db, is exactly the type of
mistake that these tests must find.

This file also shows a *test double*: a fake object that replaces a real
dependency (here, the calculation result of osu-tools-py), so that the test
can run without that dependency.
"""

from types import SimpleNamespace

import pytest

from beatmap_recommender.recommender_db_setup.beatmap_mods import (
    apply_bpm_mod,
    apply_length_mod,
    apply_mod_to_stat,
    get_modded_stats,
)


# ---------------------------------------------------------------------------
# HR / EZ multipliers (osu! rules: HR = CS x1.3, AR/OD/HP x1.4, 10 at most.
# EZ = all values x0.5).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("stat", "base", "mods", "expected"),
    [
        ("cs", 4.0, ["HR"], 5.2),
        ("cs", 9.0, ["HR"], 10.0),  # Limited to 10.
        ("cs", 4.0, ["EZ"], 2.0),
        ("hp", 5.0, ["HR"], 7.0),
        ("ar", 9.0, ["HR"], 10.0),  # 12.6 limited to 10.
        ("od", 5.0, ["HR"], 7.0),
        ("ar", 8.0, ["EZ"], 4.0),
        ("cs", 4.0, ["HD"], 4.0),   # HD changes no stats.
        ("cs", 4.0, ["hr"], 5.2),   # Lowercase mods are accepted.
    ],
)
def test_hr_and_ez_multipliers(stat, base, mods, expected):
    assert apply_mod_to_stat(base, mods, stat) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# DT / HT change AR and OD through the hit windows, not with a flat multiplier.
# Well-known reference values from the osu! wiki:
#   AR9 + DT  -> AR ~10.33      AR10 + DT -> AR11
#   OD8 + DT  -> OD ~9.75       AR9 + HT  -> AR ~7.67
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("stat", "base", "mods", "expected"),
    [
        ("ar", 9.0, ["DT"], 10.333),
        ("ar", 10.0, ["DT"], 11.0),
        ("ar", 9.0, ["HD", "DT"], 10.333),
        ("od", 8.0, ["DT"], 9.75),
        ("ar", 9.0, ["HT"], 7.667),
        ("ar", 4.0, ["DT"], 7.133),  # Below AR5, the formula uses its other branch.
        ("ar", 9.0, ["HR", "DT"], 11.0),  # HR first (10), then DT.
    ],
)
def test_clock_rate_mods_change_ar_and_od(stat, base, mods, expected):
    assert apply_mod_to_stat(base, mods, stat) == pytest.approx(expected, abs=1e-3)


def test_missing_value_stays_missing():
    assert apply_mod_to_stat(None, ["HR"], "ar") is None


def test_bpm_and_length_scale_with_clock_rate():
    assert apply_bpm_mod(200, 180, 220, ["DT"]) == (300, 270, 330)
    assert apply_bpm_mod(200, None, None, ["HT"]) == (150, None, None)
    assert apply_bpm_mod(200, 200, 200, ["HR"]) == (200, 200, 200)

    assert apply_length_mod(90, ["DT"]) == pytest.approx(60)
    assert apply_length_mod(90, ["HT"]) == pytest.approx(120)
    assert apply_length_mod(None, ["DT"]) is None


# ---------------------------------------------------------------------------
# get_modded_stats with a fake calculator result
# ---------------------------------------------------------------------------
# SimpleNamespace(a=1, b=2) builds an object with the attributes a and b. That
# is all that get_modded_stats needs from the CalculationResult of
# osu-tools-py. Thus a SimpleNamespace is a good replacement, and the test does
# not need the real calculator or a .osu file.
BASE = {"hp_drain": 5.0, "circle_size": 4.0, "od": 8.0, "ar": 9.0}

# The fields of the osu-tools-py CalculationResult that get_modded_stats reads.
RESULT = SimpleNamespace(
    stars=6.0, max_combo=1234, pp=300.0, pp_aim=150.0, pp_speed=100.0, pp_acc=50.0, pp_flashlight=0.0
)


def test_modded_stats_combine_formulas_and_calculator():
    stats = get_modded_stats(BASE, RESULT, ["HR"])

    # HP/CS/OD/AR come from the formulas (CalculationResult does not have them).
    assert stats["circle_size"] == pytest.approx(5.2)
    assert stats["ar"] == pytest.approx(10.0)
    assert stats["od"] == pytest.approx(10.0)
    assert stats["hp_drain"] == pytest.approx(7.0)

    # The other values come directly from the calculator.
    assert stats["star_rating"] == 6.0
    assert stats["max_combo"] == 1234
    assert (stats["pp"], stats["pp_aim"], stats["pp_speed"], stats["pp_acc"], stats["pp_flashlight"]) == (
        300.0, 150.0, 100.0, 50.0, 0.0,
    )


def test_modded_stats_accept_lowercase_mods():
    assert get_modded_stats(BASE, RESULT, ["hr"]) == get_modded_stats(BASE, RESULT, ["HR"])
