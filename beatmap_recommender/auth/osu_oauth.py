import time
from pathlib import Path
import os
import secrets
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

from beatmap_recommender.auth.token_store import get_tokens, update_tokens

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


print("CLIENT ID:", repr(OSU_CLIENT_ID))
print("CLIENT SECRET SET:", bool(OSU_CLIENT_SECRET))
print("CLIENT SECRET LENGTH:", len(OSU_CLIENT_SECRET or ""))
print("REDIRECT URI:", repr(OSU_REDIRECT_URI))

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


async def exchange_code_for_token(code: str) -> dict:
    payload = {
        "client_id": OSU_CLIENT_ID,
        "client_secret": OSU_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": OSU_REDIRECT_URI,
    }

    print("TOKEN REQUEST:")
    print("  client_id:", repr(OSU_CLIENT_ID))
    print("  client_secret length:", len(OSU_CLIENT_SECRET or ""))
    print("  code length:", len(code))
    print("  grant_type:", repr(payload["grant_type"]))
    print("  redirect_uri:", repr(OSU_REDIRECT_URI))

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            OSU_TOKEN_URL,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        print("TOKEN RESPONSE STATUS:", response.status_code)
        print("TOKEN RESPONSE:", response.text)
        response.raise_for_status()
        return response.json()

async def refresh_access_token(refresh_token: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            OSU_TOKEN_URL,
            data={
                "client_id": OSU_CLIENT_ID,
                "client_secret": OSU_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        response.raise_for_status()
        return response.json()

async def get_access_token(session_id: str) -> str:
    tokens = get_tokens(session_id)
    if tokens is None:
        raise ValueError("No OAuth tokens found for this session.")

    # Give ourselves a small safety margin.
    if tokens["expires_at"] > time.time() + 60:
        return tokens["access_token"]

    token_data = await refresh_access_token(tokens["refresh_token"])

    new_access_token = token_data["access_token"]
    new_refresh_token = token_data.get(
        "refresh_token",
        tokens["refresh_token"],
    )

    update_tokens(
        session_id=session_id,
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=token_data["expires_in"],
    )

    return new_access_token