import os
import uuid

import httpx
from pydantic import BaseModel, Field
from fastapi import (
    Cookie,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Response,
)
from fastapi.responses import RedirectResponse
from beatmap_recommender.api.model import RecommendationSettings
from beatmap_recommender.api.osu_api import get_authenticated_user
from beatmap_recommender.recommender import recommend_player
from beatmap_recommender.cancellation import (
    RecommendationCancelled,
    cancel_recommendation,
    create_cancellation_event,
    remove_cancellation_event,
)

from beatmap_recommender.auth.osu_oauth import (
    build_authorization_url,
    exchange_code_for_token,
    generate_state,
)

from beatmap_recommender.auth.oauth_state import (
    consume_state,
    initialize_state_store,
    store_state,
)

from beatmap_recommender.auth.session import (
    create_session,
    delete_session,
    get_current_player,
    initialize_session_store,
)

from beatmap_recommender.auth.token_store import (
    initialize_token_store, store_tokens,
)

from contextlib import asynccontextmanager

API_PREFIX = "/api/v1"
SESSION_COOKIE_SECURE = os.getenv(
    "SESSION_COOKIE_SECURE",
    "false",
).lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_token_store()
    initialize_session_store()
    initialize_state_store()
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
    """A single recommended beatmap variant."""

    beatmap_id: str = Field(
        description=(
            "Base osu! beatmap identifier. This may be a numeric beatmap "
            "ID or an MD5 identifier for maps without a numeric ID."
        ),
        examples=["5476216"],
    )

    beatmapset_id: str = Field(
        description="Base osu! beatmapset identifier.",
        examples=["5476216"],
    )

    variant_id: int = Field(
        description="Database identifier for the specific beatmap variant.",
        examples=[12345],
    )

    title: str = Field(
        description="The song's title.",
        examples=["Raise My Sword"],
    )

    artist: str = Field(
        description="The song's artist.",
        examples=["GALNERYUS"],
    )

    creator: str = Field(
        description="The beatmapset's creator.",
        examples=["ktgster"],
    )

    version: str = Field(
        description="The selected beatmap in a beatmapset.",
        examples=["Insane"],
    )

    mods: str = Field(
        description="Canonical mod combination for this recommendation.",
        examples=["NM", "HD", "HR", "HDDT"],
    )

    hp_drain: float = Field(
        description="HP Drain difficulty value.",
        examples=[5.0],
    )

    circle_size: float = Field(
        description="Circle Size difficulty value.",
        examples=[4.0],
    )

    od: float = Field(
        description="Overall Difficulty value.",
        examples=[8.5],
    )

    ar: float = Field(
        description="Approach Rate value.",
        examples=[9.0],
    )

    star_rating: float = Field(
        description="Calculated star rating for this variant.",
        examples=[5.42],
    )

    max_combo: int | None = Field(
        default=None,
        description="Maximum achievable combo.",
        examples=[1234],
    )

    bpm: float | None = Field(
        default=None,
        description="BPM of the beatmap variant.",
        examples=[180.0],
    )

    min_bpm: float | None = Field(
        default=None,
        description="Minimum BPM, where applicable.",
        examples=[180.0],
    )

    max_bpm: float | None = Field(
        default=None,
        description="Maximum BPM, where applicable.",
        examples=[180.0],
    )

    length_seconds: float = Field(
        description="Beatmap length in seconds.",
        examples=[125.5],
    )

    object_count: int = Field(
        description="Number of hit objects.",
        examples=[642],
    )

    pp: float | None = Field(
        default=None,
        description="Calculated performance points.",
        examples=[285.4],
    )

    pp_aim: float | None = Field(
        default=None,
        description="Aim component of calculated PP.",
        examples=[105.2],
    )

    pp_speed: float | None = Field(
        default=None,
        description="Speed component of calculated PP.",
        examples=[98.7],
    )

    pp_acc: float | None = Field(
        default=None,
        description="Accuracy component of calculated PP.",
        examples=[81.5],
    )

    pp_flashlight: float | None = Field(
        default=None,
        description="Flashlight component of calculated PP.",
        examples=[0.0],
    )

    content_similarity: float = Field(
        description=(
            "Similarity between the recommendation and the player's "
            "content-based seed maps."
        ),
        examples=[0.87],
    )

    mod_preference: float = Field(
        description="Score representing the player's observed mod preference.",
        examples=[0.75],
    )

    difficulty_score: float = Field(
        description=(
            "Score representing how closely the recommendation's difficulty "
            "matches the player's estimated difficulty profile."
        ),
        examples=[0.91],
    )

    classifier_score: float = Field(
        description=(
            "Score derived from the player's tournament-category preferences."
        ),
        examples=[0.82],
    )

    pp_potential: float = Field(
        description="Score representing the estimated PP-push potential.",
        examples=[0.68],
    )

    final_score: float = Field(
        description="Final recommendation score used for ranking.",
        examples=[0.84],
    )


class RecommendationResponse(BaseModel):
    """Response containing personalized beatmap recommendations."""

    recommendation_id: str = Field(
        description="Unique identifier for this recommendation request.",
    )

    player_id: int = Field(
        description="osu! player ID used to generate the recommendations.",
        examples=[12345678],
    )

    recommendation_goal: str = Field(
        description="Recommendation strategy used for this request.",
        examples=["balanced"],
    )

    recommendations: list[Recommendation] = Field(
        description="Ranked list of recommended beatmap variants.",
    )


@app.get(
    "/health",
    summary="Health check",
    description="Check whether the recommendation API is running.",
    tags=["System"],
)
def health():
    return {
        "status": "ok",
    }

########################################################################################################################
########################################################################################################################
########################################################################################################################
#
# RECOMMEND
#
########################################################################################################################
########################################################################################################################
########################################################################################################################


def require_player(session_id: str | None) -> int:
    try:
        return get_current_player(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
        )


@app.get(
    f"{API_PREFIX}/recommend",
    response_model=RecommendationResponse,
    summary="Get beatmap recommendations",
    description=(
        "Generate personalized beatmap recommendations for the "
        "authenticated osu! player."
    ),
    tags=["Recommendations"],
)
async def recommend_get(
    session_id: str | None = Cookie(default=None),
    limit: int = Query(
        default=200,
        ge=1,
        le=1000,
        description="Maximum number of recommendations to return.",
        examples=[100],
    ),
    goal: str = Query(
        default="balanced",
        description=(
            "Recommendation strategy. The available goals are defined by "
            "the server's recommendation configuration."
        ),
        examples=["balanced", "pp_potential", "NM1_to_5"],
    ),
):
    player_id = require_player(session_id)

    settings = RecommendationSettings(
        player_id=player_id,
        limit=limit,
        goal=goal,
    )

    try:
        recommendations = await recommend_player(
            settings,
            session_player_id=player_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    return {
        "recommendation_id": uuid.uuid4().hex,
        "player_id": settings.player_id,
        "recommendation_goal": settings.goal,
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
        "mod preferences, and recommendation-goal configuration."
    ),
    tags=["Recommendations"],
)
async def recommend_post(
    settings: RecommendationSettings,
    session_id: str | None = Cookie(default=None),
    recommendation_id: str | None = Header(
        default=None,
        alias="X-Recommendation-Id",
    ),
):
    session_player_id = require_player(session_id)

    if settings.player_id is None:
        settings.player_id = session_player_id

    if not recommendation_id:
        raise HTTPException(
            status_code=400,
            detail="Missing X-Recommendation-Id header.",
        )

    # Register the client-provided ID before starting the worker.
    recommendation_id, cancel_event = create_cancellation_event(recommendation_id)

    try:
        recommendations = await recommend_player(
            settings,
            session_player_id=session_player_id,
            cancel_event=cancel_event,
        )

    except RecommendationCancelled:
        return Response(
            status_code=204,
            headers={
                "X-Recommendation-Cancelled": "true",
                "X-Recommendation-Id": recommendation_id,
            },
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    finally:
        remove_cancellation_event(recommendation_id)

    return {
        "recommendation_id": recommendation_id,
        "player_id": settings.player_id,
        "recommendation_goal": settings.goal,
        "recommendations": recommendations,
    }

@app.post(
    f"{API_PREFIX}/recommend/{{recommendation_id}}/cancel",
    summary="Cancel an active recommendation request",
    tags=["Recommendations"],
)
async def recommend_cancel(
    recommendation_id: str,
    session_id: str | None = Cookie(default=None),
):
    require_player(session_id)
    cancelled = cancel_recommendation(recommendation_id)
    return {
        "recommendation_id": recommendation_id,
        "cancelled": cancelled,
    }


########################################################################################################################
########################################################################################################################
########################################################################################################################
#
# AUTHENTICATION
#
########################################################################################################################
########################################################################################################################
########################################################################################################################


@app.get(
    f"{API_PREFIX}/auth/osu",
    summary="Log in with osu!",
    tags=["Authentication"],
)
async def osu_login():
    state = generate_state()
    store_state(state)
    authorization_url = build_authorization_url(state)
    return RedirectResponse(
        url=authorization_url,
        status_code=302,
    )


@app.get(
    f"{API_PREFIX}/auth/osu/callback",
    summary="osu! OAuth callback",
    tags=["Authentication"],
)
async def osu_callback(
    response: Response,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        print("OAUTH CALLBACK ERROR:", repr(error))
        raise HTTPException(
            status_code=400,
            detail=f"osu! authorization failed: {error}",
        )

    if not code:
        print("OAUTH CALLBACK: missing code")
        raise HTTPException(
            status_code=400,
            detail="Missing authorization code.",
        )

    if not state:
        print("OAUTH CALLBACK: missing state")
        raise HTTPException(
            status_code=400,
            detail="Missing OAuth state.",
        )

    if not consume_state(state):
        print("OAUTH CALLBACK: invalid or expired state")
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state.",
        )

    print("OAUTH CALLBACK: state accepted")
    print("OAUTH CALLBACK: exchanging authorization code")

    try:
        token_data = await exchange_code_for_token(code)
        user_data = await get_authenticated_user(token_data["access_token"])
        player_id = user_data["id"]
        store_tokens(
            player_id=player_id,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_in=token_data["expires_in"],
        )

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Failed to communicate with osu!.",
        ) from exc

    session_id = create_session(user_data["id"])

    redirect_response = RedirectResponse(
        url="/",
        status_code=302,
    )

    redirect_response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=SESSION_COOKIE_SECURE,
        max_age=86400,
    )

    return redirect_response


@app.get(
    f"{API_PREFIX}/auth/me",
    summary="Get the authenticated osu! player",
    tags=["Authentication"],
)
async def auth_me(
    session_id: str | None = Cookie(default=None),
):
    try:
        player_id = get_current_player(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
        )

    return {
        "player_id": player_id,
    }

@app.post(
    f"{API_PREFIX}/auth/logout",
    summary="Log out of the application",
    tags=["Authentication"],
)
async def auth_logout(
    response: Response,
    session_id: str | None = Cookie(default=None),
):
    if session_id:
        delete_session(session_id)

    response.delete_cookie(key="session_id")

    return {
        "message": "Logged out successfully.",
    }