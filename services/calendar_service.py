"""Google Calendar API wrapper."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from services.google_auth import get_calendar_service


async def list_upcoming_events(
    max_results: int = 10,
    days_ahead: int = 7,
) -> list[dict]:
    """
    Fetch upcoming calendar events.

    Returns a list of dicts with keys: id, summary, start, end, location, attendees, organizer, link
    """
    service = get_calendar_service()

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    def _fetch():
        results = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = results.get("items", [])
        parsed = []

        for event in events:
            start = event.get("start", {})
            end = event.get("end", {})

            parsed.append({
                "id": event.get("id"),
                "summary": event.get("summary", "(No title)"),
                "start": start.get("dateTime", start.get("date", "")),
                "end": end.get("dateTime", end.get("date", "")),
                "location": event.get("location", ""),
                "attendees": [
                    a.get("email") for a in event.get("attendees", [])
                ],
                "organizer": event.get("organizer", {}).get("email", ""),
                "link": event.get("htmlLink", ""),
            })

        return parsed

    return await asyncio.to_thread(_fetch)


async def create_event(
    summary: str,
    start_time: str,        # ISO 8601 datetime string
    end_time: str,           # ISO 8601 datetime string
    timezone: str = "UTC",
    attendees: Optional[list[str]] = None,
    description: str = "",
    location: str = "",
) -> dict:
    """Create a calendar event and return the created event data."""
    service = get_calendar_service()

    event_body = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {"dateTime": start_time, "timeZone": timezone},
        "end": {"dateTime": end_time, "timeZone": timezone},
    }

    if attendees:
        event_body["attendees"] = [{"email": email} for email in attendees]

    def _create():
        return service.events().insert(
            calendarId="primary",
            body=event_body,
            sendUpdates="all",  # Notify attendees
        ).execute()

    return await asyncio.to_thread(_create)


async def get_new_events_since(since: datetime) -> list[dict]:
    """
    Fetch events updated/created since a given timestamp.
    Used by the notification poller to detect new invites.
    """
    service = get_calendar_service()

    def _fetch():
        results = service.events().list(
            calendarId="primary",
            updatedMin=since.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            showDeleted=False,
        ).execute()
        return results.get("items", [])

    return await asyncio.to_thread(_fetch)
