import {Card, Col, Form, Row} from "react-bootstrap";
import {useState} from "react";

// Years with ranked maps (MIN/MAX_BEATMAP_YEAR in beatmap_recommender/api/model.py).
const MIN_YEAR = 2007;
const MAX_YEAR = 2026;

const GOALS = [
  ["balanced", "Balanced"],
  ["pp_potential", "PP Potential"],
];

const BEATMAP_STATUSES = [
  ["all", "All"],
  ["ranked", "Ranked"],
  ["loved", "Loved"],
];

function BasicOptions({settings, updateSetting}) {
  const [minYearInput, setMinYearInput] = useState(
    settings.min_year?.toString() ?? ""
  );
  const [maxYearInput, setMaxYearInput] = useState(
    settings.max_year?.toString() ?? ""
  );

  // Applies a typed year once the field loses focus, or puts the last valid
  // value back if it's not a 4-digit year in range or crosses the other bound.
  const commitYear = (key, input, setInput, isValid) => {
    if (input === "") {
      updateSetting(key, null);
      return;
    }

    const year = parseInt(input, 10);

    if (input.length !== 4 || year < MIN_YEAR || year > MAX_YEAR || !isValid(year)) {
      setInput(settings[key]?.toString() ?? "");
      return;
    }

    updateSetting(key, year);
  };

  const commitMinYear = () =>
    commitYear(
      "min_year",
      minYearInput,
      setMinYearInput,
      (year) => settings.max_year == null || year <= settings.max_year
    );

  const commitMaxYear = () =>
    commitYear(
      "max_year",
      maxYearInput,
      setMaxYearInput,
      (year) => settings.min_year == null || year >= settings.min_year
    );

  return (
    <Card className="mb-4">
      <Card.Header>
        <strong>Basic Options</strong>
      </Card.Header>

      <Card.Body>
        <Row className="g-3">
          <Col xl={2}>
            <Form.Group controlId="player-id">
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

          <Col xl={2}>
            <Form.Group controlId="goal">
              <Form.Label>Goal</Form.Label>

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

          <Col xl={2}>
            <Form.Group controlId="exclude-already-played">
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

          <Col xl={2}>
            <Form.Group controlId="exclude-recent-plays">
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

          <Col xl={2}>
            <Form.Group controlId="beatmap-status">
              <Form.Label>Map Status</Form.Label>

              <Form.Select
                value={settings.beatmap_status ?? "all"}
                onChange={(event) =>
                  updateSetting("beatmap_status", event.target.value)
                }
              >
                {BEATMAP_STATUSES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Form.Select>
            </Form.Group>
          </Col>

          <Col xl={2}>
            <Form.Group>
              <Form.Label as="div">Year range</Form.Label>

              <div className="d-flex gap-2">
                <Form.Label htmlFor="min-year" visuallyHidden>
                  From year
                </Form.Label>
                <Form.Control
                  id="min-year"
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

                <Form.Label htmlFor="max-year" visuallyHidden>
                  To year
                </Form.Label>
                <Form.Control
                  id="max-year"
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

              <Form.Text className="text-muted">Lower/upper bounds default to {MIN_YEAR}/{MAX_YEAR}</Form.Text>
            </Form.Group>
          </Col>
        </Row>
      </Card.Body>
    </Card>
  );
}

export default BasicOptions;
