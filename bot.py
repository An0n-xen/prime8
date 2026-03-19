from __future__ import annotations
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from utils.logger import get_logger
import config

logger = get_logger(__name__)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

EXTENSIONS = [
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


async def main():
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