# The .osu [Metadata] text keys -> the keys of the parsed data.
METADATA_TEXT_KEYS = {"Title": "title", "Artist": "artist", "Creator": "creator", "Version": "version"}
# The [Metadata] ID keys, which become ints (or None if they are not numbers).
METADATA_ID_KEYS = {"BeatmapID": "beatmap_id", "BeatmapSetID": "beatmapset_id"}
# The [Difficulty] keys -> the keys of the parsed data.
DIFFICULTY_KEYS = {
    "HPDrainRate": "hp_drain",
    "CircleSize": "circle_size",
    "OverallDifficulty": "od",
    "ApproachRate": "ar",
    "SliderMultiplier": "slider_multiplier",
    "SliderTickRate": "slider_tick",
}


def decode_osu_bytes(raw):
    """
    Decode raw .osu bytes. Some old files are saved as UTF-16 (with a BOM).
    If the code read them as UTF-8 or latin-1, it would not find any key,
    also not Mode. Before this fix, maps of other game modes got through, with
    NULL difficulty values.
    """
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")

    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def parse_osu_file(file_path):
    """
    Parse an osu!standard .osu file into the metadata and stats of the BASE
    (NM) beatmap. The mods are applied later (beatmap_mods.py). Return None for
    other game modes.

    Only circles and sliders count for object_count and length_seconds
    (spinners do not).
    """

    data = {
        "beatmap_id": None,
        "beatmapset_id": None,
        "preview_time": 0,  # The default is the start of the song.
        "mode": 0,  # The default is osu!standard.
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

    bpms = []
    object_times = []

    with open(file_path, "rb") as f:
        lines = decode_osu_bytes(f.read()).splitlines()

    section = None
    for line in lines:
        line = line.strip()

        if not line:
            continue

        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue

        # General: the preview time and the game mode.
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

                # Stop at once if the map is not osu!standard (0).
                if data["mode"] != 0:
                    return None

        if section == "Metadata":
            if ":" not in line:
                continue

            key, value = line.split(":", maxsplit=1)
            value = value.strip()

            if key in METADATA_TEXT_KEYS:
                data[METADATA_TEXT_KEYS[key]] = value

            elif key in METADATA_ID_KEYS:
                try:
                    data[METADATA_ID_KEYS[key]] = int(value)
                except ValueError:
                    data[METADATA_ID_KEYS[key]] = None

        elif section == "Difficulty":
            if ":" not in line:
                continue

            key, value = line.split(":", maxsplit=1)

            try:
                value = float(value)
            except ValueError:
                continue

            if key in DIFFICULTY_KEYS:
                data[DIFFICULTY_KEYS[key]] = value

        elif section == "TimingPoints":
            obj_data = line.split(",")
            if len(obj_data) < 2:
                continue

            try:
                float(obj_data[0])
                beat_length = float(obj_data[1])
            except ValueError:
                continue

            # A positive beat length means an uninherited timing point.
            if beat_length > 0:
                bpms.append(60000.0 / beat_length)

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
            # A slider without a length field (the 8th) is skipped.
            is_slider = hit_object_type & 0b10 and len(obj_data) > 7

            if is_circle or is_slider:
                object_times.append(time)

    if bpms:
        data["bpm"] = bpms[0]
        data["min_bpm"] = min(bpms)
        data["max_bpm"] = max(bpms)

    data["object_count"] = len(object_times)

    # The length is from the first object to the last, in file order.
    if len(object_times) >= 2:
        data["length_seconds"] = (object_times[-1] - object_times[0]) / 1000.0
    else:
        data["length_seconds"] = 0.0

    return data
