"""
Smoke test against the real data in beatmap_recommender/dummy.db.

A *smoke test* does not check exact values. It runs the real code on real data
and asks "does anything catch fire?" It finds the problems that hand-made test
data never has: strange loved maps, odd mod strings, NULLs in unexpected
columns, sudden slowdowns.

It is marked `slow` (the load of all the variants from the 583MB database takes
some time), so a plain `pytest` run skips it. To run it, use:

    python -m pytest -m slow

If dummy.db is not present, the test is skipped automatically (for example,
in a new clone, because the databases are not in git).
"""

import sqlite3

import pytest

from beatmap_recommender import database
from beatmap_recommender.api.model import RecommendationSettings
from beatmap_recommender.recommender import recommend_player_sync

DUMMY_DB = database.PROJECT_ROOT / "beatmap_recommender" / "dummy.db"

pytestmark = [
    # `pytestmark` applies these marks to all the tests in this file.
    pytest.mark.slow,
    pytest.mark.skipif(not DUMMY_DB.exists(), reason="beatmap_recommender/dummy.db not found"),
]


@pytest.fixture(scope="module")
def player_ids():
    """
    The players in dummy.db with the most scores.

    `scope="module"` runs this fixture one time for the full file, not one
    time for each test. Use it for setup that is slow and read-only.
    """
    with sqlite3.connect(f"{DUMMY_DB.as_uri()}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT player_id FROM scores GROUP BY player_id ORDER BY COUNT(*) DESC LIMIT 3"
        ).fetchall()
    return [player_id for (player_id,) in rows]


@pytest.fixture(scope="module", autouse=True)
def dummy_db_path():
    # Point the recommender at dummy.db for this file. `monkeypatch` works for
    # one test only, so a module-scoped fixture uses its context manager form.
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(database, "DB_PATH", DUMMY_DB)
        yield


def test_recommendations_for_real_players(player_ids):
    for player_id in player_ids:
        settings = RecommendationSettings(player_id=player_id, limit=500)

        # update_scores=False: use the scores in dummy.db, and do not call the
        # osu! API.
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
