from copy import deepcopy
from pydantic import BaseModel, Field

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
PP_WEIGHT = 0.25

ABILITY_TOP_WEIGHT = 1.0
ABILITY_RECENT_WEIGHT = 4.0
ABILITY_PP_WEIGHT = 0.10
RECENCY_HALF_LIFE_DAYS = 30.0

PP_PUSH_TARGET_Z = 0.75
PP_PUSH_MAX_Z = 2.0

DIFFICULTY_STAR_STD_MULTIPLIER = 0.50

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
            "content": 0.50,
            "mod_preference": 0.05,
            "difficulty": 0.25,
            "classifier": 0.20,
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


class RecommendationSettings(BaseModel):
    # ── Basic recommendation options ───────────────────────────
    player_id: int | None = None

    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
    )

    goal: str = "balanced"

    mods: list[str] | None = Field(
        default=None,
    )

    excluded_mods: list[str] | None = Field(
        default=None,
    )

    exclude_already_played: bool = Field(
        default=True,
    )

    exclude_recent_plays: bool = Field(
        default=False,
    )

    # ── Difficulty constraint ──────────────────────────────────
    difficulty_star_std_multiplier: float = Field(
        default=DIFFICULTY_STAR_STD_MULTIPLIER,
        ge=0.0,
    )

    # ── Candidate filters ──────────────────────────────────────
    min_stars: float | None = None
    max_stars: float | None = None

    min_bpm: float | None = None
    max_bpm: float | None = None

    min_pp: float | None = None
    max_pp: float | None = None

    min_ar: float | None = None
    max_ar: float | None = None

    min_od: float | None = None
    max_od: float | None = None

    min_length: float | None = None
    max_length: float | None = None

    min_combo: float | None = None
    max_combo: float | None = None

    min_cs: float | None = None
    max_cs: float | None = None

    # ── Difficulty profile ─────────────────────────────────────
    difficulty_std_floors: dict[str, float] = Field(
        default_factory=lambda: DIFFICULTY_STD_FLOORS.copy()
    )

    difficulty_feature_weights: dict[str, float] = Field(
        default_factory=lambda: DIFFICULTY_FEATURE_WEIGHTS.copy()
    )

    # ── Content similarity ─────────────────────────────────────
    feature_weights: dict[str, float] = Field(
        default_factory=lambda: FEATURE_WEIGHTS.copy()
    )

    # ── Mod preferences ───────────────────────────────────────
    top_weight: float = TOP_WEIGHT
    recent_weight: float = RECENT_WEIGHT
    pp_weight: float = PP_WEIGHT

    # ── Ability profile ────────────────────────────────────────
    ability_top_weight: float = ABILITY_TOP_WEIGHT
    ability_recent_weight: float = ABILITY_RECENT_WEIGHT
    ability_pp_weight: float = ABILITY_PP_WEIGHT
    recency_half_life_days: float = RECENCY_HALF_LIFE_DAYS

    # ── PP push ────────────────────────────────────────────────
    pp_push_target_z: float = PP_PUSH_TARGET_Z
    pp_push_max_z: float = PP_PUSH_MAX_Z

    # ── Recommendation scoring ────────────────────────────────
    recommendation_config: dict = Field(
        default_factory=lambda: deepcopy(RECOMMENDATION_CONFIG)
    )