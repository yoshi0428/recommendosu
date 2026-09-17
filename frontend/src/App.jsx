import {Container, Spinner} from 'react-bootstrap'
import {Routes, Route, Navigate} from 'react-router-dom'

import LoginPage from './pages/LoginPage'
import RecommendationsPage from './pages/RecommendationsPage'
import About from './pages/About'

import {useAuth} from './hooks/useAuth'
import useTheme from './hooks/useTheme'

function App() {
  const {
    user,
    loading,
    logout,
  } = useAuth()

  const {theme} = useTheme()

  if (loading) {
    return (
      <div
        className={
          theme === 'dark'
            ? 'bg-dark text-light min-vh-100'
            : 'bg-light text-dark min-vh-100'
        }
      >
        <Container className="py-5 text-center">
          <Spinner animation="border"/>

          <div className="mt-3">
            Checking authentication...
          </div>
        </Container>
      </div>
    )
  }

  return (
    <Routes>
      <Route
        path="/about"
        element={<About/>}
      />

      <Route
        path="/"
        element={
          user ? (
            <RecommendationsPage
              user={user}
              logout={logout}
            />
          ) : (
            <LoginPage/>
          )
        }
      />

      <Route
        path="*"
        element={<Navigate to="/" replace/>}
      />
    </Routes>
  )
}


export default App
