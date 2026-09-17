// Helper function to format seconds into mm:ss or hh:mm:ss
const formatDuration = (totalSeconds) => {
  if (totalSeconds == null || isNaN(totalSeconds)) return '—'
  const seconds = Math.round(totalSeconds)
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainingSeconds = seconds % 60

  const pad = (num) => String(num).padStart(2, '0')

  if (hours > 0) {
    return `${hours}:${pad(minutes)}:${pad(remainingSeconds)}`
  }
  return `${minutes}:${pad(remainingSeconds)}`
}

function RecommendationRow({
                             recommendation,
                             onSelectRecommendation,
                           }) {
  const {
    beatmap_id,
    artist,
    title,
    version,
    creator,
    mods,
    star_rating,
    bpm,
    circle_size,
    ar,
    od,
    length_seconds,
    object_count,
    max_combo,
    pp,
  } = recommendation

  const beatmapUrl = beatmap_id
    ? `https://osu.ppy.sh/b/${beatmap_id}`
    : '#'

  const coverUrl = beatmap_id
    ? `https://assets.ppy.sh/beatmaps/${beatmap_id}/covers/list.jpg`
    : null

  // 1/3 for artist-title, and the remaining 2/3 spread across the 10 other columns (6.67% each)
  const remainingColumnWidth = `${(2 / 3) / 10 * 100}%`

  return (
    <tr
      onClick={() => onSelectRecommendation?.(recommendation)}
      style={{cursor: 'pointer'}}
      title="Click to view score breakdown"
    >
      {/* Title & Artist takes 1/3 (33.33%) with a larger cover image on the left */}
      <td style={{width: '33.33%'}}>
        <a
          href={beatmapUrl}
          target="_blank"
          rel="noreferrer"
          className="text-decoration-none text-body d-flex align-items-center gap-3 text-start"
          onClick={(e) => e.stopPropagation()}
        >
          {coverUrl && (
            <img
              src={coverUrl}
              alt=""
              width="104"
              height="58"
              className="rounded object-fit-cover flex-shrink-0 bg-secondary shadow-sm"
              loading="lazy"
              onError={(e) => {
                // Hide or fallback if cover image fails to load
                e.target.style.display = 'none'
              }}
            />
          )}
          <div className="text-truncate">
            <strong>
              {title ? `${artist} - ${title} [${version}]` : `Beatmap ${beatmap_id}`}
            </strong>
          </div>
        </a>
      </td>

      {/* Remaining columns spread evenly across the other 2/3 */}
      <td className="text-center" style={{width: remainingColumnWidth}}>{pp != null ? Number(pp).toFixed(0) : '—'}</td>
      <td className="text-center" style={{width: remainingColumnWidth}}>{mods || 'NM'}</td>
      <td className="text-center"
          style={{width: remainingColumnWidth}}>{star_rating != null ? Number(star_rating).toFixed(2) : '—'}</td>
      <td className="text-center"
          style={{width: remainingColumnWidth}}>{bpm != null ? Number(bpm).toFixed(0) : '—'}</td>
      <td className="text-center"
          style={{width: remainingColumnWidth}}>{circle_size != null ? Number(circle_size).toFixed(1) : '—'}</td>
      <td className="text-center" style={{width: remainingColumnWidth}}>{ar != null ? Number(ar).toFixed(1) : '—'}</td>
      <td className="text-center" style={{width: remainingColumnWidth}}>{od != null ? Number(od).toFixed(1) : '—'}</td>
      <td className="text-center" style={{width: remainingColumnWidth}}>{formatDuration(length_seconds)}</td>
      <td className="text-center"
          style={{width: remainingColumnWidth}}>{max_combo != null ? `${max_combo.toLocaleString()}x` : '—'}</td>
    </tr>
  )
}

export default RecommendationRow