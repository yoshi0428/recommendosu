import logging
import random
import threading
import time

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://osu.ppy.sh/api/v2"

# osu! permits at most 60 requests per minute for each app, with "some degree
# of bursting". All the clients in the process share one budget, because they
# all use the credentials of this app or tokens that osu! gave to it.
REQUESTS_PER_MINUTE = 60
# The number of requests that can go out one after another without a wait.
# For example, a score refresh sends 4 pages.
REQUEST_BURST = 4

MAX_RETRIES = 5
BACKOFF_BASE = 2


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with random jitter: about 1, 2, 4, 8... seconds."""
    return BACKOFF_BASE**attempt + random.uniform(0, 1)


class OsuAPINotFoundError(requests.HTTPError):
    """The osu! API returned 404 Not Found."""


class RateLimiter:
    """
    A token bucket (a counter of request slots that fills at a fixed rate)
    that all threads share. Up to `burst` requests can go out at once. After
    that, one request can go out every `interval` seconds.

    A caller that must wait reserves its slot under the lock. Then it sleeps
    outside the lock. Thus the callers go in order, and no caller holds the
    lock while it waits.

    Background work (acquire_background()) takes only a slot that the live
    requests do not use.
    """

    def __init__(self, burst, interval, background_idle=2.0):
        self.burst = burst
        self.interval = interval
        # A background request waits until no live request went out for this many seconds.
        self.background_idle = background_idle
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._last_foreground = float("-inf")
        self._lock = threading.Lock()

    def _refill(self, now):
        if self.interval > 0:
            self._tokens = min(self.burst, self._tokens + (now - self._updated) / self.interval)
        else:
            self._tokens = float(self.burst)
        self._updated = now

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            self._refill(now)
            self._last_foreground = now
            # A value below zero means that the slot is reserved for a later time.
            self._tokens -= 1
            wait_time = -self._tokens * self.interval if self._tokens < 0 else 0.0

        if wait_time > 0:
            time.sleep(wait_time)

    def acquire_background(self):
        """
        Wait for a slot for low-priority work. The slot comes only when the
        bucket is full again and no live request went out for background_idle
        seconds. Thus a live score refresh that arrives now still gets almost
        all of its burst.
        """
        while True:
            with self._lock:
                now = time.monotonic()
                self._refill(now)
                if self._tokens >= self.burst and now - self._last_foreground >= self.background_idle:
                    self._tokens -= 1
                    return
            time.sleep(max(self.interval, 0.25))


# These sizes keep each 60-second window at REQUESTS_PER_MINUTE requests or
# fewer: the burst, plus one request per interval for the rest of the minute.
rate_limiter = RateLimiter(
    burst=REQUEST_BURST,
    interval=60.0 / (REQUESTS_PER_MINUTE - REQUEST_BURST),
)


class OsuAPIClient:
    # Background work (played_maps.py) sets this, so that its requests wait for the live requests.
    low_priority = False

    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.access_token = access_token

    def _on_unauthorized(self):
        """
        The client calls this method on a 401 response, then tries the request
        again. A subclass that can refresh its own token does it here.
        """
        raise RuntimeError("osu! access token is invalid or expired.")

    def get(self, endpoint: str, params: dict | None = None):
        """
        Send an authenticated GET request and return the JSON body.

        The request uses the rate limit that all clients share. If the request
        fails because of the network, a rate limit, or a server error, the
        client waits and tries again, up to MAX_RETRIES times. On a rate
        limit, it obeys the Retry-After header.
        """
        url = f"{API_BASE}{endpoint}"

        for attempt in range(MAX_RETRIES):
            if self.low_priority:
                rate_limiter.acquire_background()
            else:
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

                delay = _backoff_delay(attempt)
                logger.warning("Request error: %s. Retrying in %.2fs...", exc, delay)
                time.sleep(delay)
                continue

            if response.status_code == 401:
                self._on_unauthorized()
                continue

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after is not None else _backoff_delay(attempt)
                logger.warning("Rate limited. Waiting %.2fs...", delay)
                time.sleep(delay)
                continue

            # A temporary server failure
            if 500 <= response.status_code < 600:
                if attempt == MAX_RETRIES - 1:
                    response.raise_for_status()

                delay = _backoff_delay(attempt)
                logger.warning("Server error %d. Retrying in %.2fs...", response.status_code, delay)
                time.sleep(delay)
                continue

            # Not found. For example, the user is restricted (banned) or does not exist.
            if response.status_code == 404:
                raise OsuAPINotFoundError(
                    f"osu! API returned 404 Not Found: {url}",
                    response=response,
                )

            # A success, or an error that another try cannot fix
            response.raise_for_status()
            return response.json()

        raise RuntimeError(f"Failed request after {MAX_RETRIES} attempts: {url}")
