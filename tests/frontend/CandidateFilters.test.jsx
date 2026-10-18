// Component tests for CandidateFilters: the min/max number inputs.
//
// The important behaviour is the value that ends up in settings, because
// that's what the backend receives: numbers (not strings), and null when a
// box is empty (null means "no filter").

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { SettingsHarness } from "./SettingsHarness";
import CandidateFilters from "@/components/CandidateFilters";

function renderFilters(initialSettings = {}) {
  const latest = { settings: null };
  const user = userEvent.setup();

  render(
    <SettingsHarness
      component={CandidateFilters}
      initialSettings={initialSettings}
      onSettingsChange={(settings) => {
        latest.settings = settings;
      }}
    />,
  );

  return { user, latest };
}

describe("CandidateFilters", () => {
  it("starts with every filter empty", () => {
    renderFilters();

    // A number input with no value has the value null in jest-dom.
    for (const input of screen.getAllByRole("spinbutton")) {
      expect(input).toHaveValue(null);
    }
  });

  it("stores typed values as numbers", async () => {
    const { user, latest } = renderFilters();

    await user.type(screen.getByLabelText("Min Stars"), "5.5");
    await user.type(screen.getByLabelText("Max Length"), "180");

    expect(latest.settings.min_stars).toBe(5.5);
    expect(latest.settings.max_length).toBe(180);
  });

  it("clearing a box removes the filter (null, not 0)", async () => {
    const { user, latest } = renderFilters({ max_bpm: 220 });
    const input = screen.getByLabelText("Max BPM");
    expect(input).toHaveValue(220);

    await user.clear(input);

    expect(latest.settings.max_bpm).toBeNull();
  });

  it("each box updates its own setting", async () => {
    // A copy-paste slip (e.g. "Max CS" wired to min_cs) is easy to make in
    // a component like this and hard to spot by eye. Typing into every box
    // and checking every key catches it.
    const { user, latest } = renderFilters();
    const fields = {
      "Min Stars": "min_stars",
      "Max Stars": "max_stars",
      "Min BPM": "min_bpm",
      "Max BPM": "max_bpm",
      "Min PP": "min_pp",
      "Max PP": "max_pp",
      "Min CS": "min_cs",
      "Max CS": "max_cs",
      "Min AR": "min_ar",
      "Max AR": "max_ar",
      "Min OD": "min_od",
      "Max OD": "max_od",
      "Min Length": "min_length",
      "Max Length": "max_length",
      "Min Combo": "min_combo",
      "Max Combo": "max_combo",
    };

    let value = 1;
    for (const label of Object.keys(fields)) {
      await user.type(screen.getByLabelText(label), String(value));
      value += 1;
    }

    value = 1;
    for (const key of Object.values(fields)) {
      expect(latest.settings[key], key).toBe(value);
      value += 1;
    }
  });
});
