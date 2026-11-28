// A test helper, not a test: it renders a settings component with real state.
//
// ModOptions, CandidateFilters and the others do not own their state. They get
// `settings` and call `updateSetting(key, value)`, and RecommendationsPage does
// the real state update. To test a component alone, this wrapper does the work
// of the page, with the same functional update. Thus several updateSetting
// calls in one click all apply (as in the app).
//
// `onSettingsChange` reports the latest settings object, so that the tests can
// check exactly what the backend would get.

import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState } from "react";

import { createDefaultSettings } from "@/utils/recommendation";

// Render a settings component in the harness. `latest.settings` is always the
// newest settings object.
export function renderSettings(component, initialSettings = {}) {
  const latest = { settings: null };
  const user = userEvent.setup();

  render(
    <SettingsHarness
      component={component}
      initialSettings={initialSettings}
      onSettingsChange={(settings) => {
        latest.settings = settings;
      }}
    />,
  );

  return { user, latest };
}

export function SettingsHarness({ component: Component, initialSettings, onSettingsChange }) {
  const [settings, setSettings] = useState(() => ({
    ...createDefaultSettings(),
    ...initialSettings,
  }));

  useEffect(() => {
    onSettingsChange?.(settings);
  }, [settings, onSettingsChange]);

  const updateSetting = (key, value) => {
    setSettings((current) => ({ ...current, [key]: value }));
  };

  return <Component settings={settings} updateSetting={updateSetting} />;
}
