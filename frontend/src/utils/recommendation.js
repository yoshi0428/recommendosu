export const DEFAULT_DIFFICULTY_STD_FLOORS = {
  star_rating: 0.35,
  ar: 0.50,
  od: 0.50,
  bpm: 15.0,
}

export const DEFAULT_DIFFICULTY_FEATURE_WEIGHTS = {
  star_rating: 4.0,
  ar: 1.5,
  od: 1.0,
  bpm: 0.5,
}

export const DEFAULT_FEATURE_WEIGHTS = {
  star_rating: 3.0,
  bpm: 1.0,
  length_seconds: 0.5,
  object_count: 0.5,
  ar: 1.5,
  od: 1.5,
  circle_size: 1.0,
}

export const DEFAULT_RECOMMENDATION_CONFIG = {
  balanced: {
    weights: {
      content: 0.65,
      mod_preference: 0.05,
      difficulty: 0.30,
      classifier: 0.00,
      pp_potential: 0.00,
    },
    sort_keys: [
      'final_score',
      'difficulty_score',
      'content_similarity',
    ],
  },

  pp_potential: {
    weights: {
      content: 0.45,
      mod_preference: 0.05,
      difficulty: 0.25,
      classifier: 0.00,
      pp_potential: 0.25,
    },
    sort_keys: [
      'final_score',
      'pp_potential',
      'difficulty_score',
      'content_similarity',
    ],
  },

  NM1_to_5: {
    weights: {
      content: 0.55,
      mod_preference: 0.05,
      difficulty: 0.25,
      classifier: 0.15,
      pp_potential: 0.00,
    },
    sort_keys: [
      'final_score',
      'classifier_score',
      'difficulty_score',
      'content_similarity',
    ],
  },
}

export function createDefaultSettings() {
  return {
    player_id: null,
    limit: 100,
    goal: 'balanced',
    mods: [],

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

    feature_weights: {
      ...DEFAULT_FEATURE_WEIGHTS,
    },

    top_weight: 3.0,
    recent_weight: 1.0,
    pp_weight: 0.25,

    ability_top_weight: 1.0,
    ability_recent_weight: 4.0,
    ability_pp_weight: 0.10,
    recency_half_life_days: 30.0,

    pp_push_target_z: 0.75,
    pp_push_max_z: 2.0,

    recommendation_config: structuredClone(
      DEFAULT_RECOMMENDATION_CONFIG
    ),

  }
}

export function normalizeSettings(settings) {
  return {
    ...settings,

    player_id: settings.player_id
      ? Number(settings.player_id)
      : null,

    limit: Number(settings.limit),

    mods: settings.mods ?? [],

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
      ...settings.difficulty_std_floors,
    },

    difficulty_feature_weights: {
      ...settings.difficulty_feature_weights,
    },

    feature_weights: {
      ...settings.feature_weights,
    },
  }
}
