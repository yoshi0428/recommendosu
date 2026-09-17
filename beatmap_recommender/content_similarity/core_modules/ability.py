from datetime import datetime, timezone
import numpy as np

def get_recency_weight(created_at, recency_half_life_days):
    """
    Calculate a time-decay weight for a score.
    A score loses half of its weight every RECENCY_HALF_LIFE_DAYS.

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
        age_days = max(0.0, (now - played_at).total_seconds() / 86400.0,)
        return 0.5 ** (age_days / recency_half_life_days)

    except (TypeError, ValueError):
        # If the timestamp cannot be parsed, don't discard the score.
        return 1.0

def get_ability_score_weight(source, pp, created_at, recency_half_life_days, ability_top_weight, ability_recent_weight, ability_pp_weight):
    """
    Calculate the weight of a score when estimating current ability.

    Unlike mod preference weighting, recent scores are intentionally given
    more importance because they are a better indicator of the player's current ability.

    Weight components:
        1. recency
        2. score source
        3. PP
    """
    weight = get_recency_weight(created_at, recency_half_life_days)

    # ---------------------------------------------------------------
    # Source
    # ---------------------------------------------------------------
    # "top" scores provide a stable historical baseline.
    # "recent" scores are more representative of current ability.
    # "top,recent" means the same score appeared in both collections. Treat it as recent rather than double-counting it.
    if source == "top":
        weight *= ability_top_weight
    elif source == "recent":
        weight *= ability_recent_weight
    elif source == "top,recent":
        weight *= ability_recent_weight
    else:
        weight *= 1.0

    # ---------------------------------------------------------------
    # PP
    # ---------------------------------------------------------------
    if pp is not None:
        try:
            pp = float(pp)
        except (TypeError, ValueError):
            pp = 0.0

        if pp > 0:
            weight *= 1.0 + ability_pp_weight * np.sqrt(pp) / 10.0

    return weight