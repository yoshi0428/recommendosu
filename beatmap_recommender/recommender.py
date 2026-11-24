import asyncio
import logging
import threading

from beatmap_recommender.api.model import RecommendationSettings
from beatmap_recommender.api.osu_api_client import OsuAPIClient
from beatmap_recommender.auth.osu_oauth import get_access_token, get_application_access_token
from beatmap_recommender.cancellation import check_cancelled
from beatmap_recommender.content_similarity.core_modules.classifier_influence import get_player_category_preferences
from beatmap_recommender.content_similarity.core_modules.content_similarity import build_seed_similarity_index
from beatmap_recommender.content_similarity.core_modules.mod_preferences import get_preferred_mods
from beatmap_recommender.content_similarity.core_modules.played_maps import request_sync
from beatmap_recommender.content_similarity.core_modules.score_collector import (
    scores_refreshed_recently,
    update_player_scores,
)
from beatmap_recommender.content_similarity.core_modules.variant_ranking import (
    RANGE_COLUMNS,
    get_player_difficulty_profiles,
    rank_variants,
)
from beatmap_recommender.database import connect_db

logger = logging.getLogger(__name__)

# The number of seeds in each batch of the similarity search.
BATCH_SIZE = 16_384
# The maximum number of recommendations that run at the same time.
RECOMMENDATION_CONCURRENCY = 4

_recommendation_semaphore = asyncio.Semaphore(RECOMMENDATION_CONCURRENCY)


def recommend_player_sync(
    settings: RecommendationSettings,
    access_token: str | None = None,
    update_scores=True,
    cancel_event: threading.Event | None = None,
):
    """
    Make the recommendations for settings.player_id and return the ranked
    variants (a VariantRows). This function blocks, so call it in a thread.

    If update_scores is True, first fetch the new scores of the player with
    access_token. Raise RecommendationCancelled if cancel_event is set.
    """
    recommendation_config = settings.recommendation_config
    logger.debug("Recommendation config: %s", recommendation_config)

    check_cancelled(cancel_event)
    # Open the database read-only, unless the code must write fetched scores.
    conn = connect_db(read_only=not update_scores)

    try:
        # ── Update player scores ───────────────────────────────
        if update_scores:
            check_cancelled(cancel_event)

            if access_token is None:
                raise ValueError("An osu! API access token is required to update player scores.")

            update_player_scores(conn, OsuAPIClient(access_token=access_token), settings.player_id)

        check_cancelled(cancel_event)

        # ── Content similarity ────────────────────────────────
        logger.debug("Exclude already played: %s", settings.exclude_already_played)
        logger.debug("Similarity feature weights: %s", settings.similarity_feature_weights)

        similarity_index = build_seed_similarity_index(
            conn,
            player_id=settings.player_id,
            top_k=settings.neighbors_k,
            batch_size=BATCH_SIZE,
            similarity_feature_weights=settings.similarity_feature_weights,
            exclude_already_played=settings.exclude_already_played,
            status=None if settings.beatmap_status == "all" else settings.beatmap_status,
        )

        check_cancelled(cancel_event)

        if not similarity_index:
            return []

        # ── Mod preferences ───────────────────────────────────
        preferred_mods = get_preferred_mods(
            conn,
            player_id=settings.player_id,
            top_weight=settings.top_weight,
            recent_weight=settings.recent_weight,
            pp_weight=settings.pp_weight,
        )

        mod_preferences = dict(preferred_mods)
        check_cancelled(cancel_event)

        logger.info(
            "Player %s mod preferences: %s",
            settings.player_id,
            ", ".join(f"{mods}={preference:.3f}" for mods, preference in preferred_mods),
        )

        # ── Difficulty profile ────────────────────────────────
        logger.debug("Exclude recent plays: %s", settings.exclude_recent_plays)
        difficulty_profile = get_player_difficulty_profiles(
            conn,
            player_id=settings.player_id,
            recency_half_life_days=settings.recency_half_life_days,
            ability_top_weight=settings.ability_top_weight,
            ability_recent_weight=settings.ability_recent_weight,
            ability_pp_weight=settings.ability_pp_weight,
            exclude_recent_plays=settings.exclude_recent_plays,
            cancel_event=cancel_event,
        )

        check_cancelled(cancel_event)
        logger.info(
            "Player %s difficulty profile: %s",
            settings.player_id,
            ", ".join(
                f"{feature}={difficulty_profile[f'{feature}_mean']:.3f}±{difficulty_profile[f'{feature}_std']:.3f}"
                for feature in ("star_rating", "ar", "od", "bpm", "pp")
                if f"{feature}_mean" in difficulty_profile
            ),
        )

        # ── Classifier preferences ─────────────────────────────
        category_preferences = get_player_category_preferences(
            conn,
            settings.player_id,
            recency_half_life_days=settings.recency_half_life_days,
            ability_top_weight=settings.ability_top_weight,
            ability_recent_weight=settings.ability_recent_weight,
            ability_pp_weight=settings.ability_pp_weight,
        )

        logger.info(
            "Player %s category preferences: %s",
            settings.player_id,
            ", ".join(
                f"{label}={float(probability) * 100:.2f}%" for label, probability in category_preferences.items()
            ),
        )

        check_cancelled(cancel_event)

        # ── Final ranking ──────────────────────────────────────
        ranked_variants = rank_variants(
            conn,
            similarity_index=similarity_index,
            mod_preferences=mod_preferences,
            difficulty_profile=difficulty_profile,
            difficulty_star_std_multiplier=settings.difficulty_star_std_multiplier,
            category_preferences=category_preferences,
            top_k=settings.limit,
            requested_mods=settings.mods,
            exact_mods=settings.exact_mods,
            excluded_mods=settings.excluded_mods,
            beatmap_status=settings.beatmap_status,
            ranges={
                name: (getattr(settings, f"min_{name}"), getattr(settings, f"max_{name}"))
                for name in RANGE_COLUMNS
            },
            recommendation_config=recommendation_config,
            difficulty_std_floors=settings.difficulty_std_floors,
            difficulty_feature_weights=settings.difficulty_feature_weights,
            cancel_event=cancel_event,
        )

        check_cancelled(cancel_event)

        # ── Output ─────────────────────────────────────────────
        logger.info("Player %s: %d recommendations", settings.player_id, len(ranked_variants))

        for i, variant in enumerate(ranked_variants[:10], 1):
            logger.debug(
                f"{i:2d}. "
                f"beatmap={variant['beatmap_id']}, "
                f"set={variant['beatmapset_id']}, "
                f"pp={variant['pp']}, "
                f"mods={variant['mods']}, "
                f"star={variant['star_rating']:.2f}, "
                f"bpm={variant['bpm']:.1f}, "
                f"AR={variant['ar']:.1f}, "
                f"OD={variant['od']:.1f}, "
                f"content={variant['content_similarity']:.4f}, "
                f"mod_pref={variant['mod_preference']:.4f}, "
                f"difficulty={variant['difficulty_score']:.4f}, "
                f"classifier={variant['classifier_score']:.4f}, "
                f"final={variant['final_score']:.4f}"
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
    sync_play_history=False,
):
    """
    Make the recommendations for settings.player_id in a thread, and return
    the ranked variants.

    For the logged-in player, fetch the scores with the token of the session.
    For another player, use the token of the app. If the scores were refreshed
    recently, do not fetch them.

    sync_play_history: True only for a player who uses the site or the bot
    (the logged-in player, or the linked account of a Discord user). For other
    players, the code does not fetch the full play history. Their top and
    recent scores are still excluded.
    """
    # If the full list of played beatmaps of the player is missing or old,
    # fetch it in the background. Then later requests exclude all the maps
    # that the player played.
    if sync_play_history:
        request_sync(settings.player_id)

    async with _recommendation_semaphore:
        check_cancelled(cancel_event)
        access_token = None

        if update_scores and scores_refreshed_recently(settings.player_id):
            logger.info("Player %s: scores refreshed recently, not fetching them again.", settings.player_id)
            update_scores = False

        if update_scores:
            access_token = (
                await get_access_token(session_id)
                if settings.player_id == session_player_id
                else await get_application_access_token()
            )

        check_cancelled(cancel_event)

        return await asyncio.to_thread(recommend_player_sync, settings, access_token, update_scores, cancel_event)
