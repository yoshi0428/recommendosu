import { lazy, Suspense } from "react";
import { Container, Spinner } from "react-bootstrap";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";

import PageErrorBoundary from "./components/PageErrorBoundary";
import { useAuth } from "./hooks/useAuth";

// Each page is a separate chunk, so a visitor downloads only the page that
// they open. (A signed-out visitor never loads the recommendations UI.)
const AuthScreen = lazy(() => import("./components/AuthScreen"));
// This download starts now, not at the first render, so it runs at the same
// time as the auth check, not after it. A signed-out visitor also downloads
// it, but does not use it.
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
      {/* If a page fails to load, show a way back, not a blank screen. */}
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
