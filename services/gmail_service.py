"""Gmail API wrapper — keeps Google-specific logic out of the cog."""

import asyncio
from datetime import datetime
from email.utils import parseaddr
from typing import Optional

from services.google_auth import credential_manager


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

        return detailed

    return await asyncio.to_thread(_fetch)


async def get_message(user_id: int, message_id: str) -> Optional[dict]:
    """Fetch a single message's full content."""
    service = await credential_manager.get_gmail_service(user_id)

    def _fetch():
        return service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

    return await asyncio.to_thread(_fetch)


async def get_new_messages_since(user_id: int, since: datetime, max_results: int = 20) -> list[dict]:
    """
    Fetch messages received after *since*.

    Uses Gmail's `after:` epoch-seconds query to filter server-side.
    Returns the same dict shape as list_messages().
    """
    epoch = int(since.timestamp())
    query = f"is:inbox after:{epoch}"
    return await list_messages(user_id, max_results=max_results, query=query)
