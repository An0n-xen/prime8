"""
HashiCorp Vault integration — read/write secrets via AppRole auth.
"""

import json

import hvac
from hvac.exceptions import InvalidPath

from utils.logger import get_logger

logger = get_logger(__name__)


class VaultService:
    def __init__(self, addr: str, role_id: str, secret_id: str):
        self._client = hvac.Client(url=addr)
        self._role_id = role_id
        self._secret_id = secret_id
        self._authenticate()

    def _authenticate(self):
        resp = self._client.auth.approle.login(
            role_id=self._role_id,
            secret_id=self._secret_id,
        )
        self._client.token = resp["auth"]["client_token"]
        logger.info("Authenticated with Vault via AppRole")

    def _ensure_authenticated(self):
        if not self._client.is_authenticated():
            logger.info("Vault token expired, re-authenticating")
            self._authenticate()

    def read_secret(self, path: str) -> dict:
        """Read a secret from KV v2 at secret/<path>."""
        self._ensure_authenticated()
        resp = self._client.secrets.kv.v2.read_secret_version(
            path=path, mount_point="secret"
        )
        return resp["data"]["data"]

    def write_secret(self, path: str, data: dict):
        """Write a secret to KV v2 at secret/<path>."""
        self._ensure_authenticated()
        self._client.secrets.kv.v2.create_or_update_secret(
            path=path, secret=data, mount_point="secret"
        )

    def delete_secret(self, path: str):
        """Delete a secret from KV v2 at secret/<path>."""
        self._ensure_authenticated()
        self._client.secrets.kv.v2.delete_metadata_and_all_versions(
            path=path, mount_point="secret"
        )

    # --- Convenience methods for Prime8 ---

    def get_discord_token(self) -> str:
        data = self.read_secret("prime8")
        return data["discord_token"]

    def get_github_analytics_secrets(self) -> dict:
        """Return GitHub analytics secrets (github_token, supabase_url, etc.)."""
        data = self.read_secret("prime8")
        return {
            "github_token": data.get("github_token", ""),
            "supabase_url": data.get("supabase_url", ""),
            "supabase_key": data.get("supabase_key", ""),
            "redis_url": data.get("redis_url", ""),
            "hf_api_token": data.get("hf_api_token", ""),
        }

    def get_deepinfra_api_key(self) -> str:
        """Return the DeepInfra API key."""
        data = self.read_secret("prime8")
        return data.get("deepinfra_api_key", "")

    def get_google_credentials(self) -> dict:
        """Return the Google OAuth client credentials as a dict."""
        data = self.read_secret("prime8/google")
        creds = data["credentials"]
        if isinstance(creds, str):
            return json.loads(creds)
        return creds

    def get_user_token(self, user_id: int) -> dict | None:
        """Read a user's OAuth token from Vault. Returns None if not found."""
        try:
            data = self.read_secret(f"prime8/tokens/{user_id}")
            token = data["oauth_token"]
            if isinstance(token, str):
                return json.loads(token)
            return token
        except InvalidPath:
            return None

    def save_user_token(self, user_id: int, token_data: dict):
        """Save a user's OAuth token to Vault."""
        if isinstance(token_data, str):
            token_data = json.loads(token_data)
        self.write_secret(
            f"prime8/tokens/{user_id}",
            {"oauth_token": json.dumps(token_data)},
        )
        logger.info("Saved token for user %s to Vault", user_id)

    def delete_user_token(self, user_id: int):
        """Remove a user's OAuth token from Vault."""
        try:
            self.delete_secret(f"prime8/tokens/{user_id}")
            logger.info("Deleted token for user %s from Vault", user_id)
        except InvalidPath:
            pass

    def get_ytdlp_cookies(self) -> str:
        """Return the yt-dlp cookies content (Netscape format) from Vault."""
        data = self.read_secret("prime8")
        return data.get("ytdlp_cookies", "")
