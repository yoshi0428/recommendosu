import {useEffect, useRef, useState} from "react";
import './RecommendationRow.css'

import {
  PauseFill,
  PlayFill,
  VolumeUpFill,
  X,
} from 'react-bootstrap-icons'


// shared event used to stop audio previews in other recommendation rows
const AUDIO_PREVIEW_EVENT = 'recommendosu:audio-preview'

// helper functions to format seconds into mm:ss or hh:mm:ss
const formatDuration = (totalSeconds) => {
  if (totalSeconds == null || isNaN(totalSeconds)) return '—'
  const seconds = Math.round(totalSeconds)
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainingSeconds = seconds % 60

  const pad = (num) => String(num).padStart(2, '0')

  if (hours > 0) {
    return `${hours}:${pad(minutes)}:${pad(remainingSeconds)}`
  } else {
    return `${minutes}:${pad(remainingSeconds)}`
  }
}

const formatAudioTime = (seconds) => {
  if (!Number.isFinite(seconds)) return '00:00:00'

  const totalSeconds = Math.floor(seconds)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const remainingSeconds = totalSeconds % 60

  const pad = (num) => String(num).padStart(2, '0')

  return `${pad(hours)}:${pad(minutes)}:${pad(remainingSeconds)}`
}


function RecommendationRow({
                             recommendation,
                             onSelectRecommendation,
                             audioVolume,
                             setAudioVolume,
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

  const [isPlaying, setIsPlaying] = useState(false)
  const [audioUrl, setAudioUrl] = useState(null)
  const audioRef = useRef(null)
  const audioUrlRef = useRef(null)

  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)

  const beatmapUrl = beatmap_id
    ? `https://osu.ppy.sh/b/${beatmap_id}`
    : '#'

  const coverUrl = beatmap_id
    ? `https://assets.ppy.sh/beatmaps/${beatmapset_id}/covers/list.jpg`
    : null

  const playPreview = async () => {
    try {
      // Stop the current preview if already playing.
      if (isPlaying && audioRef.current) {
        audioRef.current.pause()
        audioRef.current.currentTime = 0
        setCurrentTime(0)
        setIsPlaying(false)
        return
      }

      const params = new URLSearchParams({
        artist,
        title,
        creator,
      })

      const response = await fetch(
        `/api/v1/music/preview?${params.toString()}`,
      )

      if (!response.ok) {
        throw new Error('Failed to fetch audio preview')
      }

      const previewTime = Number(
        response.headers.get('X-Preview-Time') ?? 0,
      )

      const blob = await response.blob()
      const url = URL.createObjectURL(blob)

      // clean up the previous object URL.
      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current)
      }

      audioUrlRef.current = url
      setAudioUrl(url)

      // reset playback position for the new preview.
      setCurrentTime(previewTime / 1000)

      // wait for React to render the new audio element.
      requestAnimationFrame(() => {
        if (!audioRef.current) return

        // tell every other recommendation row to stop.
        window.dispatchEvent(
          new CustomEvent(AUDIO_PREVIEW_EVENT, {
            detail: audioRef.current,
          }),
        )

        audioRef.current.volume = audioVolume
        audioRef.current.currentTime = previewTime / 1000
        audioRef.current.play()
        setIsPlaying(true)
      })
    } catch (error) {
      console.error('Failed to play audio preview:', error)
    }
  }

  const closePreview = () => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
    }

    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current)
      audioUrlRef.current = null
    }

    setAudioUrl(null)
    setIsPlaying(false)
    setCurrentTime(0)
    setDuration(0)
  }

  // Stop this row when another recommendation starts playing.
  useEffect(() => {
    const handleOtherAudioPreview = (event) => {
      if (event.detail === audioRef.current) return
      closePreview()
    }

    window.addEventListener(
      AUDIO_PREVIEW_EVENT,
      handleOtherAudioPreview
    )

    return () => {
      window.removeEventListener(
        AUDIO_PREVIEW_EVENT,
        handleOtherAudioPreview
      )
    }
  }, [])

  return (
    <>
      <tr
        onClick={() => onSelectRecommendation?.(recommendation)}
        style={{cursor: 'pointer'}}
        title="Click to view score breakdown"
      >
        <td className="text-start" style={{width: '40%'}}>
          <div className="d-flex align-items-center gap-2 gap-md-3 text-start">
            <div
              className="rounded flex-shrink-0 shadow-sm position-relative overflow-hidden bg-secondary"
              style={{
                width: '104px',
                height: '58px',
                cursor: 'pointer',
              }}
              onClick={(e) => {
                e.stopPropagation()
                playPreview()
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
                    e.currentTarget.style.display = 'none'
                  }}
                />
              )}

              <div
                className="position-absolute top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center"
                style={{
                  backgroundColor: 'rgba(0, 0, 0, 0.45)',
                  opacity: coverUrl && !isPlaying ? 0 : 1,
                  transition: 'opacity 0.15s ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.opacity = 1
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.opacity = coverUrl && !isPlaying ? 0 : 1
                }}
              >
                <span
                  className="text-white"
                  style={{
                    fontSize: '1.5rem',
                    lineHeight: 1,
                    textShadow: '0 1px 3px rgba(0, 0, 0, 0.5)',
                  }}
                >
                  {isPlaying ? (
                    <PauseFill
                      size={24}
                      className="text-white"
                      style={{
                        filter: 'drop-shadow(0 1px 2px rgba(0, 0, 0, 0.5))',
                      }}
                    />
                  ) : (
                    <PlayFill
                      size={24}
                      className="text-white"
                      style={{
                        filter: 'drop-shadow(0 1px 2px rgba(0, 0, 0, 0.5))',
                      }}
                    />
                  )}
                </span>
              </div>
            </div>

            {audioUrl && (
              <audio
                ref={audioRef}
                src={audioUrl}
                onLoadedMetadata={() => {
                  if (audioRef.current) {
                    setDuration(audioRef.current.duration)
                  }
                }}
                onTimeUpdate={() => {
                  if (audioRef.current) {
                    setCurrentTime(audioRef.current.currentTime)
                  }
                }}
                onEnded={() => {
                  setIsPlaying(false)
                  setCurrentTime(0)

                  if (audioRef.current) {
                    audioRef.current.currentTime = 0
                  }
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
        <td className="text-center">{circle_size != null ? Number(circle_size).toFixed(1) : '—'}</td>
        <td className="text-center">{ar != null ? Number(ar).toFixed(1) : '—'}</td>
        <td className="text-center">{od != null ? Number(od).toFixed(1) : '—'}</td>
        <td className="text-center">{formatDuration(length_seconds)}</td>
        <td className="text-center">{max_combo != null ? `${max_combo.toLocaleString()}x` : '—'}</td>
      </tr>

      {/* Audio player pill */}
      {audioUrl && (
        <tr>
          <td colSpan="10" style={{padding: 0, border: 0}}>
            <div
              className="position-fixed bottom-0 start-50 translate-middle-x mb-3 px-2 px-sm-3 py-2 rounded-pill shadow d-flex align-items-center border border-3"
              style={{
                zIndex: 1050,
                width: 'min(600px, calc(100vw - 1rem))',
                minWidth: 0,
                backgroundColor: 'var(--audio-preview-bg-color)',
                '--bs-border-color': 'var(--audio-preview-border-color)',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              {/* Playback */}
              <div
                className="d-flex align-items-center flex-grow-1 rounded"
                style={{
                  minWidth: 0,
                  gap: '0.5rem',
                  backgroundColor: 'var(--audio-preview-bg-color)',
                  padding: '0.25rem 0.5rem',
                }}
              >
                {/* Play / Pause */}
                <button
                  type="button"
                  className="btn btn-sm p-0 border-0 bg-transparent d-flex align-items-center justify-content-center flex-shrink-0"
                  style={{
                    width: '20px',
                    height: '20px',
                    lineHeight: 1,
                    color: 'var(--audio-preview-text-color)',
                  }}
                  onClick={() => {
                    if (!audioRef.current) return

                    if (audioRef.current.paused) {
                      audioRef.current.play()
                      setIsPlaying(true)
                    } else {
                      audioRef.current.pause()
                      setIsPlaying(false)
                    }
                  }}
                  aria-label={isPlaying ? 'Pause preview' : 'Play preview'}
                >
                  {isPlaying ? (
                    <PauseFill size={20}/>
                  ) : (
                    <PlayFill size={20}/>
                  )}
                </button>

                {/* Audio time control */}
                <input
                  type="range"
                  className="form-range mb-0 flex-grow-1 audio-preview-range"
                  style={{
                    minWidth: 0,
                  }}
                  min="0"
                  max={duration || 0}
                  step="0.01"
                  value={currentTime}
                  onChange={(e) => {
                    const newTime = Number(e.target.value)

                    setCurrentTime(newTime)

                    if (audioRef.current) {
                      audioRef.current.currentTime = newTime
                    }
                  }}
                  aria-label="Audio progress"
                />

                <span
                  className="text-nowrap flex-shrink-0 audio-preview-time"
                  style={{
                    fontSize: '0.65rem',
                    width: '108px',
                    textAlign: 'center',
                    lineHeight: 1,
                    color: 'var(--audio-preview-secondary-color)',
                  }}
                >
                  {formatAudioTime(currentTime)}
                  <span className="audio-preview-duration">
                    {' / '}{formatAudioTime(duration)}
                  </span>
                </span>
              </div>

              {/* Volume */}
              <div
                className="d-flex align-items-center flex-shrink-0 rounded"
                style={{
                  gap: '0.5rem',
                  backgroundColor: 'var(--audio-preview-bg-color)',
                  padding: '0.25rem 0.5rem',
                }}
              >
                <VolumeUpFill
                  size={18}
                  style={{
                    color: 'var(--audio-preview-secondary-color)',
                  }}
                />

                <input
                  type="range"
                  className="form-range mb-0 audio-preview-range"
                  min="0"
                  max="0.10"
                  step="0.001"
                  value={audioVolume}
                  onChange={(e) => {
                    const newVolume = Number(e.target.value)

                    setAudioVolume(newVolume)

                    if (audioRef.current) {
                      audioRef.current.volume = newVolume
                    }
                  }}
                  aria-label="Preview volume"
                  style={{
                    width: '60px',
                  }}
                />
              </div>

              {/* Close */}
              <button
                type="button"
                className="btn btn-sm p-0 border-0 bg-transparent d-flex align-items-center justify-content-center flex-shrink-0"
                style={{
                  width: '20px',
                  height: '20px',
                  lineHeight: 1,
                  marginLeft: '0.5rem',
                  color: 'var(--audio-preview-secondary-color)',
                }}
                onClick={closePreview}
                aria-label="Close audio preview"
              >
                <X size={20}/>
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export default RecommendationRow