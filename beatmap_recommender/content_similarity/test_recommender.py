import sqlite3

from beatmap_recommender.content_similarity.core_modules.mod_preferences import canonicalize_mods
from osu_api_client import OsuAPIClient
from beatmap_recommender.content_similarity.core_modules.score_collector import update_player_scores
from beatmap_recommender.content_similarity.core_modules.content_similarity import build_seed_similarity_index
from beatmap_recommender.content_similarity.core_modules.mod_preferences import get_preferred_mods
from beatmap_recommender.content_similarity.core_modules.variant_ranking import get_player_difficulty_profile, rank_variants
from beatmap_recommender.content_similarity.core_modules.cnn_xgboost_influence import get_player_category_preferences
from pathlib import Path

# ============================================================
# Configuration
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "beatmap_recommender/test_everything.db"

NUM_RECOMMENDATIONS = 100
NEIGHBORS_K = 50000
SCORE_LIMIT = 1000

PLAYER_IDS = [
    8140599,
    10961031,
    15054306,
    7562902,
    35269285
]
# PLAYER_ID = PLAYER_IDS[1]
PLAYER_ID = 123456

REQUESTED_MODS = canonicalize_mods([])

MIN_STARS = None
MAX_STARS = None
MIN_BPM = None
MAX_BPM = None
MIN_PP = None
MAX_PP = None
MIN_AR = None
MAX_AR = None
MIN_OD = None
MAX_OD = None

# MIN_STARS = 6.5
# MAX_STARS = 7.5
# MIN_BPM = 200
# MAX_BPM = 300
# MIN_PP = 450
# MAX_PP = 550
# MIN_AR = 9.0
# MAX_AR = 11.0
# MIN_OD = 9.0
# MAX_OD = 11.0

RECOMMENDATION_GOAL = "NM1_to_5"

CUSTOM_CONFIG = {
    "weights": {
            "content": 0.55,
            "mod_preference": 0.05,
            "difficulty": 0.25,
            "classifier": 0.15,
            "pp_potential": 0.00,
    },
    "sort_keys": (
        # all possible options here
        "final_score",
        "classifier_score",
        "difficulty_score",
        "content_similarity",
        "pp_potential",
    ),
}

# Final score: content similarity + mod preference + difficulty suitability
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

    "pp_push": {
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

    "custom": CUSTOM_CONFIG
}

# Prevent a player's difficulty distribution from becoming unrealistically narrow when they have many very similar scores.
DIFFICULTY_STD_FLOORS = {
    "star_rating": 0.35,
    "ar": 0.50,
    "od": 0.50,
    "bpm": 15.0,
}

# Difficulty feature weights.
# Star rating is the primary difficulty signal.
# AR / OD / BPM provide additional information about the actual variant.
# All features are standardized using the player's own distribution before these weights are applied, so the raw units do not matter.
DIFFICULTY_FEATURE_WEIGHTS = {
    "star_rating": 4.0,
    "ar": 1.5,
    "od": 1.0,
    "bpm": 0.5,
}

FEATURE_WEIGHTS = {
    "star_rating": 3.0,
    "bpm": 1.0,
    "length_seconds": 0.5,
    "object_count": 0.5,
    "ar": 1.5,
    "od": 1.5,
    "circle_size": 1.0,
}

TOP_WEIGHT = 3.0
RECENT_WEIGHT = 1.0

# Controls how much PP influences the preference.
# 0.0 = ignore PP, 1.0 = full PP influence
PP_WEIGHT = 0.25

# Ability profile weighting
# 1 & 2. Recent scores should have substantially more influence on the player's current ability than old top scores.
# 3. Small PP influence so stronger performances contribute slightly more.
# 4. A score loses half of its recency weight every N days.
ABILITY_TOP_WEIGHT = 1.0
ABILITY_RECENT_WEIGHT = 4.0
ABILITY_PP_WEIGHT = 0.10
RECENCY_HALF_LIFE_DAYS = 30.0

# 1. Only used by the pp_push goal.
# 2. Controls how far above the player's demonstrated difficulty we consider a candidate to be a reasonable PP push.
# 3. Prevents extremely difficult maps from receiving high PP-potential scores merely because their raw PP is high.
PP_PUSH_TARGET_Z = 0.75
PP_PUSH_MAX_Z = 2.0

def main():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    api = OsuAPIClient()

    # --------------------------------------------------------
    # Update player scores
    # --------------------------------------------------------
    print(f"Updating Player {PLAYER_ID} top & recent scores...")
    update_player_scores(
        conn,
        api,
        PLAYER_ID,
        limit=50
    )
    print(f"Finished updating Player {PLAYER_ID} top & recent scores!")
    print(f"\nBuilding recommendations for player {PLAYER_ID}...")

    # --------------------------------------------------------
    # Build content similarity
    # --------------------------------------------------------
    similarity_index = build_seed_similarity_index(
        conn,
        player_id=PLAYER_ID,
        top_k=NEIGHBORS_K,
        batch_size=1024,
        feature_weights=FEATURE_WEIGHTS,
    )

    print(f"Player {PLAYER_ID}: {len(similarity_index)} seed maps with similarity results.")

    if not similarity_index:
        print("No similarity results found.")
        conn.close()
        return

    # --------------------------------------------------------
    # Inspect one similarity result
    # --------------------------------------------------------
    seed_beatmap_id = next(iter(similarity_index))
    similar_maps = similarity_index[seed_beatmap_id][:10]
    print(f"\nSeed beatmap {seed_beatmap_id}:")

    for similar_beatmap_id, similarity in similar_maps:
        print(f"  {similar_beatmap_id}: {similarity:.4f}")

    # --------------------------------------------------------
    # Fetch feature data for seed + similar maps
    # Similarity operates on base beatmaps, so inspect their NM variants.
    # --------------------------------------------------------
    beatmap_ids = [seed_beatmap_id] + [beatmap_id for beatmap_id, _ in similar_maps]
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
            f"beatmap={row[1]}, "
            f"variant={row[0]}, "
            f"mods={row[2]}, "
            f"star={row[3]:.2f}, "
            f"bpm={row[4]:.1f}, "
            f"length={row[5]:.1f}s, "
            f"objects={row[6]}, "
            f"AR={row[7]:.1f}, "
            f"OD={row[8]:.1f}, "
            f"CS={row[9]:.1f}"
        )

    # --------------------------------------------------------
    # Get player mod preferences
    # --------------------------------------------------------
    preferred_mods = get_preferred_mods(
        conn,
        player_id=PLAYER_ID,
        top_weight=TOP_WEIGHT,
        recent_weight=RECENT_WEIGHT,
        pp_weight=PP_WEIGHT,
    )
    print(f"\nPlayer {PLAYER_ID} mod preferences:")

    for mods, preference in preferred_mods:
        print(f"  {mods}: {preference:.3f}")

    mod_preferences = dict(preferred_mods)

    # --------------------------------------------------------
    # Get player difficulty profile
    # --------------------------------------------------------
    difficulty_profile = get_player_difficulty_profile(
        conn,
        player_id=PLAYER_ID, difficulty_std_floors=DIFFICULTY_STD_FLOORS,
        recency_half_life_days=RECENCY_HALF_LIFE_DAYS,
        ability_top_weight=ABILITY_TOP_WEIGHT,
        ability_recent_weight=ABILITY_RECENT_WEIGHT,
        ability_pp_weight=ABILITY_PP_WEIGHT,
    )

    print(f"\nPlayer {PLAYER_ID} difficulty profile:")

    for feature in ("star_rating", "ar", "od", "bpm",):
        mean = difficulty_profile.get(f"{feature}_mean")
        std = difficulty_profile.get(f"{feature}_std")
        if mean is None or std is None:
            continue

        print(f"  {feature}: mean={mean:.3f}, std={std:.3f}")

    # --------------------------------------------------------
    # Rank variants
    # --------------------------------------------------------
    #
    # IMPORTANT:
    # rank_variants() now receives the entire similarity index, not one seed's candidate list.
    #
    # It:
    #
    #   1. Finds the best content similarity per base map
    #   2. Loads all available variants
    #   3. Scores mod preference
    #   4. Scores difficulty match
    #   5. Selects the best variant for each base map
    #   6. Globally ranks the results
    #
    # --------------------------------------------------------
    print()
    category_preferences = get_player_category_preferences(
        conn, PLAYER_ID,
        recency_half_life_days=RECENCY_HALF_LIFE_DAYS,
        ability_top_weight=ABILITY_TOP_WEIGHT,
        ability_recent_weight=ABILITY_RECENT_WEIGHT,
        ability_pp_weight=ABILITY_PP_WEIGHT,
    )
    for label, probability in category_preferences.items():
        print(f"{label}: {float(probability) * 100:.2f}%")

    ranked_variants = rank_variants(
        conn,
        similarity_index=similarity_index,
        mod_preferences=mod_preferences,
        difficulty_profile=difficulty_profile,
        category_preferences=category_preferences,
        top_k=NUM_RECOMMENDATIONS,
        requested_mods=REQUESTED_MODS,
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
        recommendation_goal=RECOMMENDATION_GOAL,
        recommendation_config=RECOMMENDATION_CONFIG,
        difficulty_std_floors=DIFFICULTY_STD_FLOORS,
        difficulty_feature_weights=DIFFICULTY_FEATURE_WEIGHTS,
        pp_push_target_z=PP_PUSH_TARGET_Z,
        pp_push_max_z=PP_PUSH_MAX_Z,
    )

    # --------------------------------------------------------
    # Display final recommendations
    # --------------------------------------------------------
    print(f"\nRecommendation goal: {RECOMMENDATION_GOAL}")
    print(f"\nTop {len(ranked_variants)} recommendations:")

    for i, variant in enumerate(ranked_variants, start=1):
        print(
            f"{i:2d}. "
            f"beatmap={variant['beatmap_id']}, "
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

    conn.close()


if __name__ == "__main__":
    main()