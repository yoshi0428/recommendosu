import { Fragment } from "react";
import { Card, Col, Row } from "react-bootstrap";

import NumberInput from "./NumberInput";

// [heading, row classes, [[setting, label], ...]]
const SECTIONS = [
  [
    "Mod Interaction Weights",
    "g-3 mb-4",
    [
      ["top_weight", "Top Play Weight"],
      ["recent_weight", "Recent Play Weight"],
      ["pp_weight", "PP Weight"],
    ],
  ],
  [
    "Ability Profile",
    "g-3 mb-4",
    [
      ["ability_top_weight", "Top Play Ability Weight"],
      ["ability_recent_weight", "Recent Play Ability Weight"],
      ["ability_pp_weight", "PP Ability Weight"],
      ["recency_half_life_days", "Recency Half-Life (days)"],
    ],
  ],
  [
    "PP Potential",
    "g-3",
    [
      ["pp_push_target_z", "PP Push Target Z"],
      ["pp_push_max_z", "PP Push Maximum Z"],
    ],
  ],
];

function ScoringOptions({ settings, updateSetting }) {
  return (
    <Card className="mb-4">
      <Card.Header>
        {" "}
        <strong>Scoring & Ability</strong>
      </Card.Header>
      <Card.Body>
        {SECTIONS.map(([heading, rowClassName, fields]) => (
          <Fragment key={heading}>
            <h6>{heading}</h6>

            <Row className={rowClassName}>
              {fields.map(([key, label]) => (
                <Col xl={3} key={key}>
                  <NumberInput
                    label={label}
                    value={settings[key]}
                    onChange={(value) => updateSetting(key, value)}
                  />
                </Col>
              ))}
            </Row>
          </Fragment>
        ))}
      </Card.Body>
    </Card>
  );
}

export default ScoringOptions;
