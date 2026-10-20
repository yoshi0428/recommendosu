"""
Tests for the Discord bot's logic (bot/), without Discord or discord.py.

The commands themselves are thin: they turn options into a settings dict
with bot/options.py, call the backend with bot/api.py, and remember /link
with bot/links.py. Those three modules are what's tested here.
"""

import asyncio
import json

import httpx
import pytest

from bot.api import BackendClient, BackendError
from bot.help import EXAMPLES, help_embed_parts
from bot.links import LinkStore
from bot.options import (
    GOAL_CHOICES,
    HIDE_CHOICES,
    HIDE_OPTIONS,
    RANGE_FILTERS,
    STATUS_CHOICES,
    OptionError,
    build_settings,
    escape_markdown,
    format_beatmap_title,
    format_predictions,
    format_recommendation,
    link_text,
    mod_settings,
    parse_beatmap_id,
    parse_mods,
    parse_range,
    truncate_decimals,
)


# ---------------------------------------------------------------------------
# Mods
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("HD HR", (["HD", "HR"], [], [], False)),
        ("hdhr", (["HD", "HR"], [], [], False)),
        ("+HDDT, -FL ~EZ", (["HD", "DT"], ["FL"], ["EZ"], False)),
        ("-EZHT", ([], ["EZ", "HT"], [], False)),
        ("=HDDT", (["HD", "DT"], [], [], True)),
        ("", ([], [], [], False)),
    ],
)
def test_parse_mods(text, expected):
    assert parse_mods(text) == expected


@pytest.mark.parametrize("text", ["HDX", "NC", "HD -HD", "-", "="])
def test_parse_mods_rejects_bad_input(text):
    with pytest.raises(OptionError):
        parse_mods(text)


def test_no_mods_matches_the_website_defaults():
    # frontend/src/utils/recommendation.js: mods [], excluded EZ/HT/FL.
    assert mod_settings(None) == {"mods": [], "excluded_mods": ["EZ", "HT", "FL"], "exact_mods": False}


def test_asking_for_a_default_excluded_mod_lifts_its_exclusion():
    # Otherwise the backend's LIKE '%FL%' exclusion would drop every FL variant.
    assert mod_settings("HD FL")["excluded_mods"] == ["EZ", "HT"]
    assert mod_settings("~EZ -DT")["excluded_mods"] == ["HT", "FL", "DT"]


def test_exact_mods():
    assert mod_settings("=HDDT") == {"mods": ["HD", "DT"], "excluded_mods": [], "exact_mods": True}
    assert mod_settings("=HD DT")["exact_mods"] is True
    assert mod_settings("=NM")["mods"] == ["NM"]


def test_exact_mods_option_matches_the_prefix():
    assert mod_settings("HDDT", exact=True) == mod_settings("=HDDT")
    assert mod_settings("HD DT", exact=True)["exact_mods"] is True
    assert mod_settings("HDDT", exact=False)["exact_mods"] is False
    # Both at once is fine.
    assert mod_settings("=HDDT", exact=True) == mod_settings("=HDDT")


@pytest.mark.parametrize(("text", "message"), [(None, "needs `mods`"), ("HD -FL", "can't also use"), ("EZHR", "isn't a mod combination")])
def test_exact_mods_option_rejects_what_exact_mode_cannot_select(text, message):
    with pytest.raises(OptionError, match=message):
        mod_settings(text, exact=True)


@pytest.mark.parametrize("text", ["=HD -FL", "=EZHR", "=NM HD"])
def test_exact_mods_rejects_what_the_website_cannot_select(text):
    with pytest.raises(OptionError):
        mod_settings(text)


# ---------------------------------------------------------------------------
# Ranges
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        ("stars", "5.5-6.5", (5.5, 6.5)),
        ("stars", " 5.5 - 6.5 ", (5.5, 6.5)),
        ("stars", "5.5+", (5.5, None)),
        ("stars", "5.5-", (5.5, None)),
        ("stars", ">5.5", (5.5, None)),
        ("stars", ">=5.5", (5.5, None)),
        ("stars", "<6.5", (None, 6.5)),
        ("stars", "<=6.5", (None, 6.5)),
        ("stars", "-6.5", (None, 6.5)),
        ("stars", "0-0", (0.0, 0.0)),
        ("year", "2015", (2015, 2015)),
        ("year", "2015-2020", (2015, 2020)),
        ("length", "1:30-3:00", (90.0, 180.0)),
        ("length", "<120", (None, 120.0)),
        ("combo", "500-1500", (500, 1500)),
    ],
)
def test_parse_range(name, text, expected):
    assert parse_range(name, text) == expected


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        ("stars", "6", "Give a range"),  # One star rating would almost never match.
        ("stars", "-", "Give a range"),
        ("stars", "abc", "Give a range"),
        ("stars", "nan+", "Give a range"),
        ("stars", "7-6", "high to low"),
        ("combo", "1.5+", "Give a range"),
        ("length", "1:75", "Give a range"),
        ("year", "1999", "2007 to 2026"),
    ],
)
def test_parse_range_rejects_bad_input(name, text, message):
    with pytest.raises(OptionError, match=message):
        parse_range(name, text)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def test_no_options_only_sends_the_player_and_default_mods():
    # Everything else is left to the backend's defaults.
    assert build_settings(player_id=7) == {
        "player_id": 7,
        "mods": [],
        "excluded_mods": ["EZ", "HT", "FL"],
        "exact_mods": False,
    }


def test_options_map_to_recommendation_settings():
    settings = build_settings(
        player_id=7,
        goal="pp_potential",
        hide="recent",
        status="loved",
        stars="5.5-6.5",
        year="2015+",
        combo="<1500",
        length="0-",
        bpm=None,
    )

    assert settings["goal"] == "pp_potential"
    assert settings["exclude_already_played"] is False
    assert settings["exclude_recent_plays"] is True
    assert settings["beatmap_status"] == "loved"
    assert settings["min_stars"] == 5.5 and settings["max_stars"] == 6.5
    assert settings["min_year"] == 2015 and "max_year" not in settings
    assert settings["max_combo"] == 1500 and "min_combo" not in settings
    # 0 is a real filter value, not "unset".
    assert settings["min_length"] == 0.0
    assert "min_bpm" not in settings


@pytest.mark.parametrize("hide", ["played", "played_recent", "recent", "none"])
def test_hide_covers_both_website_dropdowns(hide):
    settings = build_settings(player_id=7, hide=hide)
    assert (settings["exclude_already_played"], settings["exclude_recent_plays"]) == HIDE_OPTIONS[hide]

    assert len(set(HIDE_OPTIONS.values())) == 4


def test_settings_keys_exist_in_recommendation_settings():
    from beatmap_recommender.api.model import RecommendationSettings

    every_range = {name: "1-2" for name in RANGE_FILTERS}
    every_range["year"] = "2015-2020"

    settings = build_settings(
        player_id=7, goal="balanced", mods="HD", hide="played_recent", status="all", **every_range,
    )

    assert set(settings) <= set(RecommendationSettings.model_fields)
    RecommendationSettings(**settings)


# ---------------------------------------------------------------------------
# Beatmap links
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "129891",
        "https://osu.ppy.sh/b/129891",
        "https://osu.ppy.sh/beatmaps/129891?mode=osu",
        "https://osu.ppy.sh/beatmapsets/39804#osu/129891",
        "osu.ppy.sh/beatmapsets/39804/#osu/129891",
        "https://osu.ppy.sh/p/beatmap?b=129891",
        "  <https://osu.ppy.sh/b/129891>  ",
    ],
)
def test_parse_beatmap_id(text):
    assert parse_beatmap_id(text) == "129891"


def test_beatmapset_link_asks_for_the_difficulty():
    with pytest.raises(OptionError, match="beatmapset"):
        parse_beatmap_id("https://osu.ppy.sh/beatmapsets/39804")


def test_garbage_is_rejected():
    with pytest.raises(OptionError):
        parse_beatmap_id("free pp please")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def make_row(**overrides):
    row = {
        "beatmap_id": "129891", "mods": "HDDT", "artist": "xi", "title": "FREEDOM DiVE",
        "version": "FOUR DIMENSIONS", "creator": "Nakagawa-Kanon", "star_rating": 7.123,
        "pp": 812.4, "bpm": 333.0, "length_seconds": 172.6, "ar": 10.33, "od": 9.5, "circle_size": 4.0,
    }
    return {**row, **overrides}


def test_format_recommendation():
    text = format_recommendation(1, make_row())

    assert text == (
        "**1.** [xi - FREEDOM DiVE](https://osu.ppy.sh/b/129891) [FOUR DIMENSIONS] **+HDDT**\n"
        "★7.12 · 812pp · 333 BPM · 2:53 · AR10.33 OD9.5 CS4 · by Nakagawa-Kanon"
    )


def test_format_recommendation_without_numeric_id_pp_or_bpm():
    text = format_recommendation(2, make_row(beatmap_id="d41d8cd98f00b204e9800998ecf8427e", pp=None, bpm=None, mods="NM"))

    assert text.startswith("**2.** xi - FREEDOM DiVE [FOUR DIMENSIONS] **NM**\n★7.12 · 2:53 ·")
    assert "https://" not in text and "BPM" not in text


def test_link_text_leaves_plain_punctuation_alone():
    # Escapes inside link text show up as literal backslashes in Discord.
    assert link_text("ke-ji feat. Nanahira - RE:UNION -Duo Blade Against- (Extended)") == (
        "ke-ji feat. Nanahira - RE:UNION -Duo Blade Against- (Extended)"
    )


@pytest.mark.parametrize(
    "text",
    ["Ryu* - Sakura Mirage (STARLiGHT Mix)", "Demetori - Natsukashiki Touhou no Chi ~ Sic World", "a_b", "x|y", r"a\b"],
)
def test_link_text_leaves_markdown_characters_that_cannot_pair(text):
    assert link_text(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("*Luna*", "∗Luna∗"),
        ("__init__", "＿＿init＿＿"),
        ("~~x~~", "∼∼x∼∼"),
        ("||spoiler||", "ǀǀspoilerǀǀ"),
        ("`code`", "ˋcodeˋ"),
        # Only the character that pairs is swapped.
        ("Ryu* ~ *x", "Ryu∗ ~ ∗x"),
    ],
)
def test_link_text_swaps_characters_that_could_pair(text, expected):
    assert link_text(text) == expected


def test_link_text_keeps_paired_brackets():
    assert link_text("Song [TV Size]") == "Song [TV Size]"


@pytest.mark.parametrize("text", ["a]b", "a[b", "a[[b]]", "a]b["])
def test_link_text_replaces_brackets_that_would_break_the_link(text):
    result = link_text(text)
    assert "[" not in result and "]" not in result


def test_beatmap_title_has_no_escapes():
    title = format_beatmap_title(make_row(artist="Ryu*", title=r"a\b - c (d)", version="x|y"))
    assert title == r"Ryu* - a\b - c (d) [x|y]"


def test_escape_markdown_at_line_start():
    assert escape_markdown("# hi") == r"\# hi"
    assert escape_markdown("- hi") == r"\- hi"
    assert escape_markdown("> hi") == r"\> hi"
    assert escape_markdown("a - b # c > d") == "a - b # c > d"


def test_long_titles_fit_in_an_embed_title():
    assert len(format_beatmap_title(make_row(title="x" * 500))) == 256


def test_format_predictions_bolds_the_best_category():
    best, lines = format_predictions({"NM1": 0.05, "NM2": 0.8, "NM3": 0.1, "NM4": 0.03, "NM5": 0.02})

    assert best == "Streams"
    assert lines.splitlines() == [
        "`Aim            ` ░░░░░░░░░░   5.0%",
        "**`Streams        ` ████████░░  80.0%**",
        "`Alt            ` █░░░░░░░░░  10.0%",
        "`Tech           ` ░░░░░░░░░░   3.0%",
        "`Speed & Stamina` ░░░░░░░░░░   2.0%",
    ]


# ---------------------------------------------------------------------------
# Backend client
# ---------------------------------------------------------------------------
def run(coroutine):
    return asyncio.run(coroutine)


def make_backend(handler):
    return BackendClient("http://backend:8000/", "secret", transport=httpx.MockTransport(handler))


def test_backend_client_sends_the_key_and_settings():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"recommendations": []})

    async def go():
        backend = make_backend(handler)
        await backend.recommend({"player_id": 7}, discord_user_id=123)
        await backend.get_player("Some One/x")
        await backend.recommendation_page("abc", 123, offset=50, limit=50)
        await backend.aclose()

    run(go())

    assert seen[0].url == "http://backend:8000/api/v1/bot/recommend"
    assert seen[0].headers["X-Bot-Key"] == "secret"
    assert seen[0].headers["X-Discord-User-Id"] == "123"
    assert json.loads(seen[0].content) == {"player_id": 7}
    # Spaces and slashes in usernames stay inside one path segment.
    assert seen[1].url.raw_path == b"/api/v1/bot/players/Some%20One%2Fx"
    assert seen[2].url == "http://backend:8000/api/v1/bot/recommend/abc/page?offset=50&limit=50"
    assert seen[2].headers["X-Discord-User-Id"] == "123"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(404, json={"detail": "osu! player 'x' was not found."}), "osu! player 'x' was not found."),
        (httpx.Response(400, json={"detail": [{"msg": "bad min_year"}]}), "bad min_year"),
        (httpx.Response(500, text="boom"), "Something went wrong on the server"),
        (httpx.Response(401, json={"detail": "Invalid bot API key."}), "Something went wrong on the server"),
    ],
)
def test_backend_errors_become_user_messages(response, message):
    async def go():
        backend = make_backend(lambda request: response)
        try:
            await backend.classify("1")
        finally:
            await backend.aclose()

    with pytest.raises(BackendError, match=message.split("'")[0]):
        run(go())


def test_unreachable_backend():
    def handler(request):
        raise httpx.ConnectError("refused")

    async def go():
        backend = make_backend(handler)
        try:
            await backend.classify("1")
        finally:
            await backend.aclose()

    with pytest.raises(BackendError, match="unreachable"):
        run(go())


# ---------------------------------------------------------------------------
# /rec pages (needs discord.py, which only the bot's image installs)
# ---------------------------------------------------------------------------
class FakePagingBackend:
    """Serves a result of `total` rows, recording which chunks are fetched."""

    def __init__(self, total):
        self.rows = [make_row(beatmap_id=str(i), title=f"Song {i}") for i in range(total)]
        self.fetches = []

    def first_response(self, size=50):
        return {
            "recommendation_id": "rec", "recommendation_goal": "balanced",
            "total_count": len(self.rows), "recommendations": self.rows[:size],
        }

    async def recommendation_page(self, recommendation_id, discord_user_id, offset, limit):
        self.fetches.append((offset, limit))
        return {"total_count": len(self.rows), "recommendations": self.rows[offset:offset + limit]}


def test_view_fetches_chunks_and_clamps_jumps():
    pytest.importorskip("discord")
    from bot.main import RecommendationView

    async def go():
        backend = FakePagingBackend(total=1234)
        view = RecommendationView(backend, owner_id=1, player_id=2, username="u", result=backend.first_response())

        assert view.page_count == 247
        assert "Page 1/247" in (await view.first_embed()).footer.text
        assert view.previous_page.disabled and view.back_10.disabled
        assert not view.forward_10.disabled
        assert [item.label for item in view.children] == ["« 10", "Previous", "Next", "10 »"]

        # Pages 1-10 come from the first response, without another request.
        rows = await view.page_rows(9)
        assert [row["beatmap_id"] for row in rows] == ["45", "46", "47", "48", "49"]
        assert backend.fetches == []

        # Page 101 needs the chunk holding rows 500-549.
        rows = await view.page_rows(100)
        assert rows[0]["beatmap_id"] == "500"
        assert backend.fetches == [(500, 50)]

        # The last page holds the 4 remaining rows.
        rows = await view.page_rows(246)
        assert [row["beatmap_id"] for row in rows] == ["1230", "1231", "1232", "1233"]

    run(go())


# ---------------------------------------------------------------------------
# /link storage
# ---------------------------------------------------------------------------
def test_link_store(tmp_path):
    store = LinkStore(tmp_path / "nested" / "links.db")

    assert store.get(1) is None

    store.set(1, 100, "first")
    store.set(1, 200, "relinked")
    store.set(2, 300, "other")

    assert store.get(1) == (200, "relinked")
    assert store.get(2) == (300, "other")
    store.close()

    # Links survive a restart.
    reopened = LinkStore(tmp_path / "nested" / "links.db")
    assert reopened.get(1) == (200, "relinked")
    reopened.close()


def test_unlink(tmp_path):
    store = LinkStore(tmp_path / "links.db")
    store.set(1, 100, "first")
    store.set(2, 300, "other")

    assert store.delete(1) is True
    assert store.get(1) is None
    # Only that user's link goes.
    assert store.get(2) == (300, "other")
    # Nothing left to remove.
    assert store.delete(1) is False
    store.close()


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------
def test_help_fits_in_a_discord_embed():
    title, description, fields = help_embed_parts()

    assert len(title) <= 256
    assert len(description) <= 4096
    assert len(fields) <= 25
    for name, value in fields:
        assert len(name) <= 256
        assert 0 < len(value) <= 1024, name
    assert len(title) + len(description) + sum(len(n) + len(v) for n, v in fields) <= 6000


@pytest.mark.parametrize(("options", "note"), EXAMPLES)
def test_help_examples_are_valid_rec_input(options, note):
    """Every example in /help must be something /rec accepts as typed."""
    options = dict(options)
    options.pop("user", None)

    for key, choices in (("goal", GOAL_CHOICES), ("hide", HIDE_CHOICES), ("status", STATUS_CHOICES)):
        if key in options:
            options[key] = choices[options[key]]

    build_settings(player_id=1, **options)


def test_help_mentions_every_rec_option():
    title, description, fields = help_embed_parts()
    names = " ".join(name for name, _ in fields)
    text = " ".join(value for _, value in fields)

    for option in ("user", "goal", "mods", "hide", "status", *RANGE_FILTERS):
        assert option in names
    assert "exact_mods" in text
