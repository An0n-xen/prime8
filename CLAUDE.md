# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Prime8 is a Discord bot that integrates with Gmail and Google Calendar via Google APIs. It provides slash commands (`/emails`, `/meetings`, `/schedule`) and background notification polling for new calendar events and emails.

**Stack:** Python 3.12+, discord.py 2.3+, Google API Python Client, pydantic-settings, uv package manager.

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

- **bot.py** — Entry point. Creates the Discord bot, loads cogs from `EXTENSIONS` list, runs the event loop. Syncs slash commands globally in `on_ready`.
- **config.py** — `pydantic_settings.BaseSettings` subclass that auto-loads `.env`. Imported as `from config import settings as config` throughout.
- **cogs/** — Discord.py Cog classes, each with `async def setup(bot)` for loading:
  - `gmail.py` — `/emails` command (list/search inbox)
  - `calendar.py` — `/meetings` and `/schedule` commands
  - `notifications.py` — Two background pollers (`discord.ext.tasks`) for calendar events and emails. Sends notifications via DM to bot owner.
- **services/** — Async wrappers around synchronous Google API clients using `asyncio.to_thread()`:
  - `google_auth.py` — OAuth2 credential management (load/refresh/save tokens). Also runnable standalone for initial auth.
  - `gmail_service.py` — Gmail v1 API (list messages, get message, get new messages since timestamp)
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
- The notification pollers track `seen_event_ids`/`seen_email_ids` in memory (not persisted) to prevent duplicate notifications. Pre-populated on startup via `before_loop` hooks.
- Notifications are sent as DMs to the bot owner (`application_info().owner`).
- Embeds with >5 items use `PaginatedView`; ≤5 use a summary embed.
- Slash commands use `@app_commands.allowed_installs(guilds=True, users=True)` and `@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)` for user-installable app support.

## Environment Variables

See `.env.example` for the full list. Key vars: `DISCORD_TOKEN`, `GOOGLE_CREDENTIALS_FILE`, `POLL_INTERVAL_SECONDS`, `TIMEZONE`.
