"""Chat cog — responds to @mentions with LLM-powered replies."""

from __future__ import annotations

import discord
from discord.ext import commands

from services.llm_service import llm_service
from utils.logger import get_logger

logger = get_logger(__name__)

# Per-channel conversation history (last N turns)
MAX_HISTORY = 10

# Discord embed description limit
EMBED_DESC_LIMIT = 4096
# Discord message limit
MSG_LIMIT = 2000


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
            result = await llm_service.chat_with_tools(
                content, user_id=message.author.id, history=history,
            )

        # Update history
        history.append({"role": "user", "content": content})
        history.append({"role": "assistant", "content": result.text})
        self._history[channel_id] = history[-MAX_HISTORY:]

        # Send as embed when tools were used (richer UI), plain text otherwise
        meta = result.embed_meta
        if meta and len(result.text) <= EMBED_DESC_LIMIT:
            emoji, title, color = meta
            embed = discord.Embed(
                title=f"{emoji} {title}",
                description=result.text,
                color=color,
            )
            await message.reply(embed=embed, mention_author=False)
        elif len(result.text) <= MSG_LIMIT:
            await message.reply(result.text, mention_author=False)
        else:
            # Long response — split into chunks
            chunks = [result.text[i : i + MSG_LIMIT] for i in range(0, len(result.text), MSG_LIMIT)]
            for chunk in chunks:
                await message.channel.send(chunk)


async def setup(bot: commands.Bot):
    llm_service.initialize()
    await bot.add_cog(Chat(bot))
