"""
Google OAuth2 token management.

Usage:
    # Run standalone to authenticate for the first time:
    python -m services.google_auth

    # In your code:
    from services.google_auth import get_gmail_service, get_calendar_service
    gmail = get_gmail_service()
    calendar = get_calendar_service()
"""

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import settings as config

TOKEN_FILE = config.TOKEN_DIR / "token.json"


def get_credentials() -> Credentials:
    """Load or refresh Google OAuth credentials."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(
            str(TOKEN_FILE), config.GOOGLE_SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not config.CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Missing {config.CREDENTIALS_FILE}. "
                    "Download it from Google Cloud Console → APIs & Services → Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.CREDENTIALS_FILE), config.GOOGLE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save for next time
        TOKEN_FILE.write_text(creds.to_json())

    return creds


def get_gmail_service():
    """Build and return a Gmail API service instance."""
    return build("gmail", "v1", credentials=get_credentials())


def get_calendar_service():
    """Build and return a Calendar API service instance."""
    return build("calendar", "v3", credentials=get_credentials())


# ── Standalone auth flow ─────────────────────────────────────────────
if __name__ == "__main__":
    print("Starting Google OAuth flow...")
    creds = get_credentials()
    print(f"✅ Authenticated successfully. Token saved to {TOKEN_FILE}")
