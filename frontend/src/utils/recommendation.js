const DEFAULT_DIFFICULTY_STD_FLOORS = {
  star_rating: 0.35,
  ar: 0.5,
  od: 0.5,
  bpm: 15.0,
};

const DEFAULT_DIFFICULTY_FEATURE_WEIGHTS = {
  star_rating: 4.0,
  ar: 1.5,
  od: 1.0,
  bpm: 0.5,
};

// Mods excluded from recommendations until the user re-enables them.
export const DEFAULT_EXCLUDED_MODS = ["EZ", "HT", "FL"];

// The settings the UI can change, as POST /recommend's body. Everything else
// (the result limit, similarity weights, goal weights...) is left out, so the
// backend uses its own defaults (RecommendationSettings in
// beatmap_recommender/api/model.py).
export function createDefaultSettings() {
  return {
    player_id: null,
    goal: "balanced",
    beatmap_status: "all",
    mods: [],
    excluded_mods: [...DEFAULT_EXCLUDED_MODS],

    min_stars: null,
    max_stars: null,
    min_bpm: null,
    max_bpm: null,
    min_pp: null,
    max_pp: null,
    min_ar: null,
    max_ar: null,
    min_od: null,
    max_od: null,

    difficulty_std_floors: {
      ...DEFAULT_DIFFICULTY_STD_FLOORS,
    },

    difficulty_feature_weights: {
      ...DEFAULT_DIFFICULTY_FEATURE_WEIGHTS,
    },

    top_weight: 3.0,
    recent_weight: 1.0,
    pp_weight: 0.25,

    ability_top_weight: 1.0,
    ability_recent_weight: 2.0,
    ability_pp_weight: 0.05,
    recency_half_life_days: 30.0,

    pp_push_target_z: 2.5,
    pp_push_max_z: 5.0,
  };
}
