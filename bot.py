from __future__ import annotations
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from utils.logger import get_logger
from config import settings as config

logger = get_logger(__name__)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

EXTENSIONS = [
    "cogs.auth",
    "cogs.gmail",
    "cogs.calendar",
    "cogs.notifications",
]


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")

    commands_before = bot.tree.get_commands()
    logger.info(f"Commands in tree before sync: {[c.name for c in commands_before]}")
    synced = await bot.tree.sync()
    logger.info(f"Synced {len(synced)} command(s) globally: {[c.name for c in synced]}")


@bot.tree.command(name="ping", description="Test if the bot is alive")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! 🏓")


@bot.tree.command(name="dm", description="Start a private DM conversation with the bot")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def dm(interaction: discord.Interaction):
    # Check if we're already in a 1-on-1 DM with the bot
    if isinstance(interaction.channel, discord.DMChannel) and interaction.channel.recipient == bot.user:
        await interaction.response.send_message("You're already in a DM with me!")
        return
    try:
        dm_channel = await interaction.user.create_dm()
        await dm_channel.send("Hey! You can chat with me privately here. Use any of my slash commands or just send a message.")
        await interaction.response.send_message("I've sent you a DM!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("I can't send you a DM. Please check your privacy settings.", ephemeral=True)


async def main():
    if not config.DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN environment variable is not set")
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
