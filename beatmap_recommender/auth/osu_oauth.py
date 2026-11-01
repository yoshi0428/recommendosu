import asyncio
import logging
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

from beatmap_recommender.auth.token_store import get_tokens, update_tokens

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

OSU_CLIENT_ID = os.getenv("OSU_CLIENT_ID")
OSU_CLIENT_SECRET = os.getenv("OSU_CLIENT_SECRET")
OSU_REDIRECT_URI = os.getenv("OSU_REDIRECT_URI")


if not OSU_CLIENT_ID:
    raise RuntimeError("Missing OSU_CLIENT_ID")

if not OSU_CLIENT_SECRET:
    raise RuntimeError("Missing OSU_CLIENT_SECRET")

if not OSU_REDIRECT_URI:
    raise RuntimeError("Missing OSU_REDIRECT_URI")


OSU_AUTHORIZE_URL = "https://osu.ppy.sh/oauth/authorize"
OSU_TOKEN_URL = "https://osu.ppy.sh/oauth/token"

OSU_SCOPES = "public identify"


def generate_state() -> str:
    """
    Generate a cryptographically random OAuth state value.
    """
    return secrets.token_urlsafe(32)


def build_authorization_url(state: str) -> str:
    """
    Build the osu! OAuth authorization URL.
    """
    params = {
        "client_id": OSU_CLIENT_ID,
        "redirect_uri": OSU_REDIRECT_URI,
        "response_type": "code",
        "scope": OSU_SCOPES,
        "state": state,
    }

    return f"{OSU_AUTHORIZE_URL}?{urlencode(params)}"


# Tokens are treated as expired this many seconds early, so a token doesn't
# run out between being handed out and being used.
TOKEN_EXPIRY_BUFFER = 60

_application_token: str | None = None
_application_token_expires_at = 0.0
_application_token_lock = asyncio.Lock()


async def _request_token(grant: dict) -> dict:
    """POST to osu!'s token endpoint with this application's credentials."""
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

        # A successful response body holds tokens, so only failed responses
        # are logged.
        if response.is_error:
            logger.error("Token request failed (%d): %s", response.status_code, response.text)

        response.raise_for_status()
        return response.json()


async def exchange_code_for_token(code: str) -> dict:
    """Exchange the code from the OAuth callback for the user's tokens."""
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


async def get_access_token(session_id: str) -> str:
    """The logged-in user's access token, refreshed first if it's about to expire."""
    tokens = get_tokens(session_id)

    if tokens is None:
        raise ValueError("No OAuth tokens found for this session.")

    if tokens["expires_at"] > time.time() + TOKEN_EXPIRY_BUFFER:
        return tokens["access_token"]

    token_data = await refresh_access_token(tokens["refresh_token"])
    new_access_token = token_data["access_token"]

    update_tokens(
        session_id=session_id,
        access_token=new_access_token,
        # osu! may rotate the refresh token.
        refresh_token=token_data.get("refresh_token", tokens["refresh_token"]),
        expires_in=token_data["expires_in"],
    )

    return new_access_token


async def get_application_access_token() -> str:
    """
    A client-credentials token for this application, cached until it's about
    to expire. Used to read any player's scores (e.g. for the Discord bot).
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
