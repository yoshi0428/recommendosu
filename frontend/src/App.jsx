import { lazy, Suspense } from "react";
import { Container, Spinner } from "react-bootstrap";
import { Routes, Route, Navigate } from "react-router-dom";

import { useAuth } from "./hooks/useAuth";
import useTheme from "./hooks/useTheme";

// Each page is its own chunk, so a visitor only downloads the page they land
// on (signed-out visitors never load the recommendations UI).
const LoginPage = lazy(() => import("./pages/LoginPage"));
// Started now rather than when first rendered, so it downloads alongside the
// auth check instead of after it. Signed-out visitors fetch it unused.
const recommendationsPageImport = import("./pages/RecommendationsPage");
const RecommendationsPage = lazy(() => recommendationsPageImport);
const About = lazy(() => import("./pages/About"));

function App() {
  const { user, loading, logout } = useAuth();

  const { theme } = useTheme();

  const loadingScreen = (label) => (
    <div
      className={
        theme === "dark"
          ? "bg-dark text-light min-vh-100"
          : "bg-body text-body min-vh-100"
      }
    >
      <Container className="py-5 text-center">
        <Spinner animation="border" />

        <div className="mt-3">{label}</div>
      </Container>
    </div>
  );

  if (loading) {
    return loadingScreen("Checking authentication...");
  }

  return (
    <Suspense fallback={loadingScreen("Loading...")}>
      <Routes>
        <Route path="/about" element={<About />} />

        <Route
          path="/"
          element={
            user ? (
              <RecommendationsPage user={user} logout={logout} />
            ) : (
              <LoginPage />
            )
          }
        />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}

export default App;
