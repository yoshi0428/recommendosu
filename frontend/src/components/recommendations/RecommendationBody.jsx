import { useEffect, useRef } from "react";
import { Alert, Spinner } from "react-bootstrap";
import { useVirtualizer } from "@tanstack/react-virtual";
import RecommendationRow from "./RecommendationRow";
import { useAudioPreview } from "./AudioPreview";

const COLUMNS = [
  "Artist - Title",
  "PP",
  "Mods",
  "Stars",
  "BPM",
  "CS",
  "AR",
  "OD",
  "Length",
  "Combo",
];

// The estimated height of a row in pixels, before the table measures it.
const ROW_HEIGHT = 70;

// An empty row that takes the place of the rows outside the visible window.
function SpacerRow({ height }) {
  return (
    <tr>
      <td
        colSpan={COLUMNS.length}
        style={{ height: `${height}px`, padding: 0, border: 0 }}
      />
    </tr>
  );
}

function RecommendationBody({
  recommendations,
  totalCount,
  onVisibleRangeChange,
  loading,
  onSelectRecommendation,
}) {
  const scrollRef = useRef(null);
  const { playerOpen } = useAudioPreview();

  // The React Compiler cannot optimize TanStack Virtual. This project does not
  // use the React Compiler, so the warning does not apply.
  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: totalCount,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 10,
  });

  useEffect(() => {
    rowVirtualizer.measure();
  }, [rowVirtualizer, totalCount]);

  const virtualRows = rowVirtualizer.getVirtualItems();
  const firstRow = virtualRows[0];
  const lastRow = virtualRows[virtualRows.length - 1];
  const firstIndex = firstRow?.index;
  const lastIndex = lastRow?.index;

  // When rows after the first page scroll into view, fetch them from the server.
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

  const topPadding = firstRow?.start ?? 0;
  const bottomPadding = lastRow
    ? rowVirtualizer.getTotalSize() - lastRow.end
    : 0;

  return (
    <div
      ref={scrollRef}
      className="recommendation-scroll flex-grow-1 overflow-auto position-relative"
      // Space to scroll the last rows out from under the audio player.
      style={{ minHeight: 0, paddingBottom: playerOpen ? "5rem" : 0 }}
    >
      <div className="w-100">
        <table className="recommendation-table table table-hover table-sm align-middle mb-0">
          <thead className="sticky-top bg-body">
            <tr>
              {COLUMNS.map((column) => (
                <th key={column} className="text-center">
                  {column}
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {topPadding > 0 && <SpacerRow height={topPadding} />}

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
                      colSpan={COLUMNS.length}
                      className="text-center text-muted"
                      style={{ height: `${ROW_HEIGHT}px` }}
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

            {bottomPadding > 0 && <SpacerRow height={bottomPadding} />}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default RecommendationBody;
