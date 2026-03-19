"""
Notifications cog — polls Google Calendar for new events and DMs the bot owner.

This uses a simple polling approach (check every N seconds for events updated
since last check). For production with many users, consider Google Calendar
push notifications instead (requires a public HTTPS endpoint).
"""

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

import config
from services import calendar_service, gmail_service
from utils.embeds import new_event_notification_embed, new_email_notification_embed

log = logging.getLogger(__name__)


class Notifications(commands.Cog):
    """Background task that watches for new calendar events."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_check: datetime = datetime.now(timezone.utc)
        self.last_email_check: datetime = datetime.now(timezone.utc)
        self.seen_event_ids: set[str] = set()
        self.seen_email_ids: set[str] = set()

    async def cog_load(self):
        """Start the polling loops when the cog loads."""
        self.check_new_events.start()
        self.check_new_emails.start()
        log.info(f"Notification poller started (interval: {config.POLL_INTERVAL_SECONDS}s)")

    async def cog_unload(self):
        """Stop the polling loops when the cog unloads."""
        self.check_new_events.cancel()
        self.check_new_emails.cancel()

    @tasks.loop(seconds=config.POLL_INTERVAL_SECONDS)
    async def check_new_events(self):
        try:
            events = await calendar_service.get_new_events_since(self.last_check)
            self.last_check = datetime.now(timezone.utc)

            for event in events:
                event_id = event.get("id")
                if not event_id or event_id in self.seen_event_ids:
                    continue

                self.seen_event_ids.add(event_id)

                # Build notification
                parsed = {
                    "summary": event.get("summary", "Untitled"),
                    "start": event.get("start", {}).get("dateTime", event.get("start", {}).get("date", "")),
                    "end": event.get("end", {}).get("dateTime", event.get("end", {}).get("date", "")),
                    "organizer": event.get("organizer", {}).get("email", ""),
                    "link": event.get("htmlLink", ""),
                }
                embed = new_event_notification_embed(parsed)

                await self._send_notification(embed)

        except Exception as e:
            log.error(f"Notification poll error: {e}")

    @check_new_events.before_loop
    async def before_check(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()

        # Pre-populate seen events so we don't spam on first run
        try:
            events = await calendar_service.get_new_events_since(self.last_check)
            self.seen_event_ids = {e.get("id") for e in events if e.get("id")}
            log.info(f"Pre-loaded {len(self.seen_event_ids)} existing event(s)")
        except Exception as e:
            log.warning(f"Failed to pre-load events: {e}")

    # ── Gmail polling ────────────────────────────────────────────────

    @tasks.loop(seconds=config.POLL_INTERVAL_SECONDS)
    async def check_new_emails(self):
        try:
            emails = await gmail_service.get_new_messages_since(self.last_email_check)
            self.last_email_check = datetime.now(timezone.utc)

            for email in emails:
                email_id = email.get("id")
                if not email_id or email_id in self.seen_email_ids:
                    continue

                self.seen_email_ids.add(email_id)
                embed = new_email_notification_embed(email)
                await self._send_notification(embed)

        except Exception as e:
            log.error(f"Email notification poll error: {e}")

    @check_new_emails.before_loop
    async def before_email_check(self):
        """Wait until the bot is ready, then pre-populate seen emails."""
        await self.bot.wait_until_ready()

        try:
            emails = await gmail_service.get_new_messages_since(self.last_email_check)
            self.seen_email_ids = {e.get("id") for e in emails if e.get("id")}
            log.info(f"Pre-loaded {len(self.seen_email_ids)} existing email(s)")
        except Exception as e:
            log.warning(f"Failed to pre-load emails: {e}")

    async def _send_notification(self, embed: discord.Embed):
        """
        Send a notification embed. Tries:
        1. DM the bot owner (primary for user-install apps)
        2. A configured notification channel (if set)
        """
        # DM the bot owner first — this is a user-install app
        app_info = await self.bot.application_info()
        owner = app_info.owner
        if owner:
            try:
                await owner.send(embed=embed)
                return
            except discord.Forbidden:
                log.warning("Cannot DM bot owner — DMs might be disabled")

        # Fall back to channel if configured
        if config.NOTIFICATION_CHANNEL_ID:
            channel = self.bot.get_channel(config.NOTIFICATION_CHANNEL_ID)
            if channel:
                await channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Notifications(bot))
