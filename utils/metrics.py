"""Prometheus metrics for the Prime8 bot."""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# -- Bot status --
bot_ready = Gauge("prime8_bot_ready", "Whether the bot is connected to Discord")
guild_count = Gauge("prime8_guild_count", "Number of guilds the bot is in")
registered_users = Gauge("prime8_registered_users", "Number of registered users")

# -- Slash commands --
command_invocations = Counter(
    "prime8_command_invocations_total",
    "Total slash command invocations",
    ["command", "status"],
)
command_duration = Histogram(
    "prime8_command_duration_seconds",
    "Slash command execution time",
    ["command"],
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

# -- Google API calls --
google_api_calls = Counter(
    "prime8_google_api_calls_total",
    "Total Google API calls",
    ["service", "method", "status"],
)
google_api_duration = Histogram(
    "prime8_google_api_duration_seconds",
    "Google API call duration",
    ["service", "method"],
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

# -- Notification polling --
poll_cycles = Counter(
    "prime8_poll_cycles_total",
    "Total notification poll cycles",
    ["status"],
)
poll_duration = Histogram(
    "prime8_poll_duration_seconds",
    "Duration of a full poll cycle",
)
new_events_found = Counter(
    "prime8_new_events_found_total",
    "New calendar events detected by poller",
)
new_emails_found = Counter(
    "prime8_new_emails_found_total",
    "New emails detected by poller",
)
notifications_sent = Counter(
    "prime8_notifications_sent_total",
    "Notifications sent to users",
    ["type", "status"],
)


# -- Downloads --
download_invocations = Counter(
    "prime8_download_invocations_total",
    "Total download invocations",
    ["tool", "status"],
)
download_duration = Histogram(
    "prime8_download_duration_seconds",
    "Download execution time",
    ["tool"],
    buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)


def start_metrics_server(port: int):
    """Start the Prometheus metrics HTTP server on the given port."""
    start_http_server(port)
