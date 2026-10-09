import { useEffect, useRef, useState } from "react";
import { Alert, Spinner } from "react-bootstrap";
import { useVirtualizer } from "@tanstack/react-virtual";
import RecommendationRow from "./RecommendationRow";

function RecommendationBody({
  recommendations,
  loading,
  onSelectRecommendation,
}) {
  const [audioVolume, setAudioVolume] = useState(0.01);
  const scrollRef = useRef(null);

  // TanStack Virtual can't be optimized by the React Compiler, which this
  // project doesn't use, so the warning doesn't apply.
  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: recommendations.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 70,
    overscan: 10,
  });

  useEffect(() => {
    rowVirtualizer.measure();
  }, [rowVirtualizer, recommendations.length]);

  if (loading) {
    return (
      <div
        className="d-flex flex-column align-items-center justify-content-center flex-grow-1"
        style={{ minHeight: 0 }}
      >
        <Spinner animation="border" />
        <div className="mt-3 text-muted">Generating recommendations...</div>
      </div>
    );
  }

  if (recommendations.length === 0) {
    return (
      <div className="flex-grow-1 d-flex flex-column">
        <Alert variant="secondary" className="mb-0">
          No recommendations yet. Apply some settings and run the recommender.
        </Alert>
      </div>
    );
  }

  const virtualRows = rowVirtualizer.getVirtualItems();

  const firstRow = virtualRows[0];
  const lastRow = virtualRows[virtualRows.length - 1];

  const topPadding = firstRow?.start ?? 0;
  const bottomPadding = lastRow
    ? rowVirtualizer.getTotalSize() - lastRow.end
    : 0;

  return (
    <div
      ref={scrollRef}
      className="recommendation-scroll flex-grow-1 overflow-auto position-relative"
      style={{ minHeight: 0 }}
    >
      {/* table-responsive wrapper handles smooth horizontal scrolling when zoomed in */}
      <div className="w-100">
        <table
          className="table table-hover table-sm align-middle mb-0"
          style={{
            minWidth: "850px",
            width: "100%",
          }}
        >
          <thead className="sticky-top bg-body">
            <tr>
              <th className="text-center">Artist - Title</th>
              <th className="text-center">PP</th>
              <th className="text-center">Mods</th>
              <th className="text-center">Stars</th>
              <th className="text-center">BPM</th>
              <th className="text-center">CS</th>
              <th className="text-center">AR</th>
              <th className="text-center">OD</th>
              <th className="text-center">Length</th>
              <th className="text-center">Combo</th>
            </tr>
          </thead>

          <tbody>
            {topPadding > 0 && (
              <tr>
                <td
                  colSpan="10"
                  style={{
                    height: `${topPadding}px`,
                    padding: 0,
                    border: 0,
                  }}
                />
              </tr>
            )}

            {virtualRows.map((virtualRow) => {
              const recommendation = recommendations[virtualRow.index];

              return (
                <RecommendationRow
                  key={
                    recommendation.variant_id ??
                    recommendation.beatmap_id ??
                    virtualRow.index
                  }
                  recommendation={recommendation}
                  onSelectRecommendation={onSelectRecommendation}
                  audioVolume={audioVolume}
                  setAudioVolume={setAudioVolume}
                  virtualRow={virtualRow}
                  rowVirtualizer={rowVirtualizer}
                />
              );
            })}

            {bottomPadding > 0 && (
              <tr>
                <td
                  colSpan="10"
                  style={{
                    height: `${bottomPadding}px`,
                    padding: 0,
                    border: 0,
                  }}
                />
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default RecommendationBody;
