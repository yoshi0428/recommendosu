import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Container } from "react-bootstrap";

import RecommendationBody from "../components/recommendations/RecommendationBody";
import { AudioPreviewProvider } from "../components/recommendations/AudioPreview";
import {
  cancelRecommendation,
  getRecommendationPage,
  getRecommendations,
  sendFeedback,
} from "../api/client";

import { createDefaultSettings } from "../utils/recommendation";

import SiteHeader from "../components/SiteHeader.jsx";
import RecommendationSettingsModal from "../components/recommendations/RecommendationSettingsModal.jsx";

import "./RecommendationsPage.css";

// This must be the same as RECOMMENDATION_PAGE_SIZE in main.py, which also
// sets the size of the first page that POST /recommend returns.
const RECOMMENDATION_PAGE_SIZE = 1000;

// The scores of a variant that the breakdown shows when the user clicks a row.
const SCORE_BREAKDOWN = [
  ["Final", "final_score"],
  ["Content", "content_similarity"],
  ["Difficulty", "difficulty_score"],
  ["Mod Preference", "mod_preference"],
  ["Classifier", "classifier_score"],
];

const EMPTY_RESULT = {
  id: null,
  playerId: null,
  totalCount: 0,
  rows: [],
  version: 0,
};

function RecommendationsPage({ user, logout }) {
  // App renders this page only after the user loaded, so the initial settings
  // can use the ID of the user directly.
  const [settings, setSettings] = useState(() => ({
    ...createDefaultSettings(),
    player_id: user?.player_id ?? null,
  }));

  // A full result can have millions of rows, so it stays on the server. `rows`
  // is a sparse array of length totalCount. Each page goes into it when the
  // page loads. `version` goes up after each write, so that the table renders
  // again.
  const [result, setResult] = useState(EMPTY_RESULT);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedRecommendation, setSelectedRecommendation] = useState(null);

  // The running recommendation request as { controller, id }, or null if no
  // request runs. `loading` is true exactly when this is not null.
  const runRef = useRef(null);

  // The page requests that run for the current result, and their AbortController.
  const loadingPagesRef = useRef(new Set());
  const pageAbortControllerRef = useRef(null);

  // Hide the breakdown automatically after 2 seconds.
  useEffect(() => {
    if (!selectedRecommendation) {
      return;
    }

    const timer = setTimeout(() => {
      setSelectedRecommendation(null);
    }, 2000);

    return () => clearTimeout(timer);
  }, [selectedRecommendation]);

  const updateSetting = (key, value) => {
    setSettings((current) => ({
      ...current,
      [key]: value,
    }));
  };

  const updateNestedSetting = (key, name, value) => {
    setSettings((current) => ({
      ...current,
      [key]: {
        ...current[key],
        [name]: value,
      },
    }));
  };

  // Move to "no request runs", but only if `run` is still the current run.
  // An older run must not stop the spinner of a newer run.
  const finishRun = (run) => {
    if (runRef.current === run) {
      runRef.current = null;
      setLoading(false);
    }
  };

  const handleSubmit = async () => {
    // Cancel the request that runs now, if there is one.
    runRef.current?.controller.abort();

    const run = { controller: new AbortController(), id: crypto.randomUUID() };
    const { controller, id: recommendationId } = run;
    runRef.current = run;

    setLoading(true);
    setError(null);

    try {
      const data = await getRecommendations(settings, {
        signal: controller.signal,
        recommendationId,
      });

      // null means that the backend confirmed the cancellation before the
      // browser aborted the request. In both cases, keep the previous results.
      if (data === null || controller.signal.aborted) {
        return;
      }

      const firstPage = Array.isArray(data?.recommendations)
        ? data.recommendations
        : [];
      const totalCount = data?.total_count ?? firstPage.length;

      pageAbortControllerRef.current?.abort();
      pageAbortControllerRef.current = new AbortController();
      loadingPagesRef.current = new Set();

      const rows = new Array(totalCount);
      firstPage.forEach((recommendation, index) => {
        rows[index] = recommendation;
      });

      setResult({
        id: data?.recommendation_id ?? recommendationId,
        // The user can change the settings after the run, so keep the player here.
        playerId: data?.player_id ?? settings.player_id,
        totalCount,
        rows,
        version: 0,
      });
    } catch (err) {
      if (err.name === "AbortError") {
        return;
      }

      console.error("Recommendation request failed:", err);
      setError(err.message || "Failed to generate recommendations.");
      pageAbortControllerRef.current?.abort();
      setResult(EMPTY_RESULT);
    } finally {
      finishRun(run);
    }
  };

  // Fetch the pages in [startIndex, endIndex] that did not load yet.
  const loadRange = useCallback(
    (startIndex, endIndex) => {
      const { id, totalCount, rows } = result;

      if (!id || totalCount === 0) {
        return;
      }

      const loadingPages = loadingPagesRef.current;
      const signal = pageAbortControllerRef.current?.signal;
      const firstPage = Math.floor(startIndex / RECOMMENDATION_PAGE_SIZE);
      const lastPage = Math.floor(
        Math.min(endIndex, totalCount - 1) / RECOMMENDATION_PAGE_SIZE
      );

      for (let page = firstPage; page <= lastPage; page++) {
        const offset = page * RECOMMENDATION_PAGE_SIZE;

        if (rows[offset] !== undefined || loadingPages.has(page)) {
          continue;
        }

        loadingPages.add(page);

        getRecommendationPage(id, offset, RECOMMENDATION_PAGE_SIZE, { signal })
          .then((data) => {
            data.recommendations.forEach((recommendation, index) => {
              rows[offset + index] = recommendation;
            });

            setResult((current) =>
              current.id === id
                ? { ...current, version: current.version + 1 }
                : current
            );
          })
          .catch((err) => {
            if (err.name !== "AbortError") {
              console.error("Recommendation page request failed:", err);
              setError(err.message || "Failed to load recommendations.");
            }
          })
          .finally(() => {
            loadingPages.delete(page);
          });
      }
    },
    [result]
  );

  // Log a click or a preview of a row.
  const handleFeedback = useCallback(
    (eventType, recommendation) => {
      const { id, playerId, rows } = result;
      const position = rows.indexOf(recommendation);

      // The row is from an earlier result, so its position is not known.
      if (!id || position === -1) {
        return;
      }

      sendFeedback({
        event_type: eventType,
        recommendation_id: id,
        variant_id: recommendation.variant_id,
        position,
        for_player_id: playerId,
        final_score: recommendation.final_score,
      });
    },
    [result]
  );

  const handleCancel = async () => {
    const run = runRef.current;
    if (!run) {
      return;
    }

    // Tell the backend to stop the running recommendation.
    try {
      await cancelRecommendation(run.id);
    } catch (err) {
      console.error("Failed to send recommendation cancellation:", err);
    }

    // Also abort the request of the browser.
    run.controller.abort();
    finishRun(run);
  };

  const handleLogout = async () => {
    try {
      await logout();
    } catch (err) {
      setError(err.message || "Failed to log out.");
    }
  };

  return (
    <AudioPreviewProvider playlist={result.rows} onFeedback={handleFeedback}>
      <div
        className="recommendations-page d-flex flex-column position-relative"
        style={{
          height: "100dvh",
          overflow: "hidden",
        }}
      >
        <SiteHeader
          settings={settings}
          updateSetting={updateSetting}
          onRunRecommendations={handleSubmit}
          onCancelRecommendations={handleCancel}
          loading={loading}
          advancedSettingsButton={
            <RecommendationSettingsModal
              settings={settings}
              updateSetting={updateSetting}
              updateNestedSetting={updateNestedSetting}
              onRunRecommendations={handleSubmit}
              onCancelRecommendations={handleCancel}
              loading={loading}
            />
          }
          logout={handleLogout}
        />

        <main
          className="recommendations-main flex-grow-1 d-flex flex-column overflow-hidden"
          style={{ minHeight: 0 }}
        >
          <Container
            fluid
            className="recommendations-container px-2 px-md-4 py-2 flex-grow-1 d-flex flex-column overflow-hidden"
            style={{ minHeight: 0 }}
          >
            {error && (
              <Alert
                variant="danger"
                dismissible
                onClose={() => setError(null)}
                className="flex-shrink-0 mb-2"
              >
                {error}
              </Alert>
            )}

            <div
              className="flex-grow-1 d-flex flex-column overflow-hidden"
              style={{ minHeight: 0 }}
            >
              <RecommendationBody
                recommendations={result.rows}
                totalCount={result.totalCount}
                onVisibleRangeChange={loadRange}
                loading={loading}
                onSelectRecommendation={setSelectedRecommendation}
                onFeedback={handleFeedback}
              />
            </div>
          </Container>
        </main>

        {/* At the bottom right, next to the audio player. Small screens hide
            it (see RecommendationsPage.css). */}
        {selectedRecommendation && (
          <div className="score-breakdown shadow-lg">
            <Alert
              variant="info"
              dismissible
              onClose={() => setSelectedRecommendation(null)}
              className="mb-0 border shadow-sm text-center"
            >
              <div className="fw-bold mb-2">
                {`Breakdown for ${selectedRecommendation.artist} - ${selectedRecommendation.title} [${selectedRecommendation.version}]:`}
              </div>

              <div className="d-flex flex-wrap justify-content-center gap-3 small">
                {SCORE_BREAKDOWN.map(([label, key]) => (
                  <div key={key}>
                    <strong>{label}:</strong>{" "}
                    {Number(selectedRecommendation[key]).toFixed(4)}
                  </div>
                ))}
              </div>
            </Alert>
          </div>
        )}
      </div>
    </AudioPreviewProvider>
  );
}

export default RecommendationsPage;
