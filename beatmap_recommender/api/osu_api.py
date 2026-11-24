import httpx

from beatmap_recommender.api.osu_api_client import API_BASE


async def get_authenticated_user(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{API_BASE}/me/osu",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()
