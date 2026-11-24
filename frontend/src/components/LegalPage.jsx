import { Container } from "react-bootstrap";
import { Link } from "react-router-dom";

// A link to another site, in a new tab.
export function External({ href, children }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

export function Section({ title, children }) {
  return (
    <section className="p-4 mb-4 rounded border bg-secondary bg-opacity-10 border-secondary">
      <h2 className="h4 mb-3">{title}</h2>
      {children}
    </section>
  );
}

export function Contact() {
  return (
    <Section title="Contact">
      <ul className="mb-0">
        <li>
          The{" "}
          <External href="https://discord.gg/Dh4TzKGGB7">
            recommendosu Discord server
          </External>
        </li>
        <li>
          <External href="https://github.com/yoshi0428/recommendosu/issues">
            GitHub issues
          </External>{" "}
          (these are public)
        </li>
        <li>Discord DMs at yoshiekn</li>
        <li>
          osu!pm at{" "}
          <External href="https://osu.ppy.sh/users/10961031">yoshi0428</External>
        </li>
      </ul>
    </Section>
  );
}

// The frame of the Terms and Privacy pages.
// otherPage: the {to, label} of the other legal page.
function LegalPage({ title, effective, otherPage, children }) {
  return (
    <div className="bg-dark text-light min-vh-100">
      <Container className="py-5">
        <nav className="page-nav mb-4" aria-label="Pages">
          <Link to="/" className="btn btn-outline-secondary">
            <span className="page-nav-long">Back to&nbsp;</span>
            Recommendations
          </Link>
          <Link to={otherPage.to} className="btn btn-outline-secondary">
            {otherPage.label}
          </Link>
        </nav>

        <h1 className="h2 mb-1">{title}</h1>
        <p className="text-body-secondary mb-4">Effective: {effective}</p>

        {children}
      </Container>
    </div>
  );
}

export default LegalPage;
