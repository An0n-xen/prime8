# Discord Google Workspace Bot

A Discord bot that integrates with Gmail and Google Calendar, built with discord.py.

## Features

- `/emails` — List recent Gmail inbox messages
- `/meetings` — List upcoming Google Calendar events
- `/schedule` — Create a new calendar event with attendees
- **Real-time notifications** — Get DM'd when someone schedules a meeting with you

## Architecture

```
discord-google-bot/
├── bot.py                  # Entry point — loads cogs, sets up the bot
├── config.py               # All configuration (env vars, constants)
├── requirements.txt        # Python dependencies
├── .env.example            # Template for environment variables
├── cogs/
│   ├── __init__.py
│   ├── gmail.py            # /emails command — list & search Gmail
│   ├── calendar.py         # /meetings and /schedule commands
│   └── notifications.py    # Background task — polls for new calendar events
├── services/
│   ├── __init__.py
│   ├── google_auth.py      # OAuth2 flow — token management, refresh logic
│   ├── gmail_service.py    # Gmail API wrapper (list, search, get message)
│   └── calendar_service.py # Calendar API wrapper (list, create, watch)
├── utils/
│   ├── __init__.py
│   ├── embeds.py           # Discord embed builders for emails/events
│   ├── pagination.py       # Paginated embed views (discord.ui.View)
│   └── time_helpers.py     # Timezone conversion, human-readable formatting
└── data/
    └── tokens/             # Per-user OAuth tokens (gitignored)
```

## Setup

### 1. Discord Bot

1. Go to https://discord.com/developers/applications
2. Create a new application → Bot → copy the token
3. Enable these **Privileged Gateway Intents**: Message Content (if using prefix commands)
4. Invite with scopes: `bot`, `applications.commands`
5. Required permissions: Send Messages, Embed Links, Use Slash Commands

### 2. Google Cloud Project

1. Go to https://console.cloud.google.com/
2. Create a new project
3. Enable these APIs:
   - **Gmail API**
   - **Google Calendar API**
4. Create OAuth 2.0 credentials:
   - Application type: **Desktop app** (simplest for bot use)
   - Download `credentials.json` → place in project root
5. Configure OAuth consent screen:
   - Add scopes: `gmail.readonly`, `calendar.readonly`, `calendar.events`
   - Add yourself as a test user (while in "Testing" mode)

### 3. Environment Variables

Copy `.env.example` → `.env` and fill in your values.

### 4. Install & Run

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
python bot.py
```

## How Google OAuth Works in This Bot

Since this is a personal/small-server bot, the simplest approach is:

1. Run `python services/google_auth.py` once locally — it opens a browser for Google login
2. Tokens are saved to `data/tokens/` and auto-refresh via refresh tokens
3. The bot uses these tokens for all API calls

For multi-user support, you'd implement an OAuth callback server,
but for personal use the manual flow is much simpler.

## Key Design Decisions

- **Cog-based structure**: Each feature is a separate cog for clean separation
- **Service layer**: Google API logic is decoupled from Discord logic
- **Async everywhere**: Uses `asyncio.to_thread()` to wrap Google's sync client
- **Token storage**: File-based (JSON) for simplicity — swap to DB if scaling
- **Polling for notifications**: Background task every 60s checks for new events
  (Google Push Notifications require a public HTTPS endpoint, which is overkill for most setups)

## API Cheat Sheet

### Gmail API — Key Methods
```python
# List messages
service.users().messages().list(userId='me', maxResults=10, q='is:unread').execute()

# Get a single message
service.users().messages().get(userId='me', id=msg_id, format='metadata').execute()

# Useful query strings for q parameter:
#   'is:unread'
#   'from:someone@example.com'
#   'newer_than:1d'
#   'subject:meeting'
```

### Calendar API — Key Methods
```python
# List upcoming events
service.events().list(
    calendarId='primary',
    timeMin=now_iso,          # RFC3339 timestamp
    maxResults=10,
    singleEvents=True,
    orderBy='startTime'
).execute()

# Create an event
event = {
    'summary': 'Team Sync',
    'start': {'dateTime': '2026-03-20T10:00:00', 'timeZone': 'UTC'},
    'end': {'dateTime': '2026-03-20T11:00:00', 'timeZone': 'UTC'},
    'attendees': [{'email': 'person@example.com'}],
}
service.events().insert(calendarId='primary', body=event, sendUpdates='all').execute()

# Watch for changes (push notifications — requires public HTTPS endpoint)
service.events().watch(calendarId='primary', body={...}).execute()
```

## Dependencies

| Package | Purpose |
|---|---|
| `discord.py` | Bot framework |
| `google-api-python-client` | Gmail & Calendar API |
| `google-auth-oauthlib` | OAuth2 authentication flow |
| `google-auth-httplib2` | HTTP transport for Google auth |
| `python-dotenv` | Load .env file |
| `APScheduler` | Background task scheduling |

## Scopes Reference

| Scope | What it allows |
|---|---|
| `gmail.readonly` | Read email messages and metadata |
| `calendar.readonly` | Read calendar events |
| `calendar.events` | Create, edit, delete calendar events |

## Resources

- [discord.py docs](https://discordpy.readthedocs.io/)
- [Gmail API reference](https://developers.google.com/gmail/api/reference/rest)
- [Calendar API reference](https://developers.google.com/calendar/api/v3/reference)
- [Google Auth Python guide](https://developers.google.com/identity/protocols/oauth2)
