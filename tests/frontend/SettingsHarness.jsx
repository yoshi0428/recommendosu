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

import { useEffect, useState } from "react";

import { createDefaultSettings } from "@/utils/recommendation";

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
