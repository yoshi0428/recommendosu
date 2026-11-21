import { Component, useEffect } from "react";
import { Button, Container } from "react-bootstrap";

// Set before the one automatic reload, so a page that keeps failing to load
// shows the message instead of reloading forever.
const RELOAD_FLAG = "page-chunk-reload";

// A lazily loaded page whose file is gone, typically after a redeploy while
// the site was open: the old page asks for an old file name.
function isChunkLoadError(error) {
  const message = String(error?.message ?? "");
  return (
    error?.name === "ChunkLoadError" ||
    /dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(
      message
    ) ||
    // React.lazy() on a module without a default export (e.g. an empty file).
    /Element type is invalid|lazy: Expected the result of a dynamic import/i.test(
      message
    )
  );
}

function reloadFlagSet() {
  try {
    return sessionStorage.getItem(RELOAD_FLAG) === "1";
  } catch {
    return true; // no storage: never auto-reload, so it can't loop
  }
}

function setReloadFlag(value) {
  try {
    if (value) sessionStorage.setItem(RELOAD_FLAG, "1");
    else sessionStorage.removeItem(RELOAD_FLAG);
  } catch {
    // ignore
  }
}

// Rendered next to the page: its effect only runs once the page has loaded
// and rendered, so only then may a later failure reload again.
function PageLoaded() {
  useEffect(() => setReloadFlag(false), []);
  return null;
}

/**
 * Keeps a page that fails to load or render from leaving a blank screen.
 * A missing page file is fixed by one reload (the new deploy's files);
 * anything else shows a message with a way back to the recommendations.
 * App puts it inside the Suspense, with the path as its key, so it resets
 * on navigation.
 */
class PageErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error) {
    if (isChunkLoadError(error) && !reloadFlagSet()) {
      setReloadFlag(true);
      window.location.reload();
      return;
    }
    console.error(error);
  }

  render() {
    if (!this.state.error) {
      return (
        <>
          {this.props.children}
          <PageLoaded />
        </>
      );
    }

    return (
      <div className="bg-dark text-light min-vh-100">
        <Container className="py-5 text-center">
          <h3 className="mb-3">This page didn't load</h3>
          <p className="mb-4">
            The site may have just been updated. Reloading usually fixes it.
          </p>
          <div className="d-flex justify-content-center gap-2">
            <Button variant="outline-secondary" href="/">
              Back to Recommendations
            </Button>
            <Button variant="primary" onClick={() => window.location.reload()}>
              Reload
            </Button>
          </div>
        </Container>
      </div>
    );
  }
}

export default PageErrorBoundary;
