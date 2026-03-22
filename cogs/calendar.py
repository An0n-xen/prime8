"""Calendar cog — /meetings and /schedule commands."""

import time

import discord
from discord import app_commands
from discord.ext import commands

from cogs.auth import require_auth
from services import calendar_service
from utils.embeds import event_list_embed
from utils.logger import get_logger
from utils.metrics import command_invocations, command_duration

logger = get_logger(__name__)


class Calendar(commands.Cog):
    """Interact with your Google Calendar from Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="meetings", description="List your upcoming calendar events"
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        days="How many days ahead to look (1-30, default 7)",
        count="Max number of events to show (1-20, default 10)",
    )
    async def meetings(
        self,
        interaction: discord.Interaction,
        days: app_commands.Range[int, 1, 30] = 7,
        count: app_commands.Range[int, 1, 20] = 10,
    ):
        start = time.monotonic()
        await interaction.response.defer(thinking=True)

        if not await require_auth(interaction):
            return

        try:
            events = await calendar_service.list_upcoming_events(
                interaction.user.id, max_results=count, days_ahead=days
            )
            logger.info("meeting command: days=%d count=%d", days, count)
            logger.info(f"Fetched {len(events)} events for user {interaction.user.id}")
        except Exception as e:
            logger.error(f"Calendar API error: {e}")
            command_invocations.labels(command="meetings", status="error").inc()
            command_duration.labels(command="meetings").observe(time.monotonic() - start)
            return await interaction.followup.send(
                "❌ Failed to fetch calendar events. Make sure you've authenticated with Google.\n",
                ephemeral=True,
            )

        embed = event_list_embed(events, days=days)
        await interaction.followup.send(embed=embed)
        command_invocations.labels(command="meetings", status="success").inc()
        command_duration.labels(command="meetings").observe(time.monotonic() - start)

    @app_commands.command(name="schedule", description="Create a new calendar event")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        title="Event title",
        start="Start time (ISO format: 2026-03-20T10:00:00)",
        end="End time (ISO format: 2026-03-20T11:00:00)",
        attendees="Comma-separated emails to invite (optional)",
        location="Event location (optional)",
        description="Event description (optional)",
        tz="Timezone (default: UTC, e.g. Africa/Accra, America/New_York)",
    )
    async def schedule(
        self,
        interaction: discord.Interaction,
        title: str,
        start: str,
        end: str,
        attendees: str = "",
        location: str = "",
        description: str = "",
        tz: str = "UTC",
    ):
        t0 = time.monotonic()
        await interaction.response.defer(thinking=True)

        if not await require_auth(interaction):
            return

        # Parse attendees
        attendee_list = (
            [email.strip() for email in attendees.split(",") if email.strip()]
            if attendees
            else None
        )

        try:
            created = await calendar_service.create_event(
                interaction.user.id,
                summary=title,
                start_time=start,
                end_time=end,
                timezone=tz,
                attendees=attendee_list,
                description=description,
                location=location,
            )
            logger.info(
                f"Created event for user {interaction.user.id}: {created.get('id')}"
            )
        except Exception as e:
            logger.error(f"Calendar create error: {e}")
            command_invocations.labels(command="schedule", status="error").inc()
            command_duration.labels(command="schedule").observe(time.monotonic() - t0)
            return await interaction.followup.send(
                f"❌ Failed to create event: {e}", ephemeral=True
            )

        embed = discord.Embed(
            title="✅ Event Created",
            description=f"**{title}**",
            color=0x34A853,  # Google green
            url=created.get("htmlLink", ""),
        )
        embed.add_field(name="Start", value=start, inline=True)
        embed.add_field(name="End", value=end, inline=True)
        if attendee_list:
            embed.add_field(
                name="Invited", value="\n".join(attendee_list), inline=False
            )
        if location:
            embed.add_field(name="Location", value=location, inline=False)

        await interaction.followup.send(embed=embed)
        command_invocations.labels(command="schedule", status="success").inc()
        command_duration.labels(command="schedule").observe(time.monotonic() - t0)


async def setup(bot: commands.Bot):
    await bot.add_cog(Calendar(bot))
