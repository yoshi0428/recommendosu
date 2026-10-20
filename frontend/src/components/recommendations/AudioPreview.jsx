import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  PauseFill,
  PlayFill,
  VolumeMuteFill,
  VolumeUpFill,
  X,
} from "react-bootstrap-icons";

import "./AudioPreview.css";

const AudioPreviewContext = createContext(null);

// osu!'s own ~10 second clips, which already start at the map's preview point.
const previewUrl = (beatmapsetId) => `https://b.ppy.sh/preview/${beatmapsetId}.mp3`;

const VOLUME_STORAGE_KEY = "audioPreviewVolume";
const DEFAULT_VOLUME = 0.01;
// The volume slider only goes up to this; previews are loud.
const MAX_VOLUME = 0.1;

// helper function to format seconds into m:ss (previews are short)
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
    // Storage can be unavailable (private mode, blocked site data).
  }
  return DEFAULT_VOLUME;
};

const saveVolume = (volume) => {
  try {
    localStorage.setItem(VOLUME_STORAGE_KEY, String(volume));
  } catch {
    // Not worth bothering the user about; the volume just isn't remembered.
  }
};

// Plays one audio preview at a time for the whole page. It sits above the
// virtualized table, so playback keeps going when its row scrolls out of view
// (and is unmounted).
export function AudioPreviewProvider({ children }) {
  // Key of the row whose preview is loaded, or null when the player is closed.
  const [activeKey, setActiveKey] = useState(null);
  // Key of the row whose preview is loading.
  const [loadingKey, setLoadingKey] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(loadVolume);
  const [muted, setMuted] = useState(false);

  const audioRef = useRef(null);
  const activeKeyRef = useRef(null);
  const volumeRef = useRef(volume);
  // Bumped on every new preview or close, so a slow load that finishes after
  // the user moved on doesn't open the player.
  const requestIdRef = useRef(0);

  const closePreview = useCallback(() => {
    requestIdRef.current += 1;

    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }

    activeKeyRef.current = null;
    setActiveKey(null);
    setLoadingKey(null);
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);
  }, []);

  // Play/pause the given row's preview, loading it first if another
  // preview (or none) is loaded.
  const togglePreview = useCallback(async (key, { beatmapsetId }) => {
    const audio = audioRef.current;
    if (!audio || !beatmapsetId) return;

    if (activeKeyRef.current === key) {
      if (audio.paused) {
        audio.play().catch(() => {});
      } else {
        audio.pause();
      }
      return;
    }

    const requestId = ++requestIdRef.current;
    setLoadingKey(key);

    setDuration(0);
    setCurrentTime(0);
    audio.src = previewUrl(beatmapsetId);
    audio.volume = volumeRef.current;

    try {
      // Resolves once playback starts; rejects if the preview can't be
      // loaded (e.g. osu! has none for this set).
      await audio.play();

      if (requestId !== requestIdRef.current) return;

      activeKeyRef.current = key;
      setActiveKey(key);
    } catch (error) {
      // A newer preview or a close replaced this one; nothing to report.
      if (requestId !== requestIdRef.current) return;

      console.error("Failed to play audio preview:", error);
      audio.removeAttribute("src");
      audio.load();
    } finally {
      if (requestId === requestIdRef.current) {
        setLoadingKey(null);
      }
    }
  }, []);

  const togglePlayback = () => {
    const audio = audioRef.current;
    if (!audio) return;

    if (audio.paused) {
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  };

  const changeVolume = (newVolume) => {
    setVolume(newVolume);
    volumeRef.current = newVolume;
    saveVolume(newVolume);

    if (audioRef.current) {
      audioRef.current.volume = newVolume;
    }

    // Dragging the slider up unmutes, like most players.
    if (muted && newVolume > 0) {
      setMuted(false);
    }
  };

  const value = useMemo(
    () => ({
      activeKey,
      loadingKey,
      isPlaying,
      playerOpen: activeKey !== null,
      togglePreview,
    }),
    [activeKey, loadingKey, isPlaying, togglePreview]
  );

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;
  const volumeFill = muted ? 0 : (volume / MAX_VOLUME) * 100;

  return (
    <AudioPreviewContext.Provider value={value}>
      {children}

      <audio
        ref={audioRef}
        muted={muted}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
        onEnded={(e) => {
          e.currentTarget.currentTime = 0;
          setCurrentTime(0);
        }}
      />

      {activeKey !== null && (
        <div
          className="audio-preview-bar position-fixed start-50 translate-middle-x rounded-pill shadow d-flex align-items-center"
          role="region"
          aria-label="Audio preview"
        >
          <button
            type="button"
            className="audio-preview-play btn rounded-circle d-flex align-items-center justify-content-center flex-shrink-0"
            onClick={togglePlayback}
            aria-label={isPlaying ? "Pause preview" : "Play preview"}
          >
            {isPlaying ? <PauseFill size={20} /> : <PlayFill size={20} />}
          </button>

          <span className="audio-preview-time flex-shrink-0">
            {formatAudioTime(currentTime)}
          </span>

          <label htmlFor="audio-preview-seek" className="visually-hidden">
            Audio progress
          </label>
          <input
            id="audio-preview-seek"
            type="range"
            className="form-range audio-preview-range audio-preview-seek flex-grow-1"
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

          <span className="audio-preview-time audio-preview-duration flex-shrink-0">
            {formatAudioTime(duration)}
          </span>

          <button
            type="button"
            className="audio-preview-icon-button btn d-flex align-items-center justify-content-center flex-shrink-0"
            onClick={() => setMuted((current) => !current)}
            aria-label={muted ? "Unmute preview" : "Mute preview"}
            aria-pressed={muted}
          >
            {muted ? <VolumeMuteFill size={18} /> : <VolumeUpFill size={18} />}
          </button>

          <label htmlFor="audio-preview-volume" className="visually-hidden">
            Preview volume
          </label>
          <input
            id="audio-preview-volume"
            type="range"
            className="form-range audio-preview-range audio-preview-volume flex-shrink-0"
            style={{ "--fill": `${volumeFill}%` }}
            min="0"
            max={MAX_VOLUME}
            step="0.001"
            value={muted ? 0 : volume}
            onChange={(e) => changeVolume(Number(e.target.value))}
          />

          <button
            type="button"
            className="audio-preview-icon-button btn d-flex align-items-center justify-content-center flex-shrink-0"
            onClick={closePreview}
            aria-label="Close audio preview"
          >
            <X size={22} />
          </button>
        </div>
      )}
    </AudioPreviewContext.Provider>
  );
}

export function useAudioPreview() {
  return useContext(AudioPreviewContext);
}
