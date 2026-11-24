"""
Failed plays (rank F) are stored, because the score refresh asks osu! for
them (include_fails=1). But they do not show what the player can do. They must
not change the content-similarity seeds, the difficulty profile, the mod
preferences or the NM category preferences. They still count as played, so
"exclude already played" hides them.
"""

from beatmap_recommender.content_similarity.core_modules.classifier_influence import (
    get_player_category_preferences,
)
from beatmap_recommender.content_similarity.core_modules.content_similarity import (
    get_maps,
    get_player_seed_maps,
)
from beatmap_recommender.content_similarity.core_modules.mod_preferences import get_preferred_mods
from beatmap_recommender.content_similarity.core_modules.variant_ranking import get_player_difficulty_profiles
from tests.conftest import PLAYER_ID

WEIGHTS = dict(recency_half_life_days=30.0, ability_top_weight=1.0, ability_recent_weight=2.0, ability_pp_weight=0.05)


def profiles(conn):
    seeds, matrix = get_player_seed_maps(conn, PLAYER_ID)
    return {
        "seeds": sorted(map(str, seeds)),
        "difficulty": get_player_difficulty_profiles(conn, PLAYER_ID, exclude_recent_plays=False, **WEIGHTS),
        "mods": get_preferred_mods(conn, PLAYER_ID, top_weight=3.0, recent_weight=1.0, pp_weight=0.05),
        "categories": get_player_category_preferences(conn, PLAYER_ID, **WEIGHTS),
    }


def close(a, b):
    """Return True if equal, up to float noise (the recency weights read the clock on each call)."""
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(close(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)))


def add_fails(db):
    # A 9-star map with a mod combination that the player never passed, and a
    # map with classifier predictions (the category preferences read only those).
    db.add_score(PLAYER_ID, 13, mods="HR", source="recent", pp=None, created_at="2026-11-19T00:00:00Z", rank="F")
    db.add_score(PLAYER_ID, 10, mods="HR", source="recent", pp=None, created_at="2026-11-19T00:00:00Z", rank="F")


def test_failed_plays_change_no_profile(seeded_db):
    before = profiles(seeded_db.conn)
    add_fails(seeded_db)
    assert close(profiles(seeded_db.conn), before)


def test_a_passed_play_does_change_them(seeded_db):
    # The same plays as passes do count, so the test above is not empty of meaning.
    before = profiles(seeded_db.conn)
    seeded_db.add_score(PLAYER_ID, 13, mods="HR", source="recent", pp=500, created_at="2026-11-19T00:00:00Z")
    seeded_db.add_score(PLAYER_ID, 10, mods="HR", source="recent", pp=400, created_at="2026-11-19T00:00:00Z")
    after = profiles(seeded_db.conn)
    assert all(not close(after[key], before[key]) for key in before)


def test_failed_maps_still_count_as_played(seeded_db):
    add_fails(seeded_db)
    candidates, _ = get_maps(seeded_db.conn, mods="NM", player_id=PLAYER_ID)
    assert not {"10", "13"} & set(map(str, candidates))
