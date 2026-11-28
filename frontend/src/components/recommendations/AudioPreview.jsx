import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  ArrowRepeat,
  PauseFill,
  PlayFill,
  SkipEndFill,
  SkipStartFill,
  VolumeMuteFill,
  VolumeUpFill,
  X,
} from "react-bootstrap-icons";

import "./AudioPreview.css";

const AudioPreviewContext = createContext(null);

// The clips of about 10 seconds from osu!. They start at the preview point of the map.
const previewUrl = (beatmapsetId) => `https://b.ppy.sh/preview/${beatmapsetId}.mp3`;

const VOLUME_STORAGE_KEY = "audioPreviewVolume";
const DEFAULT_VOLUME = 0.01;
// The maximum of the volume slider. The previews are loud.
const MAX_VOLUME = 0.1;

// Format seconds as m:ss. (The previews are short.)
const formatAudioTime = (seconds) => {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";

  const totalSeconds = Math.floor(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = String(totalSeconds % 60).padStart(2, "0");

  return `${minutes}:${remainingSeconds}`;
};

const loadVolume = () => {
  try {
    const stored = Number(localStorage.getItem(VOLUME_STORAGE_KEY));
    if (stored > 0 && stored <= MAX_VOLUME) return stored;
  } catch {
    // Storage can be unavailable (private mode, or blocked site data).
  }
  return DEFAULT_VOLUME;
};

const saveVolume = (volume) => {
  try {
    localStorage.setItem(VOLUME_STORAGE_KEY, String(volume));
  } catch {
    // Do not tell the user. The only effect is that the volume is not saved.
  }
};

// The key of the preview of a recommendation (RecommendationRow uses it too).
// There is one key for each variant, so only the clicked row shows as playing.
export const previewKeyOf = (recommendation) =>
  recommendation.variant_id ?? recommendation.beatmap_id;

// Find the nearest row before (step -1) or after (step 1) the playing row that
// has a different preview. The variants of one mapset share a preview, so the
// search skips them. It also skips the rows that did not load yet (holes in
// the list).
// Play the audio if it is paused. If not, pause it.
const playOrPause = (audio) => {
  if (audio.paused) {
    audio.play().catch(() => {});
  } else {
    audio.pause();
  }
};

// Stop the download of the current file and empty the audio element.
const unloadAudio = (audio) => {
  audio.removeAttribute("src");
  audio.load();
};

const neighbour = (playlist, activeKey, step) => {
  if (!playlist || activeKey === null) return null;

  const index = playlist.findIndex(
    (row) => row !== undefined && previewKeyOf(row) === activeKey
  );
  if (index === -1) return null;

  const currentSet = playlist[index].beatmapset_id;
  for (let i = index + step; i >= 0 && i < playlist.length; i += step) {
    const row = playlist[i];
    if (row !== undefined && row.beatmapset_id && row.beatmapset_id !== currentSet) {
      return row;
    }
  }
  return null;
};

// The player is always in one of these phases:
//   closed:  no preview is loaded, and the bar is hidden.
//   loading: the audio element loads the preview of `key`. The bar stays
//            visible only if it was visible before (`barVisible`).
//   open:    the preview of `key` is loaded, and the bar is visible.
// Each loading object is new, so a slow load can compare its own object with
// the current phase to know if the user moved on.
const CLOSED = { phase: "closed", key: null, barVisible: false };
const loadingPhase = (key, barVisible) => ({ phase: "loading", key, barVisible });
const openPhase = (key) => ({ phase: "open", key, barVisible: true });

// Play one audio preview at a time for the whole page. The provider is above
// the virtualized table. Thus the playback continues when its row scrolls out
// of view (and unmounts).
// playlist: the result rows in table order, for the previous/next buttons.
// onFeedback: the code calls it when a preview starts, but not when it resumes.
export function AudioPreviewProvider({ children, playlist = null, onFeedback }) {
  // The phase for rendering, and a ref with the same value for the async code.
  const [preview, setPreviewState] = useState(CLOSED);
  const previewRef = useRef(CLOSED);
  // These mirror the events of the audio element.
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(loadVolume);
  const [muted, setMuted] = useState(false);
  const [repeat, setRepeat] = useState(false);

  const audioRef = useRef(null);
  const volumeRef = useRef(volume);

  const setPreview = useCallback((next) => {
    previewRef.current = next;
    setPreviewState(next);
  }, []);

  const closePreview = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      unloadAudio(audio);
    }

    setPreview(CLOSED);
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);
  }, [setPreview]);

  // Play or pause the preview of the given row. If another preview (or no
  // preview) is loaded, load this one first.
  const togglePreview = useCallback(async (row) => {
    const key = previewKeyOf(row);
    const beatmapsetId = row.beatmapset_id;
    const audio = audioRef.current;
    if (!audio || !beatmapsetId) return;

    const current = previewRef.current;
    if (current.key === key) {
      // While this preview loads, a second click does nothing.
      if (current.phase === "open") playOrPause(audio);
      return;
    }

    const loading = loadingPhase(key, current.barVisible);
    setPreview(loading);

    setDuration(0);
    setCurrentTime(0);
    audio.src = previewUrl(beatmapsetId);
    audio.volume = volumeRef.current;

    try {
      // This resolves when the playback starts. It rejects if the preview
      // cannot load (for example, osu! has no preview for this set).
      await audio.play();

      if (previewRef.current !== loading) return;

      setPreview(openPhase(key));
      onFeedback?.("preview", row);
    } catch (error) {
      // A newer preview or a close replaced this one, so there is nothing to report.
      if (previewRef.current !== loading) return;

      console.error("Failed to play audio preview:", error);
      // The earlier preview is not in the audio element anymore, so close
      // the bar. Do not show controls for an empty player.
      closePreview();
    }
  }, [onFeedback, setPreview, closePreview]);

  const togglePlayback = () => {
    if (audioRef.current && previewRef.current.phase === "open") {
      playOrPause(audioRef.current);
    }
  };

  const changeVolume = (newVolume) => {
    setVolume(newVolume);
    volumeRef.current = newVolume;
    saveVolume(newVolume);

    if (audioRef.current) {
      audioRef.current.volume = newVolume;
    }

    // As in most players, a move of the slider above 0 unmutes the audio.
    if (muted && newVolume > 0) {
      setMuted(false);
    }
  };

  const value = useMemo(
    () => ({
      activeKey: preview.phase === "open" ? preview.key : null,
      loadingKey: preview.phase === "loading" ? preview.key : null,
      isPlaying,
      playerOpen: preview.barVisible,
      togglePreview,
    }),
    [preview, isPlaying, togglePreview]
  );

  // During a load, "Previous" and "Next" start from the row that loads. Thus
  // each quick click on "Next" moves one more row down the list.
  const previous = neighbour(playlist, preview.key, -1);
  const next = neighbour(playlist, preview.key, 1);
  const playRow = (row) => row && togglePreview(row);

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;
  const volumeFill = muted ? 0 : (volume / MAX_VOLUME) * 100;

  return (
    <AudioPreviewContext.Provider value={value}>
      {children}

      <audio
        ref={audioRef}
        muted={muted}
        loop={repeat}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
        onEnded={(e) => {
          e.currentTarget.currentTime = 0;
          setCurrentTime(0);
        }}
      />

      {preview.barVisible && (
        <div
          className="audio-preview-bar position-fixed d-flex align-items-center shadow"
          role="region"
          aria-label="Audio preview"
        >
          <button
            type="button"
            className="audio-preview-icon-button btn"
            onClick={() => playRow(previous)}
            disabled={!previous}
            aria-label="Previous preview"
          >
            <SkipStartFill size={16} />
          </button>

          <button
            type="button"
            className="audio-preview-icon-button audio-preview-play btn"
            onClick={togglePlayback}
            aria-label={isPlaying ? "Pause preview" : "Play preview"}
          >
            {isPlaying ? <PauseFill size={22} /> : <PlayFill size={22} />}
          </button>

          <button
            type="button"
            className="audio-preview-icon-button btn"
            onClick={() => playRow(next)}
            disabled={!next}
            aria-label="Next preview"
          >
            <SkipEndFill size={16} />
          </button>

          <label htmlFor="audio-preview-seek" className="visually-hidden">
            Audio progress
          </label>
          <input
            id="audio-preview-seek"
            type="range"
            className="audio-preview-range audio-preview-seek flex-grow-1"
            style={{ "--fill": `${progress}%` }}
            min="0"
            max={duration || 0}
            step="0.01"
            value={currentTime}
            onChange={(e) => {
              const newTime = Number(e.target.value);

              setCurrentTime(newTime);

              if (audioRef.current) {
                audioRef.current.currentTime = newTime;
              }
            }}
            aria-valuetext={`${formatAudioTime(currentTime)} of ${formatAudioTime(duration)}`}
          />

          <span className="audio-preview-time flex-shrink-0">
            {formatAudioTime(currentTime)}
            <span className="audio-preview-duration"> / {formatAudioTime(duration)}</span>
          </span>

          <button
            type="button"
            className="audio-preview-icon-button btn"
            onClick={() => setMuted((current) => !current)}
            aria-label={muted ? "Unmute preview" : "Mute preview"}
            aria-pressed={muted}
          >
            {muted ? <VolumeMuteFill size={16} /> : <VolumeUpFill size={16} />}
          </button>

          <label htmlFor="audio-preview-volume" className="visually-hidden">
            Preview volume
          </label>
          <input
            id="audio-preview-volume"
            type="range"
            className="audio-preview-range audio-preview-volume flex-shrink-0"
            style={{ "--fill": `${volumeFill}%` }}
            min="0"
            max={MAX_VOLUME}
            step="0.001"
            value={muted ? 0 : volume}
            onChange={(e) => changeVolume(Number(e.target.value))}
          />

          <button
            type="button"
            className={`audio-preview-icon-button btn${repeat ? " active" : ""}`}
            onClick={() => setRepeat((current) => !current)}
            aria-label="Repeat preview"
            aria-pressed={repeat}
          >
            <ArrowRepeat size={16} />
          </button>

          <button
            type="button"
            className="audio-preview-icon-button btn"
            onClick={closePreview}
            aria-label="Close audio preview"
          >
            <X size={20} />
          </button>
        </div>
      )}
    </AudioPreviewContext.Provider>
  );
}

export function useAudioPreview() {
  return useContext(AudioPreviewContext);
}
