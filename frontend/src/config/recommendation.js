export const DEFAULTS = {
  limit: 100,
  goal: 'balanced',
  mods: [],

  min_stars: '',
  max_stars: '',
  min_bpm: '',
  max_bpm: '',
  min_pp: '',
  max_pp: '',
  min_ar: '',
  max_ar: '',
  min_od: '',
  max_od: '',

  difficulty_std_floors: {
    star_rating: 0.35,
    ar: 0.50,
    od: 0.50,
    bpm: 15.0,
  },

  difficulty_feature_weights: {
    star_rating: 4.0,
    ar: 1.5,
    od: 1.0,
    bpm: 0.5,
  },

  feature_weights: {
    star_rating: 3.0,
    bpm: 1.0,
    length_seconds: 0.5,
    object_count: 0.5,
    ar: 1.5,
    od: 1.5,
    circle_size: 1.0,
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
  },

  pp_potential: {
    weights: {
      content: 0.45,
      mod_preference: 0.05,
      difficulty: 0.25,
      classifier: 0.00,
      pp_potential: 0.25,
    },
  },

  NM1_to_5: {
    weights: {
      content: 0.55,
      mod_preference: 0.05,
      difficulty: 0.25,
      classifier: 0.15,
      pp_potential: 0.00,
    },
  },
}

export const MOD_OPTIONS = [
  'NM',
  'HD',
  'HR',
  'DT',
  'EZ',
  'HT',
  'FL',
  'HDHR',
  'HDDT',
  'HDHRDT',
  'HRDT',
  'EZDT',
  'EZHD',
  'EZHT',
  'HDHT',
  'HRHT',
  'HDHRFL',
  'HDFL',
  'HRFL',
  'DTFL',
]
