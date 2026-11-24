"""
The text of /help.

As in options.py, this file does not import discord. Thus the tests can make
sure that each example parses and that the text fits in a Discord embed.
"""

from bot.options import HIDE_CHOICES, INDIVIDUAL_MODS, RANGE_FILTERS, STATUS_CHOICES

# /rec examples, as the options that a user types, with what each example does.
# The choice options use the names that Discord shows.
EXAMPLES = (
    ({}, "Your recommendations with the website's default settings"),
    ({"user": "peppy"}, "Recommendations for another player"),
    ({"stars": "6-6.5", "mods": "HDDT"}, "6 to 6.5 stars, as HD, DT or HDDT"),
    ({"mods": "HR", "exact_mods": True, "bpm": "200+", "length": "<2:00"}, "Exactly HR, 200 BPM or more, 2 minutes or shorter"),
    ({"pp": "400+", "hide": "Already played and recent plays"}, "Maps worth 400 pp or more, without any you've played"),
    ({"status": "Loved", "year": "2015-2020"}, "Loved maps from 2015 to 2020"),
    ({"mods": "~FL -DT", "ar": "<9.5"}, "Allow FL, leave out DT, AR 9.5 or lower"),
)


def format_example(options):
    """Return the /rec command line for the options of an example."""
    return " ".join(["/rec", *(f"{name}: {value}" for name, value in options.items())])


def help_embed_parts():
    """Return (title, description, [(field name, field value), ...]) for the /help embed."""
    description = (
        "`/rec` recommends maps similar to your top and recent plays, at your skill level. "
        "Every option is optional: with none, you get the same results as recommendosu.com "
        "with its default settings.\n\n"
        "Run `/link` with your osu! username once, and `/rec` uses your account "
        "without you typing `user` each time."
    )

    fields = [
        (
            "user",
            "The osu! username to recommend for. Defaults to the account you linked with `/link`.\n"
            "`user: peppy`",
        ),
        (
            "mods",
            "By default, maps come as NM, HD, HR, DT or any mix of those. EZ, HT and FL are left out.\n"
            "`HD DT` or `HDDT`: only versions made from these mods (HD, DT, HDDT)\n"
            "`exact_mods: True`: exactly the combination in `mods`, e.g. `mods: HDDT exact_mods: True` "
            "gives only HDDT (`=HDDT` is a shortcut for the same)\n"
            "Without plain mods, adjust the default instead:\n"
            "`-DT`: leave out anything with DT\n"
            "`~FL`: allow FL (also works for EZ and HT)\n"
            "Combine them: `~FL -DT`. \n"
            f"Mods: {' '.join(INDIVIDUAL_MODS)}.",
        ),
        (
            "hide",
            f"Which maps to leave out. Default: **{_name(HIDE_CHOICES, 'played')}**.\n"
            + " · ".join(HIDE_CHOICES),
        ),
        (
            "status",
            f"**{_name(STATUS_CHOICES, 'all')}** (default), "
            f"**{_name(STATUS_CHOICES, 'ranked')}** or **{_name(STATUS_CHOICES, 'loved')}**.",
        ),
        (
            " · ".join(RANGE_FILTERS),
            "Ranges, and every end is included:\n"
            "`6-6.5`: between 6 and 6.5\n"
            "`6+` or `>6`: 6 or more\n"
            "`<7` or `-7`: 7 or less\n"
            "`year: 2015`: one year only (a single number only works for `year`)\n"
            "`length` takes seconds or minutes:seconds, e.g. `1:30-3:00`\n"
            "`pp` is the pp for an SS, and `combo` the map's max combo.",
        ),
        (
            "Examples",
            "\n".join(f"`{format_example(options)}`\n{note}" for options, note in EXAMPLES),
        ),
        (
            "Browsing and other commands",
            "**« 10 / Previous / Next / 10 »** move through the list. Only the person who ran "
            "`/rec` can use them, and they stop working after 10 minutes without a click.\n"
            "`/classify index: 12`: what #12 of your last `/rec` mostly tests "
            "(aim, streams, alt, tech, or speed & stamina). Also takes a beatmap link.\n"
            "`/link username: peppy`: use this account for `/rec` by default. "
            "`/unlink` removes it.\n"
            "`/changelog`: what's new on the website and in the bot.",
        ),
    ]

    return "How to use /rec", description, fields


def _name(choices, value):
    """Return the name that Discord shows for a choice value."""
    return next(name for name, choice_value in choices.items() if choice_value == value)
