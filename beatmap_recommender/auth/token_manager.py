import time

from beatmap_recommender.auth.osu_oauth import refresh_access_token
from beatmap_recommender.auth.token_store import (
    get_tokens,
    update_tokens,
)

ACCESS_TOKEN_EXPIRY_BUFFER = 60

async def get_access_token(player_id: int) -> str:
    tokens = get_tokens(player_id)

    if tokens is None:
        raise ValueError("No OAuth tokens found for this player.")

    # Access token is still valid.
    if tokens["expires_at"] > time.time() + ACCESS_TOKEN_EXPIRY_BUFFER:
        return tokens["access_token"]

    # Access token has expired or is about to expire.
    token_data = await refresh_access_token(tokens["refresh_token"])

    new_access_token = token_data["access_token"]

    # osu! may rotate the refresh token.
    new_refresh_token = token_data.get("refresh_token", tokens["refresh_token"])

    update_tokens(
        player_id=player_id,
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=token_data["expires_in"],
    )

    return new_access_token