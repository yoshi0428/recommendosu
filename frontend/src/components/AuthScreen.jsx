import {
  Button,
  Container,
} from 'react-bootstrap'

import {login} from '../api/client'

function AuthScreen() {
  return (
    <Container className="py-5">
      <div className="text-center">
        <h1 className="mb-3">
          osu! Beatmap Recommender
        </h1>

        <p className="text-muted mb-4">
          Log in with your osu! account to get
          personalized beatmap recommendations.
        </p>

        <Button
          variant="primary"
          size="lg"
          onClick={login}
        >
          Log in with osu!
        </Button>
      </div>
    </Container>
  )
}

export default AuthScreen