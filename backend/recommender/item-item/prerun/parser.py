def parse_osu_file(
    file_path,
    max_slider_length=500.0,
    max_time_diff=1000.0,
    print_info=False,
):
    """
    Parse an osu! Standard .osu file.

    The returned object represents the BASE beatmap.

    Tournament category / folder name is deliberately NOT stored
    here. Tournament labels belong to classifier predictions.
    """

    data = {
        "beatmap_id": None,
        "hp_drain": None,
        "circle_size": None,
        "od": None,
        "ar": None,
        "slider_multiplier": None,
        "slider_tick": None,
        "bpm": None,
        "min_bpm": None,
        "max_bpm": None,
        "length_seconds": None,
        "object_count": 0,
        "hit_objects": [],
    }

    timing_points = []

    # ========================================================
    # Read file
    # ========================================================

    with open(file_path, "r", encoding="utf-8") as file:
        lines = file.readlines()

    section = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # ----------------------------------------------------
        # Section header
        # ----------------------------------------------------

        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue

        # ====================================================
        # Metadata
        # ====================================================

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
                data["beatmap_id"] = int(value)

        # ====================================================
        # Difficulty
        # ====================================================

        elif section == "Difficulty":
            if ":" not in line:
                continue

            key, value = line.split(":", maxsplit=1)
            value = float(value)

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

        # ====================================================
        # Timing Points
        # ====================================================

        elif section == "TimingPoints":

            obj_data = line.split(",")
            if len(obj_data) < 2:
                continue

            time = float(obj_data[0])
            beat_length = float(obj_data[1])

            # Positive beat length = uninherited timing point.
            if beat_length > 0:
                bpm = 60000.0 / beat_length
                timing_points.append((time, bpm))

        # ====================================================
        # Hit Objects
        # ====================================================

        elif section == "HitObjects":

            obj_data = line.split(",")
            if len(obj_data) < 4:
                continue

            x = int(obj_data[0])
            y = int(obj_data[1])
            time = int(obj_data[2])
            hit_object_type = int(obj_data[3])

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

                hit_object = {
                    "x": x,
                    "y": y,
                    "time": time,
                    "length": min(max_slider_length, slider_length,),
                }
                data["hit_objects"].append(hit_object)

    # ========================================================
    # BPM
    # ========================================================

    if timing_points:

        bpms = [bpm for _, bpm in timing_points]

        data["bpm"] = bpms[0]
        data["min_bpm"] = min(bpms)
        data["max_bpm"] = max(bpms)

    # ========================================================
    # Object Count
    # ========================================================

    data["object_count"] = len(data["hit_objects"])

    # ========================================================
    # Base Map Length
    # ========================================================

    if len(data["hit_objects"]) >= 2:
        first_object_time = (data["hit_objects"][0]["time"])
        last_object_time = (data["hit_objects"][-1]["time"])
        data["length_seconds"] = (last_object_time - first_object_time) / 1000.0

    # A one-object map has zero duration according to our object-based definition.
    elif len(data["hit_objects"]) == 1:
        data["length_seconds"] = 0.0

    else:
        data["length_seconds"] = 0.0

    # ========================================================
    # Normalize Coordinates
    # ========================================================

    max_x = 512
    max_y = 384

    for obj in data["hit_objects"]:
        obj["x_norm"] = (obj["x"] / max_x)
        obj["y_norm"] = (obj["y"] / max_y)

    # ========================================================
    # Compute Time Differences
    # ========================================================

    if data["hit_objects"]:
        data["hit_objects"][0]["time_diff"] = 0
        for i, obj in enumerate(data["hit_objects"][1:], start=1):
            obj["time_diff"] = obj["time"] - data["hit_objects"][i - 1]["time"]

    return data