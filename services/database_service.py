"""Supabase database service for GitHub analytics persistence."""

from __future__ import annotations

from datetime import UTC, datetime

from supabase import Client, create_client

from config import settings as config
from utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseService:
    def __init__(self):
        self._client: Client | None = None

    def connect(self):
        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            logger.warning("Supabase credentials not set, database disabled")
            return
        try:
            self._client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
            logger.info("Supabase client connected")
        except Exception as e:
            logger.error(f"Failed to connect to Supabase: {e}")

    @property
    def available(self) -> bool:
        return self._client is not None

    # --- Star Snapshots ---

    def insert_snapshot(self, repo_full_name: str, stars: int, forks: int, open_issues: int = 0, watchers: int = 0):
        if not self.available:
            return
        self._client.table("star_snapshots").insert({
            "repo_full_name": repo_full_name,
            "stars": stars,
            "forks": forks,
            "open_issues": open_issues,
            "watchers": watchers,
            "snapshot_at": datetime.now(UTC).isoformat(),
        }).execute()

    def get_snapshots(self, repo_full_name: str, days: int = 30) -> list[dict]:
        if not self.available:
            return []
        since = datetime.now(UTC).replace(hour=0, minute=0, second=0)
        from datetime import timedelta
        since = since - timedelta(days=days)

        result = (
            self._client.table("star_snapshots")
            .select("*")
            .eq("repo_full_name", repo_full_name)
            .gte("snapshot_at", since.isoformat())
            .order("snapshot_at", desc=False)
            .execute()
        )
        return result.data

    def get_latest_snapshot(self, repo_full_name: str) -> dict | None:
        if not self.available:
            return None
        result = (
            self._client.table("star_snapshots")
            .select("*")
            .eq("repo_full_name", repo_full_name)
            .order("snapshot_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    # --- Watchlist ---

    def add_to_watchlist(
        self,
        discord_user_id: str,
        repo_full_name: str,
        alert_threshold: float = 3.0,
    ):
        if not self.available:
            return
        self._client.table("watchlist").upsert({
            "discord_user_id": discord_user_id,
            "repo_full_name": repo_full_name,
            "alert_threshold": alert_threshold,
            "notify_on_release": True,
            "notify_on_spike": True,
            "added_at": datetime.now(UTC).isoformat(),
        }).execute()

    def remove_from_watchlist(self, discord_user_id: str, repo_full_name: str):
        if not self.available:
            return
        (
            self._client.table("watchlist")
            .delete()
            .eq("discord_user_id", discord_user_id)
            .eq("repo_full_name", repo_full_name)
            .execute()
        )

    def get_watchlist(self, discord_user_id: str) -> list[dict]:
        if not self.available:
            return []
        result = (
            self._client.table("watchlist")
            .select("*")
            .eq("discord_user_id", discord_user_id)
            .order("added_at", desc=False)
            .execute()
        )
        return result.data

    def get_all_watched_repos(self) -> list[dict]:
        if not self.available:
            return []
        result = self._client.table("watchlist").select("repo_full_name, discord_user_id, alert_threshold").execute()
        return result.data

    def set_watchlist_threshold(self, discord_user_id: str, repo_full_name: str, threshold: float):
        if not self.available:
            return
        (
            self._client.table("watchlist")
            .update({"alert_threshold": threshold})
            .eq("discord_user_id", discord_user_id)
            .eq("repo_full_name", repo_full_name)
            .execute()
        )

    # --- Digest Config ---

    def set_digest(self, discord_user_id: str, channel_id: str, schedule: str, languages: list[str] | None = None, min_stars: int = 50):
        if not self.available:
            return
        self._client.table("digest_config").upsert({
            "discord_user_id": discord_user_id,
            "channel_id": channel_id,
            "schedule": schedule,
            "languages": languages,
            "min_stars": min_stars,
            "created_at": datetime.now(UTC).isoformat(),
        }).execute()

    def get_digests_by_schedule(self, schedule: str) -> list[dict]:
        if not self.available:
            return []
        result = (
            self._client.table("digest_config")
            .select("*")
            .eq("schedule", schedule)
            .execute()
        )
        return result.data

    # --- Alerts Log ---

    def log_alert(self, repo_full_name: str, alert_type: str, details: dict | None = None):
        if not self.available:
            return
        self._client.table("alerts_log").insert({
            "repo_full_name": repo_full_name,
            "alert_type": alert_type,
            "details": details,
            "sent_at": datetime.now(UTC).isoformat(),
        }).execute()

    def was_alerted_today(self, repo_full_name: str, alert_type: str) -> bool:
        if not self.available:
            return False
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        result = (
            self._client.table("alerts_log")
            .select("id")
            .eq("repo_full_name", repo_full_name)
            .eq("alert_type", alert_type)
            .gte("sent_at", f"{today}T00:00:00")
            .limit(1)
            .execute()
        )
        return len(result.data) > 0


# Module-level singleton
database_service = DatabaseService()
