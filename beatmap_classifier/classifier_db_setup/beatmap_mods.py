def calculate_difficulty(file_path, mods, star_calculator):
    """
    Calculate difficulty attributes for a beatmap + mod combination.

    The osu-tools-py calculator accepts mods as strings such as:
        []
        ["HD"]
        ["HR"]
        ["DT"]
        ["HD", "DT"]

    Returns the CalculationResult object, or None on failure.
    """

    result = star_calculator.calculate(
        file_path=file_path,
        mode=0,
        mods=mods,
    )

    if not result.is_success:
        print(f"\nFAILED: {file_path}")
        print(f"Mods: {mods}")
        print(f"Error: {result.error}")
        return None

    return result


def get_result_attribute(result, *names):
    """
    Safely retrieve the first available attribute from a
    CalculationResult object.

    Different versions of osu-tools-py may expose slightly
    different attribute names.
    """

    for name in names:
        if hasattr(result, name):
            value = getattr(result, name)

            if value is not None:
                return value

    return None


def apply_mod_to_stat(value, mods, stat):
    """
    Apply an osu! mod transformation to a difficulty stat.

    This is primarily a fallback for attributes that are not
    directly exposed by the installed osu-tools-py version.

    HR:
        AR / CS / OD / HP are multiplied by 1.4 and capped at 10.

    EZ:
        AR / CS / OD / HP are multiplied by 0.5.

    DT:
        AR and OD are transformed according to the clock rate.

    HT:
        AR and OD are transformed according to the clock rate.

    CS and HP are not affected by DT/HT.
    """

    if value is None:
        return None

    mods = {
        mod.upper()
        for mod in mods
    }

    # --------------------------------------------------------
    # Circle Size
    # --------------------------------------------------------

    if stat == "cs":

        if "HR" in mods:
            return min(10.0, value * 1.4)

        if "EZ" in mods:
            return value * 0.5

        return value

    # --------------------------------------------------------
    # HP Drain
    # --------------------------------------------------------

    if stat == "hp":

        if "HR" in mods:
            return min(10.0, value * 1.4)

        if "EZ" in mods:
            return value * 0.5

        return value

    # --------------------------------------------------------
    # Approach Rate / Overall Difficulty
    # --------------------------------------------------------

    if stat in ("ar", "od"):

        result = value

        # HR / EZ first
        if "HR" in mods:
            result = min(10.0, result * 1.4)

        elif "EZ" in mods:
            result *= 0.5

        # Determine clock rate
        clock_rate = 1.0

        if "DT" in mods:
            clock_rate = 1.5

        elif "HT" in mods:
            clock_rate = 0.75

        # No clock-rate transformation necessary
        if clock_rate == 1.0:
            return result

        # ----------------------------------------------------
        # AR
        # ----------------------------------------------------

        if stat == "ar":
            if result <= 5.0:
                milliseconds = 1800.0 - 120.0 * result
            else:
                milliseconds = 1200.0 - 150.0 * (result - 5.0)

            milliseconds /= clock_rate

            if milliseconds >= 1200.0:
                result = (1800.0 - milliseconds) / 120.0
            else:
                result = 5.0 + (1200.0 - milliseconds) / 150.0

        # ----------------------------------------------------
        # OD
        # ----------------------------------------------------
        elif stat == "od":
            milliseconds = 79.5 - 6.0 * result
            milliseconds /= clock_rate
            result = (79.5 - milliseconds) / 6.0

        return max(0.0, min(11.0, result))

    return value


def apply_bpm_mod(
    bpm,
    min_bpm,
    max_bpm,
    mods,
):
    """
    Calculate effective BPM values for a modded variant.

    NM / HD / HR:
        1.0x

    DT:
        1.5x

    HT:
        0.75x
    """

    mods = {
        mod.upper()
        for mod in mods
    }

    multiplier = 1.0

    if "DT" in mods:
        multiplier = 1.5

    elif "HT" in mods:
        multiplier = 0.75

    return (
        bpm * multiplier
        if bpm is not None
        else None,

        min_bpm * multiplier
        if min_bpm is not None
        else None,

        max_bpm * multiplier
        if max_bpm is not None
        else None,
    )


def apply_length_mod(
    length_seconds,
    mods,
):
    """
    Calculate effective gameplay length for a modded variant.

    DT:
        duration / 1.5

    HT:
        duration / 0.75

    NM / HD / HR:
        unchanged
    """

    if length_seconds is None:
        return None

    mods = {
        mod.upper()
        for mod in mods
    }

    if "DT" in mods:
        return length_seconds / 1.5

    if "HT" in mods:
        return length_seconds / 0.75

    return length_seconds


def get_modded_stats(
    base_data,
    result,
    mods,
):
    """
    Construct the final statistics for a beatmap variant.

    Prefer values directly calculated by osu-tools-py.

    If an attribute is not exposed by the installed version,
    fall back to manual mod transformations.
    """

    base_hp = base_data["hp_drain"]
    base_cs = base_data["circle_size"]
    base_od = base_data["od"]
    base_ar = base_data["ar"]

    # --------------------------------------------------------
    # Try to get calculated values directly
    # --------------------------------------------------------

    hp = get_result_attribute(
        result,
        "hp",
        "hp_drain",
    )

    cs = get_result_attribute(
        result,
        "cs",
        "circle_size",
    )

    od = get_result_attribute(
        result,
        "od",
    )

    ar = get_result_attribute(
        result,
        "ar",
    )

    # --------------------------------------------------------
    # Fallbacks
    # --------------------------------------------------------

    if hp is None:
        hp = apply_mod_to_stat(
            base_hp,
            mods,
            "hp",
        )

    if cs is None:
        cs = apply_mod_to_stat(
            base_cs,
            mods,
            "cs",
        )

    if od is None:
        od = apply_mod_to_stat(
            base_od,
            mods,
            "od",
        )

    if ar is None:
        ar = apply_mod_to_stat(
            base_ar,
            mods,
            "ar",
        )

    # --------------------------------------------------------
    # Calculator outputs
    # --------------------------------------------------------

    stars = get_result_attribute(
        result,
        "stars",
        "star_rating",
    )

    max_combo = get_result_attribute(
        result,
        "max_combo",
    )

    pp = get_result_attribute(
        result,
        "pp",
    )

    pp_aim = get_result_attribute(
        result,
        "pp_aim",
    )

    pp_speed = get_result_attribute(
        result,
        "pp_speed",
    )

    pp_acc = get_result_attribute(
        result,
        "pp_acc",
    )

    pp_flashlight = get_result_attribute(
        result,
        "pp_flashlight",
    )

    return {
        "hp_drain": hp,
        "circle_size": cs,
        "od": od,
        "ar": ar,
        "star_rating": stars,
        "max_combo": max_combo,
        "pp": pp,
        "pp_aim": pp_aim,
        "pp_speed": pp_speed,
        "pp_acc": pp_acc,
        "pp_flashlight": pp_flashlight,
    }