import math


def parse_osu_file(
    file_path,
    max_slider_length=500.0,
    print_info=False,
):
    """
    Parse an osu! Standard .osu file.

    The returned object represents the BASE beatmap.

    Important:
        - Hit-object vectors contain RAW values.
        - No mod-specific timing transformation is performed here.
        - No CNN normalization is performed here.
        - Variant-specific transformations should be applied later.

    Base vector format:

        (
            x_diff,
            y_diff,
            time_diff,
            length
        )

    where:

        x_diff     = normalized x displacement
        y_diff     = normalized y displacement
        time_diff  = original/base time difference in milliseconds
        length     = slider length
    """

    data = {
        "beatmap_id": None,

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

    timing_points = []

    # ========================================================
    # Read file
    # ========================================================

    section = None

    with open(file_path, "r", encoding="utf-8") as file:

        for line in file:
            line = line.strip()

            if not line:
                continue

            # ------------------------------------------------
            # Section header
            # ------------------------------------------------

            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue

            # =================================================
            # Metadata
            # =================================================

            if section == "Metadata":

                if ":" not in line:
                    continue

                key, value = line.split(":", maxsplit=1)
                value = value.strip()

                if key == "Title" and print_info:
                    print("Title: " + value, end=" ")

                elif key == "Artist" and print_info:
                    print("by " + value)

                elif key == "Creator" and print_info:
                    print("Mapper: " + value)

                elif key == "Version" and print_info:
                    print("Difficulty: " + value)

                elif key == "BeatmapID":
                    try:
                        data["beatmap_id"] = int(value)
                    except ValueError:
                        data["beatmap_id"] = None

            # =================================================
            # Difficulty
            # =================================================

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

            # =================================================
            # Timing Points
            # =================================================

            elif section == "TimingPoints":

                obj_data = line.split(",")

                if len(obj_data) < 2:
                    continue

                try:
                    time = float(obj_data[0])
                    beat_length = float(obj_data[1])
                except ValueError:
                    continue

                # ------------------------------------------------
                # Positive beat length = uninherited timing point.
                # ------------------------------------------------

                if beat_length > 0:

                    bpm = 60000.0 / beat_length

                    timing_points.append(
                        (time, bpm)
                    )

            # =================================================
            # Hit Objects
            # =================================================

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

                hit_circle_flag = 0b00000001
                slider_flag = 0b00000010

                # ------------------------------------------------
                # Circle
                # ------------------------------------------------

                if hit_object_type & hit_circle_flag:

                    hit_object = {
                        "x": x,
                        "y": y,
                        "time": time,
                        "length": 0.0,
                    }

                    data["hit_objects"].append(hit_object)

                # ------------------------------------------------
                # Slider
                # ------------------------------------------------

                elif hit_object_type & slider_flag:

                    if len(obj_data) <= 7:
                        continue

                    try:
                        slider_length = float(obj_data[7])
                    except ValueError:
                        slider_length = 0.0

                    slider_length = min(
                        max_slider_length,
                        max(0.0, slider_length),
                    )

                    hit_object = {
                        "x": x,
                        "y": y,
                        "time": time,
                        "length": slider_length,
                    }

                    data["hit_objects"].append(hit_object)

    # ========================================================
    # BPM
    # ========================================================

    if timing_points:

        bpms = [
            bpm
            for _, bpm in timing_points
        ]

        data["bpm"] = bpms[0]
        data["min_bpm"] = min(bpms)
        data["max_bpm"] = max(bpms)

    # ========================================================
    # Object Count
    # ========================================================

    data["object_count"] = len(
        data["hit_objects"]
    )

    # ========================================================
    # Base Map Length
    # ========================================================

    if len(data["hit_objects"]) >= 2:

        first_object_time = (
            data["hit_objects"][0]["time"]
        )

        last_object_time = (
            data["hit_objects"][-1]["time"]
        )

        data["length_seconds"] = (
            last_object_time - first_object_time
        ) / 1000.0

    else:

        data["length_seconds"] = 0.0

    # ========================================================
    # Create RAW Base Vectors
    # ========================================================
    #
    # Coordinates are normalized because the playfield has
    # a fixed size (512 x 384).
    #
    # Time and slider length remain RAW.
    #
    # No DT/HT/etc. transformation happens here.
    # ========================================================

    max_x = 512.0
    max_y = 384.0

    hit_objects = data["hit_objects"]

    if len(hit_objects) >= 2:

        for obj in hit_objects:

            obj["x_norm"] = obj["x"] / max_x
            obj["y_norm"] = obj["y"] / max_y

        vectors = []
        previous_speed = None
        previous_time_diff = None

        for i in range(1, len(hit_objects)):

            obj = hit_objects[i]
            prev_obj = hit_objects[i - 1]

            x_diff = obj["x_norm"] - prev_obj["x_norm"]
            y_diff = obj["y_norm"] - prev_obj["y_norm"]

            time_diff = obj["time"] - prev_obj["time"]
            length = obj["length"]

            distance = math.sqrt(x_diff ** 2 + y_diff ** 2)

            if time_diff > 0:
                speed = distance / time_diff
            else:
                speed = 0.0

            if previous_speed is None:
                speed_change = 0.0
                time_diff_change = 0.0
            else:
                speed_change = speed - previous_speed
                time_diff_change = time_diff - previous_time_diff

            vectors.append((
                x_diff,
                y_diff,
                time_diff,
                length,
                distance,
                speed,
                speed_change,
                time_diff_change,
            ))

        data["vectors"] = vectors

    else:

        data["vectors"] = []

    return data