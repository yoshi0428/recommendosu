import { lazy, Suspense } from "react";
import { Container, Spinner } from "react-bootstrap";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";

import PageErrorBoundary from "./components/PageErrorBoundary";
import { useAuth } from "./hooks/useAuth";

// Each page is its own chunk, so a visitor only downloads the page they land
// on (signed-out visitors never load the recommendations UI).
const AuthScreen = lazy(() => import("./components/AuthScreen"));
// Started now rather than when first rendered, so it downloads alongside the
// auth check instead of after it. Signed-out visitors fetch it unused.
const recommendationsPageImport = import("./pages/RecommendationsPage");
const RecommendationsPage = lazy(() => recommendationsPageImport);
const About = lazy(() => import("./pages/About"));
const Changelog = lazy(() => import("./pages/Changelog"));

function App() {
  const { user, loading, logout } = useAuth();
  const { pathname } = useLocation();

  const loadingScreen = (label) => (
    <div className="bg-dark text-light min-vh-100">
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
      {/* A page that fails to load shows a way back instead of a blank screen. */}
      <PageErrorBoundary key={pathname}>
        <Routes>
          <Route path="/about" element={<About />} />
          <Route path="/changelog" element={<Changelog />} />

          <Route
            path="/"
            element={
              user ? (
                <RecommendationsPage user={user} logout={logout} />
              ) : (
                <AuthScreen />
              )
            }
          />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </PageErrorBoundary>
    </Suspense>
  );
}

export default App;
