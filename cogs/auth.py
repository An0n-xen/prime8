"""Auth cog — /connect and /disconnect commands + require_auth helper."""

import asyncio

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands

from config import settings as config
from services.google_auth import credential_manager
from services.user_manager import user_manager
from utils.logger import get_logger

logger = get_logger(__name__)


async def require_auth(interaction: discord.Interaction) -> bool:
    """Check if the user is authenticated. Sends an ephemeral message if not."""
    user_id = interaction.user.id
    if user_manager.is_registered(user_id) and credential_manager.has_credentials(
        user_id
    ):
        logger.info(f"User {user_id} is authenticated")
        return True

    logger.info(f"User {user_id} is not authenticated")
    await interaction.followup.send(
        "You need to connect your Google account first. Use `/connect`.",
        ephemeral=True,
    )
    return False


class Auth(commands.Cog):
    """Google account connection management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="connect", description="Connect your Google account")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def connect(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        if user_manager.is_registered(user_id) and credential_manager.has_credentials(
            user_id
        ):
            await interaction.response.send_message(
                "You're already connected. Use `/disconnect` first to reconnect.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            auth_url, future, runner = credential_manager.start_oauth_flow(user_id)
            logger.info(f"Started OAuth flow for user {user_id}, auth URL: {auth_url}")
        except FileNotFoundError as e:
            logger.error(f"OAuth setup error for user {user_id}: {e}")
            return await interaction.followup.send(f"Setup error: {e}", ephemeral=True)

        # Start the callback server
        await runner.setup()
        site = web.TCPSite(runner, "localhost", config.OAUTH_CALLBACK_PORT)
        try:
            await site.start()
        except OSError:
            await runner.cleanup()
            return await interaction.followup.send(
                "OAuth callback server could not start. Port may be in use.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title="Connect Your Google Account",
            description=(
                f"[Click here to authorize]({auth_url})\n\n"
                "After authorizing, the browser will redirect automatically.\n"
                "This link expires in 2 minutes."
            ),
            color=0x4285F4,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        try:
            logger.info(f"Waiting for OAuth callback for user {user_id}")
            await asyncio.wait_for(future, timeout=120)
            await user_manager.register(user_id)
            await interaction.followup.send(
                "Successfully connected your Google account!",
                ephemeral=True,
            )
        except asyncio.TimeoutError:
            # Manual fallback — prompt for code
            logger.info(f"OAuth callback timed out for user {user_id}")
            await interaction.followup.send(
                "The automatic callback timed out.\n"
                "If you authorized in the browser, copy the **full URL** from the browser's "
                "address bar after the redirect and paste the `code=` parameter value here.\n"
                "Use `/connect_code` with the code to finish connecting.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"OAuth error for user {user_id}: {e}")
            await interaction.followup.send(
                f"Authorization failed: {e}",
                ephemeral=True,
            )
        finally:
            await runner.cleanup()

    @app_commands.command(
        name="connect_code",
        description="Finish connecting with an authorization code (VPS fallback)",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(code="The authorization code from the redirect URL")
    async def connect_code(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        user_id = interaction.user.id

        try:
            await credential_manager.exchange_code(user_id, code)
            await user_manager.register(user_id)
            await interaction.followup.send(
                "Successfully connected your Google account!",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Code exchange error for user {user_id}: {e}")
            await interaction.followup.send(
                f"Failed to exchange code: {e}",
                ephemeral=True,
            )

    @app_commands.command(
        name="disconnect", description="Disconnect your Google account"
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def disconnect(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        if not user_manager.is_registered(user_id):
            logger.info(
                f"User {user_id} attempted to disconnect but was not registered"
            )
            await interaction.response.send_message(
                "You're not connected.", ephemeral=True
            )
            return

        logger.info(f"Disconnecting user {user_id}")
        await interaction.response.defer(ephemeral=True, thinking=True)

        credential_manager.remove_credentials(user_id)
        await user_manager.unregister(user_id)

        # Clean up state files
        logger.info(f"Cleaning up state files for user {user_id}")
        for suffix in ("_seen_events.json", "_seen_emails.json"):
            state_file = config.STATE_PATH / f"{user_id}{suffix}"
            if state_file.exists():
                state_file.unlink()

        await interaction.followup.send(
            "Disconnected your Google account.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Auth(bot))
