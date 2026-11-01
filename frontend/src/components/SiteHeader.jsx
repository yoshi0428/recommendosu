import { useState } from "react";
import { Form, Button } from "react-bootstrap";
import { Link } from "react-router-dom";
import { ChevronUp, Funnel } from "react-bootstrap-icons";
import useTheme from "../hooks/useTheme";
import ModCheckboxes from "./ModCheckboxes";
import "./SiteHeader.css";

// Quick filters for min_<name> / max_<name>. srName is the name screen
// readers announce ("Minimum stars").
const QUICK_RANGES = [
  { name: "stars", label: "Stars", srName: "stars", step: "0.1", inputMode: "decimal", width: "60px" },
  { name: "bpm", label: "BPM", srName: "BPM", step: "1", inputMode: "numeric", width: "60px" },
  { name: "pp", label: "PP", srName: "PP", step: "1", inputMode: "numeric", width: "65px" },
];

function RangeInput({ settings, updateSetting, name, label, srName, step, inputMode, width }) {
  const input = (bound, srBound, placeholder) => {
    const key = `${bound}_${name}`;
    const id = `header-${bound}-${name}`;

    return (
      <>
        <Form.Label htmlFor={id} visuallyHidden>
          {srBound} {srName}
        </Form.Label>
        <Form.Control
          id={id}
          type="number"
          size="sm"
          placeholder={placeholder}
          value={settings[key] ?? ""}
          step={step}
          inputMode={inputMode}
          style={{ width }}
          onChange={(e) =>
            updateSetting(key, e.target.value === "" ? null : Number(e.target.value))
          }
        />
      </>
    );
  };

  return (
    <div className="site-header-collapsible d-flex align-items-center gap-1">
      <span className="fw-semibold">{label}:</span>
      {input("min", "Minimum", "Min")}
      <span>-</span>
      {input("max", "Maximum", "Max")}
    </div>
  );
}

function SiteHeader({
  settings,
  updateSetting,
  onRunRecommendations,
  onCancelRecommendations,
  loading,
  advancedSettingsButton,
  logout,
}) {
  const { theme, toggleTheme } = useTheme();
  // Phones only: the quick filters and nav buttons are hidden behind a toggle
  // so the results get most of the screen. Larger screens always show them.
  const [controlsOpen, setControlsOpen] = useState(false);

  const handleSubmit = (e) => {
    e.preventDefault();

    if (loading) {
      onCancelRecommendations?.();
    } else {
      setControlsOpen(false);
      onRunRecommendations?.();
    }
  };

  return (
    <header
      className={`site-header border-bottom py-2${
        controlsOpen ? " controls-open" : ""
      }`}
    >
      <div className="container-fluid px-3 px-md-4">
        <div className="row align-items-center g-2">
          {/* Left side: Coffee button */}
          <div className="site-header-collapsible col-12 col-lg-2 order-last order-lg-first d-flex justify-content-center justify-content-lg-start">
            <a
              href="https://buymeacoffee.com/recommendosu"
              target="_blank"
              rel="noopener noreferrer"
              className={`btn btn-sm text-decoration-none text-nowrap ${
                theme === "dark"
                  ? "btn-outline-warning"
                  : "btn-outline-secondary"
              }`}
            >
              Buy me a coffee! ☕
            </a>
          </div>

          {/* Center section */}
          <div className="col-12 col-lg-8">
            <div className="quick-mods d-flex flex-column align-items-center gap-2 text-center">
              <h1 className="mb-0 fs-4 site-header-title">
                osu! Beatmap Recommender
              </h1>

              <Form
                onSubmit={handleSubmit}
                className="
                  d-flex
                  align-items-center
                  justify-content-center
                  flex-wrap
                  gap-1 gap-md-2
                  small
                  text-muted
                  w-100
                "
              >
                {QUICK_RANGES.map((range) => (
                  <RangeInput
                    key={range.name}
                    settings={settings}
                    updateSetting={updateSetting}
                    {...range}
                  />
                ))}

                {/* Quick Mod Checkboxes */}
                <div className="site-header-collapsible site-header-mods d-flex flex-wrap align-items-center gap-2 ps-3">
                  <ModCheckboxes
                    settings={settings}
                    updateSetting={updateSetting}
                    idPrefix="header-mod-"
                    compact
                  />
                </div>

                {/* Run / Advanced Settings */}
                <div className="site-header-actions d-flex align-items-center gap-2 flex-nowrap">
                  {loading ? (
                    <Button
                      type="button"
                      variant="outline-danger"
                      size="sm"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        onCancelRecommendations?.();
                      }}
                    >
                      Cancel
                    </Button>
                  ) : (
                    <Button type="submit" variant="primary" size="sm">
                      Apply & Run
                    </Button>
                  )}

                  {advancedSettingsButton}

                  <Button
                    type="button"
                    variant={controlsOpen ? "secondary" : "outline-secondary"}
                    size="sm"
                    className="site-header-toggle d-inline-flex align-items-center gap-1"
                    onClick={() => setControlsOpen((open) => !open)}
                    aria-expanded={controlsOpen}
                  >
                    {controlsOpen ? <ChevronUp /> : <Funnel />}
                    Filters
                  </Button>
                </div>
              </Form>
            </div>
          </div>

          {/* Right side */}
          <div className="site-header-collapsible col-12 col-lg-2">
            <div className="d-flex align-items-center justify-content-center justify-content-lg-end gap-2">
              {/* About */}
              <Button
                as={Link}
                to="/about"
                variant="outline-secondary"
                size="sm"
              >
                About
              </Button>

              {/* Theme */}
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={toggleTheme}
                aria-label="Toggle color theme"
              >
                {theme === "dark" ? "☀" : "🌙"}
              </button>

              {/* Logout */}
              {logout && (
                <Button variant="outline-danger" size="sm" onClick={logout}>
                  Logout
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}

export default SiteHeader;
