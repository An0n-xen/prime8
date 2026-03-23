"""Redis cache layer for GitHub analytics data."""

from __future__ import annotations

import json

import redis.asyncio as redis

from config import settings as config
from utils.logger import get_logger

logger = get_logger(__name__)

# TTLs in seconds
TTLS = {
    "trending": 3600,       # 1 hour
    "repo_meta": 900,       # 15 minutes
    "repo_stars": 21600,    # 6 hours
    "repo_health": 3600,    # 1 hour
    "compare": 1800,        # 30 minutes
    "fallback": 86400,      # 24 hours (stale fallback)
}


class CacheService:
    def __init__(self):
        self._redis: redis.Redis | None = None
        self._available = False

    async def connect(self):
        if not config.REDIS_URL:
            logger.warning("REDIS_URL not set, cache disabled")
            return
        try:
            self._redis = redis.from_url(config.REDIS_URL, decode_responses=True)
            await self._redis.ping()
            self._available = True
            logger.info("Redis cache connected")
        except Exception as e:
            logger.warning(f"Redis unavailable, cache disabled: {e}")
            self._available = False

    @property
    def available(self) -> bool:
        return self._available and self._redis is not None

    async def get(self, key: str) -> dict | list | None:
        if not self.available or self._redis is None:
            return None
        try:
            data = await self._redis.get(key)
            if data:
                return json.loads(data)  # type: ignore[no-any-return]
        except Exception as e:
            logger.warning(f"Cache get error for {key}: {e}")
        return None

    async def set(self, key: str, value: object, ttl_key: str = "repo_meta") -> None:
        if not self.available or self._redis is None:
            return
        try:
            ttl = TTLS.get(ttl_key, 900)
            serialized = json.dumps(value, default=str)
            await self._redis.set(key, serialized, ex=ttl)
            # Also store in fallback with longer TTL
            await self._redis.set(f"fallback:{key}", serialized, ex=TTLS["fallback"])
        except Exception as e:
            logger.warning(f"Cache set error for {key}: {e}")

    async def get_or_fallback(self, key: str) -> tuple[dict | list | None, bool]:
        """Returns (data, is_stale). Tries primary key first, then fallback."""
        data = await self.get(key)
        if data is not None:
            return data, False

        fallback = await self.get(f"fallback:{key}")
        if fallback is not None:
            return fallback, True

        return None, False

    async def delete(self, key: str) -> None:
        if not self.available or self._redis is None:
            return
        try:
            await self._redis.delete(key, f"fallback:{key}")
        except Exception as e:
            logger.warning(f"Cache delete error for {key}: {e}")

    # --- Key builders ---

    @staticmethod
    def trending_key(language: str, window: str) -> str:
        return f"trending:{language or 'all'}:{window}"

    @staticmethod
    def repo_meta_key(repo_name: str) -> str:
        return f"repo:{repo_name}:meta"

    @staticmethod
    def repo_health_key(repo_name: str) -> str:
        return f"repo:{repo_name}:health"

    @staticmethod
    def repo_stars_key(repo_name: str) -> str:
        return f"repo:{repo_name}:stars"

    @staticmethod
    def compare_key(repo_names: list[str]) -> str:
        import hashlib
        key_hash = hashlib.md5("|".join(sorted(repo_names)).encode()).hexdigest()[:8]
        return f"compare:{key_hash}"

    async def close(self):
        if self._redis:
            await self._redis.aclose()


# Module-level singleton
cache_service = CacheService()
