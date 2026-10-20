"""
recommendosu Discord bot: /rec, /link and /classify.

A separate process that talks to the backend's /api/v1/bot endpoints over
HTTP, so it never loads the recommender database itself. Run it with
`python -m bot` from the project root.

Environment:
    DISCORD_TOKEN      the bot's token from the Discord developer portal
    BOT_API_KEY        the same value as the backend's BOT_API_KEY
    BOT_BACKEND_URL    default http://backend:8000 (the compose service)
    BOT_LINKS_DB       default bot/data/links.db
    BOT_DEV_GUILD_ID   optional; sync commands to this server only, which
                       updates instantly instead of within about an hour
"""

import logging
import math
import os
from pathlib import Path

import discord
from discord import app_commands

from bot.api import BackendClient, BackendError
from bot.links import LinkStore
from bot.help import help_embed_parts
from bot.options import (
    GOAL_CHOICES,
    HIDE_CHOICES,
    STATUS_CHOICES,
    OptionError,
    beatmap_url,
    build_settings,
    escape_markdown,
    format_beatmap_title,
    format_predictions,
    format_recommendation,
    parse_beatmap_id,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

BOT_DIR = Path(__file__).resolve().parent

RECOMMENDATIONS_PER_PAGE = 5
# Rows fetched from the backend at once: 10 pages. Its first response holds
# the same number (BOT_RECOMMENDATION_PAGE_SIZE in main.py).
RECOMMENDATION_CHUNK_SIZE = 50
# Buttons stop working after this long without a click.
VIEW_TIMEOUT_SECONDS = 10 * 60
# Per Discord user, so one person can't use up the osu! API budget.
REC_COOLDOWN_SECONDS = 10.0

EMBED_COLOR = discord.Color.from_rgb(255, 102, 170)
SITE_URL = "https://recommendosu.com"


class RecommendOsuBot(discord.Client):
    def __init__(self, backend: BackendClient, links: LinkStore, dev_guild_id: int | None):
        # Slash commands need no privileged intents.
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.backend = backend
        self.links = links
        self.dev_guild_id = dev_guild_id
        # Discord user ID -> recommendation_id of their last /rec, so
        # /classify can take an index. Kept in memory: a restart forgets it.
        self.last_recommendation_ids: dict[int, str] = {}

    async def setup_hook(self):
        if self.dev_guild_id:
            guild = discord.Object(id=self.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        logger.info("Logged in as %s (%s)", self.user, self.user.id)

    async def close(self):
        await self.backend.aclose()
        self.links.close()
        await super().close()


# ── Recommendation pages ──────────────────────────────────────────────────────


class RecommendationView(discord.ui.View):
    """
    Buttons to move through a /rec result, a page or 10 pages at a time.

    The backend keeps the full result, which can be millions of rows, and
    the view fetches it RECOMMENDATION_CHUNK_SIZE rows at a time as pages are
    turned.
    """

    def __init__(self, backend, owner_id, player_id, username, result):
        super().__init__(timeout=VIEW_TIMEOUT_SECONDS)
        self.backend = backend
        self.owner_id = owner_id
        self.player_id = player_id
        self.username = username
        self.recommendation_id = result["recommendation_id"]
        self.goal = result["recommendation_goal"].replace("_", " ")
        self.total_count = result["total_count"]
        self.page_count = math.ceil(self.total_count / RECOMMENDATIONS_PER_PAGE)
        self.page = 0
        # The rows fetched last, starting at row chunk_offset of the result.
        self.chunk_offset = 0
        self.chunk_rows = result["recommendations"]
        self.message: discord.Message | None = None
        self.update_buttons()

    async def page_rows(self, page):
        start = page * RECOMMENDATIONS_PER_PAGE
        end = min(start + RECOMMENDATIONS_PER_PAGE, self.total_count)

        if not (self.chunk_offset <= start and end <= self.chunk_offset + len(self.chunk_rows)):
            chunk_offset = start - start % RECOMMENDATION_CHUNK_SIZE
            chunk = await self.backend.recommendation_page(
                self.recommendation_id,
                self.owner_id,
                offset=chunk_offset,
                limit=RECOMMENDATION_CHUNK_SIZE,
            )
            self.chunk_offset = chunk_offset
            self.chunk_rows = chunk["recommendations"]

        return self.chunk_rows[start - self.chunk_offset:end - self.chunk_offset]

    def embed(self, rows):
        start = self.page * RECOMMENDATIONS_PER_PAGE

        embed = discord.Embed(
            description="\n\n".join(
                format_recommendation(start + index + 1, row) for index, row in enumerate(rows)
            ),
            color=EMBED_COLOR,
        )
        # Author and footer text is shown as-is (no markdown), so the
        # username needs no escaping there.
        embed.set_author(
            name=f"Recommendations for {self.username}",
            url=f"https://osu.ppy.sh/users/{self.player_id}",
            icon_url=f"https://a.ppy.sh/{self.player_id}",
        )
        embed.set_footer(
            text=(
                f"Page {self.page + 1:,}/{self.page_count:,} · "
                f"{self.total_count:,} matching maps · goal: {self.goal} · "
                f"full list at {SITE_URL.removeprefix('https://')}"
            )
        )
        return embed

    async def first_embed(self):
        return self.embed(await self.page_rows(0))

    def update_buttons(self):
        at_start = self.page == 0
        at_end = self.page >= self.page_count - 1

        for button in (self.back_10, self.previous_page):
            button.disabled = at_start
        for button in (self.next_page, self.forward_10):
            button.disabled = at_end

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "These are someone else's recommendations. Run /rec for your own.",
                ephemeral=True,
            )
            return False
        return True

    async def turn_page(self, interaction: discord.Interaction, step):
        # Jumps past either end stop at the first or last page.
        page = min(max(self.page + step, 0), self.page_count - 1)

        try:
            rows = await self.page_rows(page)
        except BackendError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        self.page = page
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embed(rows), view=self)

    # Decorated buttons appear in the order they're defined.
    @discord.ui.button(label="« 10", style=discord.ButtonStyle.secondary)
    async def back_10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.turn_page(interaction, -10)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.turn_page(interaction, -1)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.turn_page(interaction, 1)

    @discord.ui.button(label="10 »", style=discord.ButtonStyle.secondary)
    async def forward_10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.turn_page(interaction, 10)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                # The message was deleted, or the interaction token expired.
                pass


# ── Commands ──────────────────────────────────────────────────────────────────


def register_commands(bot: RecommendOsuBot):
    tree = bot.tree

    @tree.command(name="rec", description="Recommend beatmaps. With no options, uses the website's default settings.")
    @app_commands.describe(
        user="osu! username (defaults to the account you linked with /link)",
        goal="What to optimise for",
        mods="e.g. HD HR. -FL excludes, ~EZ allows EZ/HT/FL (off by default), =HDDT is that exact combination",
        exact_mods="Only the exact combination in mods, e.g. mods: HDDT gives HDDT but not HD or DT",
        hide="Maps to leave out (default: already played)",
        status="Ranked, loved, or both (default: both)",
        year="Year ranked, e.g. 2015, 2015-2020 or 2020+",
        stars="Star rating range, e.g. 5.5-6.5, 6+ or <7",
        bpm="BPM range, e.g. 180-220, 200+ or <240",
        pp="SS pp range, e.g. 300-400, 300+ or <450",
        cs="Circle size range, e.g. 4-5 or <4.5",
        ar="Approach rate range, e.g. 9-10 or 9.5+",
        od="Overall difficulty range, e.g. 8-10 or 9+",
        length="Length in seconds or m:ss, e.g. 1:30-3:00 or <120",
        combo="Max combo range, e.g. 500-1500 or <1000",
    )
    @app_commands.choices(
        goal=[app_commands.Choice(name=name, value=value) for name, value in GOAL_CHOICES.items()],
        hide=[app_commands.Choice(name=name, value=value) for name, value in HIDE_CHOICES.items()],
        status=[app_commands.Choice(name=name, value=value) for name, value in STATUS_CHOICES.items()],
    )
    @app_commands.checks.cooldown(1, REC_COOLDOWN_SECONDS, key=lambda interaction: interaction.user.id)
    async def rec(
        interaction: discord.Interaction,
        user: str | None = None,
        goal: app_commands.Choice[str] | None = None,
        mods: str | None = None,
        exact_mods: bool | None = None,
        hide: app_commands.Choice[str] | None = None,
        status: app_commands.Choice[str] | None = None,
        year: str | None = None,
        stars: str | None = None,
        bpm: str | None = None,
        pp: str | None = None,
        cs: str | None = None,
        ar: str | None = None,
        od: str | None = None,
        length: str | None = None,
        combo: str | None = None,
    ):
        linked = bot.links.get(interaction.user.id)

        if user is None and linked is None:
            await interaction.response.send_message(
                "Link your osu! account with `/link`, or pass `user`.",
                ephemeral=True,
            )
            return

        # Check the options before deferring, so mistakes get a private reply.
        try:
            settings = build_settings(
                player_id=None,
                goal=goal.value if goal else None,
                mods=mods,
                exact_mods=exact_mods,
                hide=hide.value if hide else None,
                status=status.value if status else None,
                year=year, stars=stars, bpm=bpm, pp=pp, cs=cs,
                ar=ar, od=od, length=length, combo=combo,
            )
        except OptionError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        try:
            if user is None:
                player_id, username = linked
            else:
                player = await bot.backend.get_player(user)
                player_id, username = player["player_id"], player["username"]

            settings["player_id"] = player_id
            result = await bot.backend.recommend(settings, interaction.user.id)
        except BackendError as exc:
            await interaction.followup.send(str(exc))
            return

        bot.last_recommendation_ids[interaction.user.id] = result["recommendation_id"]

        if not result["recommendations"]:
            await interaction.followup.send(
                f"No maps matched those options for **{escape_markdown(username)}**. Try loosening the filters."
            )
            return

        view = RecommendationView(bot.backend, interaction.user.id, player_id, username, result)
        view.message = await interaction.followup.send(embed=await view.first_embed(), view=view, wait=True)

    @tree.command(name="link", description="Link your osu! account, so /rec uses it by default")
    @app_commands.describe(username="Your osu! username")
    async def link(interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            player = await bot.backend.get_player(username)
        except BackendError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        bot.links.set(interaction.user.id, player["player_id"], player["username"])
        await interaction.followup.send(
            f"Linked to **{escape_markdown(player['username'])}** "
            f"(<https://osu.ppy.sh/users/{player['player_id']}>). `/rec` now uses this account.",
            ephemeral=True,
        )

    @tree.command(name="unlink", description="Remove your linked osu! account and forget your last /rec")
    async def unlink(interaction: discord.Interaction):
        # The backend's cached result expires on its own, 30 minutes after
        # its last use; without its ID here, nothing can read it before then.
        bot.last_recommendation_ids.pop(interaction.user.id, None)

        if bot.links.delete(interaction.user.id):
            message = "Unlinked. The bot no longer stores your Discord ID or osu! account."
        else:
            message = "You had no linked account. Your last `/rec` is forgotten."

        await interaction.response.send_message(message, ephemeral=True)

    @tree.command(name="classify", description="What a beatmap mostly tests: aim, streams, alt, tech, or speed & stamina")
    @app_commands.describe(
        beatmap="Beatmap link or ID, e.g. https://osu.ppy.sh/b/129891",
        index="A map from your last /rec, by its number in the list",
    )
    async def classify(
        interaction: discord.Interaction,
        beatmap: str | None = None,
        index: app_commands.Range[int, 1] | None = None,
    ):
        try:
            if (beatmap is None) == (index is None):
                raise OptionError("Give either `beatmap` or `index`.")

            if beatmap is not None:
                beatmap_id = parse_beatmap_id(beatmap)
            else:
                recommendation_id = bot.last_recommendation_ids.get(interaction.user.id)
                if recommendation_id is None:
                    raise OptionError("Run `/rec` first, then pick a map from it with `index`.")
        except OptionError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        # Only the person who ran /classify sees the result.
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            if index is not None:
                page = await bot.backend.recommendation_page(
                    recommendation_id, interaction.user.id, offset=index - 1, limit=1
                )
                if not page["recommendations"]:
                    await interaction.followup.send(
                        f"Your last `/rec` has maps 1 to {page['total_count']:,}.", ephemeral=True
                    )
                    return
                beatmap_id = page["recommendations"][0]["beatmap_id"]

            result = await bot.backend.classify(beatmap_id)
        except BackendError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        best, lines = format_predictions(result["predictions"])

        embed = discord.Embed(
            title=format_beatmap_title(result),
            url=beatmap_url(result["beatmap_id"]),
            description=f"Mostly **{best}**\n\n{lines}",
            color=EMBED_COLOR,
        )
        embed.set_footer(
            text=(
                f"★{result['star_rating']:.2f} NM · mapped by {result['creator']} · "
                "classifier trained on the NoMod slots (NM1-NM5) of tournament mappools"
            )
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name="help", description="What /rec can do, with examples")
    async def help(interaction: discord.Interaction):
        title, description, fields = help_embed_parts()
        embed = discord.Embed(title=title, description=description, color=EMBED_COLOR)

        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.error
    async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Slow down a little: try again in {error.retry_after:.0f}s."
        else:
            logger.exception("Command failed", exc_info=error)
            message = "Something went wrong running that command."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def main():
    token = os.environ["DISCORD_TOKEN"]
    dev_guild_id = os.getenv("BOT_DEV_GUILD_ID")

    bot = RecommendOsuBot(
        backend=BackendClient(
            os.getenv("BOT_BACKEND_URL", "http://backend:8000"),
            os.environ["BOT_API_KEY"],
        ),
        links=LinkStore(os.getenv("BOT_LINKS_DB", BOT_DIR / "data" / "links.db")),
        dev_guild_id=int(dev_guild_id) if dev_guild_id else None,
    )
    register_commands(bot)
    # discord.py would set up its own logging otherwise; ours is above.
    bot.run(token, log_handler=None)
