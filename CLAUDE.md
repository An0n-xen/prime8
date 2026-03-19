# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Prime8 is a Discord bot that integrates with Gmail and Google Calendar via Google APIs. It provides slash commands (`/emails`, `/meetings`, `/schedule`) and background notification polling for new calendar events.

**Stack:** Python 3.12+, discord.py 2.3+, Google API Python Client, uv package manager.

## Commands

```bash
# Install dependencies
uv sync

# Run the bot
python bot.py

# Authenticate with Google (opens browser OAuth flow, must be done before first run)
python -m services.google_auth
```

There are no tests or linting configured in this project.

## Architecture

**Three-layer design:** Discord commands (cogs) → service layer → Google APIs.

- **bot.py** — Entry point. Creates the Discord bot, loads cogs, runs the event loop.
- **config.py** — Centralized env var loading and constants (scopes, paths, intervals).
- **cogs/** — Discord.py Cog classes, each with `async def setup(bot)` for loading:
  - `gmail.py` — `/emails` command (list/search inbox)
  - `calendar.py` — `/meetings` and `/schedule` commands
  - `notifications.py` — Background poller (`discord.ext.tasks`) that checks for new calendar events every `POLL_INTERVAL_SECONDS` and sends notifications to a channel or DM
- **services/** — Async wrappers around synchronous Google API clients using `asyncio.to_thread()`:
  - `google_auth.py` — OAuth2 credential management (load/refresh/save tokens to `data/tokens/token.json`)
  - `gmail_service.py` — Gmail v1 API (list messages, get message)
  - `calendar_service.py` — Calendar v3 API (list events, create event, get new events since timestamp)
- **utils/** — Shared helpers:
  - `embeds.py` — Discord embed builders using Google brand colors (red/blue/green/yellow)
  - `pagination.py` — `PaginatedView` (discord.ui.View) with Previous/Next buttons, 120s timeout
  - `time_helpers.py` — Timezone conversion via `zoneinfo`, human-readable deltas
  - `logger.py` — Colored logging via `colorlog`

## Key Patterns

- All Google API calls are wrapped in `asyncio.to_thread()` to avoid blocking the Discord event loop.
- OAuth tokens are stored as plain JSON in `data/tokens/token.json` (single-user, no DB).
- Cogs defer interactions (`interaction.response.defer()`) before making API calls to avoid Discord's 3-second timeout.
- The notification poller tracks `seen_event_ids` in memory to prevent duplicate notifications, with fallback routing: channel → owner DM.
- Embeds with >5 items use `PaginatedView`; ≤5 use a summary embed.

## Environment Variables

See `.env.example` for the full list. Key vars: `DISCORD_TOKEN`, `GOOGLE_CREDENTIALS_FILE`, `NOTIFICATION_CHANNEL_ID`, `POLL_INTERVAL_SECONDS`, `TIMEZONE`.
