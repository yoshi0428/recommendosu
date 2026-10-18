import copy
import json
import os
import sqlite3
from collections import defaultdict

import matplotlib.pyplot as plt
import numpy as np
import torch
from torch import nn, optim
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader, TensorDataset

from beatmap_classifier.classifier.cnn_model import CNNModel, compute_input_scale

# Tournament label (a tournament_predictions column) -> the mod it's played
# with. Order matters: get_tournament_labels() keeps the first label set.
# Freemod intentionally omitted for now.
TOURNAMENT_MODS = {
    "nm1": "NM",
    "nm2": "NM",
    "nm3": "NM",
    "nm4": "NM",
    "nm5": "NM",
    "nm6": "NM",
    "dt1": "DT",
    "dt2_and_dt3": "DT",
    "dt4": "DT",
    "hr1": "HR",
    "hr2": "HR",
    "hr3": "HR",
    "hd1": "HD",
    "hd2": "HD",
    "hd3": "HD",
    "tiebreaker": "NM",
}

# DT plays 1.5x faster: time_diff shrinks, speed grows.
DT_RATE = 1.5


def load_pytorch_models(model_folder, model_class, model_kwargs, device):
    model_paths = sorted(
        os.path.join(model_folder, filename)
        for filename in os.listdir(model_folder)
        if filename.endswith(".pth")
    )

    models = []

    for model_path in model_paths:
        model = model_class(**model_kwargs)
        state_dict = torch.load(model_path, map_location=device, weights_only=True)
        model.load_state_dict(state_dict)
        model.to(device)
        model.eval()
        models.append(model)

    return models


def pad_sequences_pt(sequences, dtype=torch.float32, maxlen=None):
    # Enforce float32 type and truncate sequences to maxlen if they exceed it
    processed_seqs = [torch.as_tensor(seq, dtype=dtype)[:maxlen] for seq in sequences]

    # Pad the truncated sequences
    padded = torch.nn.utils.rnn.pad_sequence(
        processed_seqs, batch_first=True, padding_value=0.0
    )

    # If the longest sequence was shorter than maxlen, manually pad the rest of the dimension
    if maxlen is not None and padded.shape[1] < maxlen:
        padding_size = maxlen - padded.shape[1]

        # pad syntax for 2D/3D tensors: (left_pad, right_pad) for the last dimension, etc.
        # This appends zeros to the end of the time/sequence dimension
        padded = torch.nn.functional.pad(
            padded, (0, 0, 0, padding_size) if padded.dim() == 3 else (0, padding_size)
        )

    return padded


def train_and_evaluate(
    X_train,
    y_train,
    X_val,
    y_val,
    input_channels,
    num_classes,
    max_length=3502,
    learning_rate=0.001,
    dropout_rate=0.5,
    l2_reg=0.001,
    batch_size=16,
    epochs=50,
    patience=5,
    random_flips=True,
):
    """
    X_train / X_val: [batch, channels, sequence], unaugmented.

    With random_flips, each training batch gets a random horizontal and/or
    vertical flip (x_diff / y_diff negated). This replaces the 4x copies
    augment_dataset() made: same augmentations, a quarter of the memory, and
    a fresh mix every epoch.
    """

    # Determine the device (GPU if available, otherwise CPU)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    X_train = torch.as_tensor(X_train, dtype=torch.float32)

    model = CNNModel(
        input_channels,
        num_classes,
        max_length,
        dropout_rate,
        input_scale=compute_input_scale(X_train),
    )
    model.to(device)

    # AdamW + Label Smoothing for smooth, regularized optimization
    optimizer = optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=l2_reg)
    scheduler = CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.1)

    train_dataset = TensorDataset(
        X_train,
        torch.as_tensor(y_train, dtype=torch.long),
    )

    val_dataset = TensorDataset(
        torch.as_tensor(X_val, dtype=torch.float32),
        torch.as_tensor(y_val, dtype=torch.long),
    )

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    # --- Setup EarlyStopping parameters ---
    patience_counter = 0
    best_val_loss = float("inf")
    best_model_weights = None

    # Setup history tracker dictionaries
    history = {
        "loss": [],
        "accuracy": [],
        "val_loss": [],
        "val_accuracy": [],
    }

    for epoch in range(epochs):
        # ================= TRAINING PHASE =================
        model.train()
        train_loss, train_correct, train_total = 0.0, 0, 0

        for inputs, targets in train_loader:
            inputs, targets = trim_padding(inputs.to(device)), targets.to(device)

            if random_flips:
                inputs = random_flip(inputs)

            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, targets)
            loss.backward()
            optimizer.step()

            # track metrics
            train_loss += loss.item() * inputs.size(0)
            predicted = outputs.argmax(dim=1)

            train_correct += (predicted == targets).sum().item()
            train_total += targets.size(0)

        scheduler.step()

        epoch_loss = train_loss / train_total
        epoch_acc = train_correct / train_total
        history["loss"].append(epoch_loss)
        history["accuracy"].append(epoch_acc)

        # ================= VALIDATION PHASE =================
        model.eval()
        val_loss, val_correct, val_total = 0.0, 0, 0

        with (
            torch.no_grad()
        ):  # Turn off gradient calculations for speed/memory efficiency
            for inputs, targets in val_loader:
                inputs, targets = trim_padding(inputs.to(device)), targets.to(device)

                outputs = model(inputs)
                loss = criterion(outputs, targets)

                val_loss += loss.item() * inputs.size(0)
                predicted = outputs.argmax(dim=1)

                val_correct += (predicted == targets).sum().item()
                val_total += targets.size(0)

        epoch_val_loss = val_loss / val_total
        epoch_val_acc = val_correct / val_total
        history["val_loss"].append(epoch_val_loss)
        history["val_accuracy"].append(epoch_val_acc)

        print(
            f"Epoch {epoch + 1}/{epochs} - loss: {epoch_loss:.4f} - acc: {epoch_acc:.4f} - val_loss: {epoch_val_loss:.4f} - val_acc: {epoch_val_acc:.4f}"
        )

        # Keep the best weights in memory & EarlyStopping
        if epoch_val_loss < best_val_loss:
            best_val_loss = epoch_val_loss
            patience_counter = 0
            best_model_weights = copy.deepcopy(model.state_dict())
        else:
            patience_counter += 1

        if patience_counter >= patience:
            print(f"Early stopping triggered at epoch {epoch + 1}")
            break

    # restore the best weights before returning the model
    if best_model_weights is not None:
        model.load_state_dict(best_model_weights)
        print(f"Restored best model weights with validation loss: {best_val_loss:.4f}")

    return model, history


def trim_padding(inputs):
    """
    Drop trailing all-zero positions shared by the whole batch.

    CNNModel masks padding, so this doesn't change its output; it only skips
    computing on padding (most maps are ~1000 objects padded to 4096).
    """
    nonzero = inputs.abs().sum(dim=(0, 1)) > 0
    if not nonzero.any():
        return inputs
    length = int(nonzero.nonzero().max()) + 1
    return inputs[:, :, :length]


def predict_proba(model, X, device, batch_size=256):
    """Softmax probabilities for X ([batch, channels, sequence]), in batches."""
    X = torch.as_tensor(X, dtype=torch.float32)
    model.eval()
    probs = []

    with torch.no_grad():
        for start in range(0, len(X), batch_size):
            logits = model(trim_padding(X[start : start + batch_size].to(device)))
            probs.append(torch.softmax(logits, dim=1).cpu())

    return torch.cat(probs).numpy()


def random_flip(inputs):
    """Negate x_diff and/or y_diff per sample. inputs: [batch, channels, sequence]."""
    batch_size = inputs.shape[0]
    flip_x = torch.randint(0, 2, (batch_size, 1), device=inputs.device) * 2 - 1
    flip_y = torch.randint(0, 2, (batch_size, 1), device=inputs.device) * 2 - 1

    inputs = inputs.clone()
    inputs[:, 0] *= flip_x
    inputs[:, 1] *= flip_y
    return inputs


def plot_training_history(history):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

    ax1.plot(history["loss"], label="Train Loss")
    ax1.plot(history["val_loss"], label="Validation Loss")
    ax1.set_title("Loss")
    ax1.legend()

    ax2.plot(history["accuracy"], label="Train Accuracy")
    ax2.plot(history["val_accuracy"], label="Validation Accuracy")
    ax2.set_title("Accuracy")
    ax2.legend()

    plt.show()


def get_tournament_labels(cursor):
    """
    Return a mapping:

        beatmap_id -> single tournament label

    Example:
        {
            123: "nm1",
            456: "dt2_and_dt3",
            789: "hr1",
        }
    """

    columns = list(TOURNAMENT_MODS)
    cursor.execute(f"""
        SELECT
            bv.beatmap_id,
            {", ".join(f"tp.{column}" for column in columns)}
        FROM beatmap_variants bv
        JOIN tournament_predictions tp
            ON tp.variant_id = bv.variant_id
    """)

    labels = {}

    for beatmap_id, *predictions in cursor.fetchall():
        for column, prediction in zip(columns, predictions):
            if prediction == 1:
                labels[beatmap_id] = column
                break

    return labels


def get_vector_normalization(cursor):
    """
    The scales get_data() divides the time_diff and length vector channels by.

    The model learns on these scaled values, so anything that feeds it later
    (precompute_nm1-5.py, test_model.py) must apply the same scaling. Save
    them next to the model with save_vector_normalization().
    """
    cursor.execute("SELECT MAX(v.time_diff), MAX(v.length) FROM beatmap_vectors v")
    max_time_diff, max_vector_length = cursor.fetchone()

    return {
        "max_time_diff": float(max_time_diff),
        "max_vector_length": float(max_vector_length),
    }


def save_vector_normalization(db_path, output_path):
    """Save get_data()'s vector scales next to the trained model."""
    conn = sqlite3.connect(db_path)
    try:
        normalization = get_vector_normalization(conn.cursor())
    finally:
        conn.close()

    with open(output_path, "w") as f:
        json.dump(normalization, f, indent=4)

    return normalization


def load_vector_normalization(path):
    with open(path) as f:
        return json.load(f)


def normalize_beatmap_vectors(vectors, normalization):
    """
    Scale parsed NM vectors (parse_osu_file()["vectors"]) the same way
    get_data() scales training vectors. Returns a new float32 array.
    """
    vectors = np.array(vectors, dtype=np.float32)
    vectors[:, 2] /= normalization["max_time_diff"]
    vectors[:, 3] /= normalization["max_vector_length"]
    vectors[:, 7] /= normalization["max_time_diff"]
    return vectors


def get_data(db_path, chunk_size=50000):
    """
    Load beatmaps
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    normalization = get_vector_normalization(cursor)
    max_vector_length = normalization["max_vector_length"]
    max_time_diff = normalization["max_time_diff"]
    print(f"Max Vector Length: {max_vector_length}")
    print(f"Max Time Diff: {max_time_diff}")

    # ========================================================
    # Tournament labels
    # ========================================================
    labels = get_tournament_labels(cursor)
    print(f"Tournament-labeled beatmaps: {len(labels)}")

    # Get maximum vector count
    cursor.execute("""
        SELECT
            beatmap_id,
            COUNT(*) AS vector_count
        FROM beatmap_vectors
        GROUP BY beatmap_id
        ORDER BY vector_count DESC
        LIMIT 1
    """)

    result = cursor.fetchone()
    if result is not None:
        print(f"Max Vector Count: {result[1]}")

    # Fetch vectors
    cursor.execute("""
        SELECT
            beatmap_id,
            x_diff,
            y_diff,
            time_diff,
            length,
            distance,
            speed,
            speed_change,
            time_diff_change
        FROM beatmap_vectors
    """)

    X = defaultdict(list)

    # Load database rows
    while True:
        rows = cursor.fetchmany(chunk_size)

        if not rows:
            break

        for (
            beatmap_id,
            x_diff,
            y_diff,
            time_diff,
            length,
            distance,
            speed,
            speed_change,
            time_diff_change,
        ) in rows:
            if beatmap_id not in labels:
                continue

            # Apply mod timing transformation
            rate = DT_RATE if TOURNAMENT_MODS[labels[beatmap_id]] == "DT" else 1.0

            # time_diff_change is scaled like time_diff, so the model sees
            # both in the same units.
            X[beatmap_id].append(
                (
                    x_diff,
                    y_diff,
                    time_diff / rate / max_time_diff,
                    length / max_vector_length,
                    distance,
                    speed * rate,
                    speed_change * rate,
                    time_diff_change / rate / max_time_diff,
                )
            )

    conn.close()

    # Convert to aligned lists
    beatmap_ids = list(X.keys())
    original_X = [
        np.array(X[beatmap_id], dtype=np.float32) for beatmap_id in beatmap_ids
    ]
    original_y = [labels[beatmap_id] for beatmap_id in beatmap_ids]

    print(f"Original beatmaps: {len(original_X)}")

    return original_X, original_y, beatmap_ids


def get_additional_features(db_path, y, beatmap_ids):
    """
    Per-map metadata for each (beatmap_id, label) from get_data(), looked up
    on the variant with that label's mod.

    Returns (raw, normalized), both keyed by (beatmap_id, mod).

    BPM should also be an additional feature
    """
    # Fixed normalization scales, sized for NM1-5. The pp values that follow
    # these eight features are left unscaled.
    scales = (
        10.0,  # ar
        10.0,  # od
        5.0,  # circle_size
        10.0,  # star_rating
        250.0,  # bpm
        3000.0,  # max_combo
        400.0,  # length_seconds
        2500.0,  # object_count
    )

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # For now, let's not take into account min/max BPM and focus on the CNN
    cursor.execute("""
        SELECT
            bv.beatmap_id,
            bv.mods,
            bv.ar,
            bv.od,
            bv.circle_size,
            bv.star_rating,
            bv.bpm,
            bv.max_combo,
            bv.length_seconds,
            bv.object_count,
            bv.pp,
            bv.pp_aim,
            bv.pp_speed,
            bv.pp_acc
        FROM beatmap_variants bv
    """)

    # Store all DB variants by (beatmap_id, mods)
    variants = {
        (beatmap_id, mods): tuple(features)
        for beatmap_id, mods, *features in cursor.fetchall()
    }

    conn.close()

    raw_additional_features = {}
    normalized_additional_features = {}

    # Match each beatmap_id with its required mod
    for beatmap_id, label in zip(beatmap_ids, y):
        key = (beatmap_id, TOURNAMENT_MODS[label])

        if key not in variants:
            print(
                f"WARNING: No variant found for beatmap_id={beatmap_id}, mods='{key[1]}'"
            )
            continue

        features = variants[key]
        raw_additional_features[key] = features
        normalized_additional_features[key] = (
            tuple(value / scale for value, scale in zip(features, scales))
            + features[len(scales) :]
        )

    return raw_additional_features, normalized_additional_features
