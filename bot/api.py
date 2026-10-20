import logging
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

# A recommendation takes ~0.5s on the server plus the osu! score fetch, which
# can wait on the shared osu! API rate limit when the site is busy.
REQUEST_TIMEOUT = 60.0


class BackendError(Exception):
    """A request the bot can't complete. The message is shown to the user."""


class BackendClient:
    """The recommendosu.com /api/v1/bot endpoints (see main.py)."""

    def __init__(self, base_url, api_key, transport=None):
        self.client = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/api/v1/bot",
            headers={"X-Bot-Key": api_key},
            timeout=REQUEST_TIMEOUT,
            transport=transport,
        )

    async def aclose(self):
        await self.client.aclose()

    async def get_player(self, username):
        """{"player_id": int, "username": str}"""
        return await self._request("GET", f"/players/{quote(username, safe='')}")

    async def recommend(self, settings, discord_user_id):
        """
        A RecommendationResponse with the first page of recommendations. The
        backend keeps the full result for this Discord user; read the rest
        with recommendation_page.
        """
        return await self._request(
            "POST",
            "/recommend",
            json=settings,
            headers={"X-Discord-User-Id": str(discord_user_id)},
        )

    async def recommendation_page(self, recommendation_id, discord_user_id, offset, limit):
        """A RecommendationPageResponse with rows offset to offset + limit."""
        return await self._request(
            "GET",
            f"/recommend/{recommendation_id}/page",
            params={"offset": offset, "limit": limit},
            headers={"X-Discord-User-Id": str(discord_user_id)},
        )

    async def classify(self, beatmap_id):
        """A BotClassifyResponse with the NM1-NM5 probabilities."""
        return await self._request("GET", f"/classify/{beatmap_id}")

    async def _request(self, method, path, **kwargs):
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("Backend request %s %s failed: %r", method, path, exc)
            raise BackendError("The recommender is unreachable right now. Try again in a bit.") from exc

        if response.is_success:
            return response.json()

        # 400 and 404 carry a message meant for the user, e.g. an unknown
        # player. Anything else is the bot's or the server's problem.
        if response.status_code in (400, 404):
            raise BackendError(_detail(response))

        logger.error("Backend request %s %s returned %s: %s", method, path, response.status_code, response.text)
        raise BackendError("Something went wrong on the server. Try again in a bit.")


def _detail(response):
    try:
        detail = response.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return response.text

    # FastAPI validation errors are a list of {"loc": ..., "msg": ...}.
    if isinstance(detail, list):
        return "; ".join(str(error.get("msg", error)) for error in detail)

    return str(detail)
