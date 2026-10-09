export const DEFAULT_DIFFICULTY_STD_FLOORS = {
  star_rating: 0.35,
  ar: 0.5,
  od: 0.5,
  bpm: 15.0,
};

export const DEFAULT_DIFFICULTY_FEATURE_WEIGHTS = {
  star_rating: 4.0,
  ar: 1.5,
  od: 1.0,
  bpm: 0.5,
};

export const DEFAULT_SIMILARITY_FEATURE_WEIGHTS = {
  star_rating: 3.0,
  bpm: 1.0,
  length_seconds: 0.5,
  object_count: 0.5,
  ar: 1.0,
  od: 1.0,
  circle_size: 1.0,
  pp_aim: 1.5,
  pp_speed: 1.5,
  pp_acc: 1.5,
};

export const DEFAULT_RECOMMENDATION_CONFIG = {
  balanced: {
    weights: {
      content: 0.5,
      mod_preference: 0.05,
      difficulty: 0.25,
      classifier: 0.2,
      pp_potential: 0.0,
    },
    sort_keys: [
      "final_score",
      "content_similarity",
      "difficulty_score",
      "classifier_score",
    ],
  },

  pp_potential: {
    weights: {
      content: 0.5,
      mod_preference: 0.05,
      difficulty: 0.1,
      classifier: 0.1,
      pp_potential: 0.25,
    },
    sort_keys: [
      "final_score",
      "content_similarity",
      "pp_potential",
      "difficulty_score",
      "classifier_score",
    ],
  },
};

// Mods excluded from recommendations until the user re-enables them.
export const DEFAULT_EXCLUDED_MODS = ["EZ", "HT", "FL"];

export function createDefaultSettings() {
  return {
    player_id: null,
    limit: 100000,
    goal: "balanced",
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

    similarity_feature_weights: {
      ...DEFAULT_SIMILARITY_FEATURE_WEIGHTS,
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
    feature_target_z: 1.0,
    feature_max_z: 3.0,

    recommendation_config: structuredClone(DEFAULT_RECOMMENDATION_CONFIG),
  };
}

export function normalizeSettings(settings) {
  return {
    ...settings,

    player_id: settings.player_id ? Number(settings.player_id) : null,

    limit: Number(settings.limit),

    mods: settings.mods ?? [],
    excluded_mods: settings.excluded_mods ?? [],

    min_stars: settings.min_stars ?? null,
    max_stars: settings.max_stars ?? null,
    min_bpm: settings.min_bpm ?? null,
    max_bpm: settings.max_bpm ?? null,
    min_pp: settings.min_pp ?? null,
    max_pp: settings.max_pp ?? null,
    min_ar: settings.min_ar ?? null,
    max_ar: settings.max_ar ?? null,
    min_od: settings.min_od ?? null,
    max_od: settings.max_od ?? null,

    difficulty_std_floors: {
      ...DEFAULT_DIFFICULTY_STD_FLOORS,
      ...(settings.difficulty_std_floors ?? {}),
    },

    difficulty_feature_weights: {
      ...DEFAULT_DIFFICULTY_FEATURE_WEIGHTS,
      ...(settings.difficulty_feature_weights ?? {}),
    },

    similarity_feature_weights: {
      ...DEFAULT_SIMILARITY_FEATURE_WEIGHTS,
      ...(settings.similarity_feature_weights ?? {}),
    },
  };
}
