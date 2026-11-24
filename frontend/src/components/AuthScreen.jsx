import { Button, Container } from "react-bootstrap";
import { Link } from "react-router-dom";

import { login } from "../api/client";

function AuthScreen() {
  return (
    <div
      className="bg-dark text-light min-vh-100 d-flex align-items-center"
    >
      <Container className="py-5">
        <div className="text-center">
          <img src="/Osu!_Logo_2016.png" alt="osu! logo" className="mb-4" />

          <h1 className="mb-3">osu! Beatmap Recommender</h1>

          <p className="text-muted mb-2">
            Log in with your osu! account to get personalized beatmap
            recommendations.
          </p>

          <p className="text-muted mb-4">
            The login tells the site who you are. Thus it can fill in your
            player ID and get your top and recent plays. The site reads only
            public data from osu!, and it never changes anything on your
            account. It stores your clicks and previews of recommendations to
            improve them. The
            osu! requests of all users together stay under the limit of 60
            requests per minute that osu! asks for. To see how it works, look
            at the{" "}
            <a
              href="https://github.com/yoshi0428/osu-predict"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub repository
            </a>{" "}
            here :)
          </p>

          <Button variant="primary" size="lg" onClick={login}>
            Log in with osu!
          </Button>

          <p className="text-muted small mt-3 mb-0">
            By logging in, you agree to the{" "}
            <Link to="/terms">Terms of Service</Link> and the{" "}
            <Link to="/privacy">Privacy Policy</Link>.
          </p>
        </div>
      </Container>
    </div>
  );
}

export default AuthScreen;
