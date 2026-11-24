import { useEffect, useState } from "react";
import { Alert, Button, Container, Spinner } from "react-bootstrap";
import { Link } from "react-router-dom";

import { getChangelog } from "../api/client";

// "2026-11-01" -> "November 1, 2026". The date is parsed and shown as UTC, so
// the day does not change with the time zone of the visitor.
const formatDate = (date) =>
  new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });

// The entries are plain text. The URLs in them become links. A ".", "," or ")"
// at the end of a URL stays outside the link.
const URL_PATTERN = /(https?:\/\/[^\s)]*[^\s).,!?;:])/;

const withLinks = (text) =>
  text.split(URL_PATTERN).map((part, index) =>
    // With a capture group, split() puts the URLs at the odd indexes.
    index % 2 === 1 ? (
      <a key={index} href={part} target="_blank" rel="noopener noreferrer">
        {part}
      </a>
    ) : (
      part
    )
  );

// A public page, like About. It shows beatmap_recommender/changelog.json from GET /api/v1/changelog.
function Changelog() {
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getChangelog()
      .then(setEntries)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="bg-dark text-light min-vh-100">
      <Container className="py-5">
        <div className="page-nav mb-4">
          <Button as={Link} to="/" variant="outline-secondary">
            <span className="page-nav-long">Back to&nbsp;</span>
            Recommendations
          </Button>
          <Button as={Link} to="/about" variant="outline-secondary">
            About
          </Button>
        </div>

        <h2 className="mb-4">Changelog</h2>

        {error && <Alert variant="danger">{error}</Alert>}

        {!error && entries === null && <Spinner animation="border" />}

        {entries?.length === 0 && <p>No changes posted yet.</p>}

        {entries?.map((entry) => (
          <section
            key={`${entry.date}-${entry.title}`}
            className="p-4 mb-4 rounded border bg-secondary bg-opacity-10 border-secondary"
          >
            <h3 className="h5 mb-1">{entry.title}</h3>
            <div className="text-body-secondary small mb-3">
              <time dateTime={entry.date}>{formatDate(entry.date)}</time>
            </div>
            <ul className="mb-0">
              {entry.changes.map((change, index) => (
                <li key={index}>{withLinks(change)}</li>
              ))}
            </ul>
          </section>
        ))}
      </Container>
    </div>
  );
}

export default Changelog;
