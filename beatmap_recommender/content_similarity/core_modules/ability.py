from datetime import datetime, timezone

import numpy as np


def get_recency_weight(created_at, recency_half_life_days):
    """
    Return a weight for a score that gets smaller with the age of the score.
    A score loses half of its weight every recency_half_life_days.

    Examples with a 30-day half-life:

        age =   0 days -> 1.000
        age =  30 days -> 0.500
        age =  60 days -> 0.250
        age =  90 days -> 0.125
    """

    if not created_at:
        return 1.0

    try:
        played_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_days = max(0.0, (now - played_at).total_seconds() / 86400.0)
        return 0.5 ** (age_days / recency_half_life_days)

    except (TypeError, ValueError):
        # If the timestamp is not valid, keep the full weight of the score.
        return 1.0


def get_ability_score_weight(
    source,
    pp,
    created_at,
    recency_half_life_days,
    ability_top_weight,
    ability_recent_weight,
    ability_pp_weight,
):
    """
    Return the weight of a score for the estimate of the current ability.

    The weight is the product of three parts: the recency, the source of the
    score, and the pp. Here, recent scores get more weight than in the mod
    preferences, because they show the current ability of the player better.
    """
    weight = get_recency_weight(created_at, recency_half_life_days)

    # Source. The "top" scores give a stable baseline from the past. The
    # "recent" scores show the current ability better. "top,recent" means that
    # the score is in both lists. It counts as top, so that it does not get
    # extra weight only because it is in two lists.
    if source in ("top", "top,recent"):
        weight *= ability_top_weight
    elif source == "recent":
        weight *= ability_recent_weight

    # PP
    if pp is not None:
        try:
            pp = float(pp)
        except (TypeError, ValueError):
            pp = 0.0

        if pp > 0:
            weight *= 1.0 + ability_pp_weight * np.sqrt(pp) / 10.0

    return weight


def weighted_mean_and_std(values, weights):
    """Return the weighted mean and the weighted population standard deviation."""
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    total_weight = weights.sum()

    if total_weight <= 0:
        return float(values.mean()), float(values.std())

    mean = np.sum(weights * values) / total_weight
    variance = np.sum(weights * (values - mean) ** 2) / total_weight
    std = np.sqrt(max(variance, 0.0))

    return float(mean), float(std)
