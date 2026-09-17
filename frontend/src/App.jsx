import {Container, Spinner} from 'react-bootstrap'

import LoginPage from './pages/LoginPage'
import RecommendationsPage from './pages/RecommendationsPage'

import {useAuth} from './hooks/useAuth'


function App() {
  const {
    user,
    loading,
    logout,
  } = useAuth()

  if (loading) {
    return (
      <Container className="py-5 text-center">
        <Spinner animation="border"/>

        <div className="mt-3">
          Checking authentication...
        </div>
      </Container>
    )
  }

  if (!user) {
    return <LoginPage/>
  }

  return (
    <RecommendationsPage
      user={user}
      logout={logout}
    />
  )
}


export default App
