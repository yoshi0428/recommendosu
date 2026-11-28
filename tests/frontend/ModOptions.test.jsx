// Component tests for ModOptions.
//
// The approach of React Testing Library: test a component as a user uses it.
// Find elements by what the user sees (a checkbox with the label "HD"), click
// them, and check what changed. Do not look at React internals. If you later
// change the style or the structure of the component, these tests still pass,
// if it still *behaves* the same.
//
//   render(<X />)                  draws the component into the fake DOM
//   screen.getByRole(...)          finds an element (throws if missing)
//   userEvent.setup() + user.click simulates a real click, including focus
//   expect(el).toBeChecked()       jest-dom matchers, from tests/frontend/setup.js

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderSettings } from "./SettingsHarness";
import ModOptions from "@/components/ModOptions";

const renderModOptions = (initialSettings) => renderSettings(ModOptions, initialSettings);

const mod = (name) => screen.getByRole("checkbox", { name });

describe("ModOptions, normal mode", () => {
  it("shows the default exclusions as indeterminate", () => {
    renderModOptions();

    // Here, an indeterminate checkbox (the dash) means "excluded".
    // jest-dom checks for it with toBePartiallyChecked.
    expect(mod("EZ")).toBePartiallyChecked();
    expect(mod("HT")).toBePartiallyChecked();
    expect(mod("FL")).toBePartiallyChecked();
    expect(mod("HD")).not.toBeChecked();
    expect(mod("HD")).not.toBePartiallyChecked();
  });

  it("cycles allowed -> required -> excluded -> allowed", async () => {
    const { user, latest } = renderModOptions();

    await user.click(mod("HD"));
    expect(mod("HD")).toBeChecked();
    expect(latest.settings.mods).toEqual(["HD"]);

    await user.click(mod("HD"));
    expect(mod("HD")).toBePartiallyChecked();
    expect(latest.settings.mods).toEqual([]);
    expect(latest.settings.excluded_mods).toContain("HD");

    await user.click(mod("HD"));
    expect(mod("HD")).not.toBeChecked();
    expect(mod("HD")).not.toBePartiallyChecked();
    expect(latest.settings.excluded_mods).not.toContain("HD");
  });

  it("re-allows a default-excluded mod with one click", async () => {
    const { user, latest } = renderModOptions();

    await user.click(mod("EZ"));

    expect(latest.settings.excluded_mods).toEqual(["HT", "FL"]);
    expect(latest.settings.mods).toEqual([]);
  });

  it("never disables mods outside exact mode", () => {
    renderModOptions({ mods: ["HD", "DT"] });

    for (const name of ["NM", "HD", "HR", "DT", "EZ", "HT", "FL"]) {
      expect(mod(name)).toBeEnabled();
    }
  });
});

describe("ModOptions, exact combination mode", () => {
  it("switching on clears mods and exclusions; switching off restores defaults", async () => {
    const { user, latest } = renderModOptions({ mods: ["HD"] });
    const exactSwitch = screen.getByLabelText("Exact combination");

    await user.click(exactSwitch);
    expect(latest.settings).toMatchObject({ exact_mods: true, mods: [], excluded_mods: [] });

    await user.click(exactSwitch);
    expect(latest.settings).toMatchObject({
      exact_mods: false,
      mods: [],
      excluded_mods: ["EZ", "HT", "FL"],
    });
  });

  it("only allows combinations that exist in the database", async () => {
    const { user, latest } = renderModOptions({ exact_mods: true, excluded_mods: [] });

    await user.click(mod("HD"));
    await user.click(mod("DT"));
    expect(latest.settings.mods).toEqual(["HD", "DT"]);

    // HDHRDT is a stored variant, so HR can still be added,
    expect(mod("HR")).toBeEnabled();
    // but there are no HDDTFL / EZHDDT / HTHDDT variants, and NM cannot
    // combine with other mods.
    expect(mod("FL")).toBeDisabled();
    expect(mod("EZ")).toBeDisabled();
    expect(mod("HT")).toBeDisabled();
    expect(mod("NM")).toBeDisabled();
  });

  it("NM on its own locks every other mod", async () => {
    const { user } = renderModOptions({ exact_mods: true, excluded_mods: [] });

    await user.click(mod("NM"));

    expect(mod("NM")).toBeChecked();
    for (const name of ["HD", "HR", "DT", "EZ", "HT", "FL"]) {
      expect(mod(name)).toBeDisabled();
    }
  });

  it("unchecking a mod in exact mode removes it without excluding it", async () => {
    const { user, latest } = renderModOptions({ exact_mods: true, excluded_mods: [] });

    await user.click(mod("HR"));
    await user.click(mod("HR"));

    expect(latest.settings.mods).toEqual([]);
    expect(latest.settings.excluded_mods).toEqual([]);
  });
});
