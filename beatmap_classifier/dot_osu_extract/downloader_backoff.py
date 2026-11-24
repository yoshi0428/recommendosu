import os
import random
import sys
import time
from pathlib import Path

"""
Download the .osu file of each beatmap ID in a list, from osu.direct. The
script waits between requests, and backs off on rate limits and server errors.

    python downloader_backoff.py [input.txt | folder]
"""

import requests

OUTPUTS = Path(__file__).resolve().parent / "outputs"
BASE_URL = "https://osu.direct/api/osu"
REQUEST_DELAY = 0.75
MAX_RETRIES = 8
INITIAL_BACKOFF = 5
MAX_BACKOFF = 300
TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    )
}


def backoff_delay(retry_number):
    """Exponential backoff with 0-25% random jitter, MAX_BACKOFF at most."""
    delay = min(INITIAL_BACKOFF * (2**retry_number), MAX_BACKOFF)
    return min(delay * random.uniform(1.0, 1.25), MAX_BACKOFF)


def get_retry_delay(response, retry_number):
    """Return the wait after a 429: the Retry-After header if it is a number. If not, use backoff_delay()."""
    try:
        return min(float(response.headers["Retry-After"]), MAX_BACKOFF)
    except (KeyError, ValueError):
        return backoff_delay(retry_number)


def download_file(session, beatmap_id, file_path):
    """
    Download one beatmap. On a rate limit, a server error or a network error,
    wait and try again, up to MAX_RETRIES times.

    Returns:
        True  -> the download succeeded
        False -> the download failed after all the retries
    """

    url = f"{BASE_URL}/{beatmap_id}"

    for retry_number in range(MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=TIMEOUT)  # The session sends HEADERS.
        except requests.RequestException as e:
            if retry_number >= MAX_RETRIES:
                print(f"{beatmap_id}: request failed after {MAX_RETRIES} retries: {e}")
                return False

            delay = backoff_delay(retry_number)
            print(f"{beatmap_id}: network error: {e}")
            print(f"Retrying in {delay:.1f} seconds...")
            time.sleep(delay)
            continue

        # Success
        if response.status_code == 200:
            with open(file_path, "wb") as outfile:
                outfile.write(response.content)
            return True

        # Rate limited
        if response.status_code == 429:
            if retry_number >= MAX_RETRIES:
                print(f"{beatmap_id}: still rate limited after {MAX_RETRIES} retries.")
                return False

            delay = get_retry_delay(response, retry_number)
            print(f"{beatmap_id}: HTTP 429 - rate limited.")
            print(f"Waiting {delay:.1f} seconds before retry...")
            time.sleep(delay)
            continue

        # Server errors
        if response.status_code in (500, 502, 503, 504):
            if retry_number >= MAX_RETRIES:
                print(f"{beatmap_id}: server error {response.status_code} after retries.")
                return False

            delay = backoff_delay(retry_number)
            print(f"{beatmap_id}: HTTP {response.status_code}.")
            print(f"Retrying in {delay:.1f} seconds...")
            time.sleep(delay)
            continue

        # Other HTTP errors
        print(f"Error downloading {beatmap_id}.osu: Status code {response.status_code}")
        return False

    return False


def download_beatmaps(input_file, output_folder):
    """Download each beatmap ID in input_file (one ID per line) that is not in output_folder yet."""
    os.makedirs(output_folder, exist_ok=True)

    with open(input_file, "r", encoding="utf-8") as infile:
        beatmap_ids = [line.strip() for line in infile if line.strip()]

    with requests.Session() as session:
        session.headers.update(HEADERS)
        total = len(beatmap_ids)
        for index, beatmap_id in enumerate(beatmap_ids, start=1):
            file_path = os.path.join(output_folder, f"{beatmap_id}.osu")

            if os.path.exists(file_path):
                print(f"[{index}/{total}] {beatmap_id}.osu already exists, skipping download")
                continue

            print(f"[{index}/{total}] Downloading {beatmap_id}.osu...")
            if download_file(session, beatmap_id, file_path):
                print(f"Downloaded {beatmap_id}.osu")

            # Wait before the next request.
            if index < total:
                time.sleep(REQUEST_DELAY * random.uniform(0.8, 1.2))


def output_folder(txt_file):
    """
    Return outputs/<list folder>/<LABEL>/. For example, tournament/NM1.txt ->
    outputs/tournament/NM1/, and expanded_collection/NM1.txt ->
    outputs/expanded_collection/NM1/. Thus lists from different folders never
    share an output folder.
    """
    path = Path(txt_file).resolve()
    return OUTPUTS / path.parent.name / path.stem


if __name__ == "__main__":
    # No argument: all the .txt files in the current folder. A .txt file: that
    # list. A folder (for example expanded_collection): all the .txt files in it.
    if len(sys.argv) > 2:
        print("Usage: python downloader_backoff.py [input.txt | folder]")
        sys.exit(1)
    target = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(".")
    txt_files = sorted(target.glob("*.txt")) if target.is_dir() else [target]
    for txt_file in txt_files:
        download_beatmaps(txt_file, output_folder(txt_file))
