// Component tests for ModOptions.
//
// React Testing Library's approach: test a component the way a user uses
// it. Find elements by what the user sees (a checkbox labelled "HD"), click
// them, and check what changed, rather than poking at React internals. If
// you later restyle or restructure the component, these tests keep passing
// as long as it still *behaves* the same.
//
//   render(<X />)                  draws the component into the fake DOM
//   screen.getByRole(...)          finds an element (throws if missing)
//   userEvent.setup() + user.click simulates a real click, including focus
//   expect(el).toBeChecked()       jest-dom matchers, from src/test/setup.js

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { SettingsHarness } from "./SettingsHarness";
import ModOptions from "@/components/ModOptions";

function renderModOptions(initialSettings = {}) {
  // Keep a reference to the latest settings, updated after every change.
  const latest = { settings: null };
  const user = userEvent.setup();

  render(
    <SettingsHarness
      component={ModOptions}
      initialSettings={initialSettings}
      onSettingsChange={(settings) => {
        latest.settings = settings;
      }}
    />,
  );

  return { user, latest };
}

const mod = (name) => screen.getByRole("checkbox", { name });

describe("ModOptions, normal mode", () => {
  it("shows the default exclusions as indeterminate", () => {
    renderModOptions();

    // An indeterminate checkbox (the dash) means "excluded" here.
    // toBePartiallyChecked is how jest-dom checks for it.
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

    // HDHRDT is a stored variant, so HR can still be added...
    expect(mod("HR")).toBeEnabled();
    // ...but there are no HDDTFL / EZHDDT / HTHDDT variants, and NM can't
    // combine with anything.
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
