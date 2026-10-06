import { Card, Col, Form, Row } from "react-bootstrap";
import { useState } from "react";

const GOALS = [
  ["balanced", "Balanced"],
  ["pp_potential", "PP Potential"],
];

function BasicOptions({ settings, updateSetting }) {
  const [minYearInput, setMinYearInput] = useState(
    settings.min_year?.toString() ?? ""
  );
  const [maxYearInput, setMaxYearInput] = useState(
    settings.max_year?.toString() ?? ""
  );

  const commitMinYear = () => {
    if (minYearInput === "") {
      updateSetting("min_year", null);
      return;
    }

    const year = parseInt(minYearInput, 10);

    if (minYearInput.length !== 4 || year < 2007 || year > 2026) {
      setMinYearInput(settings.min_year?.toString() ?? "");
      return;
    }

    if (settings.max_year != null && year > settings.max_year) {
      setMinYearInput(settings.min_year?.toString() ?? "");
      return;
    }

    updateSetting("min_year", year);
  };

  const commitMaxYear = () => {
    if (maxYearInput === "") {
      updateSetting("max_year", null);
      return;
    }

    const year = parseInt(maxYearInput, 10);

    if (maxYearInput.length !== 4 || year < 2007 || year > 2026) {
      setMaxYearInput(settings.max_year?.toString() ?? "");
      return;
    }

    if (settings.min_year != null && year < settings.min_year) {
      setMaxYearInput(settings.max_year?.toString() ?? "");
      return;
    }

    updateSetting("max_year", year);
  };

  return (
    <Card className="mb-4">
      <Card.Header>
        <strong>Basic Options</strong>
      </Card.Header>

      <Card.Body>
        <Row className="g-3">
          <Col md={2}>
            <Form.Group>
              <Form.Label>Player ID</Form.Label>

              <Form.Control
                type="number"
                min={1}
                step={1}
                maxLength={20}
                value={settings.player_id ?? ""}
                onChange={(event) => {
                  const val = event.target.value;
                  if (val === "") {
                    updateSetting("player_id", null);
                  } else if (val.length <= 20) {
                    const parsed = parseInt(val, 10);
                    const clamped = Math.max(1, isNaN(parsed) ? 1 : parsed);
                    updateSetting("player_id", clamped);
                  }
                }}
              />

              <Form.Text className="text-muted">Defaults to your ID.</Form.Text>
            </Form.Group>
          </Col>

          <Col md={3}>
            <Form.Group>
              <Form.Label>Recommendation Goal</Form.Label>

              <Form.Select
                value={settings.goal}
                onChange={(event) => updateSetting("goal", event.target.value)}
              >
                {GOALS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Form.Select>
            </Form.Group>
          </Col>

          <Col md={2}>
            <Form.Group>
              <Form.Label>Already Played</Form.Label>

              <Form.Select
                value={String(settings.exclude_already_played)}
                onChange={(event) =>
                  updateSetting(
                    "exclude_already_played",
                    event.target.value === "true"
                  )
                }
              >
                <option value="true">Exclude</option>
                <option value="false">Include</option>
              </Form.Select>
            </Form.Group>
          </Col>

          <Col md={2}>
            <Form.Group>
              <Form.Label>Recent Plays</Form.Label>

              <Form.Select
                value={String(settings.exclude_recent_plays)}
                onChange={(event) =>
                  updateSetting(
                    "exclude_recent_plays",
                    event.target.value === "true"
                  )
                }
              >
                <option value="false">Include</option>
                <option value="true">Exclude</option>
              </Form.Select>
            </Form.Group>
          </Col>
        </Row>

        <Row className="g-3 mt-1">
          <Col md={3}>
            <Form.Group>
              <Form.Label>Number of Recommendations</Form.Label>

              <Form.Control
                type="number"
                min={1}
                max={100000}
                step={1}
                value={settings.limit ?? ""}
                onChange={(event) => {
                  const val = event.target.value;
                  if (val === "") {
                    updateSetting("limit", null);
                  } else {
                    const parsed = parseInt(val, 10);
                    const clamped = Math.min(
                      100000,
                      Math.max(1, isNaN(parsed) ? 1 : parsed)
                    );
                    updateSetting("limit", clamped);
                  }
                }}
              />

              <Form.Text className="text-muted">
                Max 100000, have fun :)
              </Form.Text>
            </Form.Group>
          </Col>

          <Col md={3}>
            <Form.Group>
              <Form.Label>Number of Neighbors</Form.Label>

              <Form.Control
                type="number"
                min={1}
                max={146096}
                step={1}
                value={settings.neighbors_k ?? 20000}
                onChange={(event) => {
                  const val = event.target.value;
                  if (val === "") {
                    updateSetting("neighbors_k", "");
                    return;
                  }
                  const parsed = parseInt(val, 10);
                  const clamped = Math.min(
                    146096,
                    Math.max(1, isNaN(parsed) ? 1 : parsed)
                  );
                  updateSetting("neighbors_k", clamped);
                }}
              />

              <Form.Text className="text-muted">
                Defaults to 20000, max 146096
              </Form.Text>
            </Form.Group>
          </Col>

          <Col md={6}>
            <Form.Group>
              <Form.Label>Year range (WIP)</Form.Label>

              <div className="d-flex gap-2">
                <Form.Control
                  type="text"
                  inputMode="numeric"
                  maxLength={4}
                  placeholder="From"
                  value={minYearInput}
                  onChange={(event) => {
                    setMinYearInput(
                      event.target.value.replace(/\D/g, "").slice(0, 4)
                    );
                  }}
                  onBlur={commitMinYear}
                />

                <Form.Control
                  type="text"
                  inputMode="numeric"
                  maxLength={4}
                  placeholder="To"
                  value={maxYearInput}
                  onChange={(event) => {
                    setMaxYearInput(
                      event.target.value.replace(/\D/g, "").slice(0, 4)
                    );
                  }}
                  onBlur={commitMaxYear}
                />
              </div>

              <Form.Text className="text-muted">Inclusive range</Form.Text>
            </Form.Group>
          </Col>
        </Row>
      </Card.Body>
    </Card>
  );
}

export default BasicOptions;
