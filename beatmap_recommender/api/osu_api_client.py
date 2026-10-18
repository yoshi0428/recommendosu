import logging
import random
import threading
import time

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://osu.ppy.sh/api/v2"

# osu! asks for at most 60 requests per minute per application, with "some
# degree of bursting" allowed. Every client in the process shares one budget,
# since all of them use this application's credentials or tokens issued to it.
REQUESTS_PER_MINUTE = 60
# Requests that can go out back to back, e.g. a score refresh's 4 pages.
REQUEST_BURST = 4

MAX_RETRIES = 5
BACKOFF_BASE = 2


class OsuAPINotFoundError(requests.HTTPError):
    """The osu! API returned 404 Not Found."""


class RateLimiter:
    """
    Token bucket shared across threads: up to `burst` requests at once, then
    one every `interval` seconds.

    Waiting callers reserve their slot under the lock and sleep outside it,
    so they're served in order without holding the lock while they wait.
    """

    def __init__(self, burst, interval):
        self.burst = burst
        self.interval = interval
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            now = time.monotonic()

            if self.interval > 0:
                self._tokens = min(self.burst, self._tokens + (now - self._updated) / self.interval)
            else:
                self._tokens = float(self.burst)

            self._updated = now
            # Below zero means the slot is reserved in the future.
            self._tokens -= 1
            wait_time = -self._tokens * self.interval if self._tokens < 0 else 0.0

        if wait_time > 0:
            time.sleep(wait_time)


# Sized so no 60 second window holds more than REQUESTS_PER_MINUTE requests:
# the burst plus one request per interval for the rest of the minute.
rate_limiter = RateLimiter(
    burst=REQUEST_BURST,
    interval=60.0 / (REQUESTS_PER_MINUTE - REQUEST_BURST),
)


class OsuAPIClient:
    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.access_token = access_token

    def _on_unauthorized(self):
        """
        Called on a 401. Subclasses that can refresh their own token do so
        here, and the request is retried.
        """
        raise RuntimeError("osu! access token is invalid or expired.")

    def get(
        self,
        endpoint: str,
        params: dict | None = None,
    ):
        """
        Make an authenticated GET request.

        Includes:

        - rate limiting shared by every client in the process
        - exponential backoff
        - Retry-After support
        - retry handling for temporary server failures

        OAuth token acquisition and refresh are handled outside
        this client by the token manager.
        """
        url = f"{API_BASE}{endpoint}"

        for attempt in range(MAX_RETRIES):
            rate_limiter.acquire()

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

            except requests.RequestException as exc:
                if attempt == MAX_RETRIES - 1:
                    raise

                delay = BACKOFF_BASE**attempt + random.uniform(0, 1)
                logger.warning("Request error: %s. Retrying in %.2fs...", exc, delay)
                time.sleep(delay)
                continue

            # Unauthorized
            if response.status_code == 401:
                self._on_unauthorized()
                continue

            # Rate limited
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                if retry_after is not None:
                    delay = float(retry_after)
                else:
                    delay = BACKOFF_BASE**attempt + random.uniform(0, 1)

                logger.warning("Rate limited. Waiting %.2fs...", delay)
                time.sleep(delay)
                continue

            # Temporary server failures
            if 500 <= response.status_code < 600:
                if attempt == MAX_RETRIES - 1:
                    response.raise_for_status()

                delay = BACKOFF_BASE**attempt + random.uniform(0, 1)
                logger.warning(
                    "Server error %d. Retrying in %.2fs...", response.status_code, delay
                )
                time.sleep(delay)
                continue

            # Not found, e.g. a restricted (banned) or nonexistent user
            if response.status_code == 404:
                raise OsuAPINotFoundError(
                    f"osu! API returned 404 Not Found: {url}",
                    response=response,
                )

            # Successful / permanent response
            response.raise_for_status()
            return response.json()

        raise RuntimeError(f"Failed request after {MAX_RETRIES} attempts: {url}")
