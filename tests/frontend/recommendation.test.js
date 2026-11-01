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

import { DEFAULT_EXCLUDED_MODS, createDefaultSettings } from "@/utils/recommendation";

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
    first.difficulty_std_floors.star_rating = 99;
    first.difficulty_feature_weights.ar = 0;

    expect(second.excluded_mods).toEqual(["EZ", "HT", "FL"]);
    expect(DEFAULT_EXCLUDED_MODS).toEqual(["EZ", "HT", "FL"]);
    expect(second.difficulty_std_floors.star_rating).toBe(0.35);
    expect(second.difficulty_feature_weights.ar).toBe(1.5);
  });

  it("leaves settings the UI can't change to the backend's defaults", () => {
    // They're left out of the request, so the backend's
    // RecommendationSettings defaults apply instead of a second copy here.
    const settings = createDefaultSettings();

    for (const key of ["limit", "similarity_feature_weights", "recommendation_config", "feature_target_z", "feature_max_z"]) {
      expect(settings, key).not.toHaveProperty(key);
    }
  });
});
