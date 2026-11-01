import { Card, Form } from "react-bootstrap";
import { DEFAULT_EXCLUDED_MODS } from "../utils/recommendation";
import ModCheckboxes from "./ModCheckboxes";
import "./ModOptions.css";

function ModOptions({ settings, updateSetting }) {
  const exactMods = settings.exact_mods ?? false;

  const handleExactModsChange = (enabled) => {
    updateSetting("exact_mods", enabled);

    // Reset mod selection when switching modes. Exact mode only uses the
    // checked mods, so the default exclusions are dropped there and
    // restored when switching back.
    updateSetting("mods", []);
    updateSetting("excluded_mods", enabled ? [] : [...DEFAULT_EXCLUDED_MODS]);
  };

  return (
    <Card className="mb-4">
      <Card.Header>
        <strong>Mods</strong>
      </Card.Header>

      <Card.Body>
        <Form.Check
          type="switch"
          id="exact-mods"
          label="Exact combination"
          checked={exactMods}
          onChange={(event) => handleExactModsChange(event.target.checked)}
          className="mb-3"
        />

        <div className="mod-options-checks d-flex flex-wrap gap-4">
          <ModCheckboxes settings={settings} updateSetting={updateSetting} idPrefix="mod-" />
        </div>
      </Card.Body>
    </Card>
  );
}

export default ModOptions;
