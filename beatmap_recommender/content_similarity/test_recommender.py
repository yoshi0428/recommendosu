import os
import sqlite3
from pathlib import Path
from beatmap_recommender.recommender_db_setup.osu_api_client import OsuAPIClient
from beatmap_recommender.content_similarity.core_modules.score_collector import (
    update_player_scores,
)
from beatmap_recommender.content_similarity.core_modules.content_similarity import (
    build_seed_similarity_index,
)
from beatmap_recommender.content_similarity.core_modules.mod_preferences import (
    get_preferred_mods,
)
from beatmap_recommender.content_similarity.core_modules.variant_ranking import (
    get_player_difficulty_profiles,
    rank_variants,
)
from beatmap_recommender.content_similarity.core_modules.cnn_xgboost_influence import (
    get_player_category_preferences,
)


# ── Configuration ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DB_PATH = Path(
    os.getenv(
        "DB_PATH",
        PROJECT_ROOT / "beatmap_recommender/recommender.local.db",
    )
)

NUM_RECOMMENDATIONS = 100
NEIGHBORS_K = 20_000
BATCH_SIZE = 16_384
SCORE_LIMIT = 1000
WORKERS = -1

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

REQUESTED_MODS = ["NM"]
EXCLUDED_MODS = ["EZ", "HT", "FL", "HD"]


# ── Candidate filters ──────────────────────────────────────────

MIN_STARS = MAX_STARS = None
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
            "content": 0.65,
            "mod_preference": 0.05,
            "difficulty": 0.30,
            "classifier": 0.00,
            "pp_potential": 0.00,
        },
        "sort_keys": (
            "final_score",
            "difficulty_score",
            "content_similarity",
        ),
    },

    "pp_potential": {
        "weights": {
            "content": 0.45,
            "mod_preference": 0.05,
            "difficulty": 0.25,
            "classifier": 0.00,
            "pp_potential": 0.25,
        },
        "sort_keys": (
            "final_score",
            "pp_potential",
            "difficulty_score",
            "content_similarity",
        ),
    },

    "NM1_to_5": {
        "weights": {
            "content": 0.55,
            "mod_preference": 0.05,
            "difficulty": 0.25,
            "classifier": 0.15,
            "pp_potential": 0.00,
        },
        "sort_keys": (
            "final_score",
            "classifier_score",
            "difficulty_score",
            "content_similarity",
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

DIFFICULTY_STAR_STD_MULTIPLIER = 0.50

MIN_PROFILE_PLAYS = 5


# ── Content similarity ─────────────────────────────────────────

FEATURE_WEIGHTS = {
    "star_rating": 3.0,
    "bpm": 1.0,
    "length_seconds": 0.5,
    "object_count": 0.5,
    "ar": 1.5,
    "od": 1.5,
    "circle_size": 1.0,
}


# ── Mod preference ─────────────────────────────────────────────

TOP_WEIGHT = 3.0
RECENT_WEIGHT = 1.0
PP_WEIGHT = 0.25


# ── Ability profile ────────────────────────────────────────────

ABILITY_TOP_WEIGHT = 1.0
ABILITY_RECENT_WEIGHT = 4.0
ABILITY_PP_WEIGHT = 0.10
RECENCY_HALF_LIFE_DAYS = 30.0


# ── PP push ────────────────────────────────────────────────────

PP_PUSH_TARGET_Z = 0.75
PP_PUSH_MAX_Z = 2.0


# ── Play filtering ─────────────────────────────────────────────

EXCLUDE_RECENT_PLAYS = True
EXCLUDE_ALREADY_PLAYED = True


def main():
    if RECOMMENDATION_GOAL not in RECOMMENDATION_CONFIG:
        raise ValueError(
            f"Unknown recommendation goal: {RECOMMENDATION_GOAL}"
        )

    config = RECOMMENDATION_CONFIG[RECOMMENDATION_GOAL]
    classifier_weight = config["weights"]["classifier"]

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

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
        print(
            f"Finished updating Player {PLAYER_ID} "
            "top & recent scores!"
        )

        print(
            f"\nBuilding recommendations for player {PLAYER_ID}..."
        )

        # ── Content similarity ────────────────────────────────

        similarity_index = build_seed_similarity_index(
            conn,
            player_id=PLAYER_ID,
            top_k=NEIGHBORS_K,
            batch_size=BATCH_SIZE,
            feature_weights=FEATURE_WEIGHTS,
            workers=WORKERS,
            exclude_already_played=EXCLUDE_ALREADY_PLAYED,
        )

        print(
            f"Player {PLAYER_ID}: "
            f"{len(similarity_index)} seed maps with similarity results."
        )

        if not similarity_index:
            print("No similarity results found.")
            return

        seed_beatmap_id = next(iter(similarity_index))
        similar_maps = similarity_index[seed_beatmap_id][:10]

        print(f"\nSeed beatmap {seed_beatmap_id}:")
        for beatmap_id, similarity in similar_maps:
            print(f"  {beatmap_id}: {similarity:.4f}")

        # ── Inspect map features ──────────────────────────────

        beatmap_ids = [
            seed_beatmap_id,
            *(beatmap_id for beatmap_id, _ in similar_maps),
        ]
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
            ORDER BY
                CASE bv.beatmap_id
                    WHEN ? THEN 0
                    ELSE 1
                END,
                bv.beatmap_id
            """,
            beatmap_ids + [seed_beatmap_id],
        ).fetchall()

        print("\nNM map features:")
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
        difficulty_profile, _ = get_player_difficulty_profiles(
            conn,
            player_id=PLAYER_ID,
            difficulty_std_floors=DIFFICULTY_STD_FLOORS,
            recency_half_life_days=RECENCY_HALF_LIFE_DAYS,
            ability_top_weight=ABILITY_TOP_WEIGHT,
            ability_recent_weight=ABILITY_RECENT_WEIGHT,
            ability_pp_weight=ABILITY_PP_WEIGHT,
            exclude_recent_plays=EXCLUDE_RECENT_PLAYS,
            min_profile_plays=MIN_PROFILE_PLAYS,
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
                print(
                    f"{label}: "
                    f"{float(probability) * 100:.2f}%"
                )

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
            excluded_mods={
                mod.strip().upper()
                for mod in EXCLUDED_MODS
            },
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

    finally:
        conn.close()


if __name__ == "__main__":
    main()