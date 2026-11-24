import logging
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

# A recommendation takes about 0.5s on the server, plus the osu! score fetch.
# When the site is busy, the fetch can wait for the shared osu! API rate limit.
REQUEST_TIMEOUT = 60.0


class BackendError(Exception):
    """A request that the bot cannot complete. The user sees the message."""


class BackendClient:
    """The recommendosu.com /api/v1/bot endpoints (see main.py), and the public changelog."""

    def __init__(self, base_url, api_key, transport=None):
        base_url = base_url.rstrip("/")
        self.changelog_url = f"{base_url}/api/v1/changelog"
        self.client = httpx.AsyncClient(
            base_url=f"{base_url}/api/v1/bot",
            headers={"X-Bot-Key": api_key},
            timeout=REQUEST_TIMEOUT,
            transport=transport,
        )

    async def aclose(self):
        await self.client.aclose()

    async def get_player(self, username):
        """Return {"player_id": int, "username": str} for an osu! username."""
        return await self._request("GET", f"/players/{quote(username, safe='')}")

    async def recommend(self, settings, discord_user_id, linked=False):
        """
        Return a RecommendationResponse with the first page of recommendations.
        The backend keeps the full result for this Discord user. Read the other
        pages with recommendation_page.

        linked: True if the player is the account that this Discord user linked.
        Only then does the backend keep the full play history of the player.
        """
        headers = {"X-Discord-User-Id": str(discord_user_id)}
        if linked:
            headers["X-Linked-Player"] = "true"

        return await self._request("POST", "/recommend", json=settings, headers=headers)

    async def recommendation_page(self, recommendation_id, discord_user_id, offset, limit):
        """Return a RecommendationPageResponse with the rows from offset to offset + limit."""
        return await self._request(
            "GET",
            f"/recommend/{recommendation_id}/page",
            params={"offset": offset, "limit": limit},
            headers={"X-Discord-User-Id": str(discord_user_id)},
        )

    async def classify(self, beatmap_id):
        """Return a BotClassifyResponse with the NM1-NM5 probabilities."""
        return await self._request("GET", f"/classify/{beatmap_id}")

    async def changelog(self):
        """Return the changelog entries of the site, newest first: [{"date", "title", "changes"}, ...]"""
        # Use an absolute URL, because the changelog is not under /api/v1/bot.
        return await self._request("GET", self.changelog_url)

    async def _request(self, method, path, **kwargs):
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("Backend request %s %s failed: %r", method, path, exc)
            raise BackendError("The recommender is unreachable right now. Try again in a bit.") from exc

        if response.is_success:
            return response.json()

        # A 400 or 404 has a message for the user, for example an unknown
        # player. Any other status is a problem of the bot or the server.
        if response.status_code in (400, 404):
            raise BackendError(_detail(response))

        logger.error("Backend request %s %s returned %s: %s", method, path, response.status_code, response.text)
        raise BackendError("Something went wrong on the server. Try again in a bit.")


def _detail(response):
    """Return the error message from the "detail" field of a response, or the raw text."""
    try:
        detail = response.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return response.text

    # Only a 400 or a 404 gets here. For these, the backend always sends a
    # string detail. (The bot logs a 422 validation error as a server error.)
    return str(detail)
