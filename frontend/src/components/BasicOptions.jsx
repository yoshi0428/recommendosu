import {Card, Col, Form, Row} from 'react-bootstrap'

const GOALS = [
  ['balanced', 'Balanced'],
  ['pp_potential', 'PP Potential'],
  ['NM1_to_5', 'NM1–5 Classifier'],
]

function BasicOptions({
                        settings,
                        updateSetting,
                      }) {
  return (
    <Card className="mb-4">
      <Card.Header>
        <strong>Basic Options</strong>
      </Card.Header>

      <Card.Body>
        <Row className="g-3">
          <Col md={2}>
            <Form.Group>
              <Form.Label>
                Player ID
              </Form.Label>

              <Form.Control
                type="number"
                min={1}
                step={1}
                maxLength={20}
                value={settings.player_id ?? ''}
                onChange={(event) => {
                  const val = event.target.value
                  if (val === '') {
                    updateSetting('player_id', null)
                  } else if (val.length <= 20) {
                    const parsed = parseInt(val, 10)
                    const clamped = Math.max(1, isNaN(parsed) ? 1 : parsed)
                    updateSetting('player_id', clamped)
                  }
                }}
              />

              <Form.Text className="text-muted">
                Defaults to your osu! player ID.
              </Form.Text>
            </Form.Group>
          </Col>

          <Col md={3}>
            <Form.Group>
              <Form.Label>
                Recommendation Goal
              </Form.Label>

              <Form.Select
                value={settings.goal}
                onChange={(event) =>
                  updateSetting(
                    'goal',
                    event.target.value
                  )
                }
              >
                {GOALS.map(([value, label]) => (
                  <option
                    key={value}
                    value={value}
                  >
                    {label}
                  </option>
                ))}
              </Form.Select>
            </Form.Group>
          </Col>

          <Col md={3}>
            <Form.Group>
              <Form.Label>
                Number of Recommendations
              </Form.Label>

              <Form.Control
                type="number"
                min={1}
                max={10000}
                step={1}
                value={settings.limit ?? ''}
                onChange={(event) => {
                  const val = event.target.value
                  if (val === '') {
                    updateSetting('limit', null)
                  } else {
                    const parsed = parseInt(val, 10)
                    const clamped = Math.min(1000, Math.max(1, isNaN(parsed) ? 1 : parsed))
                    updateSetting('limit', clamped)
                  }
                }}
              />

              <Form.Text className="text-muted">
                Capped at 1000 to prevent overloading.
              </Form.Text>
            </Form.Group>
          </Col>

          <Col md={2}>
            <Form.Group>
              <Form.Label>
                Already Played
              </Form.Label>

              <Form.Select
                value={String(settings.exclude_already_played)}
                onChange={(event) =>
                  updateSetting(
                    'exclude_already_played',
                    event.target.value === 'true'
                  )
                }
              >
                <option value="true">
                  Exclude
                </option>
                <option value="false">
                  Include
                </option>
              </Form.Select>

              <Form.Text className="text-muted">
                Choose whether maps you've already played can be recommended.
              </Form.Text>
            </Form.Group>

          </Col>

          <Col md={2}>
            <Form.Group>
              <Form.Label>
                Recent Plays
              </Form.Label>

              <Form.Select
                value={String(settings.exclude_recent_plays)}
                onChange={(event) =>
                  updateSetting(
                    'exclude_recent_plays',
                    event.target.value === 'true'
                  )
                }
              >
                <option value="false">
                  Include
                </option>
                <option value="true">
                  Exclude
                </option>
              </Form.Select>

              <Form.Text className="text-muted">
                Choose whether your recent plays affects recommendations.
              </Form.Text>
            </Form.Group>

          </Col>
        </Row>
      </Card.Body>
    </Card>
  )
}

export default BasicOptions