import asyncio
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import Cookie, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from beatmap_recommender.api.model import RecommendationSettings
from beatmap_recommender.api.osu_api import get_authenticated_user
from beatmap_recommender.api.osu_api_client import OsuAPIClient, OsuAPINotFoundError
from beatmap_recommender.auth.db import initialize_auth_db
from beatmap_recommender.auth.oauth_state import consume_state, store_state
from beatmap_recommender.auth.osu_oauth import (
    OSU_CLIENT_ID,
    OSU_REDIRECT_URI,
    OsuAuthorizationRevoked,
    build_authorization_url,
    exchange_code_for_token,
    generate_state,
    get_application_access_token,
)
from beatmap_recommender.auth.session import (
    SESSION_EXPIRATION_SECONDS,
    create_session,
    delete_session,
    get_current_player,
)
from beatmap_recommender.auth.token_store import store_tokens
from beatmap_recommender.changelog import ChangelogEntry, read_changelog
from beatmap_recommender.cancellation import (
    RecommendationCancelled,
    cancel_recommendation,
    create_cancellation_event,
    remove_cancellation_event,
)
from beatmap_recommender.content_similarity.core_modules.classifier_influence import NM_LABELS
from beatmap_recommender.content_similarity.core_modules.played_maps import start_sync_worker
from beatmap_recommender.content_similarity.core_modules.score_collector import PlayerNotFoundError
from beatmap_recommender.content_similarity.core_modules.variant_table import load_variant_table
from beatmap_recommender.database import connect_db
from beatmap_recommender.recommender import recommend_player
from beatmap_recommender.result_cache import get_result_page, store_result

# The logs always go to stdout (`docker compose logs`). If you set LOG_FILE,
# the logs also go to that file. The file rotates at LOG_FILE_MAX_BYTES, and
# LOG_FILE_BACKUPS old files stay (backend.log.1, backend.log.2, ...).
LOG_FILE = os.getenv("LOG_FILE")
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
LOG_FILE_BACKUPS = 5

log_handlers = [logging.StreamHandler()]

if LOG_FILE:
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_FILE_MAX_BYTES, backupCount=LOG_FILE_BACKUPS, encoding="utf-8"
    )
    log_handlers.append(file_handler)

    # The uvicorn loggers (startup messages, one line for each request) do not
    # send their records to the root logger. Thus they need the file handler too.
    for name in ("uvicorn", "uvicorn.access"):
        logging.getLogger(name).addHandler(file_handler)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=log_handlers,
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

# The number of rows that POST /recommend and the page endpoint return for
# each request. A full result can have millions of rows, which is too large
# for one response.
RECOMMENDATION_PAGE_SIZE = 1000
MAX_RECOMMENDATION_PAGE_SIZE = 5000

SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"

# The shared secret of the Discord bot (bot/), in the X-Bot-Key header. If it
# is not set, the bot endpoints are disabled.
BOT_API_KEY = os.getenv("BOT_API_KEY")

# The bot shows a few recommendations on each Discord page. Thus it fetches
# the result in small chunks, not RECOMMENDATION_PAGE_SIZE rows at a time.
BOT_RECOMMENDATION_PAGE_SIZE = 50
MAX_BOT_RECOMMENDATION_PAGE_SIZE = 100


def make_background_api_client():
    """Return a client-credentials client of this app, at low priority, for the worker of played_maps.py."""
    from beatmap_recommender.recommender_db_setup.osu_api_client import OsuAPIClient as AppOsuAPIClient

    client = AppOsuAPIClient()
    client.low_priority = True
    return client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepare the auth database, the variant table and the sync worker before the first request."""
    logger.info("OAuth client ID: %r, redirect URI: %r", OSU_CLIENT_ID, OSU_REDIRECT_URI)
    initialize_auth_db()
    load_variant_table()
    if os.getenv("PLAYED_MAPS_SYNC", "1") != "0":
        start_sync_worker(connect=connect_db, make_api=make_background_api_client)
    yield


app = FastAPI(
    title="osu! Beatmap Recommender API",
    summary="Personalized osu! beatmap recommendations.",
    description=(
        "An API for generating personalized osu! beatmap recommendations "
        "using player scores, content similarity, difficulty profiles, "
        "mod preferences, and optional tournament-classifier preferences."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


class Recommendation(BaseModel):
    """One recommended beatmap variant."""

    # ── Identity and metadata ──────────────────────────────────
    beatmap_id: str = Field(
        description=(
            "Base osu! beatmap identifier. It is a numeric beatmap ID, or an MD5 "
            "identifier for a map without a numeric ID."
        ),
        examples=["5476216"],
    )
    beatmapset_id: str = Field(
        description=(
            "Base osu! beatmapset identifier. It can be missing for some "
            "beatmaps that have only an MD5 identifier. Other MD5 beatmaps have "
            "a numeric beatmap_id, and thus a numeric beatmapset_id too."
        ),
        examples=["5476216"],
    )
    variant_id: int = Field(description="Database identifier of this beatmap variant.", examples=[12345])
    title: str = Field(description="The title of the song.", examples=["Raise My Sword"])
    artist: str = Field(description="The artist of the song.", examples=["GALNERYUS"])
    creator: str = Field(description="The creator of the beatmapset.", examples=["ktgster"])
    version: str = Field(description="The difficulty name of the beatmap in its beatmapset.", examples=["Insane"])
    status: str = Field(description="Beatmap status in the recommender database.", examples=["ranked", "loved"])
    mods: str = Field(description="Canonical mod combination of this variant.", examples=["NM", "HD", "HR", "HDDT"])

    # ── Difficulty values ──────────────────────────────────────
    hp_drain: float = Field(description="HP Drain value.", examples=[5.0])
    circle_size: float = Field(description="Circle Size value.", examples=[4.0])
    od: float = Field(description="Overall Difficulty value.", examples=[8.5])
    ar: float = Field(description="Approach Rate value.", examples=[9.0])
    star_rating: float = Field(description="Calculated star rating of this variant.", examples=[5.42])
    max_combo: int | None = Field(default=None, description="Maximum possible combo.", examples=[1234])
    bpm: float | None = Field(default=None, description="BPM of this variant.", examples=[180.0])
    min_bpm: float | None = Field(default=None, description="Minimum BPM, if the map has one.", examples=[180.0])
    max_bpm: float | None = Field(default=None, description="Maximum BPM, if the map has one.", examples=[180.0])
    length_seconds: float = Field(description="Beatmap length in seconds.", examples=[125.5])
    object_count: int = Field(description="Number of hit objects.", examples=[642])

    # ── Performance points ─────────────────────────────────────
    pp: float | None = Field(default=None, description="Calculated performance points (pp).", examples=[285.4])
    pp_aim: float | None = Field(default=None, description="Aim part of the calculated pp.", examples=[105.2])
    pp_speed: float | None = Field(default=None, description="Speed part of the calculated pp.", examples=[98.7])
    pp_acc: float | None = Field(default=None, description="Accuracy part of the calculated pp.", examples=[81.5])
    pp_flashlight: float | None = Field(
        default=None, description="Flashlight part of the calculated pp.", examples=[0.0]
    )

    # ── Recommendation scores ──────────────────────────────────
    content_similarity: float = Field(
        description="Similarity between this map and the seed maps of the player.", examples=[0.87]
    )
    mod_preference: float = Field(
        description="How much the player prefers the mods of this variant, from the scores.", examples=[0.75]
    )
    difficulty_score: float = Field(
        description="How closely the difficulty of this variant matches the difficulty profile of the player.",
        examples=[0.91],
    )
    classifier_score: float = Field(
        description="How well this map matches the tournament category preferences of the player.",
        examples=[0.82],
    )
    final_score: float = Field(description="The final score that the ranking uses.", examples=[0.84])


class RecommendationResponse(BaseModel):
    """The first page of a new recommendation result."""

    recommendation_id: str = Field(description="Unique identifier of this recommendation request.")
    player_id: int = Field(description="The osu! player ID of the recommendations.", examples=[12345678])
    total_count: int = Field(description="Number of recommendations in the full ranked result.", examples=[4088])
    offset: int = Field(description="Index of the first recommendation in this response.", examples=[0])
    recommendations: list[Recommendation] = Field(description="Ranked list of recommended beatmap variants.")


@app.get(
    f"{API_PREFIX}/changelog",
    response_model=list[ChangelogEntry],
    summary="The site's changelog, newest first",
    description="Public, like the About page. Also shown by the Discord bot's /changelog.",
    tags=["System"],
)
def changelog():
    return read_changelog()


@app.get(
    "/health",
    summary="Health check",
    description="Check whether the recommendation API is running.",
    tags=["System"],
)
def health():
    return {"status": "ok"}


# ── Recommend ─────────────────────────────────────────────────────────────


def require_player(session_id: str | None) -> int:
    """Return the player ID of the session, or raise 401 if there is no valid session."""
    try:
        return get_current_player(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


async def run_recommender(settings: RecommendationSettings, **kwargs):
    """Call recommend_player(). Change the errors that a request can cause into HTTP errors."""
    try:
        return await recommend_player(settings, **kwargs)
    except PlayerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except OsuAuthorizationRevoked as exc:
        # The session is deleted, so the next page load shows the login screen.
        raise HTTPException(status_code=401, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def cache_and_first_page(
    recommendation_id: str,
    owner: int | str,
    settings: RecommendationSettings,
    recommendations,
    page_size: int,
) -> dict:
    """
    Cache a full result for owner (see result_cache.py), and return its first
    page_size recommendations. The owner reads the other pages later.
    """
    await asyncio.to_thread(store_result, recommendation_id, owner, recommendations)

    return {
        "recommendation_id": recommendation_id,
        "player_id": settings.player_id,
        "total_count": len(recommendations),
        "offset": 0,
        "recommendations": recommendations[:page_size],
    }


def result_page(recommendation_id: str, owner: int | str, offset: int, limit: int, expired_detail: str) -> dict:
    """Return one page of a cached result. Raise 404 if the result expired or another owner has it."""
    page = get_result_page(recommendation_id, owner, offset, limit)

    if page is None:
        raise HTTPException(status_code=404, detail=expired_detail)

    total_count, recommendations = page

    return {
        "recommendation_id": recommendation_id,
        "total_count": total_count,
        "offset": offset,
        "recommendations": recommendations,
    }


@app.post(
    f"{API_PREFIX}/recommend",
    response_model=RecommendationResponse,
    summary="Get customized beatmap recommendations",
    description=(
        "Generate personalized beatmap recommendations using a complete "
        "RecommendationSettings object. This endpoint exposes advanced "
        "recommendation filters, weighting, difficulty-profile settings, "
        "mod preferences, and score weighting. "
        "Only the first page of results is returned. Fetch the rest from "
        f"{API_PREFIX}/recommend/{{recommendation_id}}/page."
    ),
    tags=["Recommendations"],
)
async def recommend_post(
    settings: RecommendationSettings,
    session_id: str | None = Cookie(default=None),
    recommendation_id: str | None = Header(default=None, alias="X-Recommendation-Id"),
):
    session_player_id = require_player(session_id)

    if settings.player_id is None:
        settings.player_id = session_player_id

    if not recommendation_id:
        raise HTTPException(status_code=400, detail="Missing X-Recommendation-Id header.")

    # Register the ID from the client before the worker starts.
    recommendation_id, cancel_event = create_cancellation_event(recommendation_id)

    try:
        recommendations = await run_recommender(
            settings,
            session_id=session_id,
            session_player_id=session_player_id,
            cancel_event=cancel_event,
        )
    except RecommendationCancelled:
        return Response(
            status_code=204,
            headers={"X-Recommendation-Cancelled": "true", "X-Recommendation-Id": recommendation_id},
        )
    finally:
        remove_cancellation_event(recommendation_id)

    return await cache_and_first_page(
        recommendation_id, session_player_id, settings, recommendations, RECOMMENDATION_PAGE_SIZE
    )


class RecommendationPageResponse(BaseModel):
    """One page of a cached recommendation result."""

    recommendation_id: str
    total_count: int
    offset: int
    recommendations: list[Recommendation]


@app.get(
    f"{API_PREFIX}/recommend/{{recommendation_id}}/page",
    response_model=RecommendationPageResponse,
    summary="Get a page of a recommendation result",
    description=(
        "Return a slice of a result previously generated by POST "
        f"{API_PREFIX}/recommend. Results expire after 30 minutes without "
        "access, and only the latest result per player is kept."
    ),
    tags=["Recommendations"],
)
async def recommend_page(
    recommendation_id: str,
    session_id: str | None = Cookie(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=RECOMMENDATION_PAGE_SIZE, ge=1, le=MAX_RECOMMENDATION_PAGE_SIZE),
):
    return result_page(
        recommendation_id,
        require_player(session_id),
        offset,
        limit,
        "Recommendation result expired or not found. Run the recommender again.",
    )


@app.post(
    f"{API_PREFIX}/recommend/{{recommendation_id}}/cancel",
    summary="Cancel an active recommendation request",
    tags=["Recommendations"],
)
async def recommend_cancel(recommendation_id: str, session_id: str | None = Cookie(default=None)):
    require_player(session_id)
    return {"recommendation_id": recommendation_id, "cancelled": cancel_recommendation(recommendation_id)}


# ── Discord Bot ───────────────────────────────────────────────────────────


def require_bot(bot_key: str | None) -> None:
    """Raise 401 if bot_key is not the bot API key, or if no key is set."""
    if not BOT_API_KEY or not bot_key or not secrets.compare_digest(bot_key, BOT_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid bot API key.")


def bot_result_owner(discord_user_id: int) -> str:
    """Return the result cache owner for a Discord user. It cannot be equal to an osu! player ID."""
    return f"discord:{discord_user_id}"


class BotPlayerResponse(BaseModel):
    player_id: int
    username: str


@app.get(
    f"{API_PREFIX}/bot/players/{{username}}",
    response_model=BotPlayerResponse,
    summary="Look up an osu! player by username",
    tags=["Discord bot"],
)
async def bot_player(username: str, bot_key: str | None = Header(default=None, alias="X-Bot-Key")):
    require_bot(bot_key)
    access_token = await get_application_access_token()

    try:
        user = await asyncio.to_thread(
            OsuAPIClient(access_token).get,
            f"/users/{quote(username, safe='')}/osu",
            params={"key": "username"},
        )
    except OsuAPINotFoundError:
        raise HTTPException(status_code=404, detail=f"osu! player {username!r} was not found.")

    return {"player_id": user["id"], "username": user["username"]}


@app.post(
    f"{API_PREFIX}/bot/recommend",
    response_model=RecommendationResponse,
    summary="Get recommendations for any player (Discord bot)",
    description=(
        "Same settings as POST /recommend, but player_id is required and "
        "scores are fetched with the application token. Only the first "
        f"{BOT_RECOMMENDATION_PAGE_SIZE} recommendations are returned. Fetch "
        f"the rest from {API_PREFIX}/bot/recommend/{{recommendation_id}}/page."
    ),
    tags=["Discord bot"],
)
async def bot_recommend(
    settings: RecommendationSettings,
    bot_key: str | None = Header(default=None, alias="X-Bot-Key"),
    discord_user_id: int = Header(alias="X-Discord-User-Id"),
):
    require_bot(bot_key)

    if settings.player_id is None:
        raise HTTPException(status_code=400, detail="player_id is required.")

    # There is no session. A session_player_id that never matches makes the
    # recommender fetch the scores with the token of the app.
    recommendations = await run_recommender(settings, session_id=None, session_player_id=None)

    # Cache the result for the Discord user who asked, as the website does for
    # its logged-in player. Thus each Discord user keeps a separate latest
    # result, and cannot replace the result of a website user.
    return await cache_and_first_page(
        uuid.uuid4().hex,
        bot_result_owner(discord_user_id),
        settings,
        recommendations,
        BOT_RECOMMENDATION_PAGE_SIZE,
    )


@app.get(
    f"{API_PREFIX}/bot/recommend/{{recommendation_id}}/page",
    response_model=RecommendationPageResponse,
    summary="Get a page of a Discord user's recommendation result",
    description=(
        "Return a slice of a result previously generated by POST "
        f"{API_PREFIX}/bot/recommend for the same Discord user. Results expire "
        "after 30 minutes without access, and only the latest result of each user is kept."
    ),
    tags=["Discord bot"],
)
async def bot_recommend_page(
    recommendation_id: str,
    bot_key: str | None = Header(default=None, alias="X-Bot-Key"),
    discord_user_id: int = Header(alias="X-Discord-User-Id"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=BOT_RECOMMENDATION_PAGE_SIZE, ge=1, le=MAX_BOT_RECOMMENDATION_PAGE_SIZE),
):
    require_bot(bot_key)

    return result_page(
        recommendation_id,
        bot_result_owner(discord_user_id),
        offset,
        limit,
        "These recommendations expired. Run /rec again.",
    )


class BotClassifyResponse(BaseModel):
    beatmap_id: str
    beatmapset_id: str | None
    title: str
    artist: str
    creator: str
    version: str
    status: str
    star_rating: float
    predictions: dict[str, float] = Field(
        description="Fusion classifier probability for each NM tournament category (they sum to 1).",
        examples=[{"NM1": 0.05, "NM2": 0.8, "NM3": 0.1, "NM4": 0.03, "NM5": 0.02}],
    )


@app.get(
    f"{API_PREFIX}/bot/classify/{{beatmap_id}}",
    response_model=BotClassifyResponse,
    summary="Get a beatmap's NM1-NM5 classifier predictions",
    tags=["Discord bot"],
)
async def bot_classify(beatmap_id: str, bot_key: str | None = Header(default=None, alias="X-Bot-Key")):
    require_bot(bot_key)

    # The predictions exist only for the NM variants.
    conn = connect_db(read_only=True)

    try:
        row = conn.execute(
            """
            SELECT
                b.beatmap_id, b.beatmapset_id, b.title, b.artist, b.creator,
                b.version, b.status, bv.star_rating,
                vp.nm1, vp.nm2, vp.nm3, vp.nm4, vp.nm5
            FROM beatmaps b
            JOIN beatmap_variants bv
                ON bv.beatmap_id = b.beatmap_id
               AND bv.mods = 'NM'
            LEFT JOIN variant_predictions vp
                ON vp.variant_id = bv.variant_id
            WHERE b.beatmap_id = ?
            """,
            (beatmap_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(
            status_code=404, detail="Beatmap not found. Only ranked and loved osu!standard maps are in the database."
        )

    info, predictions = row[:8], row[8:]

    if any(probability is None for probability in predictions):
        raise HTTPException(status_code=404, detail="The classifier has no prediction for this beatmap.")

    keys = ("beatmap_id", "beatmapset_id", "title", "artist", "creator", "version", "status", "star_rating")
    return {**dict(zip(keys, info)), "predictions": dict(zip(NM_LABELS, predictions))}


# ── Authentication ────────────────────────────────────────────────────────


@app.get(
    f"{API_PREFIX}/auth/osu",
    summary="Log in with osu!",
    tags=["Authentication"],
)
async def osu_login():
    state = generate_state()
    store_state(state)
    return RedirectResponse(url=build_authorization_url(state), status_code=302)


@app.get(
    f"{API_PREFIX}/auth/osu/callback",
    summary="osu! OAuth callback",
    tags=["Authentication"],
)
async def osu_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        logger.warning("OAuth callback error: %r", error)
        raise HTTPException(status_code=400, detail=f"osu! authorization failed: {error}")

    if not code:
        logger.warning("OAuth callback: missing code")
        raise HTTPException(status_code=400, detail="Missing authorization code.")

    if not state:
        logger.warning("OAuth callback: missing state")
        raise HTTPException(status_code=400, detail="Missing OAuth state.")

    if not consume_state(state):
        logger.warning("OAuth callback: invalid or expired state")
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")

    logger.debug("OAuth callback: state accepted, exchanging authorization code")

    try:
        token_data = await exchange_code_for_token(code)
        user_data = await get_authenticated_user(token_data["access_token"])
        player_id = user_data["id"]
        session_id = create_session(player_id)
        store_tokens(
            session_id=session_id,
            player_id=player_id,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_in=token_data["expires_in"],
        )

    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Failed to communicate with osu!.") from exc

    redirect_response = RedirectResponse(url="/", status_code=302)
    redirect_response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        # If the cookie fails in development (plain HTTP), set SESSION_COOKIE_SECURE to false.
        secure=SESSION_COOKIE_SECURE,
        max_age=SESSION_EXPIRATION_SECONDS,
    )

    return redirect_response


@app.get(
    f"{API_PREFIX}/auth/me",
    summary="Get the authenticated osu! player",
    tags=["Authentication"],
)
async def auth_me(session_id: str | None = Cookie(default=None)):
    return {"player_id": require_player(session_id)}


@app.post(
    f"{API_PREFIX}/auth/logout",
    summary="Log out of the application",
    tags=["Authentication"],
)
async def auth_logout(response: Response, session_id: str | None = Cookie(default=None)):
    if session_id:
        delete_session(session_id)

    response.delete_cookie(key="session_id")
    return {"message": "Logged out successfully."}
