import os
import pickle
import tempfile
import time

import numpy as np
import requests
import torch
import osu_tools
import xgboost as xgb

from beatmap_classifier.classifier.augment_faster import extract_movement_features_from_X
from beatmap_classifier.scripts.beatmap_mods import get_modded_stats, calculate_difficulty
from scripts.parser import parse_osu_file
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
AR_SCALE = 10.0
OD_SCALE = 10.0
CS_SCALE = 5.0
STAR_SCALE = 10.0
BPM_SCALE = 250.0
COMBO_SCALE = 3000.0
LENGTH_SCALE = 400.0
OBJECT_COUNT_SCALE = 2500.0


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/58.0.3029.110 Safari/537.3"
    )
}

# ============================================================
# Download beatmap
# ============================================================

def download_beatmap(beatmap_id):
    url = f"https://osu.direct/api/osu/{beatmap_id}"

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    if response.status_code != 200:
        print(
            f"Failed to download beatmap {beatmap_id}: "
            f"HTTP {response.status_code}"
        )
        return None

    return response.content


# ============================================================
# Metadata extraction
# ============================================================

def get_normalized_metadata(
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

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # These attribute names depend on the exact CalculationResult
    # returned by your version of osu-tools-py.
    #
    # Replace these with the same fields you currently use in
    # get_modded_stats().
    # --------------------------------------------------------

    stats = get_modded_stats(
        beatmap_data,
        difficulty_result,
        [],
    )

    features = np.array(
        [
            stats["ar"] / AR_SCALE,
            stats["od"] / OD_SCALE,
            stats["circle_size"] / CS_SCALE,
            stats["star_rating"] / STAR_SCALE,
            beatmap_data["bpm"] / BPM_SCALE,
            stats["max_combo"] / COMBO_SCALE,
            beatmap_data["length_seconds"] / LENGTH_SCALE,
            beatmap_data["object_count"] / OBJECT_COUNT_SCALE,
        ],
        dtype=np.float32,
    )

    return features


# ============================================================
# CNN inference
# ============================================================

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

    # [batch, sequence, channels]
    # ->
    # [batch, channels, sequence]
    padded = padded.permute(0, 2, 1)

    padded = padded.to(DEVICE)

    model_predictions = []

    for model in bagged_models:
        model = model.to(DEVICE)
        model.eval()

        with torch.no_grad():
            outputs = model(padded)
            probabilities = torch.softmax(outputs, dim=1)

        model_predictions.append(
            probabilities.cpu()
        )

    mean_prediction = torch.stack(
        model_predictions
    ).mean(dim=0)

    return mean_prediction[0].numpy()


# ============================================================
# Full inference
# ============================================================

def test_model_on_beatmap_id(
    beatmap_id,
    bagged_models,
    label_encoder,
    meta_scaler,
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
        # ----------------------------------------------------
        # Save downloaded .osu temporarily
        # ----------------------------------------------------

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".osu",
        ) as temp_file:

            temp_file.write(beatmap_bytes)
            temp_file_path = temp_file.name

        # ----------------------------------------------------
        # Parse beatmap
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Calculate NM difficulty
        #
        # This is important:
        #
        # The current XGBoost training pipeline uses:
        #     normalized_additional_features[(b_id, "NM")]
        #
        # Therefore inference should calculate the NM/base
        # metadata here as well.
        # ----------------------------------------------------

        difficulty_result = calculate_difficulty(
            temp_file_path,
            mods=[],
            star_calculator=star_calculator,
        )

        if difficulty_result is None:
            return

        # ----------------------------------------------------
        # CNN prediction
        # ----------------------------------------------------

        cnn_probs = predict_cnn(
            beatmap_vectors,
            bagged_models,
        )

        # ----------------------------------------------------
        # Movement features
        #
        # IMPORTANT:
        # Use the exact same function used during training.
        # ----------------------------------------------------

        movement_features = extract_movement_features_from_X(
            np.asarray(beatmap_vectors, dtype=np.float32)
        )

        movement_features = np.asarray(
            movement_features,
            dtype=np.float32,
        )

        # ----------------------------------------------------
        # Metadata features
        # ----------------------------------------------------

        metadata_features = get_normalized_metadata(
            beatmap_data,
            difficulty_result,
        )

        # ----------------------------------------------------
        # Combine metadata + movement features
        #
        # MUST have the exact same ordering as training:
        #
        #     X_additional =
        #         [sql_features, movement_features]
        # ----------------------------------------------------

        additional_features = np.hstack(
            [
                metadata_features,
                movement_features,
            ]
        ).reshape(1, -1)

        # ----------------------------------------------------
        # Apply TRAINED scaler
        #
        # NEVER fit here.
        # ----------------------------------------------------

        additional_features_scaled = meta_scaler.transform(
            additional_features
        )

        # ----------------------------------------------------
        # CNN probabilities + scaled additional features
        #
        # Same structure as:
        #
        # X_meta_train =
        #     np.hstack([oof_cnn_predictions,
        #                X_add_train_scaled])
        # ----------------------------------------------------

        meta_features = np.hstack(
            [
                cnn_probs.reshape(1, -1),
                additional_features_scaled,
            ]
        )

        # ----------------------------------------------------
        # XGBoost prediction
        # ----------------------------------------------------

        final_probabilities = meta_model.predict_proba(
            meta_features
        )[0]

        final_class_index = int(
            np.argmax(final_probabilities)
        )

        final_label = label_encoder.inverse_transform(
            [final_class_index]
        )[0]

        # ----------------------------------------------------
        # Print results
        # ----------------------------------------------------

        print("\nCNN predictions:")

        cnn_labels = label_encoder.inverse_transform(
            np.arange(len(cnn_probs))
        )

        cnn_predictions = sorted(
            zip(cnn_labels, cnn_probs),
            key=lambda x: x[1],
            reverse=True,
        )

        for label, probability in cnn_predictions:
            print(
                f"  {label:<8} "
                f"{probability:.4f}"
            )

        print("\nFinal XGBoost predictions:")

        final_predictions = sorted(
            zip(label_encoder.classes_, final_probabilities),
            key=lambda x: x[1],
            reverse=True,
        )

        for label, probability in final_predictions:
            print(
                f"  {label:<8} "
                f"{probability:.4f}"
            )

        print(
            f"\nFINAL PREDICTION: "
            f"{final_label}"
        )

    finally:
        if (
            temp_file_path is not None
            and os.path.exists(temp_file_path)
        ):
            os.unlink(temp_file_path)


# ============================================================
# Load everything once
# ============================================================

def main():

    start = time.perf_counter()

    print(f"Using device: {DEVICE}")

    # --------------------------------------------------------
    # Label encoder
    # --------------------------------------------------------

    with open(
        LABEL_ENCODER_PATH,
        "rb",
    ) as f:
        label_encoder = pickle.load(f)

    # --------------------------------------------------------
    # Meta scaler
    # --------------------------------------------------------

    with open(
        META_SCALER_PATH,
        "rb",
    ) as f:
        meta_scaler = pickle.load(f)

    # --------------------------------------------------------
    # XGBoost meta model
    # --------------------------------------------------------

    with open(
        META_MODEL_PATH,
        "rb",
    ) as f:
        meta_model = pickle.load(f)

    # --------------------------------------------------------
    # CNN models
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Star/difficulty calculator
    #
    # Create this ONCE rather than once per beatmap.
    # --------------------------------------------------------

    star_calculator = osu_tools.OsuCalculator()

    elapsed = time.perf_counter() - start

    print(
        f"\nLoaded models in {elapsed:.2f}s"
    )

    print(
        f"Loaded {len(bagged_models)} CNN models."
    )

    print(
        f"Classes: {list(label_encoder.classes_)}"
    )

    # --------------------------------------------------------
    # Interactive testing
    # --------------------------------------------------------

    while True:

        beatmap_id = input(
            "\nEnter beatmap ID (or 'exit'): "
        ).strip()

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
            meta_scaler=meta_scaler,
            meta_model=meta_model,
            star_calculator=star_calculator,
        )


if __name__ == "__main__":
    main()