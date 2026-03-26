from __future__ import annotations

import asyncio
import signal

import discord
from discord import app_commands
from discord.ext import commands

from config import settings as config
from services.google_auth import init_vault
from utils.logger import get_logger
from utils.metrics import bot_ready, guild_count, start_metrics_server

logger = get_logger(__name__)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

EXTENSIONS = [
    "cogs.auth",
    "cogs.gmail",
    "cogs.calendar",
    "cogs.notifications",
    "cogs.github",
    "cogs.github_notifications",
    "cogs.chat",
    "cogs.downloader",
]


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    bot_ready.set(1)
    guild_count.set(len(bot.guilds))

    commands_before = bot.tree.get_commands()
    logger.info(f"Commands in tree before sync: {[c.name for c in commands_before]}")
    synced = await bot.tree.sync()
    logger.info(f"Synced {len(synced)} command(s) globally: {[c.name for c in synced]}")


# Ping command to test if the bot is alive
@bot.tree.command(name="ping", description="Test if the bot is alive")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! 🏓")


# DM command to start a private conversation with the bot
@bot.tree.command(name="dm", description="Start a private DM conversation with the bot")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def dm(interaction: discord.Interaction):
    # Check if we're already in a 1-on-1 DM with the bot
    if (
        isinstance(interaction.channel, discord.DMChannel)
        and interaction.channel.recipient == bot.user
    ):
        await interaction.response.send_message("You're already in a DM with me!")
        return
    try:
        dm_channel = await interaction.user.create_dm()
        await dm_channel.send(
            "Hey! You can chat with me privately here. Use any of my slash commands or just send a message."
        )
        await interaction.response.send_message("I've sent you a DM!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            "I can't send you a DM. Please check your privacy settings.", ephemeral=True
        )


async def main():
    # Initialize secret backend based on mode
    if config.MODE == "prod":
        from services.vault_service import VaultService

        secret_svc = VaultService(
            addr=config.VAULT_ADDR,
            role_id=config.VAULT_ROLE_ID,
            secret_id=config.VAULT_SECRET_ID,
        )
        config.DISCORD_TOKEN = secret_svc.get_discord_token()

        # Load GitHub analytics secrets from Vault
        gh_secrets = secret_svc.get_github_analytics_secrets()
        config.GITHUB_TOKEN = gh_secrets["github_token"]
        config.SUPABASE_URL = gh_secrets["supabase_url"]
        config.SUPABASE_KEY = gh_secrets["supabase_key"]
        config.REDIS_URL = gh_secrets["redis_url"]
        config.HF_API_TOKEN = gh_secrets["hf_api_token"]

        # Load LLM secret from Vault
        config.DEEPINFRA_API_KEY = secret_svc.get_deepinfra_api_key()

        logger.info("Loaded secrets from Vault (prod mode)")
    else:
        from services.local_secret_service import LocalSecretService

        secret_svc = LocalSecretService()
        logger.info("Using local secrets (dev mode)")

    init_vault(secret_svc)

    start_metrics_server(config.METRICS_PORT)
    logger.info(f"Prometheus metrics server started on port {config.METRICS_PORT}")

    if not config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN is not set. Please check your configuration.")
        return

    # Graceful shutdown on SIGTERM/SIGINT (Docker stop)
    loop = asyncio.get_running_loop()

    async def shutdown():
        logger.info("Received shutdown signal, closing bot...")
        await bot.close()

    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    except NotImplementedError:
        pass  # Windows: signal handlers not supported on ProactorEventLoop

    async with bot:
        for ext in EXTENSIONS:
            try:
                await bot.load_extension(ext)
                logger.info(f"Loaded extension: {ext}")
            except Exception as e:
                logger.error(f"Failed to load {ext}: {e}")
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
