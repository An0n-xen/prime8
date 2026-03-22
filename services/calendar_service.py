"""Google Calendar API wrapper."""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from services.google_auth import credential_manager
from utils.metrics import google_api_calls, google_api_duration


async def list_upcoming_events(
    user_id: int,
    max_results: int = 10,
    days_ahead: int = 7,
) -> list[dict]:
    """
    Fetch upcoming calendar events.

    Returns a list of dicts with keys: id, summary, start, end, location, attendees, organizer, link
    """
    service = await credential_manager.get_calendar_service(user_id)

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    def _fetch():
        t0 = time.monotonic()
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

        google_api_calls.labels(service="calendar", method="list_events", status="success").inc()
        google_api_duration.labels(service="calendar", method="list_events").observe(time.monotonic() - t0)
        return parsed

    try:
        return await asyncio.to_thread(_fetch)
    except Exception:
        google_api_calls.labels(service="calendar", method="list_events", status="error").inc()
        raise


async def create_event(
    user_id: int,
    summary: str,
    start_time: str,        # ISO 8601 datetime string
    end_time: str,           # ISO 8601 datetime string
    timezone: str = "UTC",
    attendees: Optional[list[str]] = None,
    description: str = "",
    location: str = "",
) -> dict:
    """Create a calendar event and return the created event data."""
    service = await credential_manager.get_calendar_service(user_id)

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
        t0 = time.monotonic()
        result = service.events().insert(
            calendarId="primary",
            body=event_body,
            sendUpdates="all",  # Notify attendees
        ).execute()
        google_api_calls.labels(service="calendar", method="create_event", status="success").inc()
        google_api_duration.labels(service="calendar", method="create_event").observe(time.monotonic() - t0)
        return result

    try:
        return await asyncio.to_thread(_create)
    except Exception:
        google_api_calls.labels(service="calendar", method="create_event", status="error").inc()
        raise


async def get_new_events_since(user_id: int, since: datetime) -> list[dict]:
    """
    Fetch events updated/created since a given timestamp.
    Used by the notification poller to detect new invites.
    """
    service = await credential_manager.get_calendar_service(user_id)

    def _fetch():
        t0 = time.monotonic()
        results = service.events().list(
            calendarId="primary",
            updatedMin=since.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            showDeleted=False,
        ).execute()
        google_api_calls.labels(service="calendar", method="get_new_events", status="success").inc()
        google_api_duration.labels(service="calendar", method="get_new_events").observe(time.monotonic() - t0)
        return results.get("items", [])

    try:
        return await asyncio.to_thread(_fetch)
    except Exception:
        google_api_calls.labels(service="calendar", method="get_new_events", status="error").inc()
        raise
