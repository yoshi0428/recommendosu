// Tests for src/utils/recommendation.js.
//
// Vitest works much like pytest, with different names:
//   describe("group", () => {...})  groups related tests (like a test class)
//   it("does something", () => {})  one test (like `def test_...`)
//   expect(actual).toBe(expected)   an assertion (like `assert actual == expected`)
//
// toBe compares with ===, so use it for numbers, strings and booleans. For
// objects and arrays, use toEqual, which compares the contents, as == in
// Python compares dicts and lists.

import { describe, expect, it } from "vitest";

import { DEFAULT_EXCLUDED_MODS, createDefaultSettings } from "@/utils/recommendation";

describe("createDefaultSettings", () => {
  it("starts with the default status and mod exclusions", () => {
    const settings = createDefaultSettings();

    expect(settings).not.toHaveProperty("goal");
    expect(settings.beatmap_status).toBe("all");
    expect(settings.mods).toEqual([]);
    expect(settings.excluded_mods).toEqual(["EZ", "HT", "FL"]);
  });

  it("returns independent copies every time", () => {
    // The UI edits the settings object in place. If two calls shared the same
    // nested objects, an edit of the weights of one user would change the
    // defaults for everyone after that, without an error.
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
    // They are not in the request, so the RecommendationSettings defaults of
    // the backend apply, not a second copy here.
    const settings = createDefaultSettings();

    for (const key of ["limit", "similarity_feature_weights", "recommendation_config", "feature_target_z", "feature_max_z"]) {
      expect(settings, key).not.toHaveProperty(key);
    }
  });
});
