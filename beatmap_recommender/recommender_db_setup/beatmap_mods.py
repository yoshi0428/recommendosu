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


def apply_mod_to_stat(value, mods, stat):
    """
    A difficulty stat (cs, hp, ar or od) with these mods applied.

    osu-tools-py's CalculationResult doesn't include these stats, so they're
    calculated here: HR multiplies CS by 1.3 and the rest by 1.4 (capped at
    10), EZ halves them, and DT/HT change AR and OD through the clock rate.
    """

    if value is None:
        return None

    mods = {mod.upper() for mod in mods}

    # --------------------------------------------------------
    # CS
    # --------------------------------------------------------

    if stat == "cs":
        if "HR" in mods:
            return min(10.0, value * 1.3)

        if "EZ" in mods:
            return value * 0.5

        return value

    # --------------------------------------------------------
    # HP
    # --------------------------------------------------------

    if stat == "hp":
        if "HR" in mods:
            return min(10.0, value * 1.4)

        if "EZ" in mods:
            return value * 0.5

        return value

    # --------------------------------------------------------
    # AR / OD
    # --------------------------------------------------------

    if stat in ("ar", "od"):
        result = value

        # HR / EZ
        if "HR" in mods:
            result = min(10.0, result * 1.4)

        elif "EZ" in mods:
            result *= 0.5

        # Clock rate
        if "DT" in mods:
            clock_rate = 1.5
        elif "HT" in mods:
            clock_rate = 0.75
        else:
            clock_rate = 1.0

        if clock_rate == 1.0:
            return result

        # AR
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

        # OD
        elif stat == "od":
            milliseconds = 79.5 - 6.0 * result
            milliseconds /= clock_rate
            result = (79.5 - milliseconds) / 6.0

        max_value = 11.0 if "DT" in mods else 10.0
        return max(0.0, min(max_value, result))

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

    mods = {mod.upper() for mod in mods}

    multiplier = 1.0

    if "DT" in mods:
        multiplier = 1.5

    elif "HT" in mods:
        multiplier = 0.75

    return (
        bpm * multiplier if bpm is not None else None,
        min_bpm * multiplier if min_bpm is not None else None,
        max_bpm * multiplier if max_bpm is not None else None,
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

    mods = {mod.upper() for mod in mods}

    if "DT" in mods:
        return length_seconds / 1.5

    if "HT" in mods:
        return length_seconds / 0.75

    return length_seconds


def get_modded_stats(base_data, result, mods):
    """
    Final statistics for a beatmap + mod combination: HP/CS/OD/AR from the
    base beatmap with apply_mod_to_stat(), and star rating, max combo and pp
    from osu-tools-py's CalculationResult.
    """
    return {
        "hp_drain": apply_mod_to_stat(base_data["hp_drain"], mods, "hp"),
        "circle_size": apply_mod_to_stat(base_data["circle_size"], mods, "cs"),
        "od": apply_mod_to_stat(base_data["od"], mods, "od"),
        "ar": apply_mod_to_stat(base_data["ar"], mods, "ar"),
        "star_rating": result.stars,
        "max_combo": result.max_combo,
        "pp": result.pp,
        "pp_aim": result.pp_aim,
        "pp_speed": result.pp_speed,
        "pp_acc": result.pp_acc,
        "pp_flashlight": result.pp_flashlight,
    }
