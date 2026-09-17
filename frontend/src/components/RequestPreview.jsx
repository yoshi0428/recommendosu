import {Card} from 'react-bootstrap'

function RequestPreview({settings}) {
  return (
    <Card className="mb-4">
      <Card.Header> <strong>Request Preview</strong>
      </Card.Header>
      <Card.Body>
        <pre
          className="mb-0"
          style={{
            maxHeight: '500px',
            overflow: 'auto',
            fontSize: '0.85rem',
          }}
        >
          {JSON.stringify(settings, null, 2)}
        </pre>
      </Card.Body>
    </Card>
  )
}

export default RequestPreview
