"""
Try the trained classifier on any beatmap. Enter a beatmap ID. The script
downloads the .osu file from osu.direct and prints the NM1-NM5 probabilities
of the fusion classifier.
"""

import os
import tempfile
import time

import requests

from beatmap_classifier.classifier.inference import (
    STAT_MODS,
    UnclassifiableBeatmap,
    classify,
    load_classifier,
)
from beatmap_classifier.classifier_db_setup.parser import parse_osu_file
from beatmap_classifier.dot_osu_extract.downloader_backoff import BASE_URL, HEADERS
from beatmap_recommender.recommender_db_setup.beatmap_mods import (
    apply_bpm_mod,
    apply_length_mod,
    calculate_difficulty,
    get_modded_stats,
)
from beatmap_recommender.recommender_db_setup.star_calculator import VersionAwareOsuCalculator


def download_beatmap(beatmap_id):
    """Return the .osu file of the beatmap from osu.direct, or None if the download fails."""
    response = requests.get(f"{BASE_URL}/{beatmap_id}", headers=HEADERS, timeout=30)

    if response.status_code != 200:
        print(f"Failed to download beatmap {beatmap_id}: HTTP {response.status_code}")
        return None

    return response.content


def get_stats_by_mod(file_path, star_calculator):
    """
    Return the stats of each mod that the classifier needs ({mod: stats} for
    STAT_MODS). They come from the .osu file, calculated as populate.py stores
    them in beatmap_variants (db_insertion.insert_variant()).
    """
    beatmap_data = parse_osu_file(file_path, print_info=True)

    if beatmap_data is None:
        return None

    stats_by_mod = {}

    for mod in STAT_MODS:
        mods = [] if mod == "NM" else [mod]
        difficulty_result = calculate_difficulty(file_path, mods=mods, star_calculator=star_calculator)

        if difficulty_result is None:
            return None

        stats = get_modded_stats(beatmap_data, difficulty_result, mods)
        stats["bpm"] = apply_bpm_mod(beatmap_data["bpm"], beatmap_data["min_bpm"], beatmap_data["max_bpm"], mods)[0]
        stats["length_seconds"] = apply_length_mod(beatmap_data["length_seconds"], mods)
        stats["object_count"] = beatmap_data["object_count"]
        stats_by_mod[mod] = stats

    return stats_by_mod


def test_model_on_beatmap_id(beatmap_id, classifier, star_calculator):
    """Download one beatmap, classify it, and print the result."""
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

        stats_by_mod = get_stats_by_mod(temp_file_path, star_calculator)

        if stats_by_mod is None:
            print("Invalid .osu file.")
            return

        try:
            prediction = classify(classifier, temp_file_path, stats_by_mod)
        except UnclassifiableBeatmap as e:
            print(e)
            return

        print("\nPredictions (scaled to sum to 1; per-slot probability in brackets):")
        for label, probability in sorted(prediction["probabilities"].items(), key=lambda x: x[1], reverse=True):
            print(f"  {label:<8} {probability:.4f}  ({prediction['slot_probabilities'][label]:.4f})")

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
    print(f"Loaded {len(classifier.models)} fusion models.")
    print(f"Classes: {classifier.classes}")

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
