import os
import pickle
import tempfile
import time

import numpy as np
import requests
import torch
import osu_tools

from beatmap_classifier.classifier.augment_faster import extract_movement_features_from_X
from beatmap_classifier.classifier_db_setup.beatmap_mods import get_modded_stats, calculate_difficulty
from classifier_db_setup.parser import parse_osu_file
from beatmap_classifier.classifier.utils_training import (
    pad_sequences_pt,
    load_pytorch_models,
)
from beatmap_classifier.classifier.cnn_model import CNNModel


# ============================================================
# Configuration
# ============================================================

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

MODEL_FOLDER = "models/bagged_models"
LABEL_ENCODER_PATH = "models/label_encoder.pkl"
META_SCALER_PATH = "models/meta_scaler.pkl"
META_MODEL_PATH = "models/meta_model.pkl"

MAX_SEQUENCE_LENGTH = 4096
MAX_SLIDER_LENGTH = 500.0
NUM_CLASSES = 5

# Same normalization constants used during training
# AR_SCALE = 10.0
# OD_SCALE = 10.0
# CS_SCALE = 5.0
# STAR_SCALE = 10.0
# BPM_SCALE = 250.0
# COMBO_SCALE = 3000.0
# LENGTH_SCALE = 400.0
# OBJECT_COUNT_SCALE = 2500.0


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/58.0.3029.110 Safari/537.3"
    )
}

sql_feature_names = [
    "ar",
    "od",
    "circle_size",
    "star_rating",
    "bpm",
    "max_combo",
    "length_seconds",
    "object_count",
    "pp",
    "pp_aim",
    "pp_speed",
    "pp_acc"
]

movement_feature_names = [
    "slider_ratio",
    "slider_length_std",
    "speed_std",
    "speed_change_std",
    "speed_change_max",
    "angle_std",
    "angle_mean",
    "rhythm_variance",
    "distance_mean",
    "speed_change_95th",
    "angle_90th",
    "sharp_turn_ratio",
]

cnn_feature_names = [
    # "CNN_DT1",
    # "CNN_DT2_AND_DT3",
    # "CNN_HD2",
    # "CNN_HR1",
    # "CNN_HR2",
    "CNN_NM1",
    "CNN_NM2",
    "CNN_NM3",
    "CNN_NM4",
    "CNN_NM5",
]

additional_feature_names = (
    sql_feature_names +
    movement_feature_names
)

selected_features = [
    feature
    for feature in additional_feature_names
    # if feature != "rhythm_variance"
]

indices = [
    additional_feature_names.index(name)
    for name in selected_features
]

def download_beatmap(beatmap_id):
    url = f"https://osu.direct/api/osu/{beatmap_id}"

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    if response.status_code != 200:
        print(f"Failed to download beatmap {beatmap_id}: HTTP {response.status_code}")
        return None

    return response.content

def get_metadata(
    beatmap_data,
    difficulty_result,
):
    """
    Build the same 8 metadata features used during training.

    Feature order MUST remain:

        AR
        OD
        CS
        star_rating
        BPM
        max_combo
        length_seconds
        object_count
    """
    stats = get_modded_stats(beatmap_data, difficulty_result, [],)

    features = np.array(
        [
            stats["ar"],
            stats["od"],
            stats["circle_size"],
            stats["star_rating"],
            beatmap_data["bpm"],
            stats["max_combo"],
            beatmap_data["length_seconds"],
            beatmap_data["object_count"],
            stats["pp"],
            stats["pp_aim"],
            stats["pp_speed"],
            stats["pp_acc"],
        ],
        dtype=np.float32,
    )

    return features

def predict_cnn(
    beatmap_vectors,
    bagged_models,
):
    """
    Run the beatmap through all CNN models and average
    their probability predictions.
    """

    padded = pad_sequences_pt(
        [beatmap_vectors],
        dtype=torch.float32,
        maxlen=MAX_SEQUENCE_LENGTH,
    )

    # [batch, sequence, channels] -> [batch, channels, sequence]
    padded = padded.permute(0, 2, 1)
    padded = padded.to(DEVICE)

    model_predictions = []
    for model in bagged_models:
        model = model.to(DEVICE)
        model.eval()

        with torch.no_grad():
            outputs = model(padded)
            probabilities = torch.softmax(outputs, dim=1)

        model_predictions.append(probabilities.cpu())

    mean_prediction = torch.stack(model_predictions).mean(dim=0)
    return mean_prediction[0].numpy()

def test_model_on_beatmap_id(
    beatmap_id,
    bagged_models,
    label_encoder,
    meta_model,
    star_calculator,
):
    print("\n" + "=" * 70)
    print(f"Testing beatmap ID: {beatmap_id}")
    print("=" * 70)

    beatmap_bytes = download_beatmap(beatmap_id)

    if beatmap_bytes is None:
        return

    temp_file_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".osu") as temp_file:
            temp_file.write(beatmap_bytes)
            temp_file_path = temp_file.name

        beatmap_data = parse_osu_file(
            temp_file_path,
            max_slider_length=MAX_SLIDER_LENGTH,
            print_info=True,
        )

        if beatmap_data is None:
            print("Invalid .osu file.")
            return

        beatmap_vectors = beatmap_data["vectors"]

        if len(beatmap_vectors) == 0:
            print("Beatmap contains no usable vectors.")
            return

        difficulty_result = calculate_difficulty(
            temp_file_path,
            mods=[],
            star_calculator=star_calculator,
        )

        if difficulty_result is None:
            return

        cnn_probs = predict_cnn(beatmap_vectors, bagged_models)

        # Combine metadata + movement features
        movement_features = extract_movement_features_from_X(np.asarray(beatmap_vectors, dtype=np.float32))
        movement_features = np.asarray(movement_features, dtype=np.float32)
        metadata_features = get_metadata(beatmap_data, difficulty_result)

        # MUST have the exact same ordering as training:
        # X_additional = [sql_features, movement_features]
        additional_features = np.hstack([metadata_features, movement_features]).reshape(1, -1)

        # CNN probabilities + SELECTED additional features
        meta_features = np.hstack([cnn_probs.reshape(1, -1), additional_features[:, indices]])

        # XGBoost prediction
        final_probabilities = meta_model.predict_proba(meta_features)[0]
        final_class_index = int(np.argmax(final_probabilities))
        final_label = label_encoder.inverse_transform([final_class_index])[0]

        # Print results
        print("\nCNN predictions:")

        cnn_labels = label_encoder.inverse_transform(np.arange(len(cnn_probs)))
        cnn_predictions = sorted(zip(cnn_labels, cnn_probs), key=lambda x: x[1], reverse=True)

        for label, probability in cnn_predictions:
            print(f"  {label:<8} {probability:.4f}")

        print("\nFinal XGBoost predictions:")

        final_predictions = sorted(zip(label_encoder.classes_, final_probabilities), key=lambda x: x[1], reverse=True)

        for label, probability in final_predictions:
            print(f"  {label:<8} {probability:.4f}")

        print(f"\nFINAL PREDICTION: {final_label}")

    finally:
        if temp_file_path is not None and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)

def main():

    start = time.perf_counter()
    print(f"Using device: {DEVICE}")

    with open(LABEL_ENCODER_PATH, "rb") as f:
        label_encoder = pickle.load(f)

    with open(META_MODEL_PATH, "rb") as f:
        meta_model = pickle.load(f)

    model_kwargs = {
        "input_channels": 8,
        "num_classes": NUM_CLASSES,
        "max_length": MAX_SEQUENCE_LENGTH,
        "dropout_rate": 0.5,
    }

    bagged_models = load_pytorch_models(
        MODEL_FOLDER,
        CNNModel,
        model_kwargs,
        DEVICE,
    )

    star_calculator = osu_tools.OsuCalculator()
    elapsed = time.perf_counter() - start

    print(f"\nLoaded models in {elapsed:.2f}s")
    print(f"Loaded {len(bagged_models)} CNN models.")
    print(f"Classes: {list(label_encoder.classes_)}")

    while True:
        beatmap_id = input("\nEnter beatmap ID (or 'exit'):\n").strip()

        if beatmap_id.lower() == "exit":
            break

        try:
            beatmap_id = int(beatmap_id)
        except ValueError:
            print("Beatmap ID must be an integer.")
            continue

        test_model_on_beatmap_id(
            beatmap_id=beatmap_id,
            bagged_models=bagged_models,
            label_encoder=label_encoder,
            meta_model=meta_model,
            star_calculator=star_calculator,
        )


if __name__ == "__main__":
    main()