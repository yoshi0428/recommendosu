import { useEffect, useRef } from "react";
import { Alert, Spinner } from "react-bootstrap";
import { useVirtualizer } from "@tanstack/react-virtual";
import RecommendationRow from "./RecommendationRow";
import { useAudioPreview } from "./AudioPreview";

function RecommendationBody({
  recommendations,
  totalCount,
  onVisibleRangeChange,
  loading,
  onSelectRecommendation,
}) {
  const scrollRef = useRef(null);
  const { playerOpen } = useAudioPreview();

  // TanStack Virtual can't be optimized by the React Compiler, which this
  // project doesn't use, so the warning doesn't apply.
  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: totalCount,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 70,
    overscan: 10,
  });

  useEffect(() => {
    rowVirtualizer.measure();
  }, [rowVirtualizer, totalCount]);

  const virtualRows = rowVirtualizer.getVirtualItems();
  const firstIndex = virtualRows[0]?.index;
  const lastIndex = virtualRows[virtualRows.length - 1]?.index;

  // Rows past the first page are fetched from the server as they scroll in.
  useEffect(() => {
    if (firstIndex !== undefined) {
      onVisibleRangeChange(firstIndex, lastIndex);
    }
  }, [firstIndex, lastIndex, onVisibleRangeChange]);

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

  if (totalCount === 0) {
    return (
      <div className="flex-grow-1 d-flex flex-column">
        <Alert variant="secondary" className="mb-0">
          No recommendations yet. Apply some settings and run the recommender.
        </Alert>
      </div>
    );
  }

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
      // Room to scroll the last rows out from under the audio player.
      style={{ minHeight: 0, paddingBottom: playerOpen ? "5rem" : 0 }}
    >
      {/* table-responsive wrapper handles smooth horizontal scrolling when zoomed in */}
      <div className="w-100">
        <table className="recommendation-table table table-hover table-sm align-middle mb-0">
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

              if (recommendation === undefined) {
                return (
                  <tr
                    key={`loading-${virtualRow.index}`}
                    data-index={virtualRow.index}
                    ref={rowVirtualizer.measureElement}
                  >
                    <td
                      colSpan="10"
                      className="text-center text-muted"
                      style={{ height: "70px" }}
                    >
                      Loading...
                    </td>
                  </tr>
                );
              }

              return (
                <RecommendationRow
                  key={
                    recommendation.variant_id ??
                    recommendation.beatmap_id ??
                    virtualRow.index
                  }
                  recommendation={recommendation}
                  onSelectRecommendation={onSelectRecommendation}
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
