import {Card, Col, Form, Row} from 'react-bootstrap'

function NumberInput({label, value, onChange, step = 'any'}) {
  return (
    <Form.Group>
      <Form.Label className="small mb-1">{label}</Form.Label>
      <Form.Control
        type="number"
        value={value ?? ''}
        step={step}
        style={{maxWidth: '110px'}}
        onChange={(e) =>
          onChange(e.target.value === '' ? null : Number(e.target.value))
        }
      />
    </Form.Group>
  )
}

function CandidateFilters({settings, updateSetting}) {
  return (
    <Card className="mb-4">
      <Card.Header><strong>Candidate Filters</strong></Card.Header>
      <Card.Body>
        <Row className="g-3 justify-content-start">
          {/* Column 1: Stars */}
          <Col xs={6} sm={4} md={3} lg="auto">
            <div className="d-flex flex-column gap-3">
              <NumberInput
                label="Minimum Stars"
                value={settings.min_stars}
                onChange={(value) => updateSetting('min_stars', value)}
              />
              <NumberInput
                label="Maximum Stars"
                value={settings.max_stars}
                onChange={(value) => updateSetting('max_stars', value)}
              />
            </div>
          </Col>

          {/* Column 2: BPM */}
          <Col xs={6} sm={4} md={3} lg="auto">
            <div className="d-flex flex-column gap-3">
              <NumberInput
                label="Minimum BPM"
                value={settings.min_bpm}
                onChange={(value) => updateSetting('min_bpm', value)}
              />
              <NumberInput
                label="Maximum BPM"
                value={settings.max_bpm}
                onChange={(value) => updateSetting('max_bpm', value)}
              />
            </div>
          </Col>

          {/* Column 3: PP */}
          <Col xs={6} sm={4} md={3} lg="auto">
            <div className="d-flex flex-column gap-3">
              <NumberInput
                label="Minimum PP"
                value={settings.min_pp}
                onChange={(value) => updateSetting('min_pp', value)}
              />
              <NumberInput
                label="Maximum PP"
                value={settings.max_pp}
                onChange={(value) => updateSetting('max_pp', value)}
              />
            </div>
          </Col>

          {/* Column 4: Circle Size */}
          <Col xs={6} sm={4} md={3} lg="auto">
            <div className="d-flex flex-column gap-3">
              <NumberInput
                label="Min CS"
                value={settings.min_cs}
                onChange={(value) => updateSetting('min_cs', value)}
              />
              <NumberInput
                label="Max CS"
                value={settings.max_cs}
                onChange={(value) => updateSetting('max_cs', value)}
              />
            </div>
          </Col>

          {/* Column 5: AR */}
          <Col xs={6} sm={4} md={3} lg="auto">
            <div className="d-flex flex-column gap-3">
              <NumberInput
                label="Minimum AR"
                value={settings.min_ar}
                onChange={(value) => updateSetting('min_ar', value)}
              />
              <NumberInput
                label="Maximum AR"
                value={settings.max_ar}
                onChange={(value) => updateSetting('max_ar', value)}
              />
            </div>
          </Col>

          {/* Column 6: OD */}
          <Col xs={6} sm={4} md={3} lg="auto">
            <div className="d-flex flex-column gap-3">
              <NumberInput
                label="Minimum OD"
                value={settings.min_od}
                onChange={(value) => updateSetting('min_od', value)}
              />
              <NumberInput
                label="Maximum OD"
                value={settings.max_od}
                onChange={(value) => updateSetting('max_od', value)}
              />
            </div>
          </Col>

          {/* Column 7: Length (seconds) */}
          <Col xs={6} sm={4} md={3} lg="auto">
            <div className="d-flex flex-column gap-3">
              <NumberInput
                label="Min Length (s)"
                value={settings.min_length}
                onChange={(value) => updateSetting('min_length', value)}
              />
              <NumberInput
                label="Max Length (s)"
                value={settings.max_length}
                onChange={(value) => updateSetting('max_length', value)}
              />
            </div>
          </Col>

          {/* Column 8: Combo */}
          <Col xs={6} sm={4} md={3} lg="auto">
            <div className="d-flex flex-column gap-3">
              <NumberInput
                label="Min Combo"
                value={settings.min_combo}
                onChange={(value) => updateSetting('min_combo', value)}
              />
              <NumberInput
                label="Max Combo"
                value={settings.max_combo}
                onChange={(value) => updateSetting('max_combo', value)}
              />
            </div>
          </Col>
        </Row>
      </Card.Body>
    </Card>
  )
}

export default CandidateFilters