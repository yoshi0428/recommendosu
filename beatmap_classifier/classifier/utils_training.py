import copy
import os
import sqlite3
from collections import defaultdict
import matplotlib.pyplot as plt
import torch
import torch.optim as optim
from torch import nn
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader, TensorDataset
from beatmap_classifier.classifier.cnn_model import CNNModel

TOURNAMENT_LABELS = {
    "nm1": {
        "column": "nm1",
        "mods": [],
    },

    "nm2": {
        "column": "nm2",
        "mods": [],
    },

    "nm3": {
        "column": "nm3",
        "mods": [],
    },

    "nm4": {
        "column": "nm4",
        "mods": [],
    },

    "nm5": {
        "column": "nm5",
        "mods": [],
    },

    "nm6": {
        "column": "nm6",
        "mods": [],
    },

    "dt1": {
        "column": "dt1",
        "mods": ["DT"],
    },

    "dt2_and_dt3": {
        "column": "dt2_and_dt3",
        "mods": ["DT"],
    },

    "dt4": {
        "column": "dt4",
        "mods": ["DT"],
    },

    "hr1": {
        "column": "hr1",
        "mods": ["HR"],
    },

    "hr2": {
        "column": "hr2",
        "mods": ["HR"],
    },

    "hr3": {
        "column": "hr3",
        "mods": ["HR"],
    },

    "hd1": {
        "column": "hd1",
        "mods": ["HD"],
    },

    "hd2": {
        "column": "hd2",
        "mods": ["HD"],
    },

    "hd3": {
        "column": "hd3",
        "mods": ["HD"],
    },

    "tiebreaker": {
        "column": "tiebreaker",
        "mods": [],
    },
    # Freemod intentionally omitted for now.
}


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
    processed_seqs = [torch.tensor(seq, dtype=dtype)[:maxlen] for seq in sequences]

    # Pad the truncated sequences
    padded = torch.nn.utils.rnn.pad_sequence(processed_seqs, batch_first=True, padding_value=0.0)

    # If the longest sequence was shorter than maxlen, manually pad the rest of the dimension
    if maxlen is not None and padded.shape[1] < maxlen:
        padding_size = maxlen - padded.shape[1]

        # pad syntax for 2D/3D tensors: (left_pad, right_pad) for the last dimension, etc.
        # This appends zeros to the end of the time/sequence dimension
        padded = torch.nn.functional.pad(padded, (0, 0, 0, padding_size) if padded.dim() == 3 else (0, padding_size))

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
):

    # Determine the device (GPU if available, otherwise CPU)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = CNNModel(input_channels, num_classes, max_length, dropout_rate)
    model.to(device)

    # AdamW + Label Smoothing for smooth, regularized optimization
    optimizer = optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=l2_reg)
    scheduler = CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.1)

    train_dataset = TensorDataset(
        torch.as_tensor(X_train, dtype=torch.float32),
        torch.as_tensor(y_train, dtype=torch.long),
    )

    val_dataset = TensorDataset(
        torch.as_tensor(X_val, dtype=torch.float32),
        torch.as_tensor(y_val, dtype=torch.long),
    )

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    # --- Setup EarlyStopping & ModelCheckpoint parameters ---
    patience_counter = 0
    best_val_loss = float("inf")
    best_model_weights = None
    checkpoint_path = "./models/cnn_model_best.pth"  # Replaced .h5 with PyTorch extension

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
            inputs, targets = inputs.to(device), targets.to(device)

            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, targets)
            loss.backward()
            optimizer.step()

            # track metrics
            train_loss += loss.item() * inputs.size(0)
            predicted = outputs.argmax(dim=1)

            # targets are one-hot encoded, get class index
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

        with torch.no_grad():  # Turn off gradient calculations for speed/memory efficiency
            for inputs, targets in val_loader:
                inputs, targets = inputs.to(device), targets.to(device)

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
            f"Epoch {epoch+1}/{epochs} - loss: {epoch_loss:.4f} - acc: {epoch_acc:.4f} - val_loss: {epoch_val_loss:.4f} - val_acc: {epoch_val_acc:.4f}"
        )

        # ModelCheckpoint (save_best_only=True) & EarlyStopping
        if epoch_val_loss < best_val_loss:
            best_val_loss = epoch_val_loss
            patience_counter = 0
            best_model_weights = copy.deepcopy(model.state_dict())
            torch.save(model.state_dict(), checkpoint_path)
        else:
            patience_counter += 1

        if patience_counter >= patience:
            print(f"Early stopping triggered at epoch {epoch+1}")
            break

    # restore the best weights before returning the model
    if best_model_weights is not None:
        model.load_state_dict(best_model_weights)
        print(f"Restored best model weights with validation loss: {best_val_loss:.4f}")

    return model, history

def plot_training_history(history):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

    ax1.plot(history['loss'], label='Train Loss')
    ax1.plot(history['val_loss'], label='Validation Loss')
    ax1.set_title('Loss')
    ax1.legend()

    ax2.plot(history['accuracy'], label='Train Accuracy')
    ax2.plot(history['val_accuracy'], label='Validation Accuracy')
    ax2.set_title('Accuracy')
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

    cursor.execute("""
        SELECT
            bv.beatmap_id,
            tp.nm1,
            tp.nm2,
            tp.nm3,
            tp.nm4,
            tp.nm5,
            tp.nm6,
            tp.dt1,
            tp.dt2_and_dt3,
            tp.dt4,
            tp.hr1,
            tp.hr2,
            tp.hr3,
            tp.hd1,
            tp.hd2,
            tp.hd3,
            tp.tiebreaker
        FROM beatmap_variants bv
        JOIN tournament_predictions tp
            ON tp.variant_id = bv.variant_id
    """)

    labels = {}

    columns = [
        "nm1",
        "nm2",
        "nm3",
        "nm4",
        "nm5",
        "nm6",
        "dt1",
        "dt2_and_dt3",
        "dt4",
        "hr1",
        "hr2",
        "hr3",
        "hd1",
        "hd2",
        "hd3",
        "tiebreaker",
    ]

    for row in cursor.fetchall():
        beatmap_id = row[0]
        predictions = row[1:]

        for column, prediction in zip(columns, predictions):
            if prediction == 1:
                labels[beatmap_id] = column
                break

    return labels

def get_data(
    db_path,
    chunk_size=50000
):
    """
    Load beatmaps
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT MAX(v.length) FROM beatmap_vectors v"
    )

    max_vector_length, = cursor.fetchone()
    print(f"Max Vector Length: {max_vector_length}")

    cursor.execute(
        "SELECT MAX(v.time_diff) FROM beatmap_vectors v"
    )
    max_time_diff, = cursor.fetchone()
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

        for beatmap_id, x_diff, y_diff, time_diff, length, distance, speed, speed_change, time_diff_change in rows:

            if beatmap_id not in labels:
                continue

            label = labels[beatmap_id]
            tournament_info = TOURNAMENT_LABELS[label]
            mods = tournament_info["mods"]

            # ------------------------------------------------
            # Apply mod timing transformation
            # ------------------------------------------------

            if "DT" in mods:
                effective_time_diff = time_diff / 1.5
                effective_speed = speed * 1.5
                effective_speed_change = speed_change * 1.5
                effective_time_diff_change = time_diff_change / 1.5

            else:
                effective_time_diff = time_diff
                effective_speed = speed
                effective_speed_change = speed_change
                effective_time_diff_change = time_diff_change

            normalized_time_diff = effective_time_diff / max_time_diff
            normalized_length = length / max_vector_length

            X[beatmap_id].append((
                x_diff,
                y_diff,
                normalized_time_diff,
                normalized_length,
                distance,
                effective_speed,
                effective_speed_change,
                effective_time_diff_change,
            ))

    conn.close()

    # Convert to aligned lists
    beatmap_ids = list(X.keys())
    original_X = [X[beatmap_id] for beatmap_id in beatmap_ids]
    original_y = [labels[beatmap_id] for beatmap_id in beatmap_ids]

    print(f"Original beatmaps: {len(original_X)}")

    return original_X, original_y, beatmap_ids

def get_additional_features(db_path, y, beatmap_ids):
    """
    BPM should also be an additional feature

    :param db_path:
    :return:
    """
    # Fixed normalization scales
    # This was a scale for all mods, but we're just gonna go with NM1-5 for simplicity
    # AR_SCALE = 11.0
    # OD_SCALE = 11.0
    # CS_SCALE = 10.0
    # STAR_SCALE = 11.0
    #
    # BPM_SCALE = 400.0
    # COMBO_SCALE = 10000.0
    # LENGTH_SCALE = 1800.0
    # OBJECT_COUNT_SCALE = 3000.0

    AR_SCALE = 10.0
    OD_SCALE = 10.0
    CS_SCALE = 5.0
    STAR_SCALE = 10.0

    BPM_SCALE = 250.0
    COMBO_SCALE = 3000.0
    LENGTH_SCALE = 400.0
    OBJECT_COUNT_SCALE = 2500.0

    mods = []
    mods_flattened = []
    for i in range(len(y)):
        mods.append(TOURNAMENT_LABELS[y[i]]["mods"])
    for array in mods:
        mods_flattened.append(array[0] if array else '')

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
            bv.object_count
        FROM beatmap_variants bv
    """)

    # Store all DB variants by (beatmap_id, mods)
    variants = {}

    for (
        beatmap_id,
        mods,
        ar,
        od,
        circle_size,
        star_rating,
        bpm,
        max_combo,
        length_seconds,
        object_count,
    ) in cursor.fetchall():

        variants[(beatmap_id, mods)] = (
            ar,
            od,
            circle_size,
            star_rating,
            bpm,
            max_combo,
            length_seconds,
            object_count,
        )

    conn.close()

    raw_additional_features = {}
    normalized_additional_features = {}

    # Match each beatmap_id with its required mod
    for beatmap_id, mod in zip(beatmap_ids, mods_flattened):

        mod = mod if mod else "NM"
        key = (beatmap_id, mod)

        if key not in variants:
            print(f"WARNING: No variant found for beatmap_id={beatmap_id}, mods='{mod}'")
            continue

        (
            ar,
            od,
            circle_size,
            star_rating,
            bpm,
            max_combo,
            length_seconds,
            object_count,
        ) = variants[key]

        raw_additional_features[key] = (
            ar,
            od,
            circle_size,
            star_rating,
            bpm,
            max_combo,
            length_seconds,
            object_count,
        )

        normalized_additional_features[key] = (
            ar / AR_SCALE,
            od / OD_SCALE,
            circle_size / CS_SCALE,
            star_rating / STAR_SCALE,
            bpm / BPM_SCALE,
            max_combo / COMBO_SCALE,
            length_seconds / LENGTH_SCALE,
            object_count / OBJECT_COUNT_SCALE,
        )

    return raw_additional_features, normalized_additional_features