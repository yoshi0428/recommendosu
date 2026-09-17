MOD_ORDER = [
    "EZ",
    "NF",
    "HT",
    "HD",
    "HR",
    "DT",
    "NC",
    "FL",
]

# Longest first is important if parsing concatenated strings.
KNOWN_MODS = sorted(
    MOD_ORDER,
    key=len,
    reverse=True,
)

def canonicalize_mods(mods):
    """
    Convert a mod representation into a canonical mod string.

    Supported inputs include:

        []
        ["HD", "DT"]
        ("HD", "DT")

        "HD"
        "HDDT"
        "DTHD"
        "HD,DT"
        "NM"

    Examples:

        []          -> NM
        ["HD"]      -> HD
        ["DT", "HD"] -> HDDT
        "DTHD"      -> HDDT
        "NM"        -> NM
    """

    if mods is None:
        return "NM"

    # --------------------------------------------------------
    # Iterable representation
    # --------------------------------------------------------

    if isinstance(
        mods,
        (list, tuple, set),
    ):
        parsed_mods = []

        for mod in mods:

            mod = str(mod).strip().upper()

            if not mod or mod == "NM":
                continue

            parsed_mods.extend(
                _parse_mod_string(mod)
            )

    # --------------------------------------------------------
    # String representation
    # --------------------------------------------------------

    else:
        mods = str(mods).strip().upper()

        if not mods or mods == "NM":
            return "NM"

        parsed_mods = _parse_mod_string(
            mods
        )

    # --------------------------------------------------------
    # Empty means NM
    # --------------------------------------------------------

    parsed_mods = set(parsed_mods)

    if not parsed_mods:
        return "NM"

    # --------------------------------------------------------
    # Canonical ordering
    # --------------------------------------------------------

    parsed_mods = sorted(
        parsed_mods,
        key=lambda mod: MOD_ORDER.index(mod)
    )

    return "".join(parsed_mods)


def _parse_mod_string(mod_string):
    """
    Parse a string containing one or more osu! mods.

    Examples:

        HD       -> ["HD"]
        HDDT     -> ["HD", "DT"]
        DTHD     -> ["DT", "HD"]
        DTHDHR   -> ["DT", "HD", "HR"]
        HD,DT    -> ["HD", "DT"]
    """

    # Handle common separators.
    mod_string = (
        mod_string
        .replace(",", "")
        .replace(" ", "")
        .replace("+", "")
    )

    if not mod_string:
        return []

    parsed = []
    remaining = mod_string

    while remaining:

        matched = False

        for mod in KNOWN_MODS:

            if remaining.startswith(mod):

                parsed.append(mod)

                remaining = remaining[
                    len(mod):
                ]

                matched = True
                break

        if not matched:
            raise ValueError(
                f"Unknown mod string: "
                f"{mod_string!r}, "
                f"remaining={remaining!r}"
            )

    return parsed