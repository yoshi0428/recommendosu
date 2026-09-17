import {Badge, Card, Col, Row, Stack} from 'react-bootstrap'

export default function RecommendationList({recommendations}) {
  if (!recommendations.length) {
    return null
  }

  return (
    <>
      <h2 className="mb-3">
        Recommendations

        <Badge bg="secondary" className="ms-2">
          {recommendations.length}
        </Badge>
      </h2>

      <Row>
        {recommendations.map((recommendation) => (
          <Col
            md={6}
            xl={4}
            key={`${recommendation.beatmap_id}-${recommendation.variant_id}`}
          >
            <Card className="mb-4 h-100">
              <Card.Body>
                <Stack
                  direction="horizontal"
                  className="justify-content-between mb-2"
                >
                  <Card.Title className="mb-0">
                    {recommendation.beatmap_id}
                  </Card.Title>

                  <Badge bg="dark">
                    {recommendation.mods || 'NM'}
                  </Badge>
                </Stack>

                <div className="mb-3">
                  <strong>
                    {Number(
                      recommendation.star_rating,
                    ).toFixed(2)}
                    ★
                  </strong>
                </div>

                <Row className="small">
                  <Col xs={6}>
                    <div>
                      <strong>BPM:</strong>{' '}
                      {recommendation.bpm}
                    </div>

                    <div>
                      <strong>AR:</strong>{' '}
                      {recommendation.ar}
                    </div>

                    <div>
                      <strong>OD:</strong>{' '}
                      {recommendation.od}
                    </div>

                    <div>
                      <strong>CS:</strong>{' '}
                      {recommendation.circle_size}
                    </div>
                  </Col>

                  <Col xs={6}>
                    <div>
                      <strong>Length:</strong>{' '}
                      {recommendation.length_seconds}s
                    </div>

                    <div>
                      <strong>Objects:</strong>{' '}
                      {recommendation.object_count}
                    </div>

                    <div>
                      <strong>PP:</strong>{' '}
                      {recommendation.pp ?? '-'}
                    </div>
                  </Col>
                </Row>

                <hr/>

                <div className="small">
                  <div>
                    <strong>Final:</strong>{' '}
                    {Number(
                      recommendation.final_score,
                    ).toFixed(4)}
                  </div>

                  <div>
                    <strong>Content:</strong>{' '}
                    {Number(
                      recommendation.content_similarity,
                    ).toFixed(4)}
                  </div>

                  <div>
                    <strong>Difficulty:</strong>{' '}
                    {Number(
                      recommendation.difficulty_score,
                    ).toFixed(4)}
                  </div>

                  <div>
                    <strong>Mod Preference:</strong>{' '}
                    {Number(
                      recommendation.mod_preference,
                    ).toFixed(4)}
                  </div>

                  <div>
                    <strong>Classifier:</strong>{' '}
                    {Number(
                      recommendation.classifier_score,
                    ).toFixed(4)}
                  </div>

                  <div>
                    <strong>PP Potential:</strong>{' '}
                    {Number(
                      recommendation.pp_potential,
                    ).toFixed(4)}
                  </div>
                </div>
              </Card.Body>
            </Card>
          </Col>
        ))}
      </Row>
    </>
  )
}