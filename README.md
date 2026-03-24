# Prime8

A Discord bot that integrates with Gmail, Google Calendar, and GitHub analytics. Built with discord.py, deployable as a Docker container with CI/CD, Prometheus monitoring, and HashiCorp Vault for secrets management.

**Stack:** Python 3.12+, discord.py 2.3+, Google API Client, Supabase, Redis, ChromaDB, Prometheus, Docker, uv.

## Features

### Google Workspace

- `/connect` — Link your Google account via OAuth2
- `/emails` — List recent Gmail inbox messages
- `/meetings` — List upcoming Google Calendar events
- `/schedule` — Create a new calendar event with attendees
- **Real-time notifications** — Get DM'd when new calendar events or emails arrive

### GitHub Analytics

- `/trending` — Browse trending GitHub repos by language and time window
- `/stats` — View detailed stats for any GitHub repo
- `/growth` — Star growth analytics with historical snapshots
- `/health` — Repository health report (activity, community, maintenance)
- `/compare` — Compare multiple repos side-by-side
- `/watch` — Add repos to your personal watchlist for tracking
- `/digest` — Configure a scheduled daily digest of your watched repos
- `/search` — AI-powered semantic search across indexed repos

### Background Jobs

- **Star snapshots** — Periodic star count collection for watched repos
- **Breakout detection** — Alerts when a repo's growth spikes above a configurable threshold
- **Health refresh** — Periodic recalculation of repo health scores
- **Daily digest** — Scheduled summary of watchlist activity
- **Repo indexing** — Embedding generation for semantic search (sentence-transformers / e5-small-v2)

### Utility

- `/ping` — Check if the bot is alive
- `/dm` — Start a private DM conversation with the bot

## Architecture

```
prime8/
├── bot.py                       # Entry point — loads cogs, sets up the bot
├── config.py                    # pydantic-settings config (env vars, validation)
├── Dockerfile                   # Multi-stage build (uv builder + slim runtime)
├── docker-compose.yml           # Container orchestration with monitoring network
├── pyproject.toml               # Dependencies and tool config (ruff, mypy)
├── .github/workflows/
│   └── deploy.yml               # CI/CD: lint + type check → deploy to VPS via SSH
├── cogs/
│   ├── auth.py                  # /connect — Google OAuth2 flow
│   ├── gmail.py                 # /emails — list & search Gmail
│   ├── calendar.py              # /meetings and /schedule commands
│   ├── notifications.py         # Background pollers for new emails & calendar events
│   ├── github.py                # GitHub analytics slash commands
│   └── github_notifications.py  # Background jobs: snapshots, breakout, digest, indexer
├── services/
│   ├── google_auth.py           # OAuth2 credential management (load/refresh/save)
│   ├── gmail_service.py         # Gmail v1 API wrapper
│   ├── calendar_service.py      # Calendar v3 API wrapper
│   ├── github_service.py        # GitHub REST API client (aiohttp)
│   ├── database_service.py      # Supabase persistence (watchlists, snapshots, digests)
│   ├── cache_service.py         # Redis caching layer
│   ├── analytics_service.py     # Growth calculation, breakout detection, health scoring
│   ├── ai_service.py            # Embedding generation & semantic search (ChromaDB)
│   ├── user_manager.py          # Per-user registration and token mapping
│   ├── vault_service.py         # HashiCorp Vault client (AppRole auth, prod mode)
│   └── local_secret_service.py  # Local .env-based secrets (dev mode)
├── utils/
│   ├── embeds.py                # Discord embed builders for emails/events
│   ├── github_embeds.py         # Discord embed builders for GitHub analytics
│   ├── pagination.py            # Paginated embed views (discord.ui.View)
│   ├── time_helpers.py          # Timezone conversion, human-readable formatting
│   ├── logger.py                # Colored logging via colorlog
│   └── metrics.py               # Prometheus metrics (counters, gauges, histograms)
└── data/
    ├── tokens/                  # Per-user OAuth tokens (gitignored)
    └── state/                   # Persistent state for notification pollers
```

## Setup

### 1. Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application → Bot → copy the token
3. Enable **Message Content** privileged intent
4. Invite with scopes: `bot`, `applications.commands`
5. Required permissions: Send Messages, Embed Links, Use Slash Commands

### 2. Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project and enable:
   - **Gmail API**
   - **Google Calendar API**
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download `credentials.json` → place at `data/credentials.json`
5. Configure OAuth consent screen with scopes: `gmail.readonly`, `calendar.readonly`, `calendar.events`
6. Add yourself as a test user (while in "Testing" mode)

### 3. GitHub Analytics (optional)

1. Create a [GitHub Personal Access Token](https://github.com/settings/tokens) with `public_repo` scope
2. Set up a [Supabase](https://supabase.com/) project for persistence (watchlists, snapshots)
3. Set up a Redis instance for caching
4. Optionally, get a [Hugging Face API token](https://huggingface.co/settings/tokens) for AI features

### 4. Environment Variables

Copy `.env.example` → `.env` and fill in your values. Key variables:

| Variable | Description |
|---|---|
| `MODE` | `dev` (local .env) or `prod` (HashiCorp Vault) |
| `DISCORD_TOKEN` | Discord bot token (dev mode) |
| `GOOGLE_CREDENTIALS_FILE` | Path to OAuth client credentials |
| `GITHUB_TOKEN` | GitHub PAT for analytics |
| `REDIS_URL` | Redis connection URL |
| `SUPABASE_URL` / `SUPABASE_KEY` | Supabase project credentials |
| `VAULT_ADDR` / `VAULT_ROLE_ID` / `VAULT_SECRET_ID` | Vault connection (prod mode) |
| `POLL_INTERVAL_SECONDS` | Notification polling frequency (default: 60) |
| `TIMEZONE` | Display timezone (default: UTC) |
| `METRICS_PORT` | Prometheus metrics port (default: 9091) |

See `.env.example` for the full list including GitHub analytics tuning options.

### 5. Install & Run

```bash
# Install dependencies
uv sync

# Authenticate with Google (first time only — opens browser)
python -m services.google_auth

# Run the bot
python bot.py
```

### 6. Docker Deployment

```bash
docker compose up -d --build
```

The container exposes port `8090` (OAuth callback) and `9091` (Prometheus metrics), and joins the `monitoring` Docker network.

## Secrets Management

Prime8 supports two modes controlled by the `MODE` environment variable:

- **`dev`** — Reads secrets directly from `.env` and stores OAuth tokens as local JSON files
- **`prod`** — Fetches secrets from HashiCorp Vault using AppRole authentication. All sensitive values (Discord token, Google credentials, GitHub token, Supabase keys) are stored in Vault

## CI/CD

On push to `main`, GitHub Actions runs:

1. **Lint** — `ruff check .`
2. **Type check** — `mypy .`
3. **Deploy** — SSH into VPS, pull latest, rebuild and restart the Docker container

## Monitoring

- **Prometheus metrics** served on port `9091` — bot readiness, guild count, command usage, API latency
- **Health check** built into `docker-compose.yml`
- Designed to connect to an external Prometheus + Loki monitoring stack via the `monitoring` Docker network

## Key Design Decisions

- **Cog-based structure** — Each feature is a separate cog for clean separation
- **Service layer** — API logic is decoupled from Discord command logic
- **Async everywhere** — Uses `asyncio.to_thread()` to wrap synchronous Google API clients
- **Dual-mode secrets** — Seamless switch between local dev and Vault-backed prod
- **User-installable app** — Commands work in guilds, DMs, and private channels; notifications are sent via DM
- **Polling for notifications** — Background tasks check for new events/emails (avoids requiring a public HTTPS endpoint)
- **Supabase for persistence** — Watchlists, star snapshots, digest configs, and health scores
- **Redis for caching** — Trending results, API responses with configurable TTL
- **ChromaDB for search** — Local vector store with sentence-transformers embeddings (e5-small-v2)

## Resources

- [discord.py docs](https://discordpy.readthedocs.io/)
- [Gmail API reference](https://developers.google.com/gmail/api/reference/rest)
- [Calendar API reference](https://developers.google.com/calendar/api/v3/reference)
- [GitHub REST API docs](https://docs.github.com/en/rest)
- [Supabase docs](https://supabase.com/docs)
- [HashiCorp Vault docs](https://developer.hashicorp.com/vault/docs)
