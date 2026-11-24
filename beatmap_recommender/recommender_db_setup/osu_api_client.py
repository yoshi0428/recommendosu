import os
import time

from dotenv import load_dotenv

from beatmap_recommender.api import osu_api_client

load_dotenv()

OSU_CLIENT_ID = os.getenv("OSU_CLIENT_ID")
OSU_CLIENT_SECRET = os.getenv("OSU_CLIENT_SECRET")

if not OSU_CLIENT_ID or not OSU_CLIENT_SECRET:
    raise RuntimeError("Missing OSU_CLIENT_ID or OSU_CLIENT_SECRET in .env")

TOKEN_URL = "https://osu.ppy.sh/oauth/token"


class OsuAPIClient(osu_api_client.OsuAPIClient):
    """
    The osu! API client of the app. It authenticates with the client
    credentials of the app, not with the token of a user. The database scripts
    and the played-maps worker (main.py) use it.
    """

    def __init__(self):
        super().__init__(access_token=None)
        self.token_expires_at = 0

    def authenticate(self):
        """
        Get a client credentials OAuth token. The token stays in memory, and
        ensure_authenticated() refreshes it automatically.
        """
        response = self.session.post(
            TOKEN_URL,
            data={
                "client_id": int(OSU_CLIENT_ID),
                "client_secret": OSU_CLIENT_SECRET,
                "grant_type": "client_credentials",
                "scope": "public",
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        self.access_token = data["access_token"]

        # Refresh the token a little before it expires.
        expires_in = data.get("expires_in", 3600)
        self.token_expires_at = time.time() + expires_in - 60

        print("Successfully authenticated with osu! API.")

    def ensure_authenticated(self):
        """Refresh the token if it is missing or expires soon."""
        if self.access_token is None or time.time() >= self.token_expires_at:
            self.authenticate()

    def _on_unauthorized(self):
        print("Received 401. Refreshing access token...")
        self.authenticate()

    def get(self, endpoint: str, params: dict | None = None):
        self.ensure_authenticated()
        return super().get(endpoint, params)
