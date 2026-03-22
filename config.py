from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # "dev" = local .env + file-based tokens, "prod" = HashiCorp Vault
    MODE: Literal["dev", "prod"] = "dev"

    # Vault connection (required in prod mode only)
    VAULT_ADDR: str = ""
    VAULT_ROLE_ID: str = ""
    VAULT_SECRET_ID: str = ""

    # Dev mode: loaded directly from .env
    DISCORD_TOKEN: str | None = None
    GOOGLE_CREDENTIALS_FILE: str = "data/credentials.json"
    GOOGLE_TOKEN_DIR: str = "data/tokens"

    TIMEZONE: str = "UTC"
    POLL_INTERVAL_SECONDS: int = 60
    MAX_CONCURRENT_API_CALLS: int = 4
    SERVICE_CACHE_TTL_SECONDS: int = 300
    OAUTH_CALLBACK_PORT: int = 8090
    METRICS_PORT: int = 9090
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

    @property
    def TOKEN_PATH(self) -> Path:
        return self.BASE_DIR / self.GOOGLE_TOKEN_DIR

    @property
    def CREDENTIALS_PATH(self) -> Path:
        return self.BASE_DIR / self.GOOGLE_CREDENTIALS_FILE

    @model_validator(mode="after")
    def ensure_dirs(self):
        if self.MODE == "prod":
            if (
                not self.VAULT_ADDR
                or not self.VAULT_ROLE_ID
                or not self.VAULT_SECRET_ID
            ):
                raise ValueError(
                    "VAULT_ADDR, VAULT_ROLE_ID, and VAULT_SECRET_ID are required in prod mode; "
                    "set them in the environment or .env file"
                )
        else:
            if not self.DISCORD_TOKEN:
                raise ValueError(
                    "DISCORD_TOKEN is required in dev mode; set it in .env"
                )
            self.TOKEN_PATH.mkdir(parents=True, exist_ok=True)
        self.STATE_PATH.mkdir(parents=True, exist_ok=True)
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
