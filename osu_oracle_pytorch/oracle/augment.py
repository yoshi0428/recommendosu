def augment_dataset(
    X,
    y,
    beatmap_ids,
    augmentation_types=None,
    augmentation_ids=None,
):
    """
    Augment a dataset after train/test splitting.

    The original sample is always retained.

    Parameters
    ----------
    X : list
        Beatmap vector sequences.

    y : list
        Labels.

    beatmap_ids : list
        Beatmap database IDs.

    augmentation_types : set[str] | None
        Supported:
            "horizontal"
            "vertical"
            "horizontal_vertical"

        None:
            All augmentations.

        Empty set:
            No augmentation.

    augmentation_ids : set[int] | None
        Beatmap IDs to augment.

        None:
            Augment all beatmaps.

        Set:
            Only augment those beatmaps.

    Returns
    -------
    augmented_X
    augmented_y
    augmented_ids
    """

    valid_augmentations = {
        "horizontal",
        "vertical",
        "horizontal_vertical",
    }

    if augmentation_types is None:
        augmentation_types = valid_augmentations.copy()
    else:
        augmentation_types = set(augmentation_types)

        invalid = augmentation_types - valid_augmentations

        if invalid:
            raise ValueError(
                f"Unknown augmentation types: {invalid}. "
                f"Valid types: {valid_augmentations}"
            )

    # --------------------------------------------------------
    # No augmentation
    # --------------------------------------------------------
    if not augmentation_types:
        print("Augmentation: DISABLED")

        return (
            list(X),
            list(y),
            list(beatmap_ids),
        )

    print("Augmentation: ENABLED")
    print(
        "Augmentation types:",
        sorted(augmentation_types),
    )

    if augmentation_ids is None:
        print("Augmentation IDs: ALL")
    else:
        print(
            f"Augmentation IDs: "
            f"{len(augmentation_ids)} selected"
        )

    augmented_X = []
    augmented_y = []
    augmented_ids = []

    # --------------------------------------------------------
    # Original + selected augmentations
    # --------------------------------------------------------
    for vectors, label, beatmap_id in zip(
        X,
        y,
        beatmap_ids,
    ):

        # ----------------------------------------------------
        # Always retain original
        # ----------------------------------------------------
        augmented_X.append(vectors)
        augmented_y.append(label)
        augmented_ids.append(beatmap_id)

        # ----------------------------------------------------
        # Check whether this ID should be augmented
        # ----------------------------------------------------
        if (
            augmentation_ids is not None
            and beatmap_id not in augmentation_ids
        ):
            continue

        # ----------------------------------------------------
        # Horizontal
        # ----------------------------------------------------
        if "horizontal" in augmentation_types:

            horizontal = [
                (
                    -x_diff,
                    y_diff,
                    time_diff,
                    length,
                )
                for (
                    x_diff,
                    y_diff,
                    time_diff,
                    length,
                ) in vectors
            ]

            augmented_X.append(horizontal)
            augmented_y.append(label)
            augmented_ids.append(beatmap_id)

        # ----------------------------------------------------
        # Vertical
        # ----------------------------------------------------
        if "vertical" in augmentation_types:

            vertical = [
                (
                    x_diff,
                    -y_diff,
                    time_diff,
                    length,
                )
                for (
                    x_diff,
                    y_diff,
                    time_diff,
                    length,
                ) in vectors
            ]

            augmented_X.append(vertical)
            augmented_y.append(label)
            augmented_ids.append(beatmap_id)

        # ----------------------------------------------------
        # Horizontal + Vertical
        # ----------------------------------------------------
        if "horizontal_vertical" in augmentation_types:

            horizontal_vertical = [
                (
                    -x_diff,
                    -y_diff,
                    time_diff,
                    length,
                )
                for (
                    x_diff,
                    y_diff,
                    time_diff,
                    length,
                ) in vectors
            ]

            augmented_X.append(horizontal_vertical)
            augmented_y.append(label)
            augmented_ids.append(beatmap_id)

    print(
        f"Original training samples: {len(X)}"
    )

    print(
        f"Augmented training samples: "
        f"{len(augmented_X)}"
    )

    return (
        augmented_X,
        augmented_y,
        augmented_ids,
    )