"""
Notifications cog — multi-user fan-out/fan-in polling.

Polls Google Calendar and Gmail for each registered user concurrently,
using a semaphore to cap concurrent API calls and staggered starts
to avoid request bursts.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands, tasks

from config import settings as config
from services import calendar_service, gmail_service
from services.user_manager import user_manager
from utils.embeds import new_event_notification_embed, new_email_notification_embed
from utils.logger import get_logger

logger = get_logger(__name__)

MAX_SEEN_IDS = 500


@dataclass
class UserPollState:
    last_event_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_email_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    seen_event_ids: set[str] = field(default_factory=set)
    seen_email_ids: set[str] = field(default_factory=set)


def _state_path(user_id: int, kind: str) -> Path:
    return config.STATE_PATH / f"{user_id}_seen_{kind}.json"


def _load_seen_ids(user_id: int, kind: str) -> set[str]:
    path = _state_path(user_id, kind)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            ids = set(data.get("ids", []))
            # Cap to prevent unbounded growth
            if len(ids) > MAX_SEEN_IDS:
                ids = set(list(ids)[-MAX_SEEN_IDS:])
            return ids
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def _save_seen_ids(user_id: int, kind: str, ids: set[str]):
    path = _state_path(user_id, kind)
    # Cap before saving
    capped = list(ids)[-MAX_SEEN_IDS:] if len(ids) > MAX_SEEN_IDS else list(ids)
    path.write_text(json.dumps({"ids": capped}))


class Notifications(commands.Cog):
    """Background task that watches for new calendar events and emails for all users."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._user_states: dict[int, UserPollState] = {}
        self._semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_API_CALLS)

    def _get_state(self, user_id: int) -> UserPollState:
        if user_id not in self._user_states:
            state = UserPollState(
                seen_event_ids=_load_seen_ids(user_id, "events"),
                seen_email_ids=_load_seen_ids(user_id, "emails"),
            )
            self._user_states[user_id] = state
        return self._user_states[user_id]

    async def cog_load(self):
        self.poll_all_users.start()
        logger.info(
            f"Multi-user notification poller started (interval: {config.POLL_INTERVAL_SECONDS}s)"
        )

    async def cog_unload(self):
        self.poll_all_users.cancel()
        self._persist_all_states()

    def _persist_all_states(self):
        for user_id, state in self._user_states.items():
            _save_seen_ids(user_id, "events", state.seen_event_ids)
            _save_seen_ids(user_id, "emails", state.seen_email_ids)
        logger.info(f"Persisted poll state for {len(self._user_states)} user(s)")

    @tasks.loop(seconds=config.POLL_INTERVAL_SECONDS)
    async def poll_all_users(self):
        user_ids = user_manager.get_all_user_ids()
        if not user_ids:
            return

        async def staggered_poll(index: int, uid: int):
            if index > 0:
                await asyncio.sleep(index * 0.5)
            await self._poll_user(uid)

        results = await asyncio.gather(
            *(staggered_poll(i, uid) for i, uid in enumerate(user_ids)),
            return_exceptions=True,
        )

        for uid, result in zip(user_ids, results):
            if isinstance(result, Exception):
                logger.error(f"Poll error for user {uid}: {result}")

    @poll_all_users.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

        # Pre-populate seen IDs for all registered users
        user_ids = user_manager.get_all_user_ids()
        if not user_ids:
            return

        async def prepopulate(uid: int):
            state = self._get_state(uid)
            try:
                async with self._semaphore:
                    events = await calendar_service.get_new_events_since(uid, state.last_event_check)
                    state.seen_event_ids.update(e["id"] for e in events if e.get("id"))
            except Exception as e:
                logger.warning(f"Failed to pre-load events for user {uid}: {e}")
            try:
                async with self._semaphore:
                    emails = await gmail_service.get_new_messages_since(uid, state.last_email_check)
                    state.seen_email_ids.update(e["id"] for e in emails if e.get("id"))
            except Exception as e:
                logger.warning(f"Failed to pre-load emails for user {uid}: {e}")

        await asyncio.gather(
            *(prepopulate(uid) for uid in user_ids),
            return_exceptions=True,
        )
        logger.info(f"Pre-populated seen IDs for {len(user_ids)} user(s)")

    async def _poll_user(self, user_id: int):
        state = self._get_state(user_id)

        # Poll calendar events
        try:
            async with self._semaphore:
                events = await calendar_service.get_new_events_since(user_id, state.last_event_check)
            state.last_event_check = datetime.now(timezone.utc)

            for event in events:
                event_id = event.get("id")
                if not event_id or event_id in state.seen_event_ids:
                    continue
                state.seen_event_ids.add(event_id)
                parsed = {
                    "summary": event.get("summary", "Untitled"),
                    "start": event.get("start", {}).get(
                        "dateTime", event.get("start", {}).get("date", "")
                    ),
                    "end": event.get("end", {}).get(
                        "dateTime", event.get("end", {}).get("date", "")
                    ),
                    "organizer": event.get("organizer", {}).get("email", ""),
                    "link": event.get("htmlLink", ""),
                }
                embed = new_event_notification_embed(parsed)
                await self._send_notification(user_id, embed)
        except Exception as e:
            logger.error(f"Calendar poll error for user {user_id}: {e}")

        # Poll emails
        try:
            async with self._semaphore:
                emails = await gmail_service.get_new_messages_since(user_id, state.last_email_check)
            state.last_email_check = datetime.now(timezone.utc)

            for email in emails:
                email_id = email.get("id")
                if not email_id or email_id in state.seen_email_ids:
                    continue
                state.seen_email_ids.add(email_id)
                embed = new_email_notification_embed(email)
                await self._send_notification(user_id, embed)
        except Exception as e:
            logger.error(f"Email poll error for user {user_id}: {e}")

        # Persist after each user poll
        _save_seen_ids(user_id, "events", state.seen_event_ids)
        _save_seen_ids(user_id, "emails", state.seen_email_ids)

    async def _send_notification(self, user_id: int, embed: discord.Embed):
        """DM a specific user with a notification embed."""
        try:
            user = await self.bot.fetch_user(user_id)
            await user.send(embed=embed)
        except discord.Forbidden:
            logger.warning(f"Cannot DM user {user_id} — DMs might be disabled")
        except discord.NotFound:
            logger.warning(f"User {user_id} not found")


async def setup(bot: commands.Bot):
    await bot.add_cog(Notifications(bot))
