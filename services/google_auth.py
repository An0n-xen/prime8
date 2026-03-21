"""
Google OAuth2 credential management — multi-user.

Per-user tokens stored in HashiCorp Vault at secret/prime8/tokens/{discord_user_id}.
Cached service objects with TTL to avoid rebuilding on every call.
"""

import asyncio
import json
import tempfile
import time
from dataclasses import dataclass

from aiohttp import web
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from config import settings as config
from utils.logger import get_logger

logger = get_logger(__name__)

# Initialized in init_vault() from bot.py
vault = None


def init_vault(vault_service):
    global vault
    vault = vault_service


@dataclass
class _CachedService:
    service: object
    created_at: float


class CredentialManager:
    def __init__(self):
        self._credential_cache: dict[int, Credentials] = {}
        self._service_cache: dict[tuple[int, str], _CachedService] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, user_id: int) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    def has_credentials(self, user_id: int) -> bool:
        if user_id in self._credential_cache:
            return True
        token_data = vault.get_user_token(user_id)
        return token_data is not None

    async def get_credentials(self, user_id: int) -> Credentials:
        lock = self._get_lock(user_id)
        async with lock:
            # Check in-memory cache
            if user_id in self._credential_cache:
                creds = self._credential_cache[user_id]
                if creds.valid:
                    return creds
                if creds.expired and creds.refresh_token:
                    await asyncio.to_thread(creds.refresh, Request())
                    self._save_credentials(user_id, creds)
                    return creds

            # Load from Vault
            token_data = await asyncio.to_thread(vault.get_user_token, user_id)
            if not token_data:
                raise FileNotFoundError(
                    f"No credentials for user {user_id}. Use /connect first."
                )

            creds = Credentials.from_authorized_user_info(
                token_data, config.GOOGLE_SCOPES
            )

            if not creds.valid:
                if creds.expired and creds.refresh_token:
                    await asyncio.to_thread(creds.refresh, Request())
                    self._save_credentials(user_id, creds)
                else:
                    raise ValueError(
                        f"Credentials for user {user_id} are invalid and cannot be refreshed."
                    )

            self._credential_cache[user_id] = creds
            return creds

    async def _get_service(self, user_id: int, api: str, version: str):
        cache_key = (user_id, api)
        cached = self._service_cache.get(cache_key)
        if (
            cached
            and (time.time() - cached.created_at) < config.SERVICE_CACHE_TTL_SECONDS
        ):
            return cached.service

        creds = await self.get_credentials(user_id)
        service = await asyncio.to_thread(build, api, version, credentials=creds)
        self._service_cache[cache_key] = _CachedService(
            service=service, created_at=time.time()
        )
        return service

    async def get_gmail_service(self, user_id: int):
        return await self._get_service(user_id, "gmail", "v1")

    async def get_calendar_service(self, user_id: int):
        return await self._get_service(user_id, "calendar", "v3")

    def _save_credentials(self, user_id: int, creds: Credentials):
        token_data = json.loads(creds.to_json())
        vault.save_user_token(user_id, token_data)

    def save_credentials(self, user_id: int, creds: Credentials):
        self._save_credentials(user_id, creds)
        self._credential_cache[user_id] = creds

    def remove_credentials(self, user_id: int):
        vault.delete_user_token(user_id)
        self._credential_cache.pop(user_id, None)
        for key in list(self._service_cache):
            if key[0] == user_id:
                del self._service_cache[key]
        self._locks.pop(user_id, None)

    def start_oauth_flow(
        self, user_id: int
    ) -> tuple[str, asyncio.Future, web.AppRunner]:
        """
        Start an OAuth flow for a user.

        Returns (auth_url, future, runner) where:
        - auth_url: URL the user should visit to authorize
        - future: resolves with Credentials when callback is hit
        - runner: aiohttp AppRunner to clean up after
        """
        # Load Google client credentials from Vault and write to a temp file
        # (the Google SDK requires a file path)
        google_creds = vault.get_google_credentials()
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump(google_creds, tmp)
        tmp.close()

        redirect_uri = f"http://localhost:{config.OAUTH_CALLBACK_PORT}/callback"

        flow = Flow.from_client_secrets_file(
            tmp.name,
            scopes=config.GOOGLE_SCOPES,
            redirect_uri=redirect_uri,
        )

        # Clean up temp file
        import os
        os.unlink(tmp.name)

        auth_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
        )

        loop = asyncio.get_event_loop()
        future: asyncio.Future[Credentials] = loop.create_future()

        app = web.Application()

        async def callback_handler(request: web.Request):
            code = request.query.get("code")
            if not code:
                return web.Response(text="Missing authorization code.", status=400)
            try:
                await asyncio.to_thread(flow.fetch_token, code=code)
                creds = flow.credentials
                self.save_credentials(user_id, creds)
                if not future.done():
                    future.set_result(creds)
                return web.Response(
                    text="Authorization successful! You can close this tab.",
                    content_type="text/html",
                )
            except Exception as e:
                if not future.done():
                    future.set_exception(e)
                return web.Response(text=f"Authorization failed: {e}", status=500)

        app.router.add_get("/callback", callback_handler)

        runner = web.AppRunner(app)

        self._pending_flows = getattr(self, "_pending_flows", {})
        self._pending_flows[user_id] = flow

        return auth_url, future, runner

    async def exchange_code(self, user_id: int, code: str) -> Credentials:
        """Manual fallback: exchange an authorization code for credentials."""
        pending = getattr(self, "_pending_flows", {})
        flow = pending.get(user_id)
        if not flow:
            raise ValueError("No pending OAuth flow for this user.")

        await asyncio.to_thread(flow.fetch_token, code=code)
        creds = flow.credentials
        self.save_credentials(user_id, creds)
        pending.pop(user_id, None)
        return creds


credential_manager = CredentialManager()
