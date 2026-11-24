import logging
import math
from collections import defaultdict

logger = logging.getLogger(__name__)

# All the osu! mods that the parser knows, in the canonical order. The list is
# long so that an unusual mod does not stop a recommendation.
MOD_ORDER = [
    # The original order
    "EZ", "NF", "HT", "HD", "HR", "DT", "NC", "FL",
    # Difficulty reduction
    "DC", "SR", "NR",
    # Difficulty increase
    "SD", "PF", "FI", "TC", "CO", "BL", "ST", "AC",
    # Automation
    "AT", "CN", "RX", "AP", "SO",
    # Conversion
    "TP", "DA", "CL", "RD", "DS", "MR", "AL", "SW", "SG", "IN", "CS", "HO",
    "1K", "2K", "3K", "4K", "5K", "6K", "7K", "8K", "9K", "10K",
    # Fun
    "TR", "WG", "SI", "GR", "DF", "WU", "WD", "BR", "AD", "FF", "MU", "NS",
    "MG", "RP", "AS", "FR", "BU", "MF", "SY", "DP", "BM",
    # System
    "TD", "SV2",
]  # fmt: skip

# The parser tries the longest names first. Thus a long mod name wins over a
# shorter name at the start of it.
KNOWN_MODS = sorted(MOD_ORDER, key=len, reverse=True)


def canonicalize_mods(mods):
    """
    Change a set of mods into one canonical mod string.

    The function accepts these inputs:

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

    if isinstance(mods, (list, tuple, set)):
        parsed_mods = []

        for mod in mods:
            mod = str(mod).strip().upper()
            if not mod or mod == "NM":
                continue

            parsed_mods.extend(parse_mod_string(mod))
    else:
        mods = str(mods).strip().upper()
        if not mods or mods == "NM":
            return "NM"

        parsed_mods = parse_mod_string(mods)

    parsed_mods = set(parsed_mods)
    if not parsed_mods:
        return "NM"

    # NC is DT with a higher audio pitch, so it counts as DT. beatmap_variants
    # stores only the DT combinations.
    if "NC" in parsed_mods:
        parsed_mods.discard("NC")
        parsed_mods.add("DT")

    return "".join(sorted(parsed_mods, key=MOD_ORDER.index))


def parse_mod_string(mod_string):
    """
    Split a string of one or more osu! mods into a list of mods.

    Examples:

        HD       -> ["HD"]
        HDDT     -> ["HD", "DT"]
        DTHD     -> ["DT", "HD"]
        DTHDHR   -> ["DT", "HD", "HR"]
        HD,DT    -> ["HD", "DT"]
    """

    # Remove the usual separators.
    mod_string = mod_string.replace(",", "").replace(" ", "").replace("+", "")

    parsed = []
    remaining = mod_string

    while remaining:
        for mod in KNOWN_MODS:
            if remaining.startswith(mod):
                parsed.append(mod)
                remaining = remaining[len(mod) :]
                break
        else:
            raise ValueError(f"Unknown mod string: {mod_string!r}, remaining={remaining!r}")

    return parsed


def get_score_weight(source, pp, top_weight, recent_weight, pp_weight):
    """
    Return the weight of one score in the mod preferences.

    Top plays get more weight than recent plays. A score that is in both lists
    ("top,recent") counts as a top play only, so that it does not count twice.
    The pp adds a small extra weight.
    """
    source = (source or "").lower()

    # A source that the code does not know gets the recent weight. Thus a new
    # score source does not break this function.
    base_weight = top_weight if source in ("top", "top,recent") else recent_weight

    # The square root stops very high pp scores from having too much effect.
    pp_factor = 1.0
    if pp is not None:
        try:
            pp = float(pp)
        except (TypeError, ValueError):
            pp = 0.0

        if pp > 0:
            pp_factor = 1.0 + pp_weight * (pp**0.5) / 10.0

    return base_weight * pp_factor


def get_player_mod_preferences(conn, player_id, top_weight, recent_weight, pp_weight):
    """
    Return the weighted mod preferences from the scores of the player. Each
    score adds its source weight x its pp factor to its mod combination.

    Returns:
        {
            "NM": weighted_score,
            "HD": weighted_score,
            "HDDT": weighted_score,
            ...
        }
    """
    rows = conn.execute(
        """
        SELECT
            mods,
            source,
            pp
        FROM scores
        WHERE player_id = ?
          -- A failed play (rank F) does not show what the player can do.
          AND COALESCE(rank, '') != 'F'
    """,
        (player_id,),
    ).fetchall()

    preferences = defaultdict(float)

    for mods, source, pp in rows:
        try:
            mods = canonicalize_mods(mods)
        except ValueError:
            logger.warning("Ignoring unsupported mod combination %r for player %s", mods, player_id)
            continue

        preferences[mods] += get_score_weight(source, pp, top_weight, recent_weight, pp_weight)

    return dict(preferences)


def normalize_mod_preferences(preferences):
    """Scale the preferences to [0, 1] on a log scale. The top mod combination gets 1.0."""
    if not preferences:
        return {}

    transformed = {mods: math.log1p(preference) for mods, preference in preferences.items()}

    max_preference = max(transformed.values())
    if max_preference <= 0:
        return {mods: 0.0 for mods in transformed}

    return {mods: value / max_preference for mods, value in transformed.items()}


def get_preferred_mods(
    conn,
    player_id,
    top_weight,
    recent_weight,
    pp_weight,
    min_preference=0.0,
):
    """
    Return the preferred mod combinations of the player, from the most
    preferred to the least preferred.

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
        (mods, preference) for mods, preference in normalized_preferences.items() if preference >= min_preference
    ]

    preferred_mods.sort(key=lambda item: item[1], reverse=True)
    return preferred_mods
