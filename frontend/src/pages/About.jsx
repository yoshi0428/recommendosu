import {Button, Container} from 'react-bootstrap'
import {Link} from 'react-router-dom'

import useTheme from '../hooks/useTheme'


function About() {
  const {theme} = useTheme()

  return (
    <div
      className={
        theme === 'dark'
          ? 'bg-dark text-light min-vh-100'
          : 'bg-light text-dark min-vh-100'
      }
    >
      <Container className="py-5">

        <div className="mb-4">
          <Button
            as={Link}
            to="/"
            variant="outline-secondary"
          >
            Back to Recommendations
          </Button>
        </div>

        <h1 className="mb-4">
          About
        </h1>

        <p>You can exclude mods by clicking the checkbox twice to see a dash symbol. The unchecked mods will be part of
          mod combinations that may get recommended.</p>
        <p>You can also check multiple mods for the same combinatorial effect.</p>
        <p>Checking a single mod will result in only being recommended that single mod.</p>

        <p><b>If you need to contact me, do it via yoshi0428 at osu!pm or yoshiekn on Discord</b></p>

        <br></br>

        <div className="mb-4">
          <img
            src="GoT80k9H6Gd1x.gif"
            alt="quagsire"
            className="img-fluid d-block mx-auto"
            style={{maxWidth: '400px'}}
          />
        </div>

      </Container>
    </div>
  )
}


export default About
