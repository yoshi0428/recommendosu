import { useId } from "react";
import { Card, Form } from "react-bootstrap";

import "./CandidateFilters.css";

function NumberInput({ label, value, onChange, step = "any" }) {
  // controlId links the label to the input (clicking the label focuses it,
  // and screen readers announce the input by its label).
  const id = useId();

  return (
    <Form.Group controlId={id} className="flex-fill" style={{ minWidth: 0 }}>
      <Form.Label className="small mb-1">{label}</Form.Label>
      <Form.Control
        type="number"
        value={value ?? ""}
        step={step}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : Number(e.target.value))
        }
      />
    </Form.Group>
  );
}

function CandidateFilters({ settings, updateSetting }) {
  return (
    <Card className="mb-4">
      <Card.Header>
        <strong>Candidate Filters</strong>
      </Card.Header>
      <Card.Body className="candidate-filters-body">
        <div className="candidate-filters-grid">
          {/* Column 1: Stars */}
          <div>
            <div className="d-flex gap-3">
              <NumberInput
                label="Min Stars"
                value={settings.min_stars}
                onChange={(value) => updateSetting("min_stars", value)}
              />
              <NumberInput
                label="Max Stars"
                value={settings.max_stars}
                onChange={(value) => updateSetting("max_stars", value)}
              />
            </div>
          </div>

          {/* Column 2: BPM */}
          <div>
            <div className="d-flex gap-3">
              <NumberInput
                label="Min BPM"
                value={settings.min_bpm}
                onChange={(value) => updateSetting("min_bpm", value)}
              />
              <NumberInput
                label="Max BPM"
                value={settings.max_bpm}
                onChange={(value) => updateSetting("max_bpm", value)}
              />
            </div>
          </div>

          {/* Column 3: PP */}
          <div>
            <div className="d-flex gap-3">
              <NumberInput
                label="Min PP"
                value={settings.min_pp}
                onChange={(value) => updateSetting("min_pp", value)}
              />
              <NumberInput
                label="Max PP"
                value={settings.max_pp}
                onChange={(value) => updateSetting("max_pp", value)}
              />
            </div>
          </div>

          {/* Column 4: Circle Size */}
          <div>
            <div className="d-flex gap-3">
              <NumberInput
                label="Min CS"
                value={settings.min_cs}
                onChange={(value) => updateSetting("min_cs", value)}
              />
              <NumberInput
                label="Max CS"
                value={settings.max_cs}
                onChange={(value) => updateSetting("max_cs", value)}
              />
            </div>
          </div>

          {/* Column 5: AR */}
          <div>
            <div className="d-flex gap-3">
              <NumberInput
                label="Min AR"
                value={settings.min_ar}
                onChange={(value) => updateSetting("min_ar", value)}
              />
              <NumberInput
                label="Max AR"
                value={settings.max_ar}
                onChange={(value) => updateSetting("max_ar", value)}
              />
            </div>
          </div>

          {/* Column 6: OD */}
          <div>
            <div className="d-flex gap-3">
              <NumberInput
                label="Min OD"
                value={settings.min_od}
                onChange={(value) => updateSetting("min_od", value)}
              />
              <NumberInput
                label="Max OD"
                value={settings.max_od}
                onChange={(value) => updateSetting("max_od", value)}
              />
            </div>
          </div>

          {/* Column 7: Length (seconds) */}
          <div>
            <div className="d-flex gap-3">
              <NumberInput
                label="Min Length"
                value={settings.min_length}
                onChange={(value) => updateSetting("min_length", value)}
              />
              <NumberInput
                label="Max Length"
                value={settings.max_length}
                onChange={(value) => updateSetting("max_length", value)}
              />
            </div>
          </div>

          {/* Column 8: Combo */}
          <div>
            <div className="d-flex gap-3">
              <NumberInput
                label="Min Combo"
                value={settings.min_combo}
                onChange={(value) => updateSetting("min_combo", value)}
              />
              <NumberInput
                label="Max Combo"
                value={settings.max_combo}
                onChange={(value) => updateSetting("max_combo", value)}
              />
            </div>
          </div>
        </div>
      </Card.Body>
    </Card>
  );
}

export default CandidateFilters;
