"""Gmail API wrapper — keeps Google-specific logic out of the cog."""

import asyncio
import time
from datetime import datetime
from email.utils import parseaddr
from typing import Optional

from services.google_auth import credential_manager
from utils.metrics import google_api_calls, google_api_duration


async def list_messages(
    user_id: int,
    max_results: int = 10,
    query: str = "is:inbox",
) -> list[dict]:
    """
    Fetch recent messages from Gmail.

    Returns a list of dicts with keys: id, subject, from_name, from_email, snippet, date
    """
    service = await credential_manager.get_gmail_service(user_id)

    def _fetch():
        t0 = time.monotonic()
        results = service.users().messages().list(
            userId="me", maxResults=max_results, q=query
        ).execute()

        messages = results.get("messages", [])
        detailed = []

        for msg in messages:
            data = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()

            headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
            from_name, from_email = parseaddr(headers.get("From", ""))

            detailed.append({
                "id": msg["id"],
                "subject": headers.get("Subject", "(no subject)"),
                "from_name": from_name or from_email,
                "from_email": from_email,
                "snippet": data.get("snippet", ""),
                "date": headers.get("Date", ""),
                "link": f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}",
            })

        google_api_calls.labels(service="gmail", method="list_messages", status="success").inc()
        google_api_duration.labels(service="gmail", method="list_messages").observe(time.monotonic() - t0)
        return detailed

    try:
        return await asyncio.to_thread(_fetch)
    except Exception:
        google_api_calls.labels(service="gmail", method="list_messages", status="error").inc()
        raise


async def get_message(user_id: int, message_id: str) -> Optional[dict]:
    """Fetch a single message's full content."""
    service = await credential_manager.get_gmail_service(user_id)

    def _fetch():
        t0 = time.monotonic()
        result = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
        google_api_calls.labels(service="gmail", method="get_message", status="success").inc()
        google_api_duration.labels(service="gmail", method="get_message").observe(time.monotonic() - t0)
        return result

    try:
        return await asyncio.to_thread(_fetch)
    except Exception:
        google_api_calls.labels(service="gmail", method="get_message", status="error").inc()
        raise


async def get_new_messages_since(user_id: int, since: datetime, max_results: int = 20) -> list[dict]:
    """
    Fetch messages received after *since*.

    Uses Gmail's `after:` epoch-seconds query to filter server-side.
    Returns the same dict shape as list_messages().
    """
    epoch = int(since.timestamp())
    query = f"is:inbox after:{epoch}"
    return await list_messages(user_id, max_results=max_results, query=query)
