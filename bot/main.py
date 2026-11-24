"""
recommendosu Discord bot: /rec, /link and /classify.

The bot is a separate process. It uses the /api/v1/bot endpoints of the
backend over HTTP, so it never loads the recommender database. To run it,
use `python -m bot` from the project root.

Environment:
    DISCORD_TOKEN      the bot's token from the Discord developer portal
    BOT_API_KEY        the same value as the backend's BOT_API_KEY
    BOT_BACKEND_URL    default http://backend:8000 (the compose service)
    BOT_LINKS_DB       default bot/data/links.db
    BOT_DEV_GUILD_ID   optional. Sync the commands to this server only. The
                       update is instant, not within about an hour.
"""

import logging
import math
import os
from pathlib import Path

import discord
from discord import app_commands

from bot.api import BackendClient, BackendError
from bot.changelog import changelog_embed_parts
from bot.links import LinkStore
from bot.help import help_embed_parts
from bot.options import (
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
# The number of rows that the bot fetches from the backend at a time: 10 pages.
# The first response of the backend has the same number
# (BOT_RECOMMENDATION_PAGE_SIZE in main.py).
RECOMMENDATION_CHUNK_SIZE = 50
# The buttons stop working after this many seconds without a click.
VIEW_TIMEOUT_SECONDS = 10 * 60
# For each Discord user, so that one person cannot use all of the osu! API budget.
REC_COOLDOWN_SECONDS = 10.0

EMBED_COLOR = discord.Color.from_rgb(255, 102, 170)
SITE_URL = "https://recommendosu.com"


class RecommendOsuBot(discord.Client):
    def __init__(self, backend: BackendClient, links: LinkStore, dev_guild_id: int | None):
        # Slash commands need no privileged intents (special Discord permissions).
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.backend = backend
        self.links = links
        self.dev_guild_id = dev_guild_id
        # Discord user ID -> the recommendation_id of the last /rec of the user,
        # so that /classify can take an index. This is in memory only, so a
        # restart forgets it.
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
    Buttons that move through a /rec result, one page or 10 pages at a time.

    The backend keeps the full result, which can be millions of rows. When the
    user turns the pages, the view fetches RECOMMENDATION_CHUNK_SIZE rows at a time.
    """

    def __init__(self, backend, owner_id, player_id, username, result):
        super().__init__(timeout=VIEW_TIMEOUT_SECONDS)
        self.backend = backend
        self.owner_id = owner_id
        self.player_id = player_id
        self.username = username
        self.recommendation_id = result["recommendation_id"]
        self.total_count = result["total_count"]
        self.page_count = math.ceil(self.total_count / RECOMMENDATIONS_PER_PAGE)
        self.page = 0
        # The rows of the last fetch. They start at row chunk_offset of the result.
        self.chunk_offset = 0
        self.chunk_rows = result["recommendations"]
        self.message: discord.Message | None = None
        self.update_buttons()

    async def page_rows(self, page):
        """Return the rows of a page. If they are not in the current chunk, fetch a new chunk."""
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
        # Discord shows the author and footer text as it is (no markdown), so
        # the username needs no escapes there.
        embed.set_author(
            name=f"Recommendations for {self.username}",
            url=f"https://osu.ppy.sh/users/{self.player_id}",
            icon_url=f"https://a.ppy.sh/{self.player_id}",
        )
        embed.set_footer(
            text=(
                f"Page {self.page + 1:,}/{self.page_count:,} · "
                f"{self.total_count:,} matching maps · "
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
        # A jump past either end stops at the first page or the last page.
        page = min(max(self.page + step, 0), self.page_count - 1)

        try:
            rows = await self.page_rows(page)
        except BackendError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        self.page = page
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embed(rows), view=self)

    # The buttons show in the order of their definitions.
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
                # The message is deleted, or the interaction token expired.
                pass


# ── Commands ──────────────────────────────────────────────────────────────────


def embed_with_fields(title, description, fields, url=None):
    """Return an embed with one full-width field for each (name, value) in fields."""
    embed = discord.Embed(title=title, url=url, description=description, color=EMBED_COLOR)

    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)

    return embed


def register_commands(bot: RecommendOsuBot):
    """Add the slash commands (/rec, /link, /unlink, /classify, /changelog, /help) to the tree of the bot."""
    tree = bot.tree

    @tree.command(name="rec", description="Recommend beatmaps. With no options, uses the website's default settings.")
    @app_commands.describe(
        user="osu! username (defaults to the account you linked with /link)",
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
        hide=[app_commands.Choice(name=name, value=value) for name, value in HIDE_CHOICES.items()],
        status=[app_commands.Choice(name=name, value=value) for name, value in STATUS_CHOICES.items()],
    )
    @app_commands.checks.cooldown(1, REC_COOLDOWN_SECONDS, key=lambda interaction: interaction.user.id)
    async def rec(
        interaction: discord.Interaction,
        user: str | None = None,
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

        # Check the options before the defer, so that a mistake gets a private reply.
        try:
            settings = build_settings(
                player_id=None,
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
            # /rec for your own linked account (with or without `user`) keeps your full play history.
            own_account = linked is not None and player_id == linked[0]
            result = await bot.backend.recommend(settings, interaction.user.id, linked=own_account)
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
        # The cached result on the backend expires 30 minutes after its last
        # use. Without its ID here, nothing can read it before then.
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

    @tree.command(name="changelog", description="What's new on recommendosu.com and in the bot")
    async def changelog(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            entries = await bot.backend.changelog()
        except BackendError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        description, fields = changelog_embed_parts(entries)
        embed = embed_with_fields("Changelog", description, fields, url=f"{SITE_URL}/changelog")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name="help", description="What /rec can do, with examples")
    async def help(interaction: discord.Interaction):
        embed = embed_with_fields(*help_embed_parts())
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
        backend=BackendClient(os.getenv("BOT_BACKEND_URL", "http://backend:8000"), os.environ["BOT_API_KEY"]),
        links=LinkStore(os.getenv("BOT_LINKS_DB", BOT_DIR / "data" / "links.db")),
        dev_guild_id=int(dev_guild_id) if dev_guild_id else None,
    )
    register_commands(bot)
    # Without log_handler=None, discord.py sets up its own logging. Our logging setup is at the top of this file.
    bot.run(token, log_handler=None)
