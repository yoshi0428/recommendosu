import os
import time
import random
import requests
from dotenv import load_dotenv

load_dotenv()

OSU_CLIENT_ID = os.getenv("OSU_CLIENT_ID")
OSU_CLIENT_SECRET = os.getenv("OSU_CLIENT_SECRET")

if not OSU_CLIENT_ID or not OSU_CLIENT_SECRET:
    raise RuntimeError("Missing OSU_CLIENT_ID or OSU_CLIENT_SECRET in .env")

API_BASE = "https://osu.ppy.sh/api/v2"
TOKEN_URL = "https://osu.ppy.sh/oauth/token"

MIN_REQUEST_INTERVAL = 1.1
MAX_RETRIES = 5
BACKOFF_BASE = 2

class OsuAPIClient:
    def __init__(self):
        self.session = requests.Session()
        self.access_token = None
        self.token_expires_at = 0
        self.last_request_time = 0

    def authenticate(self):
        """
        Get a client credentials OAuth token.
        The token is cached in memory and refreshed automatically.
        """
        response = self.session.post(
            TOKEN_URL,
            data={
                "client_id": int(OSU_CLIENT_ID),
                "client_secret": OSU_CLIENT_SECRET,
                "grant_type": "client_credentials",
                "scope": "public",
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        self.access_token = data["access_token"]

        # Refresh slightly before expiration.
        expires_in = data.get("expires_in", 3600)
        self.token_expires_at = time.time() + expires_in - 60

        print("Successfully authenticated with osu! API.")

    def ensure_authenticated(self):
        """
        Refresh the token if needed.
        """
        if self.access_token is None or time.time() >= self.token_expires_at:
            self.authenticate()

    def _rate_limit_wait(self):
        """
        Conservative client-side pacing.

        Ensures requests are spaced apart by at least
        MIN_REQUEST_INTERVAL seconds.
        """
        elapsed = time.time() - self.last_request_time
        wait_time = MIN_REQUEST_INTERVAL - elapsed
        if wait_time > 0:
            time.sleep(wait_time)

    def get(self, endpoint: str, params: dict = None):
        """
        GET request with:

        - token refresh
        - client-side rate limiting
        - exponential backoff
        - Retry-After support
        - 401 re-authentication
        """
        self.ensure_authenticated()
        url = f"{API_BASE}{endpoint}"

        for attempt in range(MAX_RETRIES):
            self._rate_limit_wait()
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            try:
                # print("REQUEST PARAMS:", params)
                response = self.session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=30,
                )
                # print("REQUEST URL:", response.request.url)
                self.last_request_time = time.time()

            except requests.RequestException as e:
                if attempt == MAX_RETRIES - 1:
                    raise

                delay = BACKOFF_BASE ** attempt + random.uniform(0, 1)
                print(f"Request error: {e}. Retrying in {delay:.2f}s...")
                time.sleep(delay)
                continue

            # Token expired or invalid.
            if response.status_code == 401:
                print("Received 401. Refreshing access token...")
                self.authenticate()
                continue

            # Rate limited.
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")

                if retry_after is not None:
                    delay = float(retry_after)
                else:
                    delay = BACKOFF_BASE ** attempt + random.uniform(0, 1)

                print(f"Rate limited. Waiting {delay:.2f}s...")
                time.sleep(delay)
                continue

            # Retry temporary server failures.
            if 500 <= response.status_code < 600:
                if attempt == MAX_RETRIES - 1:
                    response.raise_for_status()

                delay = BACKOFF_BASE ** attempt + random.uniform(0, 1)
                print(f"Server error {response.status_code}. Retrying in {delay:.2f}s...")
                time.sleep(delay)
                continue

            response.raise_for_status()
            return response.json()

        raise RuntimeError(f"Failed request after {MAX_RETRIES} attempts: {url}")