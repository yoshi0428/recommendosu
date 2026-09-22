import {Card, Col, Form, Row} from 'react-bootstrap'

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

function ScoringOptions({
                          settings,
                          updateSetting,
                        }) {
  return (
    <Card className="mb-4">
      <Card.Header> <strong>Scoring & Ability</strong>
      </Card.Header>
      <Card.Body>
        <h6>Mod Interaction Weights</h6>

        <Row className="g-3 mb-4">
          <Col md={3}>
            <NumberInput
              label="Top Play Weight"
              value={settings.top_weight}
              onChange={(value) =>
                updateSetting('top_weight', value)
              }
            />
          </Col>

          <Col md={3}>
            <NumberInput
              label="Recent Play Weight"
              value={settings.recent_weight}
              onChange={(value) =>
                updateSetting('recent_weight', value)
              }
            />
          </Col>

          <Col md={3}>
            <NumberInput
              label="PP Weight"
              value={settings.pp_weight}
              onChange={(value) =>
                updateSetting('pp_weight', value)
              }
            />
          </Col>
        </Row>

        <h6>Ability Profile</h6>

        <Row className="g-3 mb-4">
          <Col md={3}>
            <NumberInput
              label="Top Play Ability Weight"
              value={settings.ability_top_weight}
              onChange={(value) =>
                updateSetting(
                  'ability_top_weight',
                  value
                )
              }
            />
          </Col>

          <Col md={3}>
            <NumberInput
              label="Recent Play Ability Weight"
              value={settings.ability_recent_weight}
              onChange={(value) =>
                updateSetting(
                  'ability_recent_weight',
                  value
                )
              }
            />
          </Col>

          <Col md={3}>
            <NumberInput
              label="PP Ability Weight"
              value={settings.ability_pp_weight}
              onChange={(value) =>
                updateSetting(
                  'ability_pp_weight',
                  value
                )
              }
            />
          </Col>

          <Col md={3}>
            <NumberInput
              label="Recency Half-Life (days)"
              value={settings.recency_half_life_days}
              onChange={(value) =>
                updateSetting(
                  'recency_half_life_days',
                  value
                )
              }
            />
          </Col>
        </Row>

        <h6>PP Potential</h6>

        <Row className="g-3">
          <Col md={3}>
            <NumberInput
              label="PP Push Target Z"
              value={settings.pp_push_target_z}
              onChange={(value) =>
                updateSetting(
                  'pp_push_target_z',
                  value
                )
              }
            />
          </Col>

          <Col md={3}>
            <NumberInput
              label="PP Push Maximum Z"
              value={settings.pp_push_max_z}
              onChange={(value) =>
                updateSetting(
                  'pp_push_max_z',
                  value
                )
              }
            />
          </Col>
        </Row>
      </Card.Body>
    </Card>
  )
}

export default ScoringOptions