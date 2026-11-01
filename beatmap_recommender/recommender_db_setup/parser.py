def decode_osu_bytes(raw):
    """
    Decode raw .osu bytes. Some old files are saved as UTF-16 (with a BOM);
    reading those as UTF-8/latin-1 hides every key, including Mode, which let
    non-standard maps through with NULL difficulty values.
    """
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")

    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def parse_osu_file(file_path):
    """
    Parse an osu!standard .osu file into the BASE (NM) beatmap's metadata
    and stats; mods are applied later (beatmap_mods.py). Returns None for
    other game modes.

    Only circles and sliders count towards object_count and length_seconds
    (spinners don't).
    """

    data = {
        "beatmap_id": None,
        "beatmapset_id": None,
        "preview_time": 0,  # default to start of song
        "mode": 0,  # Default to standard
        "title": "",
        "artist": "",
        "creator": "",
        "version": "",

        # Base difficulty
        "hp_drain": None,
        "circle_size": None,
        "od": None,
        "ar": None,

        # Slider settings
        "slider_multiplier": None,
        "slider_tick": None,

        # Base timing
        "bpm": None,
        "min_bpm": None,
        "max_bpm": None,

        # Map statistics
        "length_seconds": None,
        "object_count": 0,
    }

    timing_points = []
    object_times = []

    with open(file_path, "rb") as f:
        lines = decode_osu_bytes(f.read()).splitlines()

    section = None
    for line in lines:
        line = line.strip()

        if not line:
            continue

        # Section header
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue

        # General (to check game mode)
        if section == "General":
            if ":" not in line:
                continue
            key, value = line.split(":", maxsplit=1)
            key = key.strip()
            value = value.strip()

            if key == "PreviewTime":
                try:
                    data["preview_time"] = int(value)
                except ValueError:
                    data["preview_time"] = 0

            if key == "Mode":
                try:
                    data["mode"] = int(value)
                except ValueError:
                    data["mode"] = 0

                # If it's not standard (0), skip immediately
                if data["mode"] != 0:
                    return None

        # Metadata
        if section == "Metadata":
            if ":" not in line:
                continue

            key, value = line.split(":", maxsplit=1)
            value = value.strip()

            if key == "Title":
                data["title"] = value

            elif key == "Artist":
                data["artist"] = value

            elif key == "Creator":
                data["creator"] = value

            elif key == "Version":
                data["version"] = value

            elif key == "BeatmapID":
                try:
                    data["beatmap_id"] = int(value)
                except ValueError:
                    data["beatmap_id"] = None

            elif key == "BeatmapSetID":
                try:
                    data["beatmapset_id"] = int(value)
                except ValueError:
                    data["beatmapset_id"] = None

        # Difficulty
        elif section == "Difficulty":
            if ":" not in line:
                continue

            key, value = line.split(":", maxsplit=1)

            try:
                value = float(value)
            except ValueError:
                continue

            if key == "HPDrainRate":
                data["hp_drain"] = value

            elif key == "CircleSize":
                data["circle_size"] = value

            elif key == "OverallDifficulty":
                data["od"] = value

            elif key == "ApproachRate":
                data["ar"] = value

            elif key == "SliderMultiplier":
                data["slider_multiplier"] = value

            elif key == "SliderTickRate":
                data["slider_tick"] = value

        # Timing Points
        elif section == "TimingPoints":
            obj_data = line.split(",")
            if len(obj_data) < 2:
                continue

            try:
                time = float(obj_data[0])
                beat_length = float(obj_data[1])
            except ValueError:
                continue

            # Positive beat length = uninherited timing point.
            if beat_length > 0:
                bpm = 60000.0 / beat_length
                timing_points.append((time, bpm))

        # Hit Objects
        elif section == "HitObjects":
            obj_data = line.split(",")

            if len(obj_data) < 4:
                continue

            try:
                time = float(obj_data[2])
                hit_object_type = int(obj_data[3])
                float(obj_data[0]), float(obj_data[1])  # Skip objects without a valid position.
            except ValueError:
                continue

            is_circle = hit_object_type & 0b01
            # Sliders without a length field (8th) are skipped.
            is_slider = hit_object_type & 0b10 and len(obj_data) > 7

            if is_circle or is_slider:
                object_times.append(time)

    # BPM
    if timing_points:
        bpms = [bpm for _, bpm in timing_points]

        data["bpm"] = bpms[0]
        data["min_bpm"] = min(bpms)
        data["max_bpm"] = max(bpms)

    data["object_count"] = len(object_times)

    # From the first object to the last, in file order.
    if len(object_times) >= 2:
        data["length_seconds"] = (object_times[-1] - object_times[0]) / 1000.0
    else:
        data["length_seconds"] = 0.0

    return data
