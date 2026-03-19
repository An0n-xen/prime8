import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent
TOKEN_DIR = BASE_DIR / os.getenv("GOOGLE_TOKEN_DIR", "data/tokens")
CREDENTIALS_FILE = BASE_DIR / os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# Discord
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")  # None = global slash commands (slow to register)

# Google OAuth scopes
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

# Bot settings
NOTIFICATION_CHANNEL_ID = int(os.getenv("NOTIFICATION_CHANNEL_ID", 0))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", 60))
TIMEZONE = os.getenv("TIMEZONE", "UTC")

# Ensure token directory exists
TOKEN_DIR.mkdir(parents=True, exist_ok=True)
