import os
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("OSU_CLIENT_ID")
CLIENT_SECRET = os.getenv("OSU_CLIENT_SECRET")

def get_file_content_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def fetch_beatmap_id_from_api(file_path, file_hash):

    if not file_hash:
        file_hash = get_file_content_md5(file_path)

    # 1. Authenticate with osu! API v2 using client credentials
    auth_response = requests.post("https://osu.ppy.sh/oauth/token", data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "public"
    })

    if auth_response.status_code != 200:
        raise Exception(f"Failed to authenticate with osu! API: {auth_response.text}")

    token = auth_response.json().get("access_token")

    # 2. Query the API v2 lookup endpoint via the MD5 checksum
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {
        "checksum": file_hash
    }

    response = requests.get("https://osu.ppy.sh/api/v2/beatmaps/lookup", headers=headers, params=params)

    if response.status_code == 200:
        beatmap_data = response.json()
        return beatmap_data.get("id"), beatmap_data.get("ar")
    else:
        print(f"Lookup failed with status {response.status_code}: {response.text}")
        return None


# Test with a single .osu file path
sample_path = "beatmap_recommender/data/2012/SOUND HOLIC - Drive My Life (Scorpiour) [Lunatic].osu"

beatmap_id, beatmap_ar = fetch_beatmap_id_from_api(sample_path, None)
# beatmap_id = fetch_beatmap_id_from_api(sample_path, 'fb099ade581d16f3a69926ccf8f2cf7a')


print(f"Retrieved Beatmap ID: {beatmap_id} and Beatmap AR: {beatmap_ar}")