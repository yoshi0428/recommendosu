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
    The app's osu! API client, authenticated with its own client credentials
    instead of a user's token. For scripts that populate the database.
    """

    def __init__(self):
        super().__init__(access_token=None)
        self.token_expires_at = 0

    def authenticate(self):
        """
        Get a client credentials OAuth token.
        The token is cached in memory and refreshed automatically.
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

        # Refresh slightly before expiration.
        expires_in = data.get("expires_in", 3600)
        self.token_expires_at = time.time() + expires_in - 60

        print("Successfully authenticated with osu! API.")

    def ensure_authenticated(self):
        """
        Refresh the token if needed.
        """
        if self.access_token is None or time.time() >= self.token_expires_at:
            self.authenticate()

    def _on_unauthorized(self):
        print("Received 401. Refreshing access token...")
        self.authenticate()

    def get(self, endpoint: str, params: dict | None = None):
        self.ensure_authenticated()
        return super().get(endpoint, params)
