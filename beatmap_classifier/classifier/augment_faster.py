import numpy as np


def extract_movement_features_from_X(X_beatmap):
    if hasattr(X_beatmap, "detach"):
        X_beatmap = X_beatmap.detach().cpu().numpy()
    elif not isinstance(X_beatmap, np.ndarray):
        X_beatmap = np.array(X_beatmap)

    if X_beatmap.shape[0] == 8 and X_beatmap.shape[1] != 8:
        X_beatmap = X_beatmap.T

    valid_mask = X_beatmap[:, 2] != 0
    valid_vectors = X_beatmap[valid_mask]

    if len(valid_vectors) < 3:
        return np.zeros(12, dtype=np.float32)

    x_diffs = valid_vectors[:, 0]
    y_diffs = valid_vectors[:, 1]
    time_diffs = valid_vectors[:, 2]
    lengths = valid_vectors[:, 3]
    distances = valid_vectors[:, 4]
    speeds = valid_vectors[:, 5]
    speed_changes = valid_vectors[:, 6]

    # Angles calculation
    dx1, dy1 = x_diffs[:-1], y_diffs[:-1]
    dx2, dy2 = x_diffs[1:], y_diffs[1:]
    d1, d2 = distances[:-1], distances[1:]
    dot_products = (dx1 * dx2 + dy1 * dy2) / (d1 * d2 + 1e-5)
    angles = np.arccos(np.clip(dot_products, -1.0, 1.0))

    # 1. Base Geometry Features
    slider_lengths = lengths[lengths > 0]
    slider_ratio = float(len(slider_lengths)) / float(len(valid_vectors))
    slider_length_std = (
        float(np.std(slider_lengths)) if len(slider_lengths) > 1 else 0.0
    )

    # 2. Localized Tech Indicators (90th/95th Percentiles & Ratios)
    # Tech maps exhibit localized bursts of acceleration and acute turn spikes
    speed_change_95th = (
        float(np.percentile(np.abs(speed_changes), 95))
        if len(speed_changes) > 0
        else 0.0
    )
    angle_90th = float(np.percentile(angles, 90)) if len(angles) > 0 else 0.0

    # Sharp Turn Ratio: Turns sharper than 75 degrees (1.309 rad)
    sharp_turn_ratio = (
        float(np.sum(angles > 1.309)) / float(len(angles)) if len(angles) > 0 else 0.0
    )

    # Rhythm Complexity: Ratio of non-standard rhythm gaps (< 100ms or > 250ms)
    rhythm_variance = float(np.std(time_diffs)) if len(time_diffs) > 0 else 0.0

    return np.array(
        [
            # 1. slider_ratio: Base indicator for Alt/Tech. High ratio = lots of sliders (Alt/Tech). Low = mostly circles (Aim/Stream).
            slider_ratio,
            # 2. slider_length_std: Measures slider length variance. Tech maps use drastically different slider shapes/lengths; Alt maps are more uniform.
            np.clip(slider_length_std / 200.0, 0.0, 1.0),
            # 3. std(speeds): Overall cursor speed variance. High in maps with variable spacing and SV gimmicks (Tech).
            np.clip(float(np.std(speeds)) * 100.0, 0.0, 1.0),
            # 4. std(speed_changes): Volatility of acceleration. High when maps constantly switch between slow and fast movements (Tech/Alt).
            np.clip(float(np.std(speed_changes)) * 100.0, 0.0, 1.0),
            # 5. max(speed_changes): Captures the single most extreme "stop-and-go" cursor snap. A strong indicator for Tech gimmicks.
            np.clip(float(np.max(np.abs(speed_changes))) * 50.0, 0.0, 1.0),
            # 6. std(angles): Differentiates flow aim from snap aim. Streams have low variance (consistent flow); Aim/Tech have high variance (snaps/jumps).
            np.clip(float(np.std(angles)) / np.pi, 0.0, 1.0),
            # 7. mean(angles): Average angle size. Wide angles = jump patterns (Aim). Tight angles = continuous flow (Streams).
            np.clip(float(np.mean(angles)) / np.pi, 0.0, 1.0),
            # 8. rhythm_variance: How often the time gap between objects changes. Streams are near zero; Tech is high (mixed 1/4, 1/3, 1/6 rhythms).
            np.clip(rhythm_variance / 150.0, 0.0, 1.0),
            # 9. mean(distances): Average spacing between objects. The primary indicator for Aim consistency maps (large jumps).
            np.clip(float(np.mean(distances)) * 2.0, 0.0, 1.0),
            # 10. speed_change_95th: Captures localized peak acceleration bursts, ignoring one-off anomalies. Isolates intense Tech snaps.
            np.clip(speed_change_95th * 40.0, 0.0, 1.0),
            # 11. angle_90th: Captures the upper extreme of direction changes. Identifies maps with heavy "back-and-forth" linear jumps or cut-streams.
            np.clip(angle_90th / np.pi, 0.0, 1.0),
            # 12. sharp_turn_ratio: Density of acute angles (< 75 degrees). High in Tech/Alt maps which require continuous direction processing.
            sharp_turn_ratio,
        ],
        dtype=np.float32,
    )
