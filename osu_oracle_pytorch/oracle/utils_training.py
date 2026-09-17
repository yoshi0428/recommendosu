import copy
import os
import sqlite3
from collections import defaultdict
import matplotlib.pyplot as plt
import torch
import torch.optim as optim
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

# from backend.osu_oracle_pytorch.oracle.previous_cnn_model import CNN_Model
from osu_oracle_pytorch.oracle.cnn_model import CNN_Model


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
        X_test,
        y_test,
        input_channels,
        num_classes,
        max_length=3502,
        learning_rate=0.001,
        dropout_rate=0.5,
        l2_reg=0.001,
        batch_size=16,
        epochs=50,
        patience=5
):

    # Determine the device (GPU if available, otherwise CPU)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = CNN_Model(input_channels, num_classes, max_length, dropout_rate)
    model.to(device)

    optimizer = optim.Adam(model.parameters(), lr=learning_rate, weight_decay=l2_reg)
    criterion = nn.CrossEntropyLoss()

    train_dataset = TensorDataset(
        torch.as_tensor(X_train, dtype=torch.float32),
        torch.as_tensor(y_train, dtype=torch.long),
    )

    test_dataset = TensorDataset(
        torch.as_tensor(X_test, dtype=torch.float32),
        torch.as_tensor(y_test, dtype=torch.long),
    )

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False)

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

        epoch_loss = train_loss / train_total
        epoch_acc = train_correct / train_total
        history["loss"].append(epoch_loss)
        history["accuracy"].append(epoch_acc)

        # ================= VALIDATION PHASE =================
        model.eval()
        val_loss, val_correct, val_total = 0.0, 0, 0

        with torch.no_grad():  # Turn off gradient calculations for speed/memory efficiency
            for inputs, targets in test_loader:
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

    # IMPORTANT
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
            time_diff / ? AS normalized_time_diff,
            length / ? AS normalized_length
        FROM beatmap_vectors
    """, (
        max_time_diff,
        max_vector_length,
    ))

    X = defaultdict(list)

    # Load database rows
    while True:
        rows = cursor.fetchmany(chunk_size)

        if not rows:
            break

        for beatmap_id, x_diff, y_diff, normalized_time_diff, normalized_length in rows:
            if beatmap_id not in labels:
                continue
            X[beatmap_id].append((x_diff, y_diff, normalized_time_diff, normalized_length))

    conn.close()

    # Convert to aligned lists
    beatmap_ids = list(X.keys())
    original_X = [X[beatmap_id] for beatmap_id in beatmap_ids]
    original_y = [labels[beatmap_id] for beatmap_id in beatmap_ids]

    print(f"Original beatmaps: {len(original_X)}")

    return original_X, original_y, beatmap_ids

def get_additional_features(db_path):
    """
    BPM should also be an additional feature

    :param db_path:
    :return:
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT b.beatmap_id, b.ar, b.od, b.circle_size, bv.star_rating, 
        b.bpm, b.min_bpm, b.max_bpm, bv.max_combo, bv.length_seconds, bv.object_count
        FROM beatmaps b
        JOIN beatmap_variants bv ON b.beatmap_id = bv.beatmap_id
        ORDER BY b.beatmap_id
    ''')

    additional_features = {}

    for (beatmap_id, ar, od, circle_size, star_rating, bpm,
         min_bpm, max_bpm, max_combo, length_seconds, object_count) in cursor.fetchall():
        additional_features[beatmap_id] = (
            ar,
            od,
            circle_size,
            star_rating,
            bpm,
            min_bpm,
            max_bpm,
            max_combo,
            length_seconds,
            object_count
        )

    conn.close()

    return additional_features