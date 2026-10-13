"""
Smoke test against the real data in beatmap_recommender/dummy.db.

A *smoke test* doesn't check exact values. It runs the real thing on real
data and asks "does anything catch fire?" It catches the problems hand-made
test data never contains: weird loved maps, odd mod strings, NULLs in
unexpected columns, performance cliffs.

It's marked `slow` (loading 583MB takes a while), so a plain `pytest` run
skips it. Run it explicitly with:

    python -m pytest -m slow

It's skipped automatically if dummy.db isn't present (e.g. on a fresh clone,
since the databases aren't in git).
"""

import sqlite3

import pytest

from beatmap_recommender import database
from beatmap_recommender.api.model import RecommendationSettings
from beatmap_recommender.recommender import recommend_player_sync

DUMMY_DB = database.PROJECT_ROOT / "beatmap_recommender" / "dummy.db"

pytestmark = [
    # `pytestmark` applies these marks to every test in this file.
    pytest.mark.slow,
    pytest.mark.skipif(not DUMMY_DB.exists(), reason="beatmap_recommender/dummy.db not found"),
]


@pytest.fixture(scope="module")
def player_ids():
    """
    The players in dummy.db with the most scores.

    `scope="module"` runs this fixture once for the whole file instead of
    once per test. Use it for expensive, read-only setup.
    """
    with sqlite3.connect(f"{DUMMY_DB.as_uri()}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT player_id FROM scores GROUP BY player_id ORDER BY COUNT(*) DESC LIMIT 3"
        ).fetchall()
    return [player_id for (player_id,) in rows]


@pytest.fixture(scope="module", autouse=True)
def loaded_dummy_db():
    # load_memory_db loads once per process and refuses to switch to a
    # different file afterwards. That's another reason this test is kept
    # out of the normal run.
    database.load_memory_db(DUMMY_DB)


@pytest.mark.parametrize("goal", ["balanced", "pp_potential"])
def test_recommendations_for_real_players(player_ids, goal):
    for player_id in player_ids:
        settings = RecommendationSettings(player_id=player_id, goal=goal, limit=500)

        # update_scores=False: use the scores already in dummy.db instead of
        # calling the osu! API.
        ranked = recommend_player_sync(settings, update_scores=False)

        assert ranked, f"no recommendations for player {player_id}"
        assert len(ranked) <= 500

        scores = [r["final_score"] for r in ranked]
        assert scores == sorted(scores, reverse=True)
        assert all(0.0 <= s <= 1.0 for s in scores), "final_score left [0, 1]"
        assert all(r["title"] is not None for r in ranked), "metadata missing"


def test_mod_and_status_filters_on_real_data(player_ids):
    settings = RecommendationSettings(
        player_id=player_ids[0], mods=["HD", "DT"], exact_mods=True, beatmap_status="ranked", limit=200,
    )

    ranked = recommend_player_sync(settings, update_scores=False)

    assert ranked
    assert {r["mods"] for r in ranked} == {"HDDT"}
    assert {r["status"] for r in ranked} == {"ranked"}
