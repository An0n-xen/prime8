"""Calendar cog — /meetings and /schedule commands."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services import calendar_service
from utils.embeds import event_list_embed, event_embed

log = logging.getLogger(__name__)


class Calendar(commands.Cog):
    """Interact with your Google Calendar from Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="meetings", description="List your upcoming calendar events")
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
        await interaction.response.defer(thinking=True)

        try:
            events = await calendar_service.list_upcoming_events(
                max_results=count, days_ahead=days
            )
        except Exception as e:
            log.error(f"Calendar API error: {e}")
            return await interaction.followup.send(
                "❌ Failed to fetch calendar events. Make sure you've authenticated with Google.\n"
                "Run `python -m services.google_auth` to set up.",
                ephemeral=True,
            )

        embed = event_list_embed(events, days=days)
        await interaction.followup.send(embed=embed)

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
        await interaction.response.defer(thinking=True)

        # Parse attendees
        attendee_list = [
            email.strip() for email in attendees.split(",") if email.strip()
        ] if attendees else None

        try:
            created = await calendar_service.create_event(
                summary=title,
                start_time=start,
                end_time=end,
                timezone=tz,
                attendees=attendee_list,
                description=description,
                location=location,
            )
        except Exception as e:
            log.error(f"Calendar create error: {e}")
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


async def setup(bot: commands.Bot):
    await bot.add_cog(Calendar(bot))
