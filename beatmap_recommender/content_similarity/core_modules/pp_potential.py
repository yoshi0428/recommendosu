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
        pp_push_target_z=2.5,  # For PP filtering bounds
        pp_push_max_z=7.5,  # For PP filtering bounds
        feature_target_z=1.0,  # Ideal feature push distance (AR, BPM, etc.)
        feature_max_z=3.0,  # Feature limit before exponential decay
        pp_min=None,
        pp_max=None,
):
    """
    Estimate PP potential for candidates that pass the intentional push threshold.

    Filters out maps below pp_min (pp_mean + target_z * pp_std).
    Candidates in [pp_min, pp_max] are mapped across the full [0.0, 1.0] range.
    """
    if not difficulty_profile:
        return 0.0

    # ---------------------------------------------------------------
    # 1. Hard Filtering (Validates Intentional Push Thresholds)
    # ---------------------------------------------------------------
    try:
        pp = float(variant.get("pp", 0))
    except (TypeError, ValueError):
        return 0.0

    # Strict bounds: Drops plays below pp_min or above pp_max
    if pp <= 0:
        return 0.0
    if pp_min is not None and pp < pp_min:
        return 0.0
    if pp_max is not None and pp > pp_max:
        return 0.0

    # ---------------------------------------------------------------
    # 2. Linear PP Factor across the Push Window [pp_min, pp_max]
    # ---------------------------------------------------------------
    if pp_min is not None and pp_max is not None and pp_max > pp_min:
        # Maps pp_min -> 0.0 (entry push level) up to pp_max -> 1.0 (max push level)
        pp_factor = (pp - pp_min) / (pp_max - pp_min)
    else:
        # Fallback calculation using profile std if explicit bounds aren't passed
        pp_mean = float(difficulty_profile.get("pp_mean", 0))
        pp_std = max(float(difficulty_profile.get("pp_std", 1.0)), 1.0)

        lower_bound = pp_mean + (pp_push_target_z * pp_std)
        upper_bound = pp_mean + (pp_push_max_z * pp_std)

        pp_factor = (pp - lower_bound) / max(upper_bound - lower_bound, 1e-5)

    pp_factor = np.clip(pp_factor, 0.0, 1.0)

    # ---------------------------------------------------------------
    # 3. Weighted Feature Difficulty Distance
    # ---------------------------------------------------------------
    squared_diffs = []
    weights = []

    for feature, weight in difficulty_feature_weights.items():
        val = variant.get(feature)
        f_mean = difficulty_profile.get(f"{feature}_mean")
        f_std = difficulty_profile.get(f"{feature}_std")

        if val is None or f_mean is None or f_std is None:
            continue

        try:
            val, f_mean, f_std = float(val), float(f_mean), float(f_std)
        except (TypeError, ValueError):
            continue

        std_floor = difficulty_std_floors.get(feature, 1.0)
        f_std = max(f_std, std_floor)

        z_feat = (val - f_mean) / f_std
        squared_diffs.append(weight * (z_feat ** 2))
        weights.append(weight)

    if not weights or sum(weights) <= 0:
        return 0.0

    difficulty_distance = np.sqrt(sum(squared_diffs) / sum(weights))

    # ---------------------------------------------------------------
    # 4. Difficulty Alignment Multiplier
    # ---------------------------------------------------------------
    # If difficulty is within comfort/target range, give it FULL credit (1.0).
    # Only penalize if difficulty EXCEEDS the max comfortable threshold.
    if difficulty_distance <= feature_target_z:
        difficulty_factor = 1.0  # Comfort zone maps get 100% of their PP potential!
    else:
        # Smooth exponential decay only when maps become too hard to play
        excess = difficulty_distance - feature_target_z
        scale = max(feature_max_z - feature_target_z, 0.5)
        difficulty_factor = np.exp(-0.5 * (excess / scale) ** 2)

    # ---------------------------------------------------------------
    # 5. Output Clamped Potential Score
    # ---------------------------------------------------------------
    score = pp_factor * difficulty_factor
    return float(np.clip(score, 0.0, 1.0))