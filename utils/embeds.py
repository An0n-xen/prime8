"""Discord embed builders for emails and calendar events."""

import discord
from datetime import datetime


def email_embed(email: dict) -> discord.Embed:
    """Build a Discord embed for a single email."""
    embed = discord.Embed(
        title=email["subject"][:256],
        description=email["snippet"][:4096] if email["snippet"] else "No preview available",
        color=0xEA4335,  # Gmail red
    )
    embed.set_author(name=f"📧 {email['from_name']}", url=None)
    embed.add_field(name="From", value=email["from_email"], inline=True)
    embed.add_field(name="Date", value=email["date"][:25], inline=True)
    embed.set_footer(text=f"ID: {email['id']}")
    return embed


def email_list_embed(emails: list[dict], query: str = "") -> discord.Embed:
    """Build a summary embed for multiple emails."""
    embed = discord.Embed(
        title="📬 Recent Emails",
        description=f"Query: `{query}`" if query else "Showing latest inbox messages",
        color=0xEA4335,
    )

    for i, email in enumerate(emails[:10], 1):
        from_display = email["from_name"] or email["from_email"]
        snippet = email["snippet"][:80] + "..." if len(email["snippet"]) > 80 else email["snippet"]
        embed.add_field(
            name=f"{i}. {email['subject'][:100]}",
            value=f"**From:** {from_display}\n{snippet}",
            inline=False,
        )

    embed.set_footer(text=f"Showing {len(emails)} email(s)")
    return embed


def event_embed(event: dict) -> discord.Embed:
    """Build a Discord embed for a single calendar event."""
    embed = discord.Embed(
        title=f"📅 {event['summary'][:256]}",
        url=event.get("link", ""),
        color=0x4285F4,  # Google blue
    )

    embed.add_field(name="Start", value=_format_time(event["start"]), inline=True)
    embed.add_field(name="End", value=_format_time(event["end"]), inline=True)

    if event.get("location"):
        embed.add_field(name="Location", value=event["location"], inline=False)

    if event.get("attendees"):
        attendee_list = "\n".join(event["attendees"][:10])
        if len(event["attendees"]) > 10:
            attendee_list += f"\n... and {len(event['attendees']) - 10} more"
        embed.add_field(name="Attendees", value=attendee_list, inline=False)

    if event.get("organizer"):
        embed.set_footer(text=f"Organized by {event['organizer']}")

    return embed


def event_list_embed(events: list[dict], days: int = 7) -> discord.Embed:
    """Build a summary embed for multiple calendar events."""
    embed = discord.Embed(
        title="📅 Upcoming Meetings",
        description=f"Next {days} day(s)",
        color=0x4285F4,
    )

    if not events:
        embed.description = "No upcoming events — your calendar is clear! 🎉"
        return embed

    for event in events[:15]:
        time_str = _format_time(event["start"])
        location = f" 📍 {event['location']}" if event.get("location") else ""
        embed.add_field(
            name=event["summary"][:100],
            value=f"🕐 {time_str}{location}",
            inline=False,
        )

    embed.set_footer(text=f"Showing {len(events)} event(s)")
    return embed


def new_event_notification_embed(event: dict) -> discord.Embed:
    """Build a notification embed for a newly detected calendar event."""
    embed = discord.Embed(
        title="🔔 New Meeting Scheduled",
        description=event.get("summary", "Untitled event"),
        color=0xFBBC04,  # Google yellow
        url=event.get("link", ""),
    )
    embed.add_field(name="Start", value=_format_time(event.get("start", "")), inline=True)
    embed.add_field(name="End", value=_format_time(event.get("end", "")), inline=True)

    if event.get("organizer"):
        embed.add_field(name="Organized by", value=event["organizer"], inline=False)

    return embed


def new_email_notification_embed(email: dict) -> discord.Embed:
    """Build a notification embed for a newly received email."""
    embed = discord.Embed(
        title="📧 New Email",
        description=email["subject"][:256],
        color=0xEA4335,  # Gmail red
    )
    embed.add_field(name="From", value=f"{email['from_name']} ({email['from_email']})", inline=False)
    snippet = email["snippet"][:200] + "..." if len(email["snippet"]) > 200 else email["snippet"]
    if snippet:
        embed.add_field(name="Preview", value=snippet, inline=False)
    if email.get("date"):
        embed.add_field(name="Date", value=email["date"][:25], inline=True)
    return embed


def _format_time(time_str: str) -> str:
    """Convert ISO time string to a human-readable format."""
    if not time_str:
        return "N/A"

    # Handle all-day events (date only, no 'T')
    if "T" not in time_str:
        try:
            dt = datetime.fromisoformat(time_str)
            return dt.strftime("%a, %b %d %Y")
        except ValueError:
            return time_str

    try:
        # Strip timezone suffix for parsing, handle Z
        clean = time_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%a, %b %d · %I:%M %p")
    except ValueError:
        return time_str
