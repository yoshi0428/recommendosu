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


def _as_float(value):
    """float(value), or NaN when value is missing or not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _square(values):
    """
    values ** 2 through C pow(), like Python's float ** 2. numpy's ** 2
    multiplies instead, which can differ in the last bit.
    """
    return np.float_power(values, 2.0)


def _neumaier_add(total, compensation, values, mask):
    """
    One step of sum() over floats, per element where mask is set.

    CPython's sum() uses Neumaier compensated summation for floats since
    3.12, so this is what calculate_pp_potential's sum() over a list did.
    Returns the new (total, compensation).
    """
    new_total = total + values
    step = np.where(
        np.abs(total) >= np.abs(values),
        (total - new_total) + values,
        (values - new_total) + total,
    )
    return np.where(mask, new_total, total), np.where(mask, compensation + step, compensation)


def _neumaier_result(total, compensation):
    """sum()'s final result: the total plus a nonzero, finite compensation."""
    return np.where((compensation != 0) & np.isfinite(compensation), total + compensation, total)


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
    calculate_pp_potentials() for one variant dict.
    """
    columns = {
        name: np.array([_as_float(variant.get(name))])
        for name in ("pp", *difficulty_feature_weights)
    }

    return float(
        calculate_pp_potentials(
            columns,
            difficulty_profile,
            difficulty_std_floors,
            difficulty_feature_weights,
            pp_push_target_z,
            pp_push_max_z,
            feature_target_z,
            feature_max_z,
            pp_min=pp_min,
            pp_max=pp_max,
        )[0]
    )


def calculate_pp_potentials(
    columns,
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

    columns maps "pp" and each difficulty feature to a float64 array, one
    value per variant, NaN where the variant has no usable value. A feature
    missing from columns counts as missing for every variant.

    Filters out maps below pp_min (pp_mean + target_z * pp_std).
    Candidates in [pp_min, pp_max] are mapped across the full [0.0, 1.0] range.
    """
    pp = np.asarray(columns["pp"], dtype=np.float64)
    scores = np.zeros(len(pp))

    if not difficulty_profile:
        return scores

    # ---------------------------------------------------------------
    # 1. Hard Filtering (Validates Intentional Push Thresholds)
    # ---------------------------------------------------------------
    # Strict bounds: Drops plays below pp_min or above pp_max.
    # NaN (no pp) fails pp > 0 and is dropped too.
    eligible = pp > 0
    if pp_min is not None:
        eligible &= pp >= pp_min
    if pp_max is not None:
        eligible &= pp <= pp_max

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
    # Summed one feature at a time, the way sum() over a list would.
    squared_diff_sum, squared_diff_compensation = np.zeros(len(pp)), np.zeros(len(pp))
    weight_sum, weight_compensation = np.zeros(len(pp)), np.zeros(len(pp))
    has_feature = np.zeros(len(pp), dtype=bool)

    for feature, weight in difficulty_feature_weights.items():
        f_mean = difficulty_profile.get(f"{feature}_mean")
        f_std = difficulty_profile.get(f"{feature}_std")

        if feature not in columns or f_mean is None or f_std is None:
            continue

        try:
            f_mean, f_std = float(f_mean), float(f_std)
        except (TypeError, ValueError):
            continue

        values = np.asarray(columns[feature], dtype=np.float64)
        valid = ~np.isnan(values)

        std_floor = difficulty_std_floors.get(feature, 1.0)
        f_std = max(f_std, std_floor)

        z_feat = (values - f_mean) / f_std
        squared_diff_sum, squared_diff_compensation = _neumaier_add(
            squared_diff_sum, squared_diff_compensation, weight * _square(z_feat), valid
        )
        weight_sum, weight_compensation = _neumaier_add(
            weight_sum, weight_compensation, np.full(len(pp), float(weight)), valid
        )
        has_feature |= valid

    squared_diff_sum = _neumaier_result(squared_diff_sum, squared_diff_compensation)
    weight_sum = _neumaier_result(weight_sum, weight_compensation)

    eligible &= has_feature & (weight_sum > 0)

    with np.errstate(invalid="ignore", divide="ignore"):
        difficulty_distance = np.sqrt(squared_diff_sum / weight_sum)

    # ---------------------------------------------------------------
    # 4. Difficulty Alignment Multiplier
    # ---------------------------------------------------------------
    # If difficulty is within comfort/target range, give it FULL credit (1.0).
    # Only penalize if difficulty EXCEEDS the max comfortable threshold.
    # Smooth exponential decay only when maps become too hard to play
    excess = difficulty_distance - feature_target_z
    scale = max(feature_max_z - feature_target_z, 0.5)
    difficulty_factor = np.where(
        difficulty_distance <= feature_target_z,
        1.0,  # Comfort zone maps get 100% of their PP potential!
        np.exp(-0.5 * _square(excess / scale)),
    )

    # ---------------------------------------------------------------
    # 5. Output Clamped Potential Score
    # ---------------------------------------------------------------
    scores[eligible] = np.clip(pp_factor * difficulty_factor, 0.0, 1.0)[eligible]
    return scores
