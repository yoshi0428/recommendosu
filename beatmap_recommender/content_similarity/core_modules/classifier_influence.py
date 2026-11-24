import numpy as np

from beatmap_recommender.content_similarity.core_modules.ability import (
    get_ability_score_weight,
)

NM_LABELS = ("NM1", "NM2", "NM3", "NM4", "NM5")


def get_player_category_preferences(
    conn,
    player_id,
    recency_half_life_days,
    ability_top_weight,
    ability_recent_weight,
    ability_pp_weight,
):
    """
    Return the preference of the player for each NM tournament category.

    The scores of the player use the same weights as the difficulty profile
    (ability.get_ability_score_weight): recent scores count more, top scores
    add the past, pp adds a little, and old scores count less.

    Returns:
        {
            "NM1": float,
            "NM2": float,
            "NM3": float,
            "NM4": float,
            "NM5": float,
        }
    """

    rows = conn.execute(
        """
        SELECT
            s.source,
            s.pp,
            s.created_at,
            vp.nm1,
            vp.nm2,
            vp.nm3,
            vp.nm4,
            vp.nm5
        FROM scores s
        JOIN beatmap_variants bv
            ON bv.beatmap_id = s.beatmap_id
           AND bv.mods = 'NM'
        JOIN variant_predictions vp
            ON vp.variant_id = bv.variant_id
        WHERE s.player_id = ?
          -- A failed play (rank F) does not show what the player can do.
          AND COALESCE(s.rank, '') != 'F'
          AND vp.nm1 IS NOT NULL
          AND vp.nm2 IS NOT NULL
          AND vp.nm3 IS NOT NULL
          AND vp.nm4 IS NOT NULL
          AND vp.nm5 IS NOT NULL
        """,
        (player_id,),
    ).fetchall()

    totals = {label: 0.0 for label in NM_LABELS}

    for source, pp, created_at, *probabilities in rows:
        weight = get_ability_score_weight(
            source,
            pp,
            created_at,
            recency_half_life_days,
            ability_top_weight,
            ability_recent_weight,
            ability_pp_weight,
        )

        for label, probability in zip(NM_LABELS, probabilities):
            totals[label] += weight * float(probability)

    total = sum(totals.values())

    if total <= 0:
        return {}

    return {label: value / total for label, value in totals.items()}


def calculate_classifier_scores(probabilities, preferences):
    """
    Return how well the NM1-NM5 prediction of each beatmap matches the NM
    category preferences of the player. 1.0 is a strong match, and 0.0 is a
    weak match.

    probabilities: [beatmaps, 5] NM1-NM5 probabilities, in NM_LABELS order.
    Returns a float64 array of scores in [0, 1].
    """
    probabilities = np.asarray(probabilities, dtype=np.float64)
    weights = [(preferences.get(label) or 0.0) if preferences else 0.0 for label in NM_LABELS]
    max_preference = max(weights)

    if max_preference <= 0:
        return np.zeros(len(probabilities))

    # Add one label at a time, in the same order as sum() over the labels.
    # A different order can change the last bits of the result.
    score = probabilities[:, 0] * weights[0]

    for column, weight in enumerate(weights[1:], start=1):
        score = score + probabilities[:, column] * weight

    return np.clip(score / max_preference, 0.0, 1.0)
