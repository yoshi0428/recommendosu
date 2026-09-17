import os
import time
import requests

from tqdm import tqdm
from dotenv import load_dotenv


# ============================================================
# Configuration
# ============================================================

BEATMAP_ID_FILE = "aim.txt"
OUTPUT_DIR = "./osz_files"

API_BASE = "https://osu.ppy.sh/api/v2"

# Retry configuration
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0

# HTTP status codes worth retrying
RETRY_STATUS_CODES = {
    429,  # Too Many Requests
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
}

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# Request with exponential backoff
# ============================================================

def request_with_backoff(
    session,
    method,
    url,
    **kwargs
):
    """
    Make an HTTP request with exponential backoff.

    Delays:
        1s, 2s, 4s, 8s, 16s

    If the server provides a Retry-After header, use that
    instead for 429 responses.
    """

    for attempt in range(MAX_RETRIES + 1):

        try:
            response = session.request(
                method,
                url,
                **kwargs
            )

        except requests.RequestException as error:

            if attempt >= MAX_RETRIES:
                print(
                    f"Request failed after "
                    f"{MAX_RETRIES} retries: {error}"
                )
                return None

            backoff = INITIAL_BACKOFF * (2 ** attempt)

            print(
                f"Request error: {error}. "
                f"Retrying in {backoff:.1f}s..."
            )

            time.sleep(backoff)
            continue

        # ----------------------------------------------------
        # Successful request
        # ----------------------------------------------------

        if response.status_code < 400:
            return response

        # ----------------------------------------------------
        # Retryable HTTP error
        # ----------------------------------------------------

        if response.status_code in RETRY_STATUS_CODES:

            if attempt >= MAX_RETRIES:
                print(
                    f"Request failed after "
                    f"{MAX_RETRIES} retries: "
                    f"HTTP {response.status_code}"
                )
                return response

            # Respect Retry-After if provided
            retry_after = response.headers.get(
                "Retry-After"
            )

            if retry_after is not None:

                try:
                    backoff = float(retry_after)

                except ValueError:
                    backoff = INITIAL_BACKOFF * (
                        2 ** attempt
                    )

            else:
                backoff = INITIAL_BACKOFF * (
                    2 ** attempt
                )

            print(
                f"HTTP {response.status_code}. "
                f"Retrying in {backoff:.1f}s "
                f"(attempt {attempt + 1}/{MAX_RETRIES})..."
            )

            time.sleep(backoff)
            continue

        # ----------------------------------------------------
        # Non-retryable error
        # ----------------------------------------------------

        return response

    return None


# ============================================================
# Read beatmap IDs
# ============================================================

def read_beatmap_ids(filename):
    beatmap_ids = []

    with open(filename, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line:
                continue

            try:
                beatmap_ids.append(int(line))

            except ValueError:
                print(
                    f"Skipping invalid ID: {line}"
                )

    return beatmap_ids


# ============================================================
# Look up beatmap
# ============================================================

def get_beatmap(beatmap_id, session):

    url = f"{API_BASE}/beatmaps/{beatmap_id}"

    response = request_with_backoff(
        session,
        "GET",
        url
    )

    if response is None:
        return None

    if response.status_code != 200:
        print(
            f"Failed to look up beatmap "
            f"{beatmap_id}: {response.status_code}"
        )
        return None

    return response.json()


# ============================================================
# Download beatmapset
# ============================================================

def download_beatmapset(
    beatmapset_id,
    session
):

    url = (
        f"{API_BASE}/beatmapsets/"
        f"{beatmapset_id}/download"
    )

    output_path = os.path.join(
        OUTPUT_DIR,
        f"{beatmapset_id}.osz"
    )

    # Don't download it again if already present.
    if os.path.exists(output_path):
        return True

    response = request_with_backoff(
        session,
        "GET",
        url,
        stream=True
    )

    if response is None:
        return False

    if response.status_code != 200:
        print(
            f"Failed to download beatmapset "
            f"{beatmapset_id}: {response.status_code}"
        )
        return False

    # --------------------------------------------------------
    # Write only after successful HTTP response
    # --------------------------------------------------------

    try:

        with open(output_path, "wb") as file:

            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):

                if chunk:
                    file.write(chunk)

    except OSError as error:

        print(
            f"Failed to save beatmapset "
            f"{beatmapset_id}: {error}"
        )

        # Remove potentially incomplete file
        if os.path.exists(output_path):
            os.remove(output_path)

        return False

    return True


# ============================================================
# Main
# ============================================================

def main():

    # Inject variables from .env into os.environ
    load_dotenv()

    beatmap_ids = read_beatmap_ids(
        BEATMAP_ID_FILE
    )

    print(
        f"Found {len(beatmap_ids)} beatmap IDs."
    )

    # --------------------------------------------------------
    # Authenticate your session here.
    # --------------------------------------------------------

    CLIENT_ID = os.getenv("OSU_CLIENT_ID")
    CLIENT_SECRET = os.getenv("OSU_CLIENT_SECRET")

    session = requests.Session()

    response = session.post(
        "https://osu.ppy.sh/oauth/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "client_credentials",
            "scope": "public",
        },
    )

    response.raise_for_status()

    access_token = response.json()["access_token"]

    session.headers.update({
        "Authorization": f"Bearer {access_token}"
    })

    # --------------------------------------------------------
    # Resolve beatmap IDs -> beatmapset IDs
    # --------------------------------------------------------

    beatmapset_ids = set()

    for beatmap_id in tqdm(
        beatmap_ids,
        desc="Looking up beatmaps"
    ):

        beatmap = get_beatmap(
            beatmap_id,
            session
        )

        if beatmap is None:
            continue

        beatmapset_id = beatmap.get(
            "beatmapset_id"
        )

        if beatmapset_id is not None:
            beatmapset_ids.add(
                beatmapset_id
            )

        # Avoid hammering the API.
        time.sleep(0.3)

    print(
        f"\nFound {len(beatmapset_ids)} "
        f"unique beatmapsets."
    )

    # --------------------------------------------------------
    # Download
    # --------------------------------------------------------

    for beatmapset_id in tqdm(
        sorted(beatmapset_ids),
        desc="Downloading .osz files"
    ):

        download_beatmapset(
            beatmapset_id,
            session
        )

        time.sleep(0.1)

    print("\nFinished.")


if __name__ == "__main__":
    main()
