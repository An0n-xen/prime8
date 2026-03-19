from pathlib import Path
from typing import Final, Literal, Optional
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DISCORD_TOKEN: Optional[str] = None
    TIMEZONE: str = "UTC"
    POLL_INTERVAL_SECONDS: int = 60
    GOOGLE_TOKEN_DIR: str = "data/tokens"
    GOOGLE_CREDENTIALS_FILE: str = "credentials.json"

    GOOGLE_SCOPES: list[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
    ]

    BASE_DIR: Path = Path(__file__).parent

    @property
    def TOKEN_DIR(self) -> Path:
        return self.BASE_DIR / self.GOOGLE_TOKEN_DIR

    @property
    def CREDENTIALS_FILE(self) -> Path:
        return self.BASE_DIR / self.GOOGLE_CREDENTIALS_FILE

    @model_validator(mode="after")
    def ensure_dirs(self):
        if not self.DISCORD_TOKEN:
            raise ValueError(
                "DISCORD_TOKEN is required; set it in the environment or .env file"
            )
        self.TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
