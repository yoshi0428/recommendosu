from beatmap_recommender.content_similarity.core_modules.ability import get_ability_score_weight

NM_LABELS = ("NM1", "NM2", "NM3", "NM4", "NM5")

def get_player_category_preferences(conn, player_id, recency_half_life_days, ability_top_weight, ability_recent_weight, ability_pp_weight):
    """
    Calculate the player's preference for each NM tournament category.

    Player scores are weighted using the same ability weighting as the
    difficulty profile:
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

    rows = conn.execute("""
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
    """, (player_id,)).fetchall()

    totals = {
        label: 0.0
        for label in NM_LABELS
    }

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
            recency_half_life_days, ability_top_weight, ability_recent_weight, ability_pp_weight
        )

        probabilities = {
            "NM1": nm1,
            "NM2": nm2,
            "NM3": nm3,
            "NM4": nm4,
            "NM5": nm5,
        }

        for label, probability in probabilities.items():
            totals[label] += (weight * float(probability))

    total = sum(totals.values())

    if total <= 0:
        return {}

    return {
        label: value / total
        for label, value in totals.items()
    }


def get_candidate_classifier_predictions(conn, variant_ids):
    """
    Fetch precomputed NM1-NM5 classifier probabilities for candidate variants.

    Returns:

        {
            variant_id: {
                "NM1": probability,
                "NM2": probability,
                ...
            }
        }
    """

    if not variant_ids:
        return {}

    placeholders = ",".join("?" for _ in variant_ids)
    rows = conn.execute(
        f"""
        SELECT
            variant_id,
            nm1,
            nm2,
            nm3,
            nm4,
            nm5
        FROM variant_predictions
        WHERE variant_id IN ({placeholders})
        """,
        list(variant_ids),
    ).fetchall()

    return {
        variant_id: {
            "NM1": nm1,
            "NM2": nm2,
            "NM3": nm3,
            "NM4": nm4,
            "NM5": nm5,
        }
        for (
            variant_id,
            nm1,
            nm2,
            nm3,
            nm4,
            nm5,
        ) in rows
    }


def calculate_classifier_score(
    probabilities,
    preferences,
):
    """
    Calculate how well a candidate's NM1-NM5 prediction matches
    the player's NM category preferences.

    Returns approximately [0, 1]:

        1.0 = strong match
        0.0 = weak match
        0.5 = unknown / neutral
    """

    if not probabilities or not preferences:
        return 0.5

    score = sum(
        (probabilities.get(label) or 0.0)
        * (preferences.get(label) or 0.0)
        for label in NM_LABELS
    )

    max_preference = max(
        (preferences.get(label) or 0.0)
        for label in NM_LABELS
    )

    if max_preference <= 0:
        return 0.5

    return min(max(score / max_preference, 0.0), 1.0)