"""Memory service — persistent user, guild, and conversation memory via Supabase.

Uses an in-memory TTL cache so we only hit Supabase once per key
until the cache expires (5 minutes) or is invalidated on write.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from services.database_service import database_service
from utils.logger import get_logger

logger = get_logger(__name__)

MAX_USER_MEMORIES = 50
MAX_GUILD_MEMORIES = 30
SUMMARY_MAX_CHARS = 1500
CACHE_TTL = 300  # 5 minutes


class _Cache:
    """Simple TTL cache keyed by string."""

    def __init__(self, ttl: int = CACHE_TTL):
        self._store: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, ts = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (value, time.monotonic())

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)


class MemoryService:
    """Read/write memory from Supabase with TTL cache."""

    def __init__(self) -> None:
        self._cache = _Cache()

    @property
    def _db(self):
        return database_service._db

    @property
    def available(self) -> bool:
        return database_service.available

    # ------------------------------------------------------------------
    # User memories
    # ------------------------------------------------------------------

    def get_user_memories(self, discord_user_id: str) -> list[dict[str, Any]]:
        if not self.available:
            return []
        cache_key = f"user:{discord_user_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        result = (
            self._db.table("user_memories")
            .select("id, content, category")
            .eq("discord_user_id", discord_user_id)
            .order("created_at", desc=False)
            .limit(MAX_USER_MEMORIES)
            .execute()
        )
        data = result.data or []
        self._cache.set(cache_key, data)
        return data

    def save_user_memory(
        self, discord_user_id: str, content: str, category: str = "fact"
    ) -> None:
        if not self.available:
            return
        self._db.table("user_memories").insert(
            {
                "discord_user_id": discord_user_id,
                "content": content,
                "category": category,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ).execute()
        self._cache.invalidate(f"user:{discord_user_id}")

    def delete_user_memory(self, discord_user_id: str, content_query: str) -> int:
        """Delete memories whose content contains the query string. Returns count."""
        if not self.available:
            return 0
        result = (
            self._db.table("user_memories")
            .select("id, content")
            .eq("discord_user_id", discord_user_id)
            .ilike("content", f"%{content_query}%")
            .execute()
        )
        if not result.data:
            return 0
        ids = [r["id"] for r in result.data]
        for memory_id in ids:
            self._db.table("user_memories").delete().eq("id", memory_id).execute()
        self._cache.invalidate(f"user:{discord_user_id}")
        return len(ids)

    # ------------------------------------------------------------------
    # Guild memories
    # ------------------------------------------------------------------

    def get_guild_memories(self, guild_id: str) -> list[dict[str, Any]]:
        if not self.available:
            return []
        cache_key = f"guild:{guild_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        result = (
            self._db.table("guild_memories")
            .select("id, content, category")
            .eq("guild_id", guild_id)
            .order("created_at", desc=False)
            .limit(MAX_GUILD_MEMORIES)
            .execute()
        )
        data = result.data or []
        self._cache.set(cache_key, data)
        return data

    def save_guild_memory(
        self, guild_id: str, content: str, category: str = "context"
    ) -> None:
        if not self.available:
            return
        self._db.table("guild_memories").insert(
            {
                "guild_id": guild_id,
                "content": content,
                "category": category,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ).execute()
        self._cache.invalidate(f"guild:{guild_id}")

    # ------------------------------------------------------------------
    # Conversation summaries
    # ------------------------------------------------------------------

    def get_conversation_summary(
        self, discord_user_id: str, channel_id: str
    ) -> dict[str, Any] | None:
        if not self.available:
            return None
        cache_key = f"summary:{discord_user_id}:{channel_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        result = (
            self._db.table("conversation_summaries")
            .select("*")
            .eq("discord_user_id", discord_user_id)
            .eq("channel_id", channel_id)
            .limit(1)
            .execute()
        )
        data = result.data[0] if result.data else None
        self._cache.set(cache_key, data)
        return data

    def upsert_conversation_summary(
        self,
        discord_user_id: str,
        channel_id: str,
        summary: str,
        message_count: int,
        guild_id: str | None = None,
    ) -> None:
        if not self.available:
            return
        self._db.table("conversation_summaries").upsert(
            {
                "discord_user_id": discord_user_id,
                "channel_id": channel_id,
                "guild_id": guild_id,
                "summary": summary[:SUMMARY_MAX_CHARS],
                "message_count": message_count,
                "updated_at": datetime.now(UTC).isoformat(),
            },
            on_conflict="discord_user_id,channel_id",
        ).execute()
        self._cache.invalidate(f"summary:{discord_user_id}:{channel_id}")

    # ------------------------------------------------------------------
    # Context builder
    # ------------------------------------------------------------------

    def build_context(
        self,
        discord_user_id: str,
        channel_id: str,
        guild_id: str | None = None,
    ) -> str:
        """Build a memory context string to inject into the system prompt.

        Only loads data for the specific user, channel, and guild provided.
        """
        if not self.available:
            return ""

        sections: list[str] = []

        user_mems = self.get_user_memories(discord_user_id)
        if user_mems:
            lines = [f"- {m['content']}" for m in user_mems]
            sections.append("What you know about this user:\n" + "\n".join(lines))

        if guild_id:
            guild_mems = self.get_guild_memories(guild_id)
            if guild_mems:
                lines = [f"- {m['content']}" for m in guild_mems]
                sections.append("About this server:\n" + "\n".join(lines))

        summary = self.get_conversation_summary(discord_user_id, channel_id)
        if summary and summary.get("summary"):
            sections.append(
                "Previous conversation with this user in this channel:\n"
                + summary["summary"]
            )

        if not sections:
            return ""

        return "\n\n".join(sections)


memory_service = MemoryService()
