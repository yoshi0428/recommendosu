"""
Tests for variant_ranking.py: turning candidate maps into a ranked list.

These are a mix of unit tests (score_variant, calculate_difficulty_scores)
and small *integration tests*, which check that several pieces work together
(SQL filters + scoring + sorting) against a real, if tiny, SQLite database.
"""

import threading

import pytest

from beatmap_recommender.api.model import (
    DIFFICULTY_FEATURE_WEIGHTS,
    DIFFICULTY_STD_FLOORS,
    RECOMMENDATION_CONFIG,
)
from beatmap_recommender.cancellation import RecommendationCancelled
from beatmap_recommender.content_similarity.core_modules.variant_ranking import (
    calculate_difficulty_scores,
    get_candidate_variants,
    get_player_difficulty_profiles,
    get_player_played_variants,
    rank_variants,
    score_variant,
)

# The player created by the `seeded_db` fixture in conftest.py. (Don't import
# from conftest.py directly; pytest loads it specially, and importing it a
# second time as a normal module causes confusing duplicate state.)
PLAYER_ID = 100
CANDIDATES = ["10", "11", "12", "13", "14"]


def variant_mods(variants):
    """The set of (beatmap_id, mods) pairs, which is easy to assert on."""
    return {(v["beatmap_id"], v["mods"]) for v in variants}


# ---------------------------------------------------------------------------
# score_variant
# ---------------------------------------------------------------------------
def test_score_variant_is_weighted_sum():
    # balanced weights: content .50, mod .05, difficulty .25, classifier .20
    score = score_variant(
        content_similarity=1.0, mod_preference=1.0, difficulty_score=0.0,
        classifier_score=0.5, pp_potential=1.0,
        recommendation_goal="balanced", recommendation_config=RECOMMENDATION_CONFIG,
    )
    assert score == pytest.approx(0.50 + 0.05 + 0.20 * 0.5)


def test_score_variant_rejects_unknown_goal():
    with pytest.raises(ValueError, match="Unknown recommendation goal"):
        score_variant(1, 1, 1, recommendation_goal="farm", recommendation_config=RECOMMENDATION_CONFIG)


def test_goal_weights_sum_to_one():
    # A cheap sanity check on configuration: if someone tweaks a weight and
    # forgets to rebalance, final scores silently drift out of [0, 1].
    for goal, config in RECOMMENDATION_CONFIG.items():
        assert sum(config["weights"].values()) == pytest.approx(1.0), goal


# ---------------------------------------------------------------------------
# calculate_difficulty_scores
# ---------------------------------------------------------------------------
def test_difficulty_score_is_highest_at_players_mean():
    profile = {"star_rating_mean": 5.0, "star_rating_std": 0.5}
    variants = [{"star_rating": 5.0}, {"star_rating": 5.5}, {"star_rating": 7.0}]

    scores = calculate_difficulty_scores(variants, profile, DIFFICULTY_STD_FLOORS, {"star_rating": 1.0})

    assert scores[0] == pytest.approx(1.0)
    assert scores[0] > scores[1] > scores[2]
    # One standard deviation away -> exp(-0.5).
    assert scores[1] == pytest.approx(0.6065, abs=1e-3)


def test_difficulty_score_is_neutral_without_profile():
    scores = calculate_difficulty_scores([{"star_rating": 5.0}], {}, DIFFICULTY_STD_FLOORS, DIFFICULTY_FEATURE_WEIGHTS)
    assert list(scores) == [0.5]


# ---------------------------------------------------------------------------
# get_candidate_variants (SQL filters)
# ---------------------------------------------------------------------------
def test_requested_mods_include_subsets(seeded_db):
    # Asking for HD + DT (not exact) allows HD, DT, and HDDT.
    variants = get_candidate_variants(seeded_db.conn, ["10"], requested_mods={"HD", "DT"})
    assert {v["mods"] for v in variants} == {"HD", "DT", "HDDT"}


def test_requested_mods_with_nm(seeded_db):
    variants = get_candidate_variants(seeded_db.conn, ["10"], requested_mods={"NM", "HD"})
    assert {v["mods"] for v in variants} == {"NM", "HD"}


def test_exact_mods_only_returns_that_combination(seeded_db):
    variants = get_candidate_variants(seeded_db.conn, ["10"], requested_mods={"DT", "HD"}, exact_mods=True)
    assert {v["mods"] for v in variants} == {"HDDT"}


def test_excluded_mods(seeded_db):
    variants = get_candidate_variants(seeded_db.conn, ["10"], excluded_mods={"DT", "NM"})
    assert {v["mods"] for v in variants} == {"HD", "HR", "HDHR"}


def test_numeric_filters_and_status(seeded_db):
    variants = get_candidate_variants(
        seeded_db.conn, CANDIDATES,
        requested_mods={"NM"}, min_stars=4.0, max_stars=6.0, beatmap_status="ranked",
    )
    # 11 is loved, 13 too hard, 14 too easy.
    assert variant_mods(variants) == {("10", "NM"), ("12", "NM")}


def test_year_filter(seeded_db):
    variants = get_candidate_variants(seeded_db.conn, CANDIDATES, requested_mods={"NM"}, max_year=2015)
    assert variant_mods(variants) == {("12", "NM")}


def test_full_scan_path_matches_chunked_path(seeded_db, monkeypatch):
    # Above FULL_SCAN_MIN_CANDIDATES the function switches to a different
    # query strategy. Production has ~150k maps, so we'd never reach that
    # branch with test data... unless we lower the threshold. monkeypatch
    # changes the module constant for this test only.
    from beatmap_recommender.content_similarity.core_modules import variant_ranking

    chunked = get_candidate_variants(seeded_db.conn, CANDIDATES, min_stars=4.0)
    monkeypatch.setattr(variant_ranking, "FULL_SCAN_MIN_CANDIDATES", 1)
    full_scan = get_candidate_variants(seeded_db.conn, CANDIDATES, min_stars=4.0)

    assert variant_mods(full_scan) == variant_mods(chunked)
    assert len(full_scan) > 0


# ---------------------------------------------------------------------------
# Player history
# ---------------------------------------------------------------------------
def test_played_variants_match_canonical_mods(seeded_db):
    played = get_player_played_variants(seeded_db.conn, PLAYER_ID)
    # Score mods "HD,DT" must be matched to the "HDDT" variant row.
    assert variant_mods(played) == {("1", "NM"), ("2", "HDDT"), ("3", "HD"), ("4", "NM")}


def test_nightcore_plays_match_double_time_variants(seeded_db):
    # NC is DT with pitch-shifted audio. beatmap_variants only stores DT
    # combinations, so NC plays must resolve to them instead of being dropped.
    seeded_db.add_beatmap(60)
    seeded_db.add_beatmap(61)
    seeded_db.add_score(300, 60, mods="NC")
    seeded_db.add_score(300, 61, mods="HD,NC")

    played = get_player_played_variants(seeded_db.conn, 300)

    assert variant_mods(played) == {("60", "DT"), ("61", "HDDT")}


def test_exclude_recent_plays_keeps_top_plays(seeded_db):
    played = get_player_played_variants(seeded_db.conn, PLAYER_ID, exclude_recent_plays=True)
    # Map 4 was only a recent play; map 3 was "top,recent" so it stays.
    assert variant_mods(played) == {("1", "NM"), ("2", "HDDT"), ("3", "HD")}


def difficulty_profile(conn, player_id, exclude_recent_plays=False):
    return get_player_difficulty_profiles(
        conn, player_id,
        recency_half_life_days=30.0, ability_top_weight=1.0,
        ability_recent_weight=2.0, ability_pp_weight=0.05,
        exclude_recent_plays=exclude_recent_plays,
    )


def test_difficulty_profile_reflects_player(seeded_db):
    profile = difficulty_profile(seeded_db.conn, PLAYER_ID)

    # The player's plays are 5.0, 5.8 (HDDT), 5.67 (HD) and one 2.0-star
    # warm-up worth only 30pp. Star rating is weighted by pp, so that warm-up
    # should pull the mean down *less* than it would in a plain average.
    unweighted_mean = (5.0 + 5.8 + 5.67 + 2.0) / 4
    assert unweighted_mean < profile["star_rating_mean"] < 5.8

    # pp uses only top plays (300, 280, 250), heavily weighted toward the best.
    assert 250 < profile["pp_mean"] < 300


def test_difficulty_profile_for_player_without_plays_is_empty_dict(seeded_db):
    # Regression test: this used to return the tuple ({}, {}), and callers
    # crashed on profile.get(...) with a 500. Real-world trigger: a player
    # whose plays are all "recent" requests recommendations with
    # exclude_recent_plays=True.
    seeded_db.add_beatmap(50)
    seeded_db.add_score(555, 50, source="recent")

    profile = difficulty_profile(seeded_db.conn, 555, exclude_recent_plays=True)

    assert profile == {}


# ---------------------------------------------------------------------------
# rank_variants (the whole ranking step)
# ---------------------------------------------------------------------------
def rank(conn, **overrides):
    """Call rank_variants with the app's default settings plus overrides."""
    similarity_index = {"10": 0.9, "11": 0.8, "12": 0.7, "13": 0.95, "14": 0.95}
    kwargs = dict(
        similarity_index=similarity_index,
        mod_preferences={"HD": 1.0, "NM": 0.5},
        difficulty_profile={
            "star_rating_mean": 5.2, "star_rating_std": 0.5,
            "ar_mean": 9.0, "ar_std": 0.5,
            "pp_mean": 250.0, "pp_std": 30.0,
        },
        difficulty_star_std_multiplier=1.0,
        category_preferences={"NM1": 0.1, "NM2": 0.1, "NM3": 0.6, "NM4": 0.1, "NM5": 0.1},
        recommendation_goal="balanced",
        recommendation_config=RECOMMENDATION_CONFIG,
        difficulty_std_floors=DIFFICULTY_STD_FLOORS,
        difficulty_feature_weights=DIFFICULTY_FEATURE_WEIGHTS,
        pp_push_target_z=2.5, pp_push_max_z=5.0,
        feature_target_z=1.0, feature_max_z=3.0,
    )
    kwargs.update(overrides)
    return rank_variants(conn, **kwargs)


def test_rank_variants_returns_sorted_results_with_metadata(seeded_db):
    ranked = rank(seeded_db.conn)

    assert ranked, "expected at least one recommendation"
    final_scores = [r["final_score"] for r in ranked]
    assert final_scores == sorted(final_scores, reverse=True)

    first = ranked[0]
    assert first["title"] == f"Song {first['beatmap_id']}"
    for field in ("content_similarity", "mod_preference", "difficulty_score", "classifier_score", "pp_potential"):
        assert field in first


def test_rank_variants_applies_star_window(seeded_db):
    # Window is mean +/- 1 std = [4.7, 5.7]. Maps 13 (9*) and 14 (1.5*) have
    # high content similarity but must still be excluded.
    ranked = rank(seeded_db.conn)

    assert {r["beatmap_id"] for r in ranked}.isdisjoint({"13", "14"})
    assert all(4.7 <= r["star_rating"] <= 5.7 for r in ranked)


def test_explicit_star_filter_overrides_window(seeded_db):
    ranked = rank(seeded_db.conn, min_stars=8.0)
    assert {r["beatmap_id"] for r in ranked} == {"13"}


def test_ranking_without_difficulty_profile(seeded_db):
    # What the ranker receives for a player with no matching plays (see the
    # regression test above). It must still rank, just without a star window.
    ranked = rank(seeded_db.conn, difficulty_profile={})

    assert {r["beatmap_id"] for r in ranked} == set(CANDIDATES)


def test_pp_potential_goal_keeps_only_the_pp_push_range(seeded_db):
    # Push range = 500 + [2.5, 5.0] * 20 = [550, 600] pp. Test variants have
    # pp = 20 * stars**2, so that's roughly 5.24-5.48 stars; the star window
    # [4.7, 5.7] alone would let more through.
    profile = {
        "star_rating_mean": 5.2, "star_rating_std": 0.5,
        "ar_mean": 9.0, "ar_std": 0.5,
        "pp_mean": 500.0, "pp_std": 20.0,
    }
    balanced = rank(seeded_db.conn, difficulty_profile=profile)
    pushed = rank(seeded_db.conn, difficulty_profile=profile, recommendation_goal="pp_potential")

    assert pushed, "expected some maps inside the push range"
    assert len(pushed) < len(balanced)
    assert all(550 <= r["pp"] <= 600 for r in pushed)


def test_pp_push_range_intersects_explicit_pp_filters(seeded_db):
    profile = {"star_rating_mean": 5.2, "star_rating_std": 0.5, "pp_mean": 500.0, "pp_std": 20.0}

    narrowed = rank(seeded_db.conn, difficulty_profile=profile, recommendation_goal="pp_potential", max_pp=570)
    assert narrowed and all(550 <= r["pp"] <= 570 for r in narrowed)

    # A pp filter entirely outside the push range leaves nothing.
    assert rank(seeded_db.conn, difficulty_profile=profile, recommendation_goal="pp_potential", max_pp=500) == []


def test_top_k_truncates(seeded_db):
    assert len(rank(seeded_db.conn, top_k=3)) == 3


def test_min_greater_than_max_is_rejected(seeded_db):
    with pytest.raises(ValueError, match="min_bpm"):
        rank(seeded_db.conn, min_bpm=200, max_bpm=100)


def test_empty_similarity_index_returns_nothing(seeded_db):
    assert rank(seeded_db.conn, similarity_index={}) == []


def test_cancelled_request_stops_ranking(seeded_db):
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(RecommendationCancelled):
        rank(seeded_db.conn, cancel_event=cancel_event)
