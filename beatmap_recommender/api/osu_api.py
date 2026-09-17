import httpx

OSU_API_BASE = "https://osu.ppy.sh/api/v2"

async def get_authenticated_user(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{OSU_API_BASE}/me/osu",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()