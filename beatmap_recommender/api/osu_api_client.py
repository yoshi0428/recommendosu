import time
import random
import requests


API_BASE = "https://osu.ppy.sh/api/v2"

MIN_REQUEST_INTERVAL = 1.1
MAX_RETRIES = 5
BACKOFF_BASE = 2


class OsuAPIClient:
    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.access_token = access_token
        self.last_request_time = 0

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

    def get(
        self,
        endpoint: str,
        params: dict | None = None,
    ):
        """
        Make an authenticated GET request.

        Includes:

        - client-side rate limiting
        - exponential backoff
        - Retry-After support
        - retry handling for temporary server failures

        OAuth token acquisition and refresh are handled outside
        this client by the token manager.
        """
        url = f"{API_BASE}{endpoint}"

        for attempt in range(MAX_RETRIES):
            self._rate_limit_wait()

            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            try:
                response = self.session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=30,
                )

                self.last_request_time = time.time()

            except requests.RequestException as exc:
                if attempt == MAX_RETRIES - 1:
                    raise

                delay = BACKOFF_BASE ** attempt + random.uniform(0, 1)
                print(f"Request error: {exc}. Retrying in {delay:.2f}s...")
                time.sleep(delay)
                continue

            # Unauthorized
            if response.status_code == 401:
                raise RuntimeError("osu! access token is invalid or expired.")

            # Rate limited
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                if retry_after is not None:
                    delay = float(retry_after)
                else:
                    delay = BACKOFF_BASE ** attempt + random.uniform(0, 1)

                print(f"Rate limited. Waiting {delay:.2f}s...")
                time.sleep(delay)
                continue

            # Temporary server failures
            if 500 <= response.status_code < 600:
                if attempt == MAX_RETRIES - 1:
                    response.raise_for_status()

                delay = BACKOFF_BASE ** attempt + random.uniform(0, 1)
                print(f"Server error {response.status_code}. Retrying in {delay:.2f}s...")
                time.sleep(delay)
                continue

            # Successful / permanent response
            response.raise_for_status()
            return response.json()

        raise RuntimeError(f"Failed request after {MAX_RETRIES} attempts: {url}")