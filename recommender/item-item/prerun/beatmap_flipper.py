import copy

def flip_beatmap(
    beatmap_data,
    horizontal=False,
    vertical=False,
    max_slider_length=500.0,
    max_time_diff=1000.0
):
    """
    Create a flipped copy of the base beatmap.

    These are data augmentations for the CNN.

    They are NOT separate beatmap records and do NOT receive
    separate variant IDs.
    """
    max_x = 512
    max_y = 384

    flipped_data = copy.deepcopy(
        beatmap_data
    )

    # --------------------------------------------------------
    # Flip coordinates
    # --------------------------------------------------------

    for obj in flipped_data["hit_objects"]:

        if horizontal:
            obj["x"] = max_x - obj["x"]

        if vertical:
            obj["y"] = max_y - obj["y"]

    # --------------------------------------------------------
    # Recalculate normalized coordinates
    # --------------------------------------------------------

    for obj in flipped_data["hit_objects"]:

        obj["x_norm"] = (
            obj["x"] / max_x
        )

        obj["y_norm"] = (
            obj["y"] / max_y
        )

    # --------------------------------------------------------
    # Recalculate vectors
    # --------------------------------------------------------

    vectors = []

    for i, obj in enumerate(
        flipped_data["hit_objects"][1:],
        start=1,
    ):

        prev_obj = (
            flipped_data["hit_objects"][i - 1]
        )

        x_diff = (
            obj["x_norm"]
            - prev_obj["x_norm"]
        )

        y_diff = (
            obj["y_norm"]
            - prev_obj["y_norm"]
        )

        time_diff = obj["time_diff"]
        length = obj["length"]

        vectors.append((
            x_diff,
            y_diff,
            time_diff / max_time_diff,
            length / max_slider_length,
        ))

    flipped_data["vectors"] = vectors

    return flipped_data
