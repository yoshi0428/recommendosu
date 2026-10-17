import "./RecommendationRow.css";

import { Spinner } from "react-bootstrap";
import { PauseFill, PlayFill } from "react-bootstrap-icons";

import { useAudioPreview } from "./AudioPreview";

// helper function to format seconds into mm:ss or hh:mm:ss
const formatDuration = (totalSeconds) => {
  if (totalSeconds == null || isNaN(totalSeconds)) return "—";
  const seconds = Math.round(totalSeconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;

  const pad = (num) => String(num).padStart(2, "0");

  if (hours > 0) {
    return `${hours}:${pad(minutes)}:${pad(remainingSeconds)}`;
  } else {
    return `${minutes}:${pad(remainingSeconds)}`;
  }
};

function RecommendationRow({
  recommendation,
  onSelectRecommendation,
  virtualRow,
  rowVirtualizer,
}) {
  const {
    beatmap_id,
    beatmapset_id,
    artist,
    title,
    version,
    creator,
    mods,
    status,
    star_rating,
    bpm,
    circle_size,
    ar,
    od,
    length_seconds,
    max_combo,
    pp,
  } = recommendation;

  const {
    activeKey,
    loadingKey,
    isPlaying: previewPlaying,
    togglePreview,
  } = useAudioPreview();
  const previewKey = recommendation.variant_id ?? beatmap_id;
  const isPlaying = activeKey === previewKey && previewPlaying;
  const isLoading = loadingKey === previewKey;

  const beatmapUrl = beatmap_id ? `https://osu.ppy.sh/b/${beatmap_id}` : "#";

  const coverUrl = beatmap_id
    ? `https://assets.ppy.sh/beatmaps/${beatmapset_id}/covers/list.jpg`
    : null;

  // Keep the play/pause overlay visible while loading or playing.
  const overlayHidden = coverUrl && !isPlaying && !isLoading;

  return (
    <tr
      data-index={virtualRow.index}
      ref={(node) => {
        rowVirtualizer.measureElement(node);
      }}
      onClick={() => onSelectRecommendation?.(recommendation)}
      style={{ cursor: "pointer" }}
      title="Click to view score breakdown"
    >
      <td className="text-start" style={{ width: "40%" }}>
        <div className="d-flex align-items-center gap-2 gap-md-3 text-start">
          <div
            className="recommendation-cover rounded flex-shrink-0 shadow-sm position-relative overflow-hidden bg-secondary"
            style={{ cursor: "pointer" }}
            onClick={(e) => {
              e.stopPropagation();
              togglePreview(previewKey, { artist, title, creator });
            }}
          >
            {coverUrl && (
              <img
                src={coverUrl}
                alt=""
                width="104"
                height="58"
                className="w-100 h-100 object-fit-cover"
                loading="lazy"
                onError={(e) => {
                  e.currentTarget.style.display = "none";
                }}
              />
            )}

            <div
              className="recommendation-cover-overlay position-absolute top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center"
              style={{
                backgroundColor: "rgba(0, 0, 0, 0.45)",
                opacity: overlayHidden ? 0 : 1,
                transition: "opacity 0.15s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.opacity = 1;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.opacity = overlayHidden ? 0 : 1;
              }}
            >
              <span
                className="text-white"
                style={{
                  fontSize: "1.5rem",
                  lineHeight: 1,
                  textShadow: "0 1px 3px rgba(0, 0, 0, 0.5)",
                }}
              >
                {isLoading ? (
                  <Spinner
                    animation="border"
                    size="sm"
                    variant="light"
                    role="status"
                    aria-label="Loading preview"
                  />
                ) : isPlaying ? (
                  <PauseFill
                    size={24}
                    className="text-white"
                    style={{
                      filter: "drop-shadow(0 1px 2px rgba(0, 0, 0, 0.5))",
                    }}
                  />
                ) : (
                  <PlayFill
                    size={24}
                    className="text-white"
                    style={{
                      filter: "drop-shadow(0 1px 2px rgba(0, 0, 0, 0.5))",
                    }}
                  />
                )}
              </span>
            </div>
          </div>

          <div className="text-break" style={{ minWidth: 0 }}>
            <a
              href={beatmapUrl}
              target="_blank"
              rel="noreferrer"
              className="text-body d-block"
              style={{ textDecoration: "none" }}
              onMouseEnter={(e) => {
                e.currentTarget.style.textDecoration = "underline";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.textDecoration = "none";
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <strong
                className={`text-break d-block${
                  status ? ` beatmap-status-${status}` : ""
                }`}
              >
                {title
                  ? `${artist} - ${title} [${version}]`
                  : `Beatmap ${beatmap_id}`}
              </strong>
            </a>

            {/* Stats shown under the title on phones, where the stat columns are hidden */}
            <div className="recommendation-mobile-stats small text-body-secondary">
              <span className="fw-semibold text-body">
                {pp != null ? `${Number(pp).toFixed(0)}pp` : "—"}
              </span>
              <span>{mods || "NM"}</span>
              <span>
                {star_rating != null
                  ? `${Number(star_rating).toFixed(2)}★`
                  : "—"}
              </span>
              <span>{bpm != null ? `${Number(bpm).toFixed(0)} BPM` : "—"}</span>
              <span>
                CS {circle_size != null ? Number(circle_size).toFixed(1) : "—"}
                {" · "}AR {ar != null ? Number(ar).toFixed(1) : "—"}
                {" · "}OD {od != null ? Number(od).toFixed(1) : "—"}
              </span>
              <span>{formatDuration(length_seconds)}</span>
              <span>
                {max_combo != null ? `${max_combo.toLocaleString()}x` : "—"}
              </span>
            </div>
          </div>
        </div>
      </td>

      {/* Core stats visible on all screens */}
      <td className="text-center recommendation-stat">
        {pp != null ? Number(pp).toFixed(0) : "—"}
      </td>
      <td className="text-center recommendation-stat">{mods || "NM"}</td>
      <td className="text-center recommendation-stat">
        {star_rating != null ? Number(star_rating).toFixed(2) : "—"}
      </td>
      <td className="text-center recommendation-stat">
        {bpm != null ? Number(bpm).toFixed(0) : "—"}
      </td>
      <td className="text-center recommendation-stat">
        {circle_size != null ? Number(circle_size).toFixed(1) : "—"}
      </td>
      <td className="text-center recommendation-stat">
        {ar != null ? Number(ar).toFixed(1) : "—"}
      </td>
      <td className="text-center recommendation-stat">
        {od != null ? Number(od).toFixed(1) : "—"}
      </td>
      <td className="text-center recommendation-stat">
        {formatDuration(length_seconds)}
      </td>
      <td className="text-center recommendation-stat">
        {max_combo != null ? `${max_combo.toLocaleString()}x` : "—"}
      </td>
    </tr>
  );
}

export default RecommendationRow;
