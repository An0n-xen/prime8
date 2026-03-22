"""
Local file-based secret service for dev mode.

Mirrors the VaultService interface so the rest of the codebase
works identically regardless of which backend is active.
"""

import json
from pathlib import Path

from config import settings as config
from utils.logger import get_logger

logger = get_logger(__name__)


class LocalSecretService:
    """Read secrets from .env / local files instead of Vault."""

    def get_discord_token(self) -> str | None:
        return config.DISCORD_TOKEN

    def get_google_credentials(self) -> dict:
        """Load Google OAuth client credentials from a local JSON file."""
        creds_path = config.CREDENTIALS_PATH
        if not creds_path.exists():
            raise FileNotFoundError(
                f"Google credentials file not found at {creds_path}. "
                "Download it from the Google Cloud Console."
            )
        with open(creds_path) as f:
            return json.load(f)

    def get_user_token(self, user_id: int) -> dict | None:
        token_file = config.TOKEN_PATH / f"{user_id}.json"
        if not token_file.exists():
            return None
        with open(token_file) as f:
            return json.load(f)

    def save_user_token(self, user_id: int, token_data: dict):
        token_file = config.TOKEN_PATH / f"{user_id}.json"
        with open(token_file, "w") as f:
            json.dump(token_data, f)
        logger.info("Saved token for user %s to %s", user_id, token_file)

    def delete_user_token(self, user_id: int):
        token_file = config.TOKEN_PATH / f"{user_id}.json"
        if token_file.exists():
            token_file.unlink()
            logger.info("Deleted token for user %s from %s", user_id, token_file)
