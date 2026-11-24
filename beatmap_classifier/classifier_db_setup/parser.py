import io
import math

from beatmap_recommender.recommender_db_setup.parser import decode_osu_bytes

# The .osu [Difficulty] keys -> the keys of the parsed data.
DIFFICULTY_KEYS = {
    "HPDrainRate": "hp_drain",
    "CircleSize": "circle_size",
    "OverallDifficulty": "od",
    "ApproachRate": "ar",
    "SliderMultiplier": "slider_multiplier",
    "SliderTickRate": "slider_tick",
}

# The [Metadata] keys that print_info prints, with their labels.
PRINTED_METADATA = {"Title": "Title: ", "Artist": "by ", "Creator": "Mapper: ", "Version": "Difficulty: "}

HIT_CIRCLE_FLAG = 0b00000001
SLIDER_FLAG = 0b00000010

# The playfield size of osu!. The coordinates are divided by these values.
MAX_X = 512.0
MAX_Y = 384.0


def parse_osu_file(
    file_path,
    max_slider_length=500.0,
    print_info=False,
):
    """
    Parse an osu!standard .osu file. Return None for another game mode.

    The result describes the BASE beatmap:
        - The hit-object vectors hold RAW values.
        - This function does no mod timing change (DT, HT...) and no CNN
          normalization. Later steps apply the changes for each variant.

    Each vector describes the move from the previous hit object to this one:

        (x_diff, y_diff, time_diff, length, distance, speed, speed_change, time_diff_change)

    where:

        x_diff, y_diff    = the move, divided by the playfield size (512 x 384)
        time_diff         = the time from the previous object, in milliseconds
        length            = the slider length (0 for a circle), max_slider_length at most
        distance          = the length of (x_diff, y_diff)
        speed             = distance / time_diff (0 if time_diff is 0)
        speed_change      = speed minus the speed of the previous vector
        time_diff_change  = time_diff minus the time_diff of the previous vector

    Spinners are not in the hit objects.
    """

    data = {
        "beatmap_id": None,
        "mode": 0,  # The default is osu!standard.
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
        # Raw hit objects
        "hit_objects": [],
        # Raw base vectors
        "vectors": [],
    }

    bpms = []

    # The file is UTF-8, UTF-16 (old files with a BOM) or latin-1. StringIO
    # with newline=None splits the lines as a read in text mode did.
    with open(file_path, "rb") as f:
        lines = list(io.StringIO(decode_osu_bytes(f.read()), newline=None))

    section = None
    for line in lines:
        line = line.strip()

        if not line:
            continue

        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue

        # General: only the game mode matters.
        if section == "General":
            if ":" not in line:
                continue
            key, value = line.split(":", maxsplit=1)

            if key.strip() == "Mode":
                try:
                    data["mode"] = int(value.strip())
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

            if print_info and key in PRINTED_METADATA:
                print(PRINTED_METADATA[key] + value, end=" " if key == "Title" else "\n")

            elif key == "BeatmapID":
                try:
                    data["beatmap_id"] = int(value)
                except ValueError:
                    data["beatmap_id"] = None

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
                x = float(obj_data[0])
                y = float(obj_data[1])
                time = float(obj_data[2])
                hit_object_type = int(obj_data[3])
            except ValueError:
                continue

            if hit_object_type & HIT_CIRCLE_FLAG:
                length = 0.0

            elif hit_object_type & SLIDER_FLAG:
                if len(obj_data) <= 7:
                    continue

                try:
                    length = float(obj_data[7])
                except ValueError:
                    length = 0.0

                length = min(max_slider_length, max(0.0, length))

            else:
                continue  # A spinner

            data["hit_objects"].append({"x": x, "y": y, "time": time, "length": length})

    if bpms:
        data["bpm"] = bpms[0]
        data["min_bpm"] = min(bpms)
        data["max_bpm"] = max(bpms)

    hit_objects = data["hit_objects"]
    data["object_count"] = len(hit_objects)

    if len(hit_objects) >= 2:
        data["length_seconds"] = (hit_objects[-1]["time"] - hit_objects[0]["time"]) / 1000.0
    else:
        data["length_seconds"] = 0.0

    # The RAW base vectors. The coordinates are divided by the playfield size,
    # because the playfield size is fixed. The time and the slider length stay
    # RAW, and no DT/HT change happens here.
    previous_speed = None
    previous_time_diff = None

    for prev_obj, obj in zip(hit_objects, hit_objects[1:]):
        x_diff = obj["x"] / MAX_X - prev_obj["x"] / MAX_X
        y_diff = obj["y"] / MAX_Y - prev_obj["y"] / MAX_Y

        time_diff = obj["time"] - prev_obj["time"]
        distance = math.sqrt(x_diff**2 + y_diff**2)
        speed = distance / time_diff if time_diff > 0 else 0.0

        if previous_speed is None:
            speed_change = 0.0
            time_diff_change = 0.0
        else:
            speed_change = speed - previous_speed
            time_diff_change = time_diff - previous_time_diff

        previous_speed = speed
        previous_time_diff = time_diff

        data["vectors"].append(
            (x_diff, y_diff, time_diff, obj["length"], distance, speed, speed_change, time_diff_change)
        )

    # Old maps have no ApproachRate line. For these maps, osu! uses OD as AR.
    if data["ar"] is None:
        data["ar"] = data["od"]

    return data
