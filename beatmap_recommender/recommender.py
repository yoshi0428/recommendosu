import os
import time
from pathlib import Path
import asyncio
import sqlite3
import requests

from beatmap_recommender.api.model import RecommendationSettings
from beatmap_recommender.auth.token_manager import get_access_token

from beatmap_recommender.content_similarity.core_modules.mod_preferences import (
    canonicalize_mods,
    get_preferred_mods,
)
from beatmap_recommender.content_similarity.core_modules.score_collector import (
    update_player_scores,
)
from beatmap_recommender.content_similarity.core_modules.content_similarity import (
    build_seed_similarity_index,
)
from beatmap_recommender.content_similarity.core_modules.variant_ranking import (
    get_player_difficulty_profile,
    rank_variants,
)
from beatmap_recommender.content_similarity.core_modules.cnn_xgboost_influence import (
    get_player_category_preferences,
)

from beatmap_recommender.api.osu_api_client import OsuAPIClient
import threading
from beatmap_recommender.cancellation import check_cancelled

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(
    os.getenv(
        "DB_PATH",
        PROJECT_ROOT / "beatmap_recommender/recommender.db",
    )
)

NEIGHBORS_K = 20_000
BATCH_SIZE = 16384
RECOMMENDATION_CONCURRENCY = 4
WORKERS = -1

_recommendation_semaphore = asyncio.Semaphore(RECOMMENDATION_CONCURRENCY)

OSU_CLIENT_ID = os.getenv("OSU_CLIENT_ID")
OSU_CLIENT_SECRET = os.getenv("OSU_CLIENT_SECRET")

APPLICATION_TOKEN_REFRESH_BUFFER = 60
_application_access_token: str | None = None
_application_token_expires_at: float = 0.0
_application_token_lock = asyncio.Lock()

def get_client_credentials_token(
    client_id: str,
    client_secret: str,
) -> tuple[str, int]:
    response = requests.post(
        "https://osu.ppy.sh/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "public",
        },
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=30,
    )

    response.raise_for_status()
    data = response.json()
    return data["access_token"], data["expires_in"]


async def get_application_access_token() -> str:
    global _application_access_token
    global _application_token_expires_at

    if not OSU_CLIENT_ID:
        raise RuntimeError("OSU_CLIENT_ID is not configured.")
    if not OSU_CLIENT_SECRET:
        raise RuntimeError("OSU_CLIENT_SECRET is not configured.")

    now = time.time()

    # Existing token is still valid.
    if _application_access_token is not None and now < _application_token_expires_at:
        return _application_access_token

    # Only one request should refresh the token at a time.
    async with _application_token_lock:
        now = time.time()

        # Another coroutine may have refreshed the token while we were waiting for the lock.
        if _application_access_token is not None and now < _application_token_expires_at:
            return _application_access_token

        token, expires_in = await asyncio.to_thread(
            get_client_credentials_token,
            OSU_CLIENT_ID,
            OSU_CLIENT_SECRET,
        )

        _application_access_token = token
        _application_token_expires_at = time.time() + expires_in - APPLICATION_TOKEN_REFRESH_BUFFER
        return _application_access_token

def recommend_player_sync(
    settings: RecommendationSettings,
    access_token: str | None = None,
    update_scores=True,
    cancel_event: threading.Event | None = None,
):
    recommendation_config = settings.recommendation_config
    if settings.goal not in recommendation_config:
        raise ValueError(f"Unknown recommendation goal: {settings.goal}")

    check_cancelled(cancel_event)

    requested_mods = (
        {mod.strip().upper() for mod in settings.mods}
        if settings.mods
        else None
    )

    excluded_mods = {
        mod.strip().upper()
        for mod in (settings.excluded_mods or [])
    }

    conn = sqlite3.connect(DB_PATH)

    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # --------------------------------------------------------
        # Update player scores
        # --------------------------------------------------------
        check_cancelled(cancel_event)

        if update_scores:
            if access_token is None:
                raise ValueError("An osu! API access token is required to update player scores.")

            api = OsuAPIClient(access_token=access_token)
            update_player_scores(
                conn,
                api,
                settings.player_id,
                settings.limit,
            )

        check_cancelled(cancel_event)
        # --------------------------------------------------------
        # Build content similarity
        # --------------------------------------------------------

        print(f"ALREADY PLAYED: {settings.exclude_already_played}")

        similarity_index = build_seed_similarity_index(
            conn,
            player_id=settings.player_id,
            top_k=NEIGHBORS_K,
            batch_size=BATCH_SIZE,
            feature_weights=settings.feature_weights,
            workers=WORKERS,
            exclude_already_played=settings.exclude_already_played,
        )

        check_cancelled(cancel_event)

        if not similarity_index:
            return []

        # --------------------------------------------------------
        # Mod preferences
        # --------------------------------------------------------

        preferred_mods = get_preferred_mods(
            conn,
            player_id=settings.player_id,
            top_weight=settings.top_weight,
            recent_weight=settings.recent_weight,
            pp_weight=settings.pp_weight,
        )

        check_cancelled(cancel_event)

        print(f"\nPlayer {settings.player_id} mod preferences:")
        for mods, preference in preferred_mods:
            print(f"  {mods}: {preference:.3f}")

        mod_preferences = dict(preferred_mods)

        # --------------------------------------------------------
        # Difficulty profile
        # --------------------------------------------------------

        print(f"\nEXCLUDE RECENT PLAYS: {settings.exclude_recent_plays}")

        difficulty_profile = get_player_difficulty_profile(
            conn,
            player_id=settings.player_id,
            difficulty_std_floors=settings.difficulty_std_floors,
            recency_half_life_days=settings.recency_half_life_days,
            ability_top_weight=settings.ability_top_weight,
            ability_recent_weight=settings.ability_recent_weight,
            ability_pp_weight=settings.ability_pp_weight,
            exclude_recent_plays=settings.exclude_recent_plays,
            cancel_event=cancel_event,
        )

        check_cancelled(cancel_event)

        print(f"\nPlayer {settings.player_id} difficulty profile:")

        for feature in ("star_rating", "ar", "od", "bpm",):
            mean = difficulty_profile.get(f"{feature}_mean")
            std = difficulty_profile.get(f"{feature}_std")
            if mean is None or std is None:
                continue

            print(f"  {feature}: mean={mean:.3f}, std={std:.3f}")

        # --------------------------------------------------------
        # Classifier preferences
        # --------------------------------------------------------
        classifier_weight = recommendation_config[settings.goal]["weights"]["classifier"]
        if classifier_weight <= 0:
            category_preferences = {}
        else:
            category_preferences = get_player_category_preferences(
                conn,
                settings.player_id,
                recency_half_life_days=settings.recency_half_life_days,
                ability_top_weight=settings.ability_top_weight,
                ability_recent_weight=settings.ability_recent_weight,
                ability_pp_weight=settings.ability_pp_weight,
            )

            print()
            for label, probability in category_preferences.items():
                print(f"{label}: {float(probability) * 100:.2f}%")

        check_cancelled(cancel_event)

        # --------------------------------------------------------
        # Final ranking
        # --------------------------------------------------------

        ranked_variants = rank_variants(
            conn,
            similarity_index=similarity_index,
            mod_preferences=mod_preferences,
            difficulty_profile=difficulty_profile,
            category_preferences=category_preferences,
            top_k=settings.limit,
            requested_mods=requested_mods,
            excluded_mods=excluded_mods,
            min_stars=settings.min_stars,
            max_stars=settings.max_stars,
            min_bpm=settings.min_bpm,
            max_bpm=settings.max_bpm,
            min_pp=settings.min_pp,
            max_pp=settings.max_pp,
            min_ar=settings.min_ar,
            max_ar=settings.max_ar,
            min_od=settings.min_od,
            max_od=settings.max_od,
            min_length=settings.min_length,
            max_length=settings.max_length,
            min_combo=settings.min_combo,
            max_combo=settings.max_combo,
            min_cs=settings.min_cs,
            max_cs=settings.max_cs,
            recommendation_goal=settings.goal,
            recommendation_config=recommendation_config,
            difficulty_std_floors=settings.difficulty_std_floors,
            difficulty_feature_weights=settings.difficulty_feature_weights,
            pp_push_target_z=settings.pp_push_target_z,
            pp_push_max_z=settings.pp_push_max_z,
            cancel_event=cancel_event,
        )

        check_cancelled(cancel_event)

        print(f"\nRecommendation goal: {settings.goal}")
        print(f"\nTop {len(ranked_variants)} recommendations:")

        for i, variant in enumerate(ranked_variants, start=1):
            print(
                f"{i:2d}. "
                f"beatmap={variant['beatmap_id']}, "
                f"beatmapset={variant['beatmapset_id']}, "
                f"variant={variant['variant_id']}, "
                f"mods={variant['mods']}, "
                f"star={variant['star_rating']:.2f}, "
                f"bpm={variant['bpm']:.1f}, "
                f"AR={variant['ar']:.1f}, "
                f"OD={variant['od']:.1f}, "
                f"content={variant['content_similarity']:.4f}, "
                f"mod_pref={variant['mod_preference']:.4f}, "
                f"difficulty={variant['difficulty_score']:.4f}, "
                f"pp={variant['pp']:.4f}, "
                f"pp_potential={variant['pp_potential']:.4f}, "
                f"score={variant['final_score']:.4f}"
            )

        return ranked_variants

    finally:
        conn.close()


async def recommend_player(
    settings: RecommendationSettings,
    session_id: str,
    session_player_id: int,
    update_scores=True,
    cancel_event: threading.Event | None = None,
):
    async with _recommendation_semaphore:
        check_cancelled(cancel_event)
        access_token = None

        if update_scores:
            if settings.player_id == session_player_id:
                access_token = await get_access_token(session_id)
            else:
                access_token = await get_application_access_token()

        check_cancelled(cancel_event)

        return await asyncio.to_thread(
            recommend_player_sync,
            settings,
            access_token,
            update_scores,
            cancel_event,
        )