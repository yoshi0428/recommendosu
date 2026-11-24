import { Card, Col, Row } from "react-bootstrap";

import NumberInput from "./NumberInput";

const DIFFICULTY_FEATURES = [
  ["star_rating", "Star Rating"],
  ["ar", "AR"],
  ["od", "OD"],
  ["bpm", "BPM"],
];

// One number input for each difficulty feature in settings[setting].
function FeatureInputs({ settings, setting, updateNestedSetting, className }) {
  return (
    <Row className={className}>
      {DIFFICULTY_FEATURES.map(([key, label]) => (
        <Col xl={3} key={key}>
          <NumberInput
            label={label}
            value={settings[setting][key]}
            onChange={(value) => updateNestedSetting(setting, key, value)}
          />
        </Col>
      ))}
    </Row>
  );
}

function DifficultyProfile({ settings, updateNestedSetting }) {
  return (
    <Card className="mb-4">
      <Card.Header>
        <strong>Difficulty Profile</strong>
      </Card.Header>
      <Card.Body>
        <p className="text-muted">
          Controls how strongly the recommender compares a candidate's
          difficulty to the player's estimated ability.
        </p>

        <h6 className="mt-3">Difficulty Standard Deviation Floors</h6>
        <FeatureInputs
          settings={settings}
          setting="difficulty_std_floors"
          updateNestedSetting={updateNestedSetting}
          className="g-3 mb-4"
        />

        <h6>Difficulty Feature Weights</h6>
        <FeatureInputs
          settings={settings}
          setting="difficulty_feature_weights"
          updateNestedSetting={updateNestedSetting}
          className="g-3"
        />
      </Card.Body>
    </Card>
  );
}

export default DifficultyProfile;
