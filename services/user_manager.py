"""File-based registry of connected Discord user IDs."""

import asyncio
import json
from pathlib import Path

from config import settings as config
from utils.logger import get_logger

logger = get_logger(__name__)

USERS_FILE = config.BASE_DIR / "data" / "users.json"


class UserManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._user_ids: set[int] = set()
        self._load()

    def _load(self):
        if USERS_FILE.exists():
            try:
                data = json.loads(USERS_FILE.read_text())
                self._user_ids = set(data.get("user_ids", []))
                logger.info(f"Loaded {len(self._user_ids)} registered user(s)")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load users file: {e}")

    def _save(self):
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        USERS_FILE.write_text(json.dumps({"user_ids": list(self._user_ids)}))

    async def register(self, user_id: int):
        async with self._lock:
            self._user_ids.add(user_id)
            self._save()
            logger.info(f"Registered user {user_id}")

    async def unregister(self, user_id: int):
        async with self._lock:
            self._user_ids.discard(user_id)
            self._save()
            logger.info(f"Unregistered user {user_id}")

    def is_registered(self, user_id: int) -> bool:
        return user_id in self._user_ids

    def get_all_user_ids(self) -> list[int]:
        return list(self._user_ids)

    def user_count(self) -> int:
        return len(self._user_ids)


user_manager = UserManager()
