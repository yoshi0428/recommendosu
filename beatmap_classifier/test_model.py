import os
import pickle
import tempfile
import time
import numpy as np
import requests
import torch
from scripts.parser import parse_osu_file
from beatmap_classifier.oracle.utils_training import pad_sequences_pt, load_pytorch_models
from beatmap_classifier.oracle.cnn_model import CNNModel

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def test_model_on_beatmap_id(
    beatmap_id,
    bagged_models,
    max_sequence_length,
    max_slider_length,
    label_encoder_path
):
    # ---------------------------------------------------------
    # Load the label encoder
    # ---------------------------------------------------------
    with open(label_encoder_path, "rb") as f:
        label_encoder = pickle.load(f)

    # ---------------------------------------------------------
    # Fetch the .osu file
    # ---------------------------------------------------------
    url = f"https://osu.direct/api/osu/{beatmap_id}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/58.0.3029.110 Safari/537.3"
        )
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"Error fetching .osu file for beatmap ID {beatmap_id}: {response.status_code}")
        return

    # ---------------------------------------------------------
    # Save the .osu file temporarily
    # ---------------------------------------------------------
    temp_file_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(response.content)
            temp_file_path = temp_file.name

        # -----------------------------------------------------
        # Parse the beatmap
        # -----------------------------------------------------
        beatmap_data = parse_osu_file(temp_file_path, max_slider_length, print_info=True)

        if beatmap_data is None:
            print("Invalid .osu file.")
            return

        beatmap_vectors = beatmap_data["vectors"]

        # -----------------------------------------------------
        # Pad sequence
        # -----------------------------------------------------
        beatmap_vectors_padded = pad_sequences_pt(
            [beatmap_vectors],
            dtype=torch.float32,
            maxlen=max_sequence_length
        )

        # CNN expects:
        # [1, 4, sequence_length]
        beatmap_vectors_padded = beatmap_vectors_padded.permute(0, 2, 1)

        # -----------------------------------------------------
        # Get predictions from each model
        # -----------------------------------------------------
        model_predictions = []

        for model in bagged_models:
            model.to(device)
            model.eval()

            with torch.no_grad():
                inputs = beatmap_vectors_padded.to(device)
                outputs = model(inputs)
                probabilities = torch.softmax(outputs, dim=1)

            model_predictions.append(probabilities.cpu())

            # Keep only one model on the GPU at a time
            model.cpu()

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        # -----------------------------------------------------
        # Average predictions across the bagged models
        # -----------------------------------------------------
        y_preds_mean = torch.stack(model_predictions).mean(dim=0)
        confidences = y_preds_mean[0].numpy()

        # -----------------------------------------------------
        # Convert class indices back to category names
        # -----------------------------------------------------
        categories = label_encoder.inverse_transform(np.arange(len(confidences)))

        predictions = list(zip(categories, confidences))

        # Sort by confidence
        sorted_predictions = sorted(predictions, key=lambda x: x[1], reverse=True)

        # Print predictions
        print("\nPredictions:")
        for category, confidence in sorted_predictions:
            print(f"{category} - confidence: {confidence:.2f}")

    finally:
        if temp_file_path is not None and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)

def test_model(model_folder, label_encoder_path, max_length, num_classes):
    """
    Load PyTorch models from each folder and interactively classify
    osu! beatmaps by beatmap ID.

    :param folders: List of model folders.
    :param label_encoder_path: Path to the shared label encoder.
    """

    start = time.perf_counter()

    model_kwargs = {
        "input_channels": 8,
        "num_classes": num_classes,
        "max_length": max_length, # tweak this later
        "dropout_rate": 0.5,
    }

    models = load_pytorch_models(model_folder, CNNModel, model_kwargs, device)
    print("----------------------------------------------------")
    print(f"Model: {models[0]}")
    print("----------------------------------------------------")

    end = time.perf_counter()

    max_slider_length = 500.0

    print(f"Loading Time: {end - start:.2f}s")

    while True:
        print("----------------------------------------------------")
        beatmap_id = input("Enter a beatmap ID to classify (or 'exit' to quit):\n")

        if beatmap_id.lower() == "exit":
            break

        print("----------------------------------------------------")

        test_model_on_beatmap_id(
            beatmap_id,
            models,
            max_sequence_length=max_length,
            max_slider_length=max_slider_length,
            label_encoder_path=label_encoder_path,
        )

def main():
    label_encoder_path = "models/label_encoder.pkl"
    max_length = 4096
    num_classes = 5
    test_model("models/bagged_models", label_encoder_path, max_length, num_classes)

if __name__ == "__main__":
    main()