import {Card, Col, Form, Row} from 'react-bootstrap'

const DIFFICULTY_FEATURES = [
  ['star_rating', 'Star Rating'],
  ['ar', 'AR'],
  ['od', 'OD'],
  ['bpm', 'BPM'],
]

function NumberInput({label, value, onChange, step = 'any'}) {
  return (
    <Form.Group>
      <Form.Label>{label}</Form.Label>
      <Form.Control
        type="number"
        value={value ?? ''}
        step={step}
        onChange={(e) =>
          onChange(
            e.target.value === ''
              ? 0
              : Number(e.target.value)
          )
        }
      />
    </Form.Group>
  )
}

function DifficultyProfile({settings, updateNestedSetting}) {
  return (<Card className="mb-4">
      <Card.Header> <strong>Difficulty Profile</strong>
      </Card.Header>
      <Card.Body>
        <p className="text-muted">
          Controls how strongly the recommender compares a
          candidate's difficulty to the player's estimated ability.
        </p>

        <h6 className="mt-3">
          Standard Deviation Floors
        </h6>

        <Row className="g-3 mb-4">
          {DIFFICULTY_FEATURES.map(([key, label]) => (
            <Col md={3} key={key}>
              <NumberInput
                label={label}
                value={settings.difficulty_std_floors[key]}
                onChange={(value) =>
                  updateNestedSetting(
                    'difficulty_std_floors',
                    key,
                    value
                  )
                }
              />
            </Col>
          ))}
        </Row>

        <h6>Feature Weights</h6>

        <Row className="g-3">
          {DIFFICULTY_FEATURES.map(([key, label]) => (
            <Col md={3} key={key}>
              <NumberInput
                label={label}
                value={
                  settings.difficulty_feature_weights[key]
                }
                onChange={(value) =>
                  updateNestedSetting(
                    'difficulty_feature_weights',
                    key,
                    value
                  )
                }
              />
            </Col>
          ))}
        </Row>
      </Card.Body>
    </Card>
  )
}

export default DifficultyProfile
