import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Container } from "react-bootstrap";

import RecommendationBody from "../components/recommendations/RecommendationBody";
import { AudioPreviewProvider } from "../components/recommendations/AudioPreview";
import {
  cancelRecommendation,
  getRecommendationPage,
  getRecommendations,
} from "../api/client";

import {
  createDefaultSettings,
  normalizeSettings,
} from "../utils/recommendation";

import SiteHeader from "../components/SiteHeader.jsx";
import RecommendationSettingsModal from "../components/recommendations/RecommendationSettingsModal.jsx";

// Must match RECOMMENDATION_PAGE_SIZE in main.py, which also sizes the first
// page returned by POST /recommend.
const RECOMMENDATION_PAGE_SIZE = 1000;

const EMPTY_RESULT = {
  id: null,
  totalCount: 0,
  rows: [],
  version: 0,
};

function RecommendationsPage({ user, logout }) {
  // App only renders this page once the user has loaded, so their ID can
  // seed the initial settings directly.
  const [settings, setSettings] = useState(() => ({
    ...createDefaultSettings(),
    player_id: user?.player_id ?? null,
  }));

  // Full results can be millions of rows, so they stay on the server. `rows`
  // is a sparse array of length totalCount that pages are written into as
  // they load; `version` is bumped after each write so the table re-renders.
  const [result, setResult] = useState(EMPTY_RESULT);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedRecommendation, setSelectedRecommendation] = useState(null);

  // Reference to hold the active AbortController for requests
  const abortControllerRef = useRef(null);
  const recommendationIdRef = useRef(null);

  // Page requests in flight for the current result, and their AbortController.
  const loadingPagesRef = useRef(new Set());
  const pageAbortControllerRef = useRef(null);

  // Automatically hide the breakdown notification after 2 seconds
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

  const handleSubmit = async () => {
    // Cancel any existing request.
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    const recommendationId = crypto.randomUUID();

    abortControllerRef.current = controller;
    recommendationIdRef.current = recommendationId;

    setLoading(true);
    setError(null);

    try {
      const requestSettings = normalizeSettings(settings);

      console.log(
        "Normalized similarity weights:",
        requestSettings.similarity_feature_weights
      );

      const data = await getRecommendations(requestSettings, {
        signal: controller.signal,
        recommendationId,
      });

      if (controller.signal.aborted) {
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
        totalCount,
        rows,
        version: 0,
      });
    } catch (err) {
      if (
        err.name === "AbortError" ||
        err.code === "ERR_CANCELED" ||
        err.name === "CanceledError"
      ) {
        console.log("Recommendation request successfully cancelled.");
        return;
      }

      console.error("Recommendation request failed:", err);
      setError(err.message || "Failed to generate recommendations.");
      pageAbortControllerRef.current?.abort();
      setResult(EMPTY_RESULT);
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
        recommendationIdRef.current = null;
        setLoading(false);
      }
    }
  };

  // Fetch any pages overlapping [startIndex, endIndex] that are not loaded yet.
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

  const handleCancel = async () => {
    const controller = abortControllerRef.current;
    const recommendationId = recommendationIdRef.current;

    // Tell the backend to stop the running recommendation.
    if (recommendationId) {
      try {
        await cancelRecommendation(recommendationId);
      } catch (err) {
        console.error("Failed to send recommendation cancellation:", err);
      }
    }

    // Also abort the browser's request.
    if (controller) {
      controller.abort();
    }

    abortControllerRef.current = null;
    recommendationIdRef.current = null;
    setLoading(false);
  };

  return (
    <AudioPreviewProvider>
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
              user={user}
              logout={logout}
              settings={settings}
              updateSetting={updateSetting}
              updateNestedSetting={updateNestedSetting}
              onRunRecommendations={handleSubmit}
              onCancelRecommendations={handleCancel}
              loading={loading}
            />
          }
          logout={logout}
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
              />
            </div>
          </Container>
        </main>

        {/* Hidden on phones, where it would cover the results and audio player. */}
        {selectedRecommendation && (
          <div
            className="d-none d-md-block position-fixed bottom-0 start-50 translate-middle-x mb-3 shadow-lg"
            style={{
              zIndex: 1050,
              width: "80%",
            }}
          >
            <Alert
              variant="info"
              dismissible
              onClose={() => setSelectedRecommendation(null)}
              className="mb-0 border shadow-sm text-center"
            >
              <div className="fw-bold mb-2">
                Breakdown for {selectedRecommendation.artist} -{" "}
                {selectedRecommendation.title} [{selectedRecommendation.version}
                ]:
              </div>

              <div className="d-flex flex-wrap justify-content-center gap-3 small">
                <div>
                  <strong>Final:</strong>{" "}
                  {Number(selectedRecommendation.final_score).toFixed(4)}
                </div>

                <div>
                  <strong>Content:</strong>{" "}
                  {Number(selectedRecommendation.content_similarity).toFixed(4)}
                </div>

                <div>
                  <strong>Difficulty:</strong>{" "}
                  {Number(selectedRecommendation.difficulty_score).toFixed(4)}
                </div>

                <div>
                  <strong>Mod Preference:</strong>{" "}
                  {Number(selectedRecommendation.mod_preference).toFixed(4)}
                </div>

                <div>
                  <strong>Classifier:</strong>{" "}
                  {Number(selectedRecommendation.classifier_score).toFixed(4)}
                </div>

                <div>
                  <strong>PP Potential:</strong>{" "}
                  {Number(selectedRecommendation.pp_potential).toFixed(4)}
                </div>
              </div>
            </Alert>
          </div>
        )}
      </div>
    </AudioPreviewProvider>
  );
}

export default RecommendationsPage;
