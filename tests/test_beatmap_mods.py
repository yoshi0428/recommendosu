"""
Unit tests for recommender_db_setup/beatmap_mods.py: the fallback formulas
that turn a map's base stats into modded stats.

These formulas encode osu! game rules, so the expected values come from the
game itself rather than from running the code. That matters: a test whose
expected value was copied from the code's own output only proves the code
does what it does. The HR circle-size bug fixed in commit 8c7e9db is exactly
the kind of mistake these tests are meant to catch.

This file also shows a *test double*: a fake object standing in for a real
dependency (here, osu-tools-py's calculation result) so the code can be
tested without that dependency.
"""

from types import SimpleNamespace

import pytest

from beatmap_recommender.recommender_db_setup.beatmap_mods import (
    apply_bpm_mod,
    apply_length_mod,
    apply_mod_to_stat,
    get_modded_stats,
    get_result_attribute,
)


# ---------------------------------------------------------------------------
# HR / EZ multipliers (osu! rules: HR = CS x1.3, AR/OD/HP x1.4, capped at 10;
# EZ = everything x0.5).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("stat", "base", "mods", "expected"),
    [
        ("cs", 4.0, ["HR"], 5.2),
        ("cs", 9.0, ["HR"], 10.0),  # Capped.
        ("cs", 4.0, ["EZ"], 2.0),
        ("hp", 5.0, ["HR"], 7.0),
        ("ar", 9.0, ["HR"], 10.0),  # 12.6 capped to 10.
        ("od", 5.0, ["HR"], 7.0),
        ("ar", 8.0, ["EZ"], 4.0),
        ("cs", 4.0, ["HD"], 4.0),   # HD changes no stats.
        ("cs", 4.0, ["hr"], 5.2),   # Lowercase mods are accepted.
    ],
)
def test_hr_and_ez_multipliers(stat, base, mods, expected):
    assert apply_mod_to_stat(base, mods, stat) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# DT / HT change AR and OD through the hit windows, not by a flat multiplier.
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
        ("ar", 4.0, ["DT"], 7.133),  # Below AR5, the other branch of the formula.
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
# get_result_attribute / get_modded_stats with a fake calculator result
# ---------------------------------------------------------------------------
# SimpleNamespace(a=1, b=2) builds an object whose attributes are a and b.
# That's all get_modded_stats needs from osu-tools-py's CalculationResult, so
# a SimpleNamespace is a perfectly good stand-in, and the test doesn't need
# the real calculator or a .osu file.
BASE = {"hp_drain": 5.0, "circle_size": 4.0, "od": 8.0, "ar": 9.0}


def test_get_result_attribute_tries_names_in_order():
    result = SimpleNamespace(star_rating=6.1, stars=None)
    # `stars` exists but is None, so it falls through to `star_rating`.
    assert get_result_attribute(result, "stars", "star_rating") == 6.1
    assert get_result_attribute(result, "missing") is None


def test_modded_stats_prefer_calculator_values():
    result = SimpleNamespace(ar=10.5, od=9.9, cs=4.0, hp=5.0, stars=6.0, pp=300.0)

    stats = get_modded_stats(BASE, result, ["DT"])

    assert stats["ar"] == 10.5  # From the calculator, not the fallback formula.
    assert stats["star_rating"] == 6.0
    assert stats["pp"] == 300.0
    assert stats["pp_aim"] is None  # Not provided by this fake.


def test_modded_stats_fall_back_to_formulas():
    # An older osu-tools-py version that only exposes star rating.
    result = SimpleNamespace(star_rating=6.0)

    stats = get_modded_stats(BASE, result, ["HR"])

    assert stats["circle_size"] == pytest.approx(5.2)
    assert stats["ar"] == pytest.approx(10.0)
    assert stats["od"] == pytest.approx(10.0)
    assert stats["hp_drain"] == pytest.approx(7.0)
    assert stats["star_rating"] == 6.0
