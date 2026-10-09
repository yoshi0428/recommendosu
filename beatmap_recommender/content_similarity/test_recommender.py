from pathlib import Path

from beatmap_recommender.content_similarity.core_modules.cnn_xgboost_influence import (
    get_player_category_preferences,
)
from beatmap_recommender.content_similarity.core_modules.content_similarity import (
    build_seed_similarity_index,
)
from beatmap_recommender.content_similarity.core_modules.mod_preferences import (
    get_preferred_mods,
)
from beatmap_recommender.content_similarity.core_modules.score_collector import (
    update_player_scores,
)
from beatmap_recommender.content_similarity.core_modules.variant_ranking import (
    get_player_difficulty_profiles,
    rank_variants,
)
from beatmap_recommender.database import connect_memory_db, load_memory_db
from beatmap_recommender.recommender_db_setup.osu_api_client import OsuAPIClient

# ── Configuration ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Loaded into memory; fetched scores are written back to this file.
LOCAL_DB_PATH = PROJECT_ROOT / "beatmap_recommender/recommender.local.db"

NUM_RECOMMENDATIONS = 100
NEIGHBORS_K = 147_152
BATCH_SIZE = 16_384
SCORE_LIMIT = 1000

PLAYER_IDS = [
    8140599,
    10961031,
    15054306,
    7562902,
    35269285,
]
PLAYER_ID = PLAYER_IDS[3]

RECOMMENDATION_GOAL = "balanced"


# ── Mod filters ────────────────────────────────────────────────

# None = all mods.
# Otherwise, selected mods are the allowed components.
#
# ["NM"]          → NM
# ["HD"]          → HD
# ["HD", "HR"]    → HD, HR, HDHR
# ["HD", "HR", "DT"]
#                   → HD, HR, DT, HDHR, HDDT, HRDT, HDHRDT

REQUESTED_MODS = []
EXCLUDED_MODS = ["EZ", "HT", "FL"]


# ── Candidate filters ──────────────────────────────────────────

MIN_STARS = None
MAX_STARS = None

MIN_BPM = MAX_BPM = None
MIN_PP = MAX_PP = None
MIN_AR = MAX_AR = None
MIN_OD = MAX_OD = None
MIN_LENGTH = MAX_LENGTH = None
MIN_COMBO = MAX_COMBO = None
MIN_CS = MAX_CS = None

# Example:
# MIN_STARS, MAX_STARS = 6.5, 7.5
# MIN_BPM, MAX_BPM = 200, 300
# MIN_PP, MAX_PP = 450, 550
# MIN_AR, MAX_AR = 9.0, 11.0
# MIN_OD, MAX_OD = 9.0, 11.0


# ── Recommendation configurations ─────────────────────────────
RECOMMENDATION_CONFIG = {
    "balanced": {
        "weights": {
            "content": 0.50,
            "mod_preference": 0.05,
            "difficulty": 0.25,
            "classifier": 0.20,
            "pp_potential": 0.00,
        },
        "sort_keys": (
            "final_score",
            "content_similarity",
            "difficulty_score",
            "classifier_score",
        ),
    },
    "pp_potential": {
        "weights": {
            "content": 0.50,
            "mod_preference": 0.05,
            "difficulty": 0.10,
            "classifier": 0.10,
            "pp_potential": 0.25,
        },
        "sort_keys": (
            "final_score",
            "content_similarity",
            "pp_potential",
            "difficulty_score",
            "classifier_score",
        ),
    },
}

# ── Difficulty ─────────────────────────────────────────────────

DIFFICULTY_STD_FLOORS = {
    "star_rating": 0.35,
    "ar": 0.50,
    "od": 0.50,
    "bpm": 15.0,
}

DIFFICULTY_FEATURE_WEIGHTS = {
    "star_rating": 4.0,
    "ar": 1.5,
    "od": 1.0,
    "bpm": 0.5,
}

DIFFICULTY_STAR_STD_MULTIPLIER = 1.00


# ── Content similarity ─────────────────────────────────────────

SIMILARITY_FEATURE_WEIGHTS = {
    "star_rating": 3.0,
    "bpm": 1.0,
    "length_seconds": 0.5,
    "object_count": 0.5,
    "ar": 1.0,
    "od": 1.0,
    "circle_size": 1.0,
    "pp_aim": 1.5,
    "pp_speed": 1.5,
    "pp_acc": 1.5,
}


# ── Mod preference ─────────────────────────────────────────────

TOP_WEIGHT = 3.0
RECENT_WEIGHT = 1.0
PP_WEIGHT = 0.25


# ── Ability profile ────────────────────────────────────────────

ABILITY_TOP_WEIGHT = 1.0
ABILITY_RECENT_WEIGHT = 2.0
ABILITY_PP_WEIGHT = 0.05
RECENCY_HALF_LIFE_DAYS = 30.0


# ── PP push ────────────────────────────────────────────────────

PP_PUSH_TARGET_Z = 0.75
PP_PUSH_MAX_Z = 2.0
FEATURE_TARGET_Z = 1.00
FEATURE_MAX_Z = 3.00


# ── Play filtering ─────────────────────────────────────────────

EXCLUDE_RECENT_PLAYS = True
EXCLUDE_ALREADY_PLAYED = True


def main():
    if RECOMMENDATION_GOAL not in RECOMMENDATION_CONFIG:
        raise ValueError(f"Unknown recommendation goal: {RECOMMENDATION_GOAL}")

    config = RECOMMENDATION_CONFIG[RECOMMENDATION_GOAL]
    classifier_weight = config["weights"]["classifier"]

    load_memory_db(LOCAL_DB_PATH)
    conn = connect_memory_db()

    try:
        api = OsuAPIClient()

        # ── Update scores ──────────────────────────────────────
        print(f"Updating Player {PLAYER_ID} top & recent scores...")
        update_player_scores(
            conn,
            api,
            PLAYER_ID,
            limit=SCORE_LIMIT,
        )
        print(f"Finished updating Player {PLAYER_ID} top & recent scores!")
        print(f"\nBuilding recommendations for player {PLAYER_ID}...")

        # ── Content similarity ────────────────────────────────
        print(SIMILARITY_FEATURE_WEIGHTS)
        similarity_index = build_seed_similarity_index(
            conn,
            player_id=PLAYER_ID,
            top_k=NEIGHBORS_K,
            batch_size=BATCH_SIZE,
            similarity_feature_weights=SIMILARITY_FEATURE_WEIGHTS,
            exclude_already_played=EXCLUDE_ALREADY_PLAYED,
        )

        print(
            f"Player {PLAYER_ID}: {len(similarity_index)} candidate maps with similarity results."
        )

        if not similarity_index:
            print("No similarity results found.")
            return

        most_similar = sorted(
            similarity_index.items(), key=lambda item: item[1], reverse=True
        )[:10]

        print("\nMost similar candidates:")
        for beatmap_id, similarity in most_similar:
            print(f"  {beatmap_id}: {similarity:.4f}")

        # ── Inspect map features ──────────────────────────────

        beatmap_ids = [beatmap_id for beatmap_id, _ in most_similar]
        similarity_rank = {beatmap_id: rank for rank, beatmap_id in enumerate(beatmap_ids)}
        placeholders = ",".join("?" for _ in beatmap_ids)

        rows = conn.execute(
            f"""
            SELECT
                bv.variant_id,
                bv.beatmap_id,
                bv.mods,
                bv.star_rating,
                bv.bpm,
                bv.length_seconds,
                bv.object_count,
                bv.ar,
                bv.od,
                bv.circle_size
            FROM beatmap_variants AS bv
            WHERE bv.mods = 'NM'
              AND bv.beatmap_id IN ({placeholders})
            """,
            beatmap_ids,
        ).fetchall()
        rows.sort(key=lambda row: similarity_rank[str(row[1])])

        print("\nNM map features (most similar first):")
        for row in rows:
            print(
                f"beatmap={row[1]}, variant={row[0]}, mods={row[2]}, "
                f"star={row[3]:.2f}, bpm={row[4]:.1f}, "
                f"length={row[5]:.1f}s, objects={row[6]}, "
                f"AR={row[7]:.1f}, OD={row[8]:.1f}, CS={row[9]:.1f}"
            )

        # ── Mod preferences ───────────────────────────────────
        preferred_mods = get_preferred_mods(
            conn,
            player_id=PLAYER_ID,
            top_weight=TOP_WEIGHT,
            recent_weight=RECENT_WEIGHT,
            pp_weight=PP_WEIGHT,
        )
        mod_preferences = dict(preferred_mods)

        print(f"\nPlayer {PLAYER_ID} mod preferences:")
        for mods, preference in preferred_mods:
            print(f"  {mods}: {preference:.3f}")

        # ── Difficulty profiles ───────────────────────────────
        difficulty_profile = get_player_difficulty_profiles(
            conn,
            player_id=PLAYER_ID,
            recency_half_life_days=RECENCY_HALF_LIFE_DAYS,
            ability_top_weight=ABILITY_TOP_WEIGHT,
            ability_recent_weight=ABILITY_RECENT_WEIGHT,
            ability_pp_weight=ABILITY_PP_WEIGHT,
            exclude_recent_plays=EXCLUDE_RECENT_PLAYS,
        )

        print("\nGLOBAL DIFFICULTY PROFILE:")
        print(difficulty_profile)

        # ── Classifier preferences ─────────────────────────────

        if classifier_weight <= 0:
            category_preferences = {}
        else:
            category_preferences = get_player_category_preferences(
                conn,
                PLAYER_ID,
                recency_half_life_days=RECENCY_HALF_LIFE_DAYS,
                ability_top_weight=ABILITY_TOP_WEIGHT,
                ability_recent_weight=ABILITY_RECENT_WEIGHT,
                ability_pp_weight=ABILITY_PP_WEIGHT,
            )

            print()
            for label, probability in category_preferences.items():
                print(f"{label}: {float(probability) * 100:.2f}%")

        # ── Final ranking ─────────────────────────────────────

        ranked_variants = rank_variants(
            conn,
            similarity_index=similarity_index,
            mod_preferences=mod_preferences,
            difficulty_profile=difficulty_profile,
            difficulty_star_std_multiplier=DIFFICULTY_STAR_STD_MULTIPLIER,
            category_preferences=category_preferences,
            top_k=NUM_RECOMMENDATIONS,
            requested_mods=(
                {mod.strip().upper() for mod in REQUESTED_MODS}
                if REQUESTED_MODS
                else None
            ),
            excluded_mods={mod.strip().upper() for mod in EXCLUDED_MODS},
            min_stars=MIN_STARS,
            max_stars=MAX_STARS,
            min_bpm=MIN_BPM,
            max_bpm=MAX_BPM,
            min_pp=MIN_PP,
            max_pp=MAX_PP,
            min_ar=MIN_AR,
            max_ar=MAX_AR,
            min_od=MIN_OD,
            max_od=MAX_OD,
            min_length=MIN_LENGTH,
            max_length=MAX_LENGTH,
            min_combo=MIN_COMBO,
            max_combo=MAX_COMBO,
            min_cs=MIN_CS,
            max_cs=MAX_CS,
            recommendation_goal=RECOMMENDATION_GOAL,
            recommendation_config=RECOMMENDATION_CONFIG,
            difficulty_std_floors=DIFFICULTY_STD_FLOORS,
            difficulty_feature_weights=DIFFICULTY_FEATURE_WEIGHTS,
            pp_push_target_z=PP_PUSH_TARGET_Z,
            pp_push_max_z=PP_PUSH_MAX_Z,
            feature_target_z=FEATURE_TARGET_Z,
            feature_max_z=FEATURE_MAX_Z,
        )

        # ── Results ────────────────────────────────────────────

        print("\nTOP RECOMMENDATIONS:")

        for variant in ranked_variants[:20]:
            print(
                f"{variant['mods']:>8} "
                f"{variant['star_rating']:5.2f}★ "
                f"difficulty="
                f"{variant.get('difficulty_score', 0.0):.6f} "
                f"final="
                f"{variant.get('final_score', 0.0):.6f} "
                f"{variant['artist']} - {variant['title']}"
            )

        if ranked_variants:
            print("\nVARIANT KEYS:")
            print(ranked_variants[0].keys())

        print(f"\nRecommendation goal: {RECOMMENDATION_GOAL}")
        print(f"\nTop {len(ranked_variants)} recommendations:")
        for i, variant in enumerate(ranked_variants, 1):
            print(
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
                f"pp_potential={variant['pp_potential']:.4f}, "
                f"final={variant['final_score']:.4f}"
            )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
