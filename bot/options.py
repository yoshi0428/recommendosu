"""
Turns /rec and /classify input into what the backend expects, and formats
the backend's rows as Discord markdown.

Nothing here imports discord, so the tests can run without discord.py.
"""

import math
import re
from decimal import ROUND_DOWN, Decimal

# Same as the website (frontend/src/components/ModOptions.jsx and
# frontend/src/utils/recommendation.js), so /rec with no options gives the
# same results as the site with default settings.
INDIVIDUAL_MODS = ("NM", "HD", "HR", "DT", "EZ", "HT", "FL")
DEFAULT_EXCLUDED_MODS = ("EZ", "HT", "FL")

# Every mod combination stored in the database besides NM (MOD_VARIANTS in
# ModOptions.jsx). Exact mode can only ask for one of these.
MOD_COMBINATIONS = {
    frozenset(mods)
    for mods in (
        ("HD",), ("HR",), ("DT",), ("EZ",), ("HT",), ("FL",),
        ("HD", "HR"), ("HD", "DT"), ("HD", "HR", "DT"), ("HR", "DT"),
        ("EZ", "DT"), ("EZ", "HD"), ("EZ", "HT"), ("HD", "HT"), ("HR", "HT"),
        ("HD", "HR", "FL"), ("HD", "FL"), ("HR", "FL"), ("DT", "FL"),
    )
}

# MIN_BEATMAP_YEAR / MAX_BEATMAP_YEAR in beatmap_recommender/api/model.py.
MIN_BEATMAP_YEAR = 2007
MAX_BEATMAP_YEAR = 2026

# The hide option -> (exclude_already_played, exclude_recent_plays). The
# website's two dropdowns, as one choice.
HIDE_OPTIONS = {
    "played": (True, False),
    "played_recent": (True, True),
    "recent": (False, True),
    "none": (False, False),
}

# /rec's choice options: the name Discord shows -> the value build_settings
# takes. /help describes them by these names too.
GOAL_CHOICES = {"Balanced": "balanced", "PP Potential": "pp_potential"}
HIDE_CHOICES = {
    "Already played": "played",
    "Already played and recent plays": "played_recent",
    "Recent plays only": "recent",
    "Nothing": "none",
}
STATUS_CHOICES = {"All": "all", "Ranked": "ranked", "Loved": "loved"}

NM_LABELS = ("NM1", "NM2", "NM3", "NM4", "NM5")

# What each tournament NoMod slot tests, in the mappools the classifier was
# trained on.
NM_SKILLS = {
    "NM1": "Aim",
    "NM2": "Streams",
    "NM3": "Alt",
    "NM4": "Tech",
    "NM5": "Speed & Stamina",
}

BEATMAP_URL_PATTERNS = (
    re.compile(r"osu\.ppy\.sh/(?:b|beatmaps)/(\d+)"),
    re.compile(r"osu\.ppy\.sh/beatmapsets/\d+/?#\w+/(\d+)"),
    re.compile(r"osu\.ppy\.sh/p/beatmap\?b=(\d+)"),
)

# The characters discord.utils.escape_markdown escapes: inline markdown
# anywhere, plus quotes, headers and lists at the start of a line. Backslashes
# are escaped too, so a real one in a title isn't read as an escape.
MARKDOWN_SPECIAL = re.compile(r"([\\*_~`|])|^(>(?:>>)?\s|#{1,3}|\s*-)", re.MULTILINE)

# Embed titles are capped at 256 characters.
EMBED_TITLE_LIMIT = 256


class OptionError(ValueError):
    """Input the user has to fix. The message is shown to them as-is."""


# ── /rec ──────────────────────────────────────────────────────────────────────


def parse_mods(text):
    """
    Split mod input like "HD HR -FL ~EZ", "HDHR" or "=HDDT" into required,
    excluded and allowed mods, and whether the combination is exact.

    Plain mods are the ones to recommend (website: checked), "-" excludes a
    mod (website: crossed out), "~" allows one of the mods excluded by
    default (website: unchecked), and "=" asks for exactly that combination
    (website: the "Exact combination" switch).
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
    The mods, excluded_mods and exact_mods settings for the mods option.
    `exact` is the exact_mods option, which does the same as an "=" prefix.
    """
    required, excluded, allowed, prefixed_exact = parse_mods(text or "")
    exact = bool(exact) or prefixed_exact

    if exact:
        # The website drops the default exclusions in exact mode, since only
        # the checked mods are used.
        if not required:
            raise OptionError("`exact_mods` needs `mods`, e.g. `mods: HDDT exact_mods: True`.")

        if excluded or allowed:
            raise OptionError("An exact combination can't also use `-` or `~`.")

        if required != ["NM"] and frozenset(required) not in MOD_COMBINATIONS:
            raise OptionError(f"{''.join(required)} isn't a mod combination in the database.")

        return {"mods": required, "excluded_mods": [], "exact_mods": True}

    excluded_mods = [
        mod for mod in DEFAULT_EXCLUDED_MODS if mod not in required and mod not in allowed
    ]
    excluded_mods += [mod for mod in excluded if mod not in excluded_mods]

    return {"mods": required, "excluded_mods": excluded_mods, "exact_mods": False}


def _number(text):
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise ValueError(text)
    return value


def _integer(text):
    value = _number(text)
    if not value.is_integer():
        raise ValueError(text)
    return int(value)


def _year(text):
    value = _integer(text)
    if not MIN_BEATMAP_YEAR <= value <= MAX_BEATMAP_YEAR:
        raise OptionError(f"Years go from {MIN_BEATMAP_YEAR} to {MAX_BEATMAP_YEAR}.")
    return value


def _length(text):
    """Seconds, or minutes:seconds."""
    if ":" not in text:
        return _number(text)

    minutes, seconds = text.split(":", 1)
    seconds = _number(seconds)
    if seconds >= 60:
        raise ValueError(text)
    return _integer(minutes) * 60 + seconds


# Range option -> (parse one bound, whether a single value means "exactly
# this"). A single star rating would almost never match, so only years take
# one value. The min_/max_ names are as in RecommendationSettings.
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
    (low, high) from range input like "5.5-6.5", "5.5+", ">5.5", "<6.5" or
    "-6.5". A missing side is None. Bounds are inclusive either way.
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
    goal=None,
    mods=None,
    exact_mods=None,
    hide=None,
    status=None,
    **ranges,
):
    """
    The POST /bot/recommend body. Options left out are left out of the body
    too, so the backend's defaults apply (the same defaults as the website).

    `ranges` holds the range options as typed, e.g. stars="5.5-6.5".
    """
    settings = {"player_id": player_id, **mod_settings(mods, exact_mods)}

    if goal is not None:
        settings["goal"] = goal

    if hide is not None:
        settings["exclude_already_played"], settings["exclude_recent_plays"] = HIDE_OPTIONS[hide]

    if status is not None:
        settings["beatmap_status"] = status

    unknown = set(ranges) - set(RANGE_FILTERS)
    if unknown:
        raise TypeError(f"Unknown range options: {', '.join(sorted(unknown))}")

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
    """A beatmap ID from a plain ID or an osu! beatmap link."""
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
    return MARKDOWN_SPECIAL.sub(lambda match: f"\\{match.group(0)}", text)


def beatmap_url(beatmap_id):
    """The osu! page for a beatmap, or None for maps only known by MD5."""
    return f"https://osu.ppy.sh/b/{beatmap_id}" if str(beatmap_id).isdigit() else None


def format_length(seconds):
    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes}:{seconds:02d}"


def truncate_decimals(value, places=2):
    """
    `value` cut (not rounded) to `places` decimals, without trailing zeros:
    10.3333 -> "10.33", 9.75 -> "9.75", 4.0 -> "4".
    """
    # Round away float noise first, so 9.799999999999999 (7 * 1.4) is cut to
    # 9.8 rather than 9.79.
    exact = Decimal(repr(round(value, 9)))
    cut = exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)
    return f"{cut.normalize():f}"


def format_beatmap_title(row):
    """"Artist - Title [Version]" for /classify's embed title, which links to the map."""
    return link_text(f"{row['artist']} - {row['title']} [{row['version']}]"[:EMBED_TITLE_LIMIT])


# Markdown characters that format text in pairs, and lookalikes that don't.
MARKDOWN_LOOKALIKES = {"*": "∗", "_": "＿", "~": "∼", "|": "ǀ", "`": "ˋ"}


def link_text(text):
    """
    `text` made safe for the [text](url) part of a markdown link, or an
    embed title (which is a link too).

    Discord shows backslash escapes there literally ("Ryu\\*"), so nothing
    is escaped. A single *, _, ~, | or ` can't format anything, so those are
    left as they are; only when one appears often enough to form a pair is
    it swapped for a lookalike. Brackets are left alone when they pair up,
    e.g. "Song [TV Size]"; a stray one would end the link early, so then
    they're swapped for fullwidth lookalikes too.
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
    """Two lines for one recommendation: the map, then its stats."""
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
    filled = round(probability * width)
    return "█" * filled + "░" * (width - filled)


def format_predictions(predictions):
    """
    (most likely skill, one line per NM category with the most likely one
    in bold). Lines show the skill rather than the slot, since few players
    know the slots.
    """
    best = max(NM_LABELS, key=lambda label: predictions[label])
    width = max(len(skill) for skill in NM_SKILLS.values())
    lines = []

    for label in NM_LABELS:
        probability = predictions[label]
        # Padded inside a code span, so the bars line up.
        line = f"`{NM_SKILLS[label]:<{width}}` {probability_bar(probability)} {probability:6.1%}"
        lines.append(f"**{line}**" if label == best else line)

    return NM_SKILLS[best], "\n".join(lines)
