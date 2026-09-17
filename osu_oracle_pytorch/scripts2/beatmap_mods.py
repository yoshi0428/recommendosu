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
                result = (
                    1800.0 - milliseconds
                ) / 120.0

            else:
                result = (
                    5.0
                    + (1200.0 - milliseconds) / 150.0
                )

        # ----------------------------------------------------
        # OD
        # ----------------------------------------------------

        elif stat == "od":

            milliseconds = 79.5 - 6.0 * result

            milliseconds /= clock_rate

            result = (
                79.5 - milliseconds
            ) / 6.0

        return max(
            0.0,
            min(10.0, result),
        )

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

    return {
        "hp_drain": hp,
        "circle_size": cs,
        "od": od,
        "ar": ar,
        "star_rating": stars,
        "max_combo": max_combo,
    }


def create_variant_vectors(
    base_vectors,
    mods,
    time_scale=1000.0,
    length_scale=500.0,
):
    """
    Convert RAW base vectors into CNN-ready vectors for a
    particular mod combination.

    Input vectors:

        (
            x_diff,
            y_diff,
            time_diff,
            length
        )

    The database should contain RAW values.

    Mod-specific transformation and normalization happen here.

    DT:
        time_diff / 1.5

    HT:
        time_diff / 0.75

    HR / EZ / HD:
        no sequence-level transformation here.

    IMPORTANT:
        time_scale and length_scale should be fixed across
        the dataset rather than calculated independently for
        each beatmap or variant.

    This preserves the information that DT is faster than NM.
    """

    mods = {
        mod.upper()
        for mod in mods
    }

    # --------------------------------------------------------
    # Clock rate
    # --------------------------------------------------------

    if "DT" in mods:
        speed_multiplier = 1.5

    elif "HT" in mods:
        speed_multiplier = 0.75

    else:
        speed_multiplier = 1.0

    # --------------------------------------------------------
    # Convert vectors
    # --------------------------------------------------------

    vectors = []

    for (
        x_diff,
        y_diff,
        time_diff,
        length,
    ) in base_vectors:

        effective_time_diff = (
            time_diff / speed_multiplier
        )

        vectors.append(
            (
                x_diff,
                y_diff,
                effective_time_diff / time_scale,
                length / length_scale,
            )
        )

    return vectors