import { Container, Navbar } from 'react-bootstrap'

function App() {
  return (
    <>
      <Navbar bg="dark" variant="dark">
        <Container>
          <Navbar.Brand>osu! Beatmap Recommender</Navbar.Brand>
        </Container>
      </Navbar>

      <Container className="py-5">
        <h1>osu! Beatmap Recommender</h1>
        <p className="text-muted">
          Personalized beatmap recommendations.
        </p>
      </Container>
    </>
  )
}

export default App