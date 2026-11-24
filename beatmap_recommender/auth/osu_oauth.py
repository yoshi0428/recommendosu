import asyncio
import logging
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

from beatmap_recommender.auth.session import delete_session
from beatmap_recommender.auth.token_store import get_tokens, update_tokens

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

OSU_CLIENT_ID = os.getenv("OSU_CLIENT_ID")
OSU_CLIENT_SECRET = os.getenv("OSU_CLIENT_SECRET")
OSU_REDIRECT_URI = os.getenv("OSU_REDIRECT_URI")

_missing = [name for name in ("OSU_CLIENT_ID", "OSU_CLIENT_SECRET", "OSU_REDIRECT_URI") if not os.getenv(name)]
if _missing:
    raise RuntimeError(f"Missing {', '.join(_missing)}")


OSU_AUTHORIZE_URL = "https://osu.ppy.sh/oauth/authorize"
OSU_TOKEN_URL = "https://osu.ppy.sh/oauth/token"

OSU_SCOPES = "public identify"


def generate_state() -> str:
    """Make a random OAuth state value that nobody can guess."""
    return secrets.token_urlsafe(32)


def build_authorization_url(state: str) -> str:
    """Make the osu! login URL that the user goes to."""
    params = {
        "client_id": OSU_CLIENT_ID,
        "redirect_uri": OSU_REDIRECT_URI,
        "response_type": "code",
        "scope": OSU_SCOPES,
        "state": state,
    }

    return f"{OSU_AUTHORIZE_URL}?{urlencode(params)}"


# A token counts as expired this many seconds early. Thus a token does not
# expire between the time that the code gets it and the time that it uses it.
TOKEN_EXPIRY_BUFFER = 60

_application_token: str | None = None
_application_token_expires_at = 0.0
_application_token_lock = asyncio.Lock()


async def _request_token(grant: dict) -> dict:
    """Send a POST request to the osu! token endpoint with the credentials of this app."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            OSU_TOKEN_URL,
            data={
                "client_id": OSU_CLIENT_ID,
                "client_secret": OSU_CLIENT_SECRET,
                **grant,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        # The body of a successful response holds tokens. Thus the code logs
        # only the failed responses.
        if response.is_error:
            logger.error("Token request failed (%d): %s", response.status_code, response.text)

        response.raise_for_status()
        return response.json()


async def exchange_code_for_token(code: str) -> dict:
    """Exchange the code from the OAuth callback for the tokens of the user."""
    logger.debug(
        "Token request: client_id=%r, code length=%d, redirect_uri=%r",
        OSU_CLIENT_ID,
        len(code),
        OSU_REDIRECT_URI,
    )
    return await _request_token(
        {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": OSU_REDIRECT_URI,
        }
    )


async def refresh_access_token(refresh_token: str) -> dict:
    return await _request_token(
        {
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    )


class OsuAuthorizationRevoked(Exception):
    """osu! rejected the refresh token of this session. The user must log in again."""


async def get_access_token(session_id: str) -> str:
    """
    Return the access token of the logged-in user. If the token expires soon,
    refresh it first.

    If osu! rejects the refresh token, end the session and raise
    OsuAuthorizationRevoked. For example, the user revoked this app in the
    osu! settings. Raise other failures unchanged, so that an osu! outage
    does not log out the users.
    """
    tokens = get_tokens(session_id)

    if tokens is None:
        raise ValueError("No OAuth tokens found for this session.")

    if tokens["expires_at"] > time.time() + TOKEN_EXPIRY_BUFFER:
        return tokens["access_token"]

    try:
        token_data = await refresh_access_token(tokens["refresh_token"])
    except httpx.HTTPStatusError as exc:
        # osu! answers an invalid or revoked refresh token with 400 or 401.
        if exc.response.status_code not in (400, 401):
            raise

        # osu! cancels a refresh token after one use. Another request of this
        # session (for example, a second tab) can refresh first. Then our copy
        # is old, but the stored token is new and good, so use it.
        current = get_tokens(session_id)
        if current is not None and current["refresh_token"] != tokens["refresh_token"]:
            return current["access_token"]

        logger.info("osu! rejected the refresh token of a session. Ending the session.")
        delete_session(session_id)  # ON DELETE CASCADE also deletes its tokens.
        raise OsuAuthorizationRevoked(
            "Your osu! authorization expired or was revoked. Please log in again."
        ) from exc

    new_access_token = token_data["access_token"]

    update_tokens(
        session_id=session_id,
        access_token=new_access_token,
        # osu! can send a new refresh token. If it does not, keep the old one.
        refresh_token=token_data.get("refresh_token", tokens["refresh_token"]),
        expires_in=token_data["expires_in"],
    )

    return new_access_token


async def get_application_access_token() -> str:
    """
    Return a client-credentials token for this app. The token stays in memory
    until it expires soon. The code uses it to read the scores of any player,
    for example for the Discord bot.
    """
    global _application_token, _application_token_expires_at

    async with _application_token_lock:
        if _application_token is None or time.time() >= _application_token_expires_at:
            token_data = await _request_token(
                {
                    "grant_type": "client_credentials",
                    "scope": "public",
                }
            )
            _application_token = token_data["access_token"]
            _application_token_expires_at = time.time() + token_data["expires_in"] - TOKEN_EXPIRY_BUFFER

        return _application_token
