// A test helper, not a test: renders a settings component with real state.
//
// ModOptions, CandidateFilters, etc. don't own their state; they receive
// `settings` and call `updateSetting(key, value)`, and RecommendationsPage
// does the actual state update. To test a component on its own, this wrapper
// plays the page's role using the same functional update, so several
// updateSetting calls in one click all apply (as they do in the app).
//
// `onSettingsChange` reports the latest settings object, so tests can assert
// on exactly what would be sent to the backend.

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
