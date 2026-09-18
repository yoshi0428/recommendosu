import {
  Button,
  Container,
} from 'react-bootstrap'

import {login} from '../api/client'
import useTheme from '../hooks/useTheme'

function AuthScreen() {
  const {theme} = useTheme()

  const isDark = theme === 'dark'

  return (
    <div
      className={
        isDark
          ? 'bg-dark text-light min-vh-100 d-flex align-items-center'
          : 'bg-light text-dark min-vh-100 d-flex align-items-center'
      }
    >
      <Container className="py-5">
        <div className="text-center">
          <h1 className="mb-3">
            osu! Beatmap Recommender
          </h1>

          <p
            className={
              isDark
                ? 'text-secondary mb-2'
                : 'text-muted mb-2'
            }
          >
            Log in with your osu! account to get
            personalized beatmap recommendations.
          </p>

          <p
            className={
              isDark
                ? 'text-secondary mb-4'
                : 'text-muted mb-4'
            }
          >
            Logging in is required so recommendations
            can be generated using your own osu! account.
            This helps avoid putting too much load on a
            single shared OAuth token when multiple people
            are using the site.
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
    </div>
  )
}

export default AuthScreen