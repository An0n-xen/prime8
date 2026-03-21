from pathlib import Path
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Vault connection (loaded from .env)
    VAULT_ADDR: str = ""
    VAULT_ROLE_ID: str = ""
    VAULT_SECRET_ID: str = ""

    # Set at runtime after Vault loads
    DISCORD_TOKEN: Optional[str] = None

    TIMEZONE: str = "UTC"
    POLL_INTERVAL_SECONDS: int = 60
    MAX_CONCURRENT_API_CALLS: int = 4
    SERVICE_CACHE_TTL_SECONDS: int = 300
    OAUTH_CALLBACK_PORT: int = 8090
    STATE_DIR: str = "data/state"

    GOOGLE_SCOPES: list[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
    ]

    BASE_DIR: Path = Path(__file__).parent

    @property
    def STATE_PATH(self) -> Path:
        return self.BASE_DIR / self.STATE_DIR

    @model_validator(mode="after")
    def ensure_dirs(self):
        if not self.VAULT_ADDR or not self.VAULT_ROLE_ID or not self.VAULT_SECRET_ID:
            raise ValueError(
                "VAULT_ADDR, VAULT_ROLE_ID, and VAULT_SECRET_ID are required; "
                "set them in the environment or .env file"
            )
        self.STATE_PATH.mkdir(parents=True, exist_ok=True)
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
