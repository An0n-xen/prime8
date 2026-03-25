"""Chat cog — responds to @mentions with LLM-powered replies."""

from __future__ import annotations

import discord
from discord.ext import commands

from services.llm_service import llm_service
from utils.logger import get_logger

logger = get_logger(__name__)

# Per-channel conversation history (last N turns)
MAX_HISTORY = 10


class Chat(commands.Cog):
    """Respond to mentions with AI-powered chat."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._history: dict[int, list[dict]] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Respond in DMs or when mentioned in a server
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = self.bot.user in message.mentions if message.guild else False

        if not is_dm and not is_mentioned:
            return

        # Strip the mention from the message content
        content = message.content
        if self.bot.user:
            content = content.replace(f"<@{self.bot.user.id}>", "").strip()

        if not content:
            return

        channel_id = message.channel.id
        history = self._history.get(channel_id, [])

        async with message.channel.typing():
            response = await llm_service.chat(content, history=history)

        # Update history
        history.append({"role": "user", "content": content})
        history.append({"role": "assistant", "content": response})
        self._history[channel_id] = history[-MAX_HISTORY:]

        # Discord has a 2000 char limit — split if needed
        if len(response) <= 2000:
            await message.reply(response, mention_author=False)
        else:
            chunks = [response[i : i + 2000] for i in range(0, len(response), 2000)]
            for chunk in chunks:
                await message.channel.send(chunk)


async def setup(bot: commands.Bot):
    llm_service.initialize()
    await bot.add_cog(Chat(bot))
