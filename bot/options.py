"""
Change the /rec and /classify input into the format that the backend
expects, and format the rows from the backend as Discord markdown.

This file does not import discord, so the tests can run without discord.py.
"""

import math
import re
from decimal import ROUND_DOWN, Decimal

# These are the same as on the website (frontend/src/components/ModCheckboxes.jsx
# and frontend/src/utils/recommendation.js). Thus /rec with no options gives the
# same results as the site with the default settings. The Docker image of the
# bot has only bot/, so these values are copies. tests/test_shared_constants.py
# makes sure that the copies still match.
INDIVIDUAL_MODS = ("NM", "HD", "HR", "DT", "EZ", "HT", "FL")
DEFAULT_EXCLUDED_MODS = ("EZ", "HT", "FL")

# All the mod combinations in the database, other than NM (MOD_VARIANTS in
# populate.py, MOD_COMBINATIONS in ModCheckboxes.jsx). Exact mode can ask
# only for one of these.
MOD_COMBINATIONS = {
    frozenset(mods)
    for mods in (
        ("HD",), ("HR",), ("DT",), ("EZ",), ("HT",), ("FL",),
        ("HD", "HR"), ("HD", "DT"), ("HD", "HR", "DT"), ("HR", "DT"),
        ("EZ", "DT"), ("EZ", "HD"), ("EZ", "HT"), ("HD", "HT"), ("HR", "HT"),
        ("HD", "HR", "FL"), ("HD", "FL"), ("HR", "FL"), ("DT", "FL"),
    )
}

# Copies of MIN_BEATMAP_YEAR and MAX_BEATMAP_YEAR in beatmap_recommender/api/model.py.
MIN_BEATMAP_YEAR = 2007
MAX_BEATMAP_YEAR = 2026

# The hide option -> (exclude_already_played, exclude_recent_plays). This is
# the two dropdowns of the website as one choice.
HIDE_OPTIONS = {
    "played": (True, False),
    "played_recent": (True, True),
    "recent": (False, True),
    "none": (False, False),
}

# The choice options of /rec: the name that Discord shows -> the value that
# build_settings takes. /help also uses these names.
HIDE_CHOICES = {
    "Already played": "played",
    "Already played and recent plays": "played_recent",
    "Recent plays only": "recent",
    "Nothing": "none",
}
STATUS_CHOICES = {"All": "all", "Ranked": "ranked", "Loved": "loved"}

NM_LABELS = ("NM1", "NM2", "NM3", "NM4", "NM5")

# What each tournament NoMod slot tests, in the mappools that the classifier
# learned from.
NM_SKILLS = {
    "NM1": "Aim",
    "NM2": "Streams",
    "NM3": "Alt",
    "NM4": "Tech",
    "NM5": "Speed",
}

BEATMAP_URL_PATTERNS = (
    re.compile(r"osu\.ppy\.sh/(?:b|beatmaps)/(\d+)"),
    re.compile(r"osu\.ppy\.sh/beatmapsets/\d+/?#\w+/(\d+)"),
    re.compile(r"osu\.ppy\.sh/p/beatmap\?b=(\d+)"),
)

# The characters that discord.utils.escape_markdown escapes: inline markdown
# anywhere, plus quotes, headers and lists at the start of a line. Backslashes
# are escaped too, so that a real backslash in a title does not act as an escape.
MARKDOWN_SPECIAL = re.compile(r"([\\*_~`|])|^(>(?:>>)?\s|#{1,3}|\s*-)", re.MULTILINE)

# An embed title can have 256 characters at most.
EMBED_TITLE_LIMIT = 256


class OptionError(ValueError):
    """Input that the user must fix. The user sees the message as it is."""


# ── /rec ──────────────────────────────────────────────────────────────────────


def parse_mods(text):
    """
    Split mod input such as "HD HR -FL ~EZ", "HDHR" or "=HDDT" into required,
    excluded and allowed mods. Also return True if the combination is exact.

    A plain mod is a mod to recommend (on the website: checked). "-" excludes a
    mod (website: crossed out). "~" allows a mod that is excluded by default
    (website: unchecked). "=" asks for exactly that combination (website: the
    "Exact combination" switch).
    """
    lists = {"": [], "-": [], "~": []}
    exact = False

    for token in re.split(r"[\s,+]+", text.strip().upper()):
        if not token:
            continue

        prefix = token[0] if token[0] in "-~=" else ""
        body = token[len(prefix):]

        if prefix == "=":
            exact = True
            prefix = ""

        if not body or len(body) % 2:
            raise OptionError(f"Can't read the mods {token!r}. Write them like `HD HR` or `HDHR`.")

        for mod in (body[index:index + 2] for index in range(0, len(body), 2)):
            if mod not in INDIVIDUAL_MODS:
                raise OptionError(f"Unknown mod {mod!r}. Use {', '.join(INDIVIDUAL_MODS)}.")

            if mod not in lists[prefix]:
                lists[prefix].append(mod)

    required, excluded, allowed = lists[""], lists["-"], lists["~"]

    for mod in INDIVIDUAL_MODS:
        if sum(mod in mods for mods in (required, excluded, allowed)) > 1:
            raise OptionError(f"{mod} is listed more than once with different prefixes.")

    return required, excluded, allowed, exact


def mod_settings(text, exact=False):
    """
    Return the mods, excluded_mods and exact_mods settings for the mods option.
    `exact` is the exact_mods option. It does the same as an "=" prefix.
    """
    required, excluded, allowed, prefixed_exact = parse_mods(text or "")
    exact = bool(exact) or prefixed_exact

    if exact:
        # In exact mode, the website does not use the default exclusions,
        # because it uses only the checked mods.
        if not required:
            raise OptionError("`exact_mods` needs `mods`, e.g. `mods: HDDT exact_mods: True`.")

        if excluded or allowed:
            raise OptionError("An exact combination can't also use `-` or `~`.")

        if required != ["NM"] and frozenset(required) not in MOD_COMBINATIONS:
            raise OptionError(f"{''.join(required)} isn't a mod combination in the database.")

        return {"mods": required, "excluded_mods": [], "exact_mods": True}

    excluded_mods = [mod for mod in DEFAULT_EXCLUDED_MODS if mod not in required and mod not in allowed]
    excluded_mods += [mod for mod in excluded if mod not in excluded_mods]

    return {"mods": required, "excluded_mods": excluded_mods, "exact_mods": False}


def _number(text):
    """Parse a finite number that is 0 or more. Raise ValueError if the text is not one."""
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise ValueError(text)
    return value


def _integer(text):
    """Parse a whole number that is 0 or more."""
    value = _number(text)
    if not value.is_integer():
        raise ValueError(text)
    return int(value)


def _year(text):
    """Parse a year in the range of the database."""
    value = _integer(text)
    if not MIN_BEATMAP_YEAR <= value <= MAX_BEATMAP_YEAR:
        raise OptionError(f"Years go from {MIN_BEATMAP_YEAR} to {MAX_BEATMAP_YEAR}.")
    return value


def _length(text):
    """Parse a length in seconds, or in minutes:seconds."""
    if ":" not in text:
        return _number(text)

    minutes, seconds = text.split(":", 1)
    seconds = _number(seconds)
    if seconds >= 60:
        raise ValueError(text)
    return _integer(minutes) * 60 + seconds


# Range option -> (the parser of one bound, True if one value means "exactly
# this"). One exact star rating almost never matches, so only the year takes
# one value. The min_/max_ names are the same as in RecommendationSettings.
RANGE_FILTERS = {
    "year": (_year, True),
    "stars": (_number, False),
    "bpm": (_number, False),
    "pp": (_number, False),
    "cs": (_number, False),
    "ar": (_number, False),
    "od": (_number, False),
    "length": (_length, False),
    "combo": (_integer, False),
}


def parse_range(name, text):
    """
    Return (low, high) from range input such as "5.5-6.5", "5.5+", ">5.5",
    "<6.5" or "-6.5". A missing side is None. The bounds are always included.
    """
    parse, allow_single = RANGE_FILTERS[name]
    compact = re.sub(r"\s+", "", text)

    if compact.startswith((">=", "<=")):
        operator, rest = compact[:2], compact[2:]
    elif compact.startswith((">", "<")):
        operator, rest = compact[:1], compact[1:]
    elif compact.endswith("+"):
        operator, rest = ">", compact[:-1]
    else:
        operator, rest = "", compact

    try:
        if operator:
            value = parse(rest)
            low, high = (value, None) if operator[0] == ">" else (None, value)
        elif "-" in rest:
            low_text, high_text = rest.split("-", 1)
            if not low_text and not high_text:
                raise ValueError(text)
            low = parse(low_text) if low_text else None
            high = parse(high_text) if high_text else None
        elif allow_single:
            low = high = parse(rest)
        else:
            raise ValueError(text)
    except OptionError:
        raise
    except ValueError:
        raise OptionError(
            f"Can't read `{name}: {text}`. Give a range like `5-6`, `5+` or `<6`."
        ) from None

    if low is not None and high is not None and low > high:
        raise OptionError(f"`{name}: {text}` goes from high to low.")

    return low, high


def build_settings(
    player_id,
    mods=None,
    exact_mods=None,
    hide=None,
    status=None,
    **ranges,
):
    """
    Return the body of POST /bot/recommend. An option that the user did not
    give is also not in the body. Thus the defaults of the backend apply (the
    same defaults as on the website).

    `ranges` holds the range options as the user typed them, for example
    stars="5.5-6.5".
    """
    settings = {"player_id": player_id, **mod_settings(mods, exact_mods)}

    if hide is not None:
        settings["exclude_already_played"], settings["exclude_recent_plays"] = HIDE_OPTIONS[hide]

    if status is not None:
        settings["beatmap_status"] = status

    for name, text in ranges.items():
        if text is None:
            continue

        low, high = parse_range(name, text)

        if low is not None:
            settings[f"min_{name}"] = low
        if high is not None:
            settings[f"max_{name}"] = high

    return settings


# ── /classify ─────────────────────────────────────────────────────────────────


def parse_beatmap_id(text):
    """Return the beatmap ID from a plain ID or from an osu! beatmap link."""
    text = text.strip()

    if text.isdigit():
        return text

    for pattern in BEATMAP_URL_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)

    if "osu.ppy.sh/beatmapsets/" in text or "osu.ppy.sh/s/" in text:
        raise OptionError(
            "That's a beatmapset link. Open the difficulty you want and copy "
            "that link instead (it ends in `#osu/<id>`)."
        )

    raise OptionError("Give a beatmap ID or an osu.ppy.sh beatmap link.")


# ── Formatting ────────────────────────────────────────────────────────────────


def escape_markdown(text):
    """Put a backslash before each Discord markdown character in text."""
    return MARKDOWN_SPECIAL.sub(lambda match: f"\\{match.group(0)}", text)


def beatmap_url(beatmap_id):
    """Return the osu! page of a beatmap, or None for a map that has only an MD5 identifier."""
    return f"https://osu.ppy.sh/b/{beatmap_id}" if str(beatmap_id).isdigit() else None


def format_length(seconds):
    """Change seconds into "m:ss"."""
    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes}:{seconds:02d}"


def truncate_decimals(value, places=2):
    """
    Return `value` cut (not rounded) to `places` decimals, without trailing
    zeros: 10.3333 -> "10.33", 9.75 -> "9.75", 4.0 -> "4".
    """
    # First, round off the float noise. Thus 9.799999999999999 (7 * 1.4)
    # becomes 9.8, not 9.79.
    exact = Decimal(repr(round(value, 9)))
    cut = exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)
    return f"{cut.normalize():f}"


def format_beatmap_title(row):
    """Return "Artist - Title [Version]" for the embed title of /classify. The title links to the map."""
    return link_text(f"{row['artist']} - {row['title']} [{row['version']}]"[:EMBED_TITLE_LIMIT])


# Markdown characters that format text in pairs, and lookalikes that do not.
MARKDOWN_LOOKALIKES = {"*": "∗", "_": "＿", "~": "∼", "|": "ǀ", "`": "ˋ"}


def link_text(text):
    """
    Return `text` made safe for the [text](url) part of a markdown link, or
    for an embed title (which is also a link).

    Discord shows backslash escapes there as they are ("Ryu\\*"), so this
    function escapes nothing. A single *, _, ~, | or ` cannot format text, so
    it stays. Only if a character occurs two or more times does it change to
    a lookalike. Brackets stay if they make pairs, for example "Song [TV Size]".
    A bracket without a pair ends the link too early, so then all brackets
    change to fullwidth lookalikes.
    """
    for character, lookalike in MARKDOWN_LOOKALIKES.items():
        if text.count(character) >= 2:
            text = text.replace(character, lookalike)

    depth = 0
    for character in text:
        depth += {"[": 1, "]": -1}.get(character, 0)
        if not 0 <= depth <= 1:
            break

    if depth != 0:
        text = text.replace("[", "［").replace("]", "］")

    return text


def format_recommendation(rank, row):
    """Return two lines for one recommendation: the map, then its stats."""
    mods = "NM" if row["mods"] == "NM" else f"+{row['mods']}"
    name = f"{row['artist']} - {row['title']}"
    url = beatmap_url(row["beatmap_id"])
    name = f"[{link_text(name)}]({url})" if url else escape_markdown(name)

    stats = [f"★{row['star_rating']:.2f}"]
    if row.get("pp") is not None:
        stats.append(f"{row['pp']:.0f}pp")
    if row.get("bpm") is not None:
        stats.append(f"{row['bpm']:.0f} BPM")
    stats += [
        format_length(row["length_seconds"]),
        " ".join(
            f"{label}{truncate_decimals(row[key])}"
            for label, key in (("AR", "ar"), ("OD", "od"), ("CS", "circle_size"))
        ),
        f"by {escape_markdown(row['creator'])}",
    ]

    return (
        f"**{rank}.** {name} [{escape_markdown(row['version'])}] **{mods}**\n"
        f"{' · '.join(stats)}"
    )


def probability_bar(probability, width=10):
    """Return a text bar of `width` blocks, with the filled part for probability."""
    filled = round(probability * width)
    return "█" * filled + "░" * (width - filled)


def format_predictions(predictions):
    """
    Return (the most likely skill, one line for each NM category). The line
    of the most likely category is bold. The lines show the skill, not the
    slot, because few players know the slots.
    """
    best = max(NM_LABELS, key=lambda label: predictions[label])
    width = max(len(skill) for skill in NM_SKILLS.values())
    lines = []

    for label in NM_LABELS:
        probability = predictions[label]
        # Pad the skill inside a code span, so that the bars line up.
        line = f"`{NM_SKILLS[label]:<{width}}` {probability_bar(probability)} {probability:6.1%}"
        lines.append(f"**{line}**" if label == best else line)

    return NM_SKILLS[best], "\n".join(lines)
