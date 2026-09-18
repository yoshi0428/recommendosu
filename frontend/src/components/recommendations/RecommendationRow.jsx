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
    beatmapset_id,
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
    ? `https://assets.ppy.sh/beatmaps/${beatmapset_id}/covers/list.jpg`
    : null

  return (
    <tr
      onClick={() => onSelectRecommendation?.(recommendation)}
      style={{cursor: 'pointer'}}
      title="Click to view score breakdown"
    >
      <td className="text-start" style={{width: '40%'}}>
        <div className="d-flex align-items-center gap-2 gap-md-3 text-start">
          {coverUrl && (
            <img
              src={coverUrl}
              alt=""
              width="104"
              height="58"
              className="rounded object-fit-cover flex-shrink-0 bg-secondary shadow-sm"
              loading="lazy"
              onError={(e) => {
                e.target.style.display = 'none'
              }}
            />
          )}

          <div className="text-break" style={{minWidth: 0}}>
            <a
              href={beatmapUrl}
              target="_blank"
              rel="noreferrer"
              className="text-body d-block"
              style={{textDecoration: 'none'}}
              onMouseEnter={(e) => {
                e.currentTarget.style.textDecoration = 'underline'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.textDecoration = 'none'
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <strong className="text-break d-block">
                {title
                  ? `${artist} - ${title} [${version}]`
                  : `Beatmap ${beatmap_id}`}
              </strong>
            </a>
          </div>
        </div>
      </td>

      {/* Core stats visible on all screens */}
      <td className="text-center">{pp != null ? Number(pp).toFixed(0) : '—'}</td>
      <td className="text-center">{mods || 'NM'}</td>
      <td className="text-center">{star_rating != null ? Number(star_rating).toFixed(2) : '—'}</td>
      <td className="text-center">{bpm != null ? Number(bpm).toFixed(0) : '—'}</td>
      <td
        className="text-center">{circle_size != null ? Number(circle_size).toFixed(1) : '—'}</td>
      <td className="text-center">{ar != null ? Number(ar).toFixed(1) : '—'}</td>
      <td className="text-center">{od != null ? Number(od).toFixed(1) : '—'}</td>
      <td className="text-center">{formatDuration(length_seconds)}</td>
      <td
        className="text-center">{max_combo != null ? `${max_combo.toLocaleString()}x` : '—'}</td>
    </tr>
  )
}

export default RecommendationRow