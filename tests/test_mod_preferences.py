"""
Unit tests for mod_preferences.py.

A *unit test* checks one small part of code (usually one function) alone.
These tests are the cheapest to write and run, and they fix the exact
behavior: "for this input, I expect exactly this output".

Each test has the same three steps, often called Arrange / Act / Assert:
    1. Arrange: prepare the input.
    2. Act: call the function that the test checks.
    3. Assert: check the result with a plain `assert`. pytest changes assert
       statements so that a failure shows both sides of the comparison.
"""

import math

import pytest

from beatmap_recommender.content_similarity.core_modules.mod_preferences import (
    canonicalize_mods,
    get_preferred_mods,
    get_score_weight,
    normalize_mod_preferences,
)


# ---------------------------------------------------------------------------
# canonicalize_mods
# ---------------------------------------------------------------------------
# `@pytest.mark.parametrize` runs the same test one time for each row of inputs.
# Each row shows as a separate test in the output (for example
# `test_canonicalize_mods[HD,DT-HDDT]`), so you can see exactly which case
# failed. This is the usual way to check many input/output pairs without a
# copy of the test body for each.
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Empty or missing values all mean "no mod".
        (None, "NM"),
        ("", "NM"),
        ("NM", "NM"),
        ([], "NM"),
        (["NM"], "NM"),
        # The osu! API stores mods separated by commas. This is the real format
        # in the scores table of dummy.db.
        ("HD,DT", "HDDT"),
        ("HD,HR,DT", "HDHRDT"),
        ("NF,HD,DT", "NFHDDT"),
        # The order of the input must have no effect.
        ("DTHD", "HDDT"),
        ("DT,HD", "HDDT"),
        (["DT", "HD"], "HDDT"),
        (("HR", "HD"), "HDHR"),
        # Case and whitespace are allowed.
        ("hd, dt", "HDDT"),
        (" hr ", "HR"),
        # HT comes before HD in MOD_ORDER. The beatmap_variants table stores
        # this combination as "HTHD", so the canonical form must match it.
        ("HD,HT", "HTHD"),
        # NC is DT with different audio, so its canonical form is DT.
        ("NC", "DT"),
        ("HD,NC", "HDDT"),
        ("DT,NC", "DT"),  # Some clients send both.
        # Duplicates become one mod.
        ("HDHD", "HD"),
        # Mods that only lazer has (seen in real scores such as "HR,SO").
        ("HR,SO", "HRSO"),
        # Longer mod names must match before shorter ones.
        ("SV2", "SV2"),
        ("10K", "10K"),
    ],
)
def test_canonicalize_mods(raw, expected):
    assert canonicalize_mods(raw) == expected


def test_canonicalize_mods_rejects_unknown_mod():
    # `pytest.raises` checks that the code in the `with` block raises this
    # exception. If it does not raise it, the test fails. `match` is a regex
    # that must match the error message.
    with pytest.raises(ValueError, match="Unknown mod string"):
        canonicalize_mods("HDXX")


def test_canonicalize_mods_is_idempotent():
    # A *property* to test: the canonical form of a canonical string must be
    # the same string. This finds many types of ordering bugs at once.
    for mods in ["NM", "HD", "HDDT", "HTHD", "EZHDDT", "HDHRDTFL", "HDNC"]:
        assert canonicalize_mods(canonicalize_mods(mods)) == canonicalize_mods(mods)


# ---------------------------------------------------------------------------
# get_score_weight
# ---------------------------------------------------------------------------
def test_top_plays_weigh_more_than_recent_plays():
    top = get_score_weight("top", pp=None, top_weight=3.0, recent_weight=1.0, pp_weight=0.0)
    recent = get_score_weight("recent", pp=None, top_weight=3.0, recent_weight=1.0, pp_weight=0.0)
    assert top == 3.0
    assert recent == 1.0


def test_score_in_both_top_and_recent_is_not_double_counted():
    both = get_score_weight("top,recent", None, 3.0, 1.0, 0.0)
    assert both == 3.0  # The same as a plain top play, not 3.0 + 1.0.


def test_unknown_source_falls_back_to_recent_weight():
    assert get_score_weight("something_new", None, 3.0, 1.0, 0.0) == 1.0
    assert get_score_weight(None, None, 3.0, 1.0, 0.0) == 1.0


def test_pp_factor_uses_square_root():
    # pp_factor = 1 + pp_weight * sqrt(pp) / 10
    # With pp=400 and pp_weight=0.5: 1 + 0.5 * 20 / 10 = 2.0
    assert get_score_weight("recent", 400, 3.0, 1.0, 0.5) == pytest.approx(2.0)


@pytest.mark.parametrize("bad_pp", [0, -50, "not a number"])
def test_non_positive_or_invalid_pp_adds_nothing(bad_pp):
    assert get_score_weight("top", bad_pp, 3.0, 1.0, 0.5) == 3.0


# ---------------------------------------------------------------------------
# normalize_mod_preferences
# ---------------------------------------------------------------------------
def test_normalize_scales_favourite_mod_to_one():
    normalized = normalize_mod_preferences({"HD": 10.0, "NM": 2.0})

    assert normalized["HD"] == 1.0
    # log1p makes big differences smaller: 10x the raw weight is NOT 10x the
    # normalized value. A float comparison with == can fail because of
    # rounding, so use pytest.approx for all calculated values.
    assert normalized["NM"] == pytest.approx(math.log1p(2) / math.log1p(10))


def test_normalize_handles_empty_and_zero_input():
    assert normalize_mod_preferences({}) == {}
    assert normalize_mod_preferences({"NM": 0.0}) == {"NM": 0.0}


# ---------------------------------------------------------------------------
# get_preferred_mods (reads from a database)
# ---------------------------------------------------------------------------
def test_get_preferred_mods_from_scores(recommender_db):
    # `recommender_db` comes from conftest.py: a temporary database with the
    # real schema. The test adds exactly the scores that it needs.
    db = recommender_db
    db.add_beatmap(1)
    db.add_beatmap(2)
    db.add_beatmap(3)

    db.add_score(7, 1, mods="HD,DT", source="top", pp=None)
    db.add_score(7, 2, mods="DT,HD", source="top", pp=None)  # The same combination, in another order.
    db.add_score(7, 3, mods="", source="recent", pp=None)
    db.add_score(7, 3, mods="XYZ", source="top", pp=None)  # An unknown mod: skipped, not a crash.
    db.add_score(999, 1, mods="HR", source="top", pp=None)  # Another player: ignored.

    result = get_preferred_mods(db.conn, 7, top_weight=3.0, recent_weight=1.0, pp_weight=0.0)

    # Sorted from the most preferred to the least preferred.
    assert [mods for mods, _ in result] == ["HDDT", "NM"]
    assert result[0][1] == 1.0
    assert result[1][1] == pytest.approx(math.log1p(1) / math.log1p(6))


def test_get_preferred_mods_min_preference_filters(recommender_db):
    db = recommender_db
    db.add_beatmap(1)
    db.add_score(7, 1, mods="HD", source="top", pp=None)
    db.add_score(7, 1, mods="", source="recent", pp=None)

    result = get_preferred_mods(db.conn, 7, 3.0, 1.0, 0.0, min_preference=0.9)

    assert result == [("HD", 1.0)]
