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
    Calculate the player's preference for each NM tournament category.

    Player scores are weighted using the same ability weighting as the difficulty profile:
        - recent scores have more influence
        - top scores provide historical influence
        - PP provides a small additional weighting
        - old scores decay over time

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
          AND vp.nm1 IS NOT NULL
          AND vp.nm2 IS NOT NULL
          AND vp.nm3 IS NOT NULL
          AND vp.nm4 IS NOT NULL
          AND vp.nm5 IS NOT NULL
        """,
        (player_id,),
    ).fetchall()

    totals = {label: 0.0 for label in NM_LABELS}

    for (
        source,
        pp,
        created_at,
        nm1,
        nm2,
        nm3,
        nm4,
        nm5,
    ) in rows:
        weight = get_ability_score_weight(
            source,
            pp,
            created_at,
            recency_half_life_days,
            ability_top_weight,
            ability_recent_weight,
            ability_pp_weight,
        )

        probabilities = {
            "NM1": nm1,
            "NM2": nm2,
            "NM3": nm3,
            "NM4": nm4,
            "NM5": nm5,
        }

        for label, probability in probabilities.items():
            totals[label] += weight * float(probability)

    total = sum(totals.values())

    if total <= 0:
        return {}

    return {label: value / total for label, value in totals.items()}


def calculate_classifier_scores(probabilities, preferences):
    """
    calculate_classifier_score() for many beatmaps at once.

    probabilities: [beatmaps, 5] NM1-NM5 probabilities, in NM_LABELS order.
    Returns a float64 array of scores in [0, 1].
    """
    probabilities = np.asarray(probabilities, dtype=np.float64)
    weights = [(preferences.get(label) or 0.0) if preferences else 0.0 for label in NM_LABELS]
    max_preference = max(weights)

    if max_preference <= 0:
        return np.zeros(len(probabilities))

    # Summed one label at a time, like sum() over the labels would.
    score = probabilities[:, 0] * weights[0]

    for column, weight in enumerate(weights[1:], start=1):
        score = score + probabilities[:, column] * weight

    return np.clip(score / max_preference, 0.0, 1.0)


def calculate_classifier_score(
    probabilities,
    preferences,
):
    """
    Calculate how well a candidate's NM1-NM5 prediction matches the player's NM category preferences.

    Returns [0, 1]:

        1.0 = strong match
        0.0 = weak match

    Missing classifier probabilities or player preferences return 0.0 rather than a neutral 0.5 fallback.
    """

    if not probabilities or not preferences:
        return 0.0

    row = [(probabilities.get(label) or 0.0) for label in NM_LABELS]
    return float(calculate_classifier_scores([row], preferences)[0])
