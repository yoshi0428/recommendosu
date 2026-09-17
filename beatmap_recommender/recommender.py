from pathlib import Path
import asyncio
import sqlite3

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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "beatmap_recommender/test_everything.db"

# Server-controlled.
NEIGHBORS_K = 50_000

RECOMMENDATION_CONCURRENCY = 4
_recommendation_semaphore = asyncio.Semaphore(
    RECOMMENDATION_CONCURRENCY
)


def recommend_player_sync(
    settings: RecommendationSettings,
    access_token: str | None = None,
    update_scores=True,
):
    recommendation_config = settings.recommendation_config

    if settings.goal not in recommendation_config:
        raise ValueError(
            f"Unknown recommendation goal: {settings.goal}"
        )

    requested_mods = canonicalize_mods(settings.mods)

    conn = sqlite3.connect(DB_PATH)

    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # --------------------------------------------------------
        # Update player scores
        # --------------------------------------------------------

        if update_scores:
            if access_token is None:
                raise ValueError("An OAuth access token is required to update player scores.")

            api = OsuAPIClient(access_token=access_token)
            update_player_scores(
                conn,
                api,
                settings.player_id,
                settings.limit,
            )

        # --------------------------------------------------------
        # Build content similarity
        # --------------------------------------------------------

        similarity_index = build_seed_similarity_index(
            conn,
            player_id=settings.player_id,
            top_k=NEIGHBORS_K,
            batch_size=1024,
            feature_weights=settings.feature_weights,
        )

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

        mod_preferences = dict(preferred_mods)

        # --------------------------------------------------------
        # Difficulty profile
        # --------------------------------------------------------

        difficulty_profile = get_player_difficulty_profile(
            conn,
            player_id=settings.player_id,
            difficulty_std_floors=settings.difficulty_std_floors,
            recency_half_life_days=settings.recency_half_life_days,
            ability_top_weight=settings.ability_top_weight,
            ability_recent_weight=settings.ability_recent_weight,
            ability_pp_weight=settings.ability_pp_weight,
        )

        # --------------------------------------------------------
        # Classifier preferences
        # --------------------------------------------------------

        category_preferences = get_player_category_preferences(
            conn,
            settings.player_id,
            recency_half_life_days=settings.recency_half_life_days,
            ability_top_weight=settings.ability_top_weight,
            ability_recent_weight=settings.ability_recent_weight,
            ability_pp_weight=settings.ability_pp_weight,
        )

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

            recommendation_goal=settings.goal,
            recommendation_config=recommendation_config,

            difficulty_std_floors=settings.difficulty_std_floors,
            difficulty_feature_weights=settings.difficulty_feature_weights,

            pp_push_target_z=settings.pp_push_target_z,
            pp_push_max_z=settings.pp_push_max_z,
        )

        return ranked_variants

    finally:
        conn.close()


async def recommend_player(
    settings: RecommendationSettings,
    update_scores=True,
):
    async with _recommendation_semaphore:
        access_token = None
        if update_scores:
            access_token = await get_access_token(settings.player_id)

        return await asyncio.to_thread(
            recommend_player_sync,
            settings,
            access_token,
            update_scores,
        )