def calculate_difficulty(file_path, mods, star_calculator):
    """
    Calculate the difficulty attributes of a beatmap + mod combination.

    The osu-tools-py calculator accepts mods as lists of strings, such as:
        []
        ["HD"]
        ["HR"]
        ["DT"]
        ["HD", "DT"]

    Return the CalculationResult object, or None if the calculation fails.
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


def _clock_rate(mods):
    """Return the speed of the song with these mods: 1.5 for DT, 0.75 for HT, or 1.0."""
    mods = {mod.upper() for mod in mods}

    if "DT" in mods:
        return 1.5
    if "HT" in mods:
        return 0.75
    return 1.0


def apply_mod_to_stat(value, mods, stat):
    """
    Return a difficulty stat (cs, hp, ar or od) with these mods applied.

    The CalculationResult of osu-tools-py does not have these stats, so this
    function calculates them. HR multiplies CS by 1.3 and the others by 1.4
    (10 at most). EZ halves them. DT/HT change AR and OD through the clock rate.
    """

    if value is None:
        return None

    mods = {mod.upper() for mod in mods}

    if stat in ("cs", "hp"):
        if "HR" in mods:
            return min(10.0, value * (1.3 if stat == "cs" else 1.4))

        if "EZ" in mods:
            return value * 0.5

        return value

    if stat in ("ar", "od"):
        result = value

        if "HR" in mods:
            result = min(10.0, result * 1.4)

        elif "EZ" in mods:
            result *= 0.5

        clock_rate = _clock_rate(mods)

        if clock_rate == 1.0:
            return result

        # DT/HT change the time windows, not the values. Change AR or OD into
        # milliseconds, scale the time, and change it back.
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

        else:
            milliseconds = 79.5 - 6.0 * result
            milliseconds /= clock_rate
            result = (79.5 - milliseconds) / 6.0

        max_value = 11.0 if "DT" in mods else 10.0
        return max(0.0, min(max_value, result))

    return value


def apply_bpm_mod(bpm, min_bpm, max_bpm, mods):
    """
    Return the effective (bpm, min_bpm, max_bpm) of a modded variant: 1.5x for
    DT, 0.75x for HT, and 1.0x for the other mods.
    """
    multiplier = _clock_rate(mods)

    return (
        bpm * multiplier if bpm is not None else None,
        min_bpm * multiplier if min_bpm is not None else None,
        max_bpm * multiplier if max_bpm is not None else None,
    )


def apply_length_mod(length_seconds, mods):
    """
    Return the effective play length of a modded variant: the length / 1.5
    for DT, / 0.75 for HT, and no change for the other mods.
    """
    if length_seconds is None:
        return None

    clock_rate = _clock_rate(mods)
    return length_seconds if clock_rate == 1.0 else length_seconds / clock_rate


def get_modded_stats(base_data, result, mods):
    """
    Return the final statistics of a beatmap + mod combination: HP/CS/OD/AR
    from the base beatmap with apply_mod_to_stat(), and the star rating, the
    max combo and the pp from the CalculationResult of osu-tools-py.
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
