import numpy as np

def weighted_mean_and_std(values, weights):
    """
    Calculate a weighted mean and population standard deviation.
    """
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    total_weight = weights.sum()

    if total_weight <= 0:
        return float(values.mean()), float(values.std())

    mean = np.sum(weights * values) / total_weight
    variance = np.sum(weights * (values - mean) ** 2) / total_weight
    std = np.sqrt(max(variance, 0.0))

    return float(mean), float(std)

def calculate_pp_potential(
    variant,
    difficulty_profile,
    difficulty_std_floors,
    difficulty_feature_weights,
    pp_push_target_z,
    pp_push_max_z,
):
    """
    Estimate the PP potential of a candidate relative to the player's demonstrated difficulty.
    This is NOT an estimate of guaranteed PP gain.

    Returns:
        pp_potential_score: approximately [0, 1]

    Higher values indicate that the candidate has relatively high PP potential while remaining within a reasonable difficulty range.

    The candidate's PP is combined with its difficulty relative to the player's current profile.
    A candidate that is extremely difficult receives a penalty even if its raw PP is very high.
    """

    if not difficulty_profile:
        return 0.5

    pp = variant.get("pp")

    if pp is None:
        return 0.5

    try:
        pp = float(pp)
    except (TypeError, ValueError):
        return 0.5

    if pp <= 0:
        return 0.5

    # ---------------------------------------------------------------
    # Calculate weighted difficulty distance.
    # ---------------------------------------------------------------

    weighted_squared_distance = 0.0
    total_weight = 0.0

    for feature, feature_weight in difficulty_feature_weights.items():

        value = variant.get(feature)
        if value is None:
            continue

        mean = difficulty_profile.get(f"{feature}_mean")
        std = difficulty_profile.get(f"{feature}_std")

        if mean is None or std is None:
            continue

        try:
            value = float(value)
            mean = float(mean)
            std = float(std)
        except (TypeError, ValueError):
            continue

        if std <= 0:
            std = difficulty_std_floors[feature]

        z = (value - mean) / std
        weighted_squared_distance += (feature_weight * z ** 2)
        total_weight += feature_weight

    if total_weight <= 0:
        return 0.5

    difficulty_distance = np.sqrt(weighted_squared_distance / total_weight)

    # ---------------------------------------------------------------
    # Determine whether the candidate is in the useful PP-push range.
    #
    # We want candidates somewhat above current ability, rather than
    # candidates that are either trivial or wildly beyond ability.
    # ---------------------------------------------------------------

    # If candidate is below the player's normal difficulty, reduce its PP-push value.
    if difficulty_distance < pp_push_target_z:
        difficulty_factor = difficulty_distance / pp_push_target_z
    else:
        difficulty_factor = 1.0

    # Penalize candidates that are extremely far from the player's demonstrated difficulty.
    if difficulty_distance > pp_push_max_z:
        excess = difficulty_distance - pp_push_max_z
        difficulty_factor *= np.exp(-excess ** 2)

    # ---------------------------------------------------------------
    # PP itself.
    # log1p prevents very high PP values from completely dominating.
    # ---------------------------------------------------------------
    pp_factor = np.log1p(pp)

    # Normalize PP factor to a practical range.
    # 300pp -> roughly 0.85
    # 400pp -> roughly 0.90
    # 500pp -> roughly 0.93
    #
    # This intentionally has diminishing returns.
    pp_factor = pp_factor / np.log1p(500.0)
    pp_factor = min(max(pp_factor, 0.0), 1.0)
    score = (pp_factor * difficulty_factor)

    return float(np.clip(score, 0.0, 1.0))