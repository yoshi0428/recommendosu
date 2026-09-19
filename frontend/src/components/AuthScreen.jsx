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
          <img src="/Osu!_Logo_2016.png" alt="osu! logo" className="mb-4"/>

          <h1 className="mb-3">
            osu! Beatmap Recommender
          </h1>

          <p className={'text-muted mb-2'}>
            Log in with your osu! account to get personalized beatmap recommendations.
          </p>

          <p className={'text-muted mb-4'}>
            Logging in is required so recommendations can be generated using your own osu! account.
            This avoids overloading a single shared OAuth token when multiple people are using the site.
            If this still doesn't convince you, you can have a look at the <a
            href="https://github.com/yoshi0428/osu-predict"
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub repository
          </a> here :)
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