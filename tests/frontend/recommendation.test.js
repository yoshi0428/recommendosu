// Tests for src/utils/recommendation.js.
//
// Vitest works much like pytest, with different spelling:
//   describe("group", () => {...})  groups related tests (like a test class)
//   it("does something", () => {})  one test (like `def test_...`)
//   expect(actual).toBe(expected)   an assertion (like `assert actual == expected`)
//
// toBe compares with ===, so it's for numbers, strings and booleans. For
// objects and arrays use toEqual, which compares contents, the way Python's
// == compares dicts and lists.

import { describe, expect, it } from "vitest";

import {
  DEFAULT_EXCLUDED_MODS,
  DEFAULT_RECOMMENDATION_CONFIG,
  DEFAULT_SIMILARITY_FEATURE_WEIGHTS,
  createDefaultSettings,
  normalizeSettings,
} from "@/utils/recommendation";

describe("createDefaultSettings", () => {
  it("starts with the default goal, status and mod exclusions", () => {
    const settings = createDefaultSettings();

    expect(settings.goal).toBe("balanced");
    expect(settings.beatmap_status).toBe("all");
    expect(settings.mods).toEqual([]);
    expect(settings.excluded_mods).toEqual(["EZ", "HT", "FL"]);
  });

  it("returns independent copies every time", () => {
    // The settings object is edited in place by the UI. If two calls shared
    // the same nested objects, editing one user's weights would silently
    // change the defaults for everyone afterwards.
    const first = createDefaultSettings();
    const second = createDefaultSettings();

    first.excluded_mods.push("DT");
    first.similarity_feature_weights.star_rating = 99;
    first.recommendation_config.balanced.weights.content = 0;

    expect(second.excluded_mods).toEqual(["EZ", "HT", "FL"]);
    expect(DEFAULT_EXCLUDED_MODS).toEqual(["EZ", "HT", "FL"]);
    expect(DEFAULT_SIMILARITY_FEATURE_WEIGHTS.star_rating).toBe(3.0);
    expect(DEFAULT_RECOMMENDATION_CONFIG.balanced.weights.content).toBe(0.5);
  });

  it("has goal weights that sum to 1", () => {
    for (const [goal, config] of Object.entries(DEFAULT_RECOMMENDATION_CONFIG)) {
      const total = Object.values(config.weights).reduce((a, b) => a + b, 0);
      // toBeCloseTo is the JavaScript version of pytest.approx.
      expect(total, goal).toBeCloseTo(1.0);
    }
  });
});

describe("normalizeSettings", () => {
  it("turns a typed-in player ID into a number", () => {
    // Input fields give strings; the API expects an integer.
    expect(normalizeSettings({ player_id: "12345", limit: "100" })).toMatchObject({
      player_id: 12345,
      limit: 100,
    });
  });

  it("sends null for an empty player ID", () => {
    // null tells the backend "use the logged-in player".
    expect(normalizeSettings({ player_id: "", limit: 1 }).player_id).toBeNull();
    expect(normalizeSettings({ player_id: null, limit: 1 }).player_id).toBeNull();
  });

  it("fills in missing lists and filters", () => {
    const normalized = normalizeSettings({ limit: 1 });

    expect(normalized.mods).toEqual([]);
    expect(normalized.excluded_mods).toEqual([]);
    expect(normalized.min_stars).toBeNull();
    expect(normalized.max_od).toBeNull();
  });

  it("keeps zero as a real filter value", () => {
    // `??` only replaces null/undefined. If this used `||`, a minimum of 0
    // would become null and the filter would silently disappear.
    expect(normalizeSettings({ limit: 1, min_stars: 0 }).min_stars).toBe(0);
  });

  it("merges partial weights over the defaults", () => {
    const normalized = normalizeSettings({
      limit: 1,
      similarity_feature_weights: { bpm: 2.5 },
    });

    expect(normalized.similarity_feature_weights).toEqual({
      ...DEFAULT_SIMILARITY_FEATURE_WEIGHTS,
      bpm: 2.5,
    });
  });

  it("passes other settings through unchanged", () => {
    // `toMatchObject` only checks the listed keys, ignoring the rest.
    const normalized = normalizeSettings({ limit: 1, goal: "pp_potential", exact_mods: true });
    expect(normalized).toMatchObject({ goal: "pp_potential", exact_mods: true });
  });

  it("produces exactly what the defaults would send", () => {
    // Normalizing an untouched default form shouldn't change anything except
    // the fields it's meant to coerce.
    const defaults = createDefaultSettings();
    expect(normalizeSettings(defaults)).toEqual(defaults);
  });
});
