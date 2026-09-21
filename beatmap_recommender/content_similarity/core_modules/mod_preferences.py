import math
from collections import defaultdict

MOD_ORDER = [
    # Original order
    "EZ",
    "NF",
    "HT",
    "HD",
    "HR",
    "DT",
    "NC",
    "FL",

    # Difficulty Reduction
    "DC",
    "SR",
    "NR",

    # Difficulty Increase
    "SD",
    "PF",
    "FI",
    "TC",
    "CO",
    "BL",
    "ST",
    "AC",

    # Automation
    "AT",
    "CN",
    "RX",
    "AP",
    "SO",

    # Conversion
    "TP",
    "DA",
    "CL",
    "RD",
    "DS",
    "MR",
    "AL",
    "SW",
    "SG",
    "IN",
    "CS",
    "HO",
    "1K",
    "2K",
    "3K",
    "4K",
    "5K",
    "6K",
    "7K",
    "8K",
    "9K",
    "10K",

    # Fun
    "TR",
    "WG",
    "SI",
    "GR",
    "DF",
    "WU",
    "WD",
    "BR",
    "AD",
    "FF",
    "MU",
    "NS",
    "MG",
    "RP",
    "AS",
    "FR",
    "BU",
    "MF",
    "SY",
    "DP",
    "BM",

    # System
    "TD",
    "SV2",
]

# Longest first is important if parsing concatenated strings.
KNOWN_MODS = sorted(
    MOD_ORDER,
    key=len,
    reverse=True,
)

# --------------------------------------------------------
# Preference weighting
# --------------------------------------------------------

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
    if isinstance(mods, (list, tuple, set),):
        parsed_mods = []

        for mod in mods:
            mod = str(mod).strip().upper()
            if not mod or mod == "NM":
                continue

            parsed_mods.extend(_parse_mod_string(mod))

    # --------------------------------------------------------
    # String representation
    # --------------------------------------------------------
    else:
        mods = str(mods).strip().upper()
        if not mods or mods == "NM":
            return "NM"

        parsed_mods = _parse_mod_string(mods)

    # --------------------------------------------------------
    # Empty means NM
    # --------------------------------------------------------
    parsed_mods = set(parsed_mods)
    if not parsed_mods:
        return "NM"

    # --------------------------------------------------------
    # Canonical ordering
    # --------------------------------------------------------
    parsed_mods = sorted(parsed_mods, key=lambda mod: MOD_ORDER.index(mod))

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
                remaining = remaining[len(mod):]
                matched = True
                break

        if not matched:
            raise ValueError(f"Unknown mod string: {mod_string!r}, remaining={remaining!r}")

    return parsed


def get_score_weight(source, pp, top_weight, recent_weight, pp_weight):
    """
    Calculate the contribution of one score to mod preference.
    Top plays receive more weight than recent plays.
    A score appearing in both collections is treated as a top play only, preventing it from being counted twice.
    PP provides a small additional weighting factor.
    """

    source = (source or "").lower()

    # --------------------------------------------------------
    # Determine base source weight.
    # --------------------------------------------------------
    if source == "top":
        base_weight = top_weight
    elif source == "recent":
        base_weight = recent_weight
    elif source == "top,recent":
        base_weight = top_weight # Already a top play, so don't double-count it.
    else:
        # Unknown source.
        # This also makes the function reasonably safe if additional score sources are added later.
        base_weight = recent_weight

    # --------------------------------------------------------
    # Add a small PP contribution.
    # sqrt keeps very high PP scores from dominating.
    # --------------------------------------------------------
    if pp is None:
        pp_factor = 1.0
    else:
        try:
            pp = float(pp)
        except (TypeError, ValueError):
            pp = 0.0

        if pp > 0:
            pp_factor = 1.0 + pp_weight * (pp ** 0.5) / 10.0
        else:
            pp_factor = 1.0

    return base_weight * pp_factor


def get_player_mod_preferences(conn, player_id, top_weight, recent_weight, pp_weight):
    """
    Calculate weighted mod preferences from the player's scores.
    Each score contributes according to:
        source weight × PP factor

    Returns:
        {
            "NM": weighted_score,
            "HD": weighted_score,
            "HDDT": weighted_score,
            ...
        }
    """
    rows = conn.execute("""
        SELECT
            mods,
            source,
            pp
        FROM scores
        WHERE player_id = ?
    """, (player_id,)).fetchall()

    preferences = defaultdict(float)

    for mods, source, pp in rows:
        try:
            mods = canonicalize_mods(mods)
        except ValueError:
            print(f"Warning: ignoring unsupported mod combination {mods!r} for player {player_id}")
            continue

        weight = get_score_weight(source, pp, top_weight, recent_weight, pp_weight)
        preferences[mods] += weight

    return dict(preferences)


def normalize_mod_preferences(preferences):
    if not preferences:
        return {}

    transformed = {
        mods: math.log1p(preference)
        for mods, preference in preferences.items()
    }

    max_preference = max(transformed.values())
    if max_preference <= 0:
        return {
            mods: 0.0
            for mods in transformed
        }

    return {
        mods: value / max_preference
        for mods, value in transformed.items()
    }


def get_preferred_mods(
    conn,
    player_id,
    top_weight,
    recent_weight,
    pp_weight,
    min_preference=0.0,
):
    """
    Get the player's preferred mod combinations.
    Returns a list sorted from most preferred to least preferred.

    Example:

        [
            ("HD", 1.0),
            ("HDDT", 0.81),
            ("NM", 0.64),
            ("DT", 0.42),
        ]
    """

    raw_preferences = get_player_mod_preferences(conn, player_id, top_weight, recent_weight, pp_weight)
    normalized_preferences = normalize_mod_preferences(raw_preferences)

    preferred_mods = [
        (mods, preference,)
        for mods, preference in normalized_preferences.items()
        if preference >= min_preference
    ]

    preferred_mods.sort(key=lambda item: item[1], reverse=True)
    return preferred_mods