import sys
import os
import time
import random
import requests
import glob

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

def get_retry_delay(response, retry_number):
    """
    Determine how long to wait before retrying.

    Priority:
    1. Retry-After header
    2. Exponential backoff
    3. Random jitter
    """

    retry_after = response.headers.get("Retry-After")

    if retry_after:
        try:
            delay = float(retry_after)
            return min(delay, MAX_BACKOFF)
        except ValueError:
            pass

    # Exponential backoff
    delay = min(INITIAL_BACKOFF * (2 ** retry_number), MAX_BACKOFF)
    delay *= random.uniform(1.0, 1.25) # add 0-25% jitter

    return min(delay, MAX_BACKOFF)


def download_file(session, beatmap_id, file_path):
    """
    Download one beatmap with rate-limit handling.

    Returns:
        True  -> successfully downloaded
        False -> failed after retries
    """

    url = f"{BASE_URL}/{beatmap_id}"

    for retry_number in range(MAX_RETRIES + 1):
        try:
            response = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as e:
            if retry_number >= MAX_RETRIES:
                print(f"{beatmap_id}: request failed after {MAX_RETRIES} retries: {e}")
                return False

            delay = min(INITIAL_BACKOFF * (2 ** retry_number), MAX_BACKOFF)
            delay *= random.uniform(1.0, 1.25)

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

            delay = min(INITIAL_BACKOFF * (2 ** retry_number), MAX_BACKOFF)
            delay *= random.uniform(1.0, 1.25)

            print(f"{beatmap_id}: HTTP {response.status_code}.")
            print(f"Retrying in {delay:.1f} seconds...")
            time.sleep(delay)
            continue

        # Other HTTP errors
        print(f"Error downloading {beatmap_id}.osu: Status code {response.status_code}")
        return False

    return False

def download_beatmaps(input_file, output_folder):

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
            success = download_file(session, beatmap_id, file_path)

            if success:
                print(f"Downloaded {beatmap_id}.osu")

            # Delay before the next request
            if index < total:
                delay = REQUEST_DELAY * random.uniform(0.8, 1.2)
                time.sleep(delay)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        txt_files = glob.glob("*.txt")
        for txt_file in txt_files:
            output_folder = f"./outputs/{os.path.splitext(txt_file)[0]}"
            download_beatmaps(txt_file, output_folder)
    elif len(sys.argv) == 2:
        input_file = sys.argv[1]
        output_folder = f"./outputs/{os.path.splitext(input_file)[0]}"
        download_beatmaps(input_file, output_folder)
    else:
        print("Usage: python downloader_backoff.py [input.txt]")
        sys.exit(1)