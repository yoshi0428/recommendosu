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
            ← Back to Recommendations
          </Button>
        </div>

        <h1 className="mb-4">
          About
        </h1>

        {/* Add your About page content here */}

      </Container>
    </div>
  )
}


export default About
