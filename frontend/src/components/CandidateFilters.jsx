import { Card } from "react-bootstrap";

import NumberInput from "./NumberInput";
import "./CandidateFilters.css";

// One column per filter: [setting name (min_<name> / max_<name>), label].
const RANGE_FILTERS = [
  ["stars", "Stars"],
  ["bpm", "BPM"],
  ["pp", "PP"],
  ["cs", "CS"],
  ["ar", "AR"],
  ["od", "OD"],
  ["length", "Length"],
  ["combo", "Combo"],
];

function CandidateFilters({ settings, updateSetting }) {
  return (
    <Card className="mb-4">
      <Card.Header>
        <strong>Candidate Filters</strong>
      </Card.Header>
      <Card.Body className="candidate-filters-body">
        <div className="candidate-filters-grid">
          {RANGE_FILTERS.map(([name, label]) => (
            <div key={name}>
              <div className="d-flex gap-3">
                {["min", "max"].map((bound) => {
                  const key = `${bound}_${name}`;

                  return (
                    <NumberInput
                      key={key}
                      label={`${bound === "min" ? "Min" : "Max"} ${label}`}
                      value={settings[key]}
                      onChange={(value) => updateSetting(key, value)}
                      emptyValue={null}
                      className="flex-fill"
                      style={{ minWidth: 0 }}
                      labelClassName="small mb-1"
                    />
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </Card.Body>
    </Card>
  );
}

export default CandidateFilters;
