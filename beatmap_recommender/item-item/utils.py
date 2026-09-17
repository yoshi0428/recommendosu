import numpy as np
import math

def safe_float(value, default=0.0):
    if value is None:
        return default

    try:
        value = float(value)

        if not math.isfinite(value):
            return default

        return value

    except (TypeError, ValueError):
        return default

def safe_stats(values):
    """
    Calculate statistics for an array.
    """

    values = np.asarray(values, dtype=np.float32)

    values = values[
        np.isfinite(values)
    ]

    if len(values) == 0:
        return {
            "mean": 0.0,
            "median": 0.0,
            "std": 0.0,
            "p25": 0.0,
            "p75": 0.0,
            "min": 0.0,
            "max": 0.0,
        }

    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "std": float(np.std(values)),
        "p25": float(np.percentile(values, 25)),
        "p75": float(np.percentile(values, 75)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
    }

def normalize_mods(mods):
    """
    Convert a mod list into a canonical string.

    Examples:

        []          -> NM
        ["HD"]      -> HD
        ["HR"]      -> HR
        ["DT"]      -> DT
        ["HD","DT"] -> HDDT
    """

    if not mods:
        return "NM"

    mods = sorted(mods)

    return "".join(mods)

def get_clock_rate(mods):
    """
    Determine the clock rate associated with a mod combination.
    """

    if not mods:
        return 1.0
    if "DT" in mods:
        return 1.5
    if "HT" in mods:
        return 0.75

    return 1.0
