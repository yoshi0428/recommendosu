"""
Try the trained classifier on any beatmap: enter a beatmap ID, and it
downloads the .osu file from osu.direct and prints the CNN's and the final
model's NM1-NM5 probabilities.
"""

import os
import tempfile
import time

import requests

from beatmap_classifier.classifier.inference import (
    UnclassifiableBeatmap,
    classify,
    load_classifier,
    read_vectors,
)
from beatmap_classifier.classifier_db_setup.parser import parse_osu_file
from beatmap_recommender.recommender_db_setup.beatmap_mods import (
    calculate_difficulty,
    get_modded_stats,
)
from beatmap_recommender.recommender_db_setup.star_calculator import (
    VersionAwareOsuCalculator,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/58.0.3029.110 Safari/537.3"
    )
}


def download_beatmap(beatmap_id):
    url = f"https://osu.direct/api/osu/{beatmap_id}"
    response = requests.get(url, headers=HEADERS, timeout=30)

    if response.status_code != 200:
        print(f"Failed to download beatmap {beatmap_id}: HTTP {response.status_code}")
        return None

    return response.content


def get_stats(file_path, star_calculator):
    """
    The NM stats the classifier needs (inference.SQL_FEATURE_NAMES), worked
    out from the .osu file the way populate.py stores them in beatmap_variants.
    """
    beatmap_data = parse_osu_file(file_path, print_info=True)
    difficulty_result = calculate_difficulty(file_path, mods=[], star_calculator=star_calculator)

    if beatmap_data is None or difficulty_result is None:
        return None

    stats = get_modded_stats(beatmap_data, difficulty_result, [])

    for name in ("bpm", "length_seconds", "object_count"):
        stats[name] = beatmap_data[name]

    return stats


def test_model_on_beatmap_id(beatmap_id, classifier, star_calculator):
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

        stats = get_stats(temp_file_path, star_calculator)

        if stats is None:
            print("Invalid .osu file.")
            return

        try:
            prediction = classify(classifier, read_vectors(temp_file_path), stats)
        except UnclassifiableBeatmap as e:
            print(e)
            return

        labels = classifier.label_encoder.classes_

        print("\nCNN predictions:")
        for label, probability in sorted(zip(labels, prediction["cnn_probabilities"]), key=lambda x: x[1], reverse=True):
            print(f"  {label:<8} {probability:.4f}")

        print("\nFinal XGBoost predictions:")
        for label, probability in sorted(prediction["probabilities"].items(), key=lambda x: x[1], reverse=True):
            print(f"  {label:<8} {probability:.4f}")

        print(f"\nFINAL PREDICTION: {prediction['label']}")

    finally:
        if temp_file_path is not None and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


def main():
    start = time.perf_counter()

    classifier = load_classifier()
    star_calculator = VersionAwareOsuCalculator()

    print(f"\nLoaded models in {time.perf_counter() - start:.2f}s")
    print(f"Using device: {classifier.device}")
    print(f"Loaded {len(classifier.cnn_models)} CNN models.")
    print(f"Classes: {list(classifier.label_encoder.classes_)}")

    while True:
        beatmap_id = input("\nEnter beatmap ID (or 'exit'): \n").strip()

        if beatmap_id.lower() == "exit":
            break

        try:
            beatmap_id = int(beatmap_id)
        except ValueError:
            print("Beatmap ID must be an integer.")
            continue

        test_model_on_beatmap_id(beatmap_id, classifier, star_calculator)


if __name__ == "__main__":
    main()
