"""
The text of /help.

Kept free of discord imports like options.py, so tests can check that every
example parses and that the text fits in a Discord embed.
"""

from bot.options import GOAL_CHOICES, HIDE_CHOICES, INDIVIDUAL_MODS, RANGE_FILTERS, STATUS_CHOICES

# /rec examples as the options someone would type, with what each does.
# Choice options use the names Discord shows.
EXAMPLES = (
    ({}, "Your recommendations with the website's default settings"),
    ({"user": "peppy"}, "Recommendations for another player"),
    ({"stars": "6-6.5", "mods": "HDDT"}, "6 to 6.5 stars, as HD, DT or HDDT"),
    ({"mods": "HR", "exact_mods": True, "bpm": "200+", "length": "<2:00"}, "Exactly HR, 200 BPM or more, 2 minutes or shorter"),
    ({"goal": "PP Potential", "hide": "Already played and recent plays"}, "Maps worth more pp than your usual plays, without any you've played"),
    ({"status": "Loved", "year": "2015-2020"}, "Loved maps from 2015 to 2020"),
    ({"mods": "~FL -DT", "ar": "<9.5"}, "Allow FL, leave out DT, AR 9.5 or lower"),
)


def format_example(options):
    return " ".join(["/rec", *(f"{name}: {value}" for name, value in options.items())])


def help_embed_parts():
    """(title, description, [(field name, field value), ...]) for the /help embed."""
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
            "goal",
            f"**{_name(GOAL_CHOICES, 'balanced')}** (default): maps like the ones you play, at your level.\n"
            f"**{_name(GOAL_CHOICES, 'pp_potential')}**: only maps worth clearly more pp than your usual plays, "
            "but still within reach.",
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
            "Combine them: `~FL -DT`. "
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
            "`/rec` can use them, and the list expires after 30 minutes without use.\n"
            "`/classify index: 12`: what #12 of your last `/rec` mostly tests "
            "(aim, streams, alt, tech, or speed & stamina). Also takes a beatmap link.\n"
            "`/link username: peppy`: use this account for `/rec` by default. "
            "`/unlink` removes it.",
        ),
    ]

    return "How to use /rec", description, fields


def _name(choices, value):
    """The name Discord shows for a choice value."""
    return next(name for name, choice_value in choices.items() if choice_value == value)
