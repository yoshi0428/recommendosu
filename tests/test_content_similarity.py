"""
Tests for content_similarity.py.

calculate_seed_similarity is only numpy math, so very small hand-made matrices
can test it: two or three maps with obvious distances. When code is optimized
(batches, argpartition, einsum), small inputs that a person can check are the
best way to make sure that the optimized version still gives the right answer.
"""

import numpy as np
import pytest

from beatmap_recommender.content_similarity.core_modules.content_similarity import (
    SIMILARITY_FEATURES,
    build_seed_similarity_index,
    calculate_seed_similarity,
    get_maps,
)

N_FEATURES = len(SIMILARITY_FEATURES)


def maps(*rows):
    """Return a (n_maps x n_features) matrix where each feature has the given value."""
    return np.array([[value] * N_FEATURES for value in rows], dtype=np.float32)


def ids(*names):
    return np.array(names, dtype=object)


def test_identical_map_has_similarity_one():
    result = calculate_seed_similarity(
        seed_beatmap_ids=ids("seed"),
        seed_matrix=maps(5.0),
        candidate_beatmap_ids=ids("same", "far"),
        candidate_matrix=maps(5.0, 9.0),
    )

    # similarity = 1 / (1 + distance), so distance 0 -> 1.0.
    assert result["same"] == pytest.approx(1.0)
    assert result["far"] < result["same"]


def test_each_candidate_keeps_its_best_seed():
    # The candidate is exactly on seed "b", so its similarity must come from
    # "b" (distance 0), not from the distant seed "a".
    result = calculate_seed_similarity(
        ids("a", "b"), maps(0.0, 10.0),
        ids("c1", "c2", "c3"), maps(10.0, 5.0, 0.0),
    )
    assert result["c1"] == pytest.approx(1.0)
    assert result["c3"] == pytest.approx(1.0)
    assert result["c2"] < 1.0


def test_top_k_limits_neighbours_per_seed():
    # With top_k=1, each seed "claims" only its one nearest candidate.
    result = calculate_seed_similarity(
        ids("seed"), maps(0.0),
        ids("near", "middle", "far"), maps(0.1, 5.0, 10.0),
        top_k=1,
    )
    assert set(result) == {"near"}


def test_batching_does_not_change_the_result():
    # The function processes the seeds in batches to limit memory. The batches
    # are an implementation detail, so batch_size=1 and a large batch must give
    # the same result. Random data with a fixed seed is the same on each run, so
    # the test does not fail at random.
    rng = np.random.default_rng(seed=0)
    seeds = rng.normal(size=(7, N_FEATURES)).astype(np.float32)
    candidates = rng.normal(size=(40, N_FEATURES)).astype(np.float32)
    candidate_ids = ids(*[f"c{i}" for i in range(40)])
    seed_ids = ids(*[f"s{i}" for i in range(7)])

    one_at_a_time = calculate_seed_similarity(seed_ids, seeds, candidate_ids, candidates, top_k=5, batch_size=1)
    all_at_once = calculate_seed_similarity(seed_ids, seeds, candidate_ids, candidates, top_k=5, batch_size=1000)

    assert one_at_a_time.keys() == all_at_once.keys()
    for key in one_at_a_time:
        assert one_at_a_time[key] == pytest.approx(all_at_once[key])


def test_empty_inputs_return_empty_dict():
    empty_ids = ids()
    empty = np.empty((0, N_FEATURES), dtype=np.float32)
    assert calculate_seed_similarity(empty_ids, empty, ids("c"), maps(1.0)) == {}
    assert calculate_seed_similarity(ids("s"), maps(1.0), empty_ids, empty) == {}


def test_feature_weights_change_what_counts_as_similar():
    # Two candidates: one is different only in star_rating, the other only in bpm.
    seed = np.zeros((1, N_FEATURES), dtype=np.float32)
    star_diff = np.zeros(N_FEATURES, dtype=np.float32)
    bpm_diff = np.zeros(N_FEATURES, dtype=np.float32)
    star_diff[SIMILARITY_FEATURES.index("star_rating")] = 1.0
    bpm_diff[SIMILARITY_FEATURES.index("bpm")] = 1.0
    # A third, unrelated candidate, so that the standard deviations are not degenerate.
    other = np.full(N_FEATURES, 0.5, dtype=np.float32)
    candidates = np.stack([star_diff, bpm_diff, other])

    weights = {feature: 1.0 for feature in SIMILARITY_FEATURES}
    weights["star_rating"] = 5.0  # Now differences in star rating have a large effect.

    result = calculate_seed_similarity(
        ids("seed"), seed, ids("star", "bpm", "other"), candidates,
        similarity_feature_weights=weights,
    )
    assert result["bpm"] > result["star"]


def test_inf_bpm_does_not_poison_every_similarity(recommender_db):
    # Regression test for the loved gimmick maps with infinite BPM. Before the
    # fix, one inf made all means and stds NaN, and all similarities failed.
    # A *regression test* repeats a bug that was fixed, so that the bug cannot
    # come back without notice.
    db = recommender_db
    db.add_beatmap(1, stars=5.0)
    db.add_beatmap(2, stars=5.1)
    db.add_beatmap(3, stars=5.2, bpm=float("inf"), status="loved")
    db.add_score(7, 1)

    index = build_seed_similarity_index(db.conn, 7)

    assert set(index) == {"2", "3"}
    assert all(np.isfinite(value) for value in index.values())


def test_build_index_excludes_played_maps_by_default(seeded_db):
    index = build_seed_similarity_index(seeded_db.conn, 100)
    assert not {"1", "2", "3", "4"} & set(index)

    with_played = build_seed_similarity_index(seeded_db.conn, 100, exclude_already_played=False)
    assert {"1", "2", "3", "4"} <= set(with_played)


def test_build_index_status_filter(seeded_db):
    loved_only = build_seed_similarity_index(seeded_db.conn, 100, status="loved")
    assert set(loved_only) == {"11"}


def test_player_without_scores_gets_empty_index(seeded_db):
    assert build_seed_similarity_index(seeded_db.conn, 424242) == {}


@pytest.mark.parametrize(
    ("player_id", "status"),
    [(None, None), (100, None), (100, "loved"), (None, "ranked"), (424242, None)],
)
def test_get_maps_matches_sql(seeded_db, player_id, status):
    # get_maps() reads the variant table in memory. This is the SQL that it replaced.
    query = f"""
        SELECT CAST(bv.beatmap_id AS TEXT), {", ".join(f"COALESCE(bv.{name}, 0.0)" for name in SIMILARITY_FEATURES)}
        FROM beatmap_variants AS bv
        WHERE bv.mods = 'NM'
    """
    params = []
    if status is not None:
        query += " AND bv.status = ?"
        params.append(status)
    if player_id is not None:
        query += " AND NOT EXISTS (SELECT 1 FROM scores AS s WHERE s.player_id = ? AND s.beatmap_id = bv.beatmap_id)"
        params.append(player_id)
    query += " ORDER BY bv.rowid"

    rows = seeded_db.conn.execute(query, params).fetchall()
    expected = np.nan_to_num(np.array([row[1:] for row in rows], dtype=np.float32), posinf=0.0, neginf=0.0)

    beatmap_ids, matrix = get_maps(seeded_db.conn, mods="NM", player_id=player_id, status=status)

    assert beatmap_ids.tolist() == [row[0] for row in rows]
    np.testing.assert_array_equal(matrix, expected.reshape(len(rows), N_FEATURES))
