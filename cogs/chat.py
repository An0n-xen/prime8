"""Chat cog — responds to @mentions and DMs with LLM-powered replies."""

from __future__ import annotations

import asyncio

import discord
from discord.ext import commands, tasks
from langchain_core.chat_history import InMemoryChatMessageHistory

from services.llm_service import llm_service
from utils.logger import get_logger

logger = get_logger(__name__)

# Per user+channel conversation history (last N turns kept)
MAX_HISTORY = 20

# How often to flush dirty conversations to Supabase (seconds)
PERSIST_INTERVAL = 300  # 5 minutes

# Discord limits
EMBED_DESC_LIMIT = 4096
MSG_LIMIT = 2000


def _history_key(user_id: int, channel_id: int) -> str:
    return f"{user_id}:{channel_id}"


class Chat(commands.Cog):
    """Respond to mentions and DMs with AI-powered chat."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._histories: dict[str, InMemoryChatMessageHistory] = {}
        self._msg_counts: dict[str, int] = {}
        self._dirty: set[str] = set()
        self._guild_ids: dict[str, int | None] = {}

    async def cog_load(self) -> None:
        self._persist_loop.start()

    async def cog_unload(self) -> None:
        self._persist_loop.cancel()
        await self._flush_all()

    def _get_history(self, key: str) -> InMemoryChatMessageHistory:
        if key not in self._histories:
            self._histories[key] = InMemoryChatMessageHistory()
        return self._histories[key]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = self.bot.user in message.mentions if message.guild else False

        if not is_dm and not is_mentioned:
            return

        content = message.content
        if self.bot.user:
            content = content.replace(f"<@{self.bot.user.id}>", "").strip()

        if not content:
            return

        user_id = message.author.id
        channel_id = message.channel.id
        guild_id = message.guild.id if message.guild else None
        key = _history_key(user_id, channel_id)

        history = self._get_history(key)

        # Convert to dict format for llm_service
        history_dicts = [
            {"role": "user" if msg.type == "human" else "assistant", "content": msg.content}
            for msg in history.messages
        ]

        async with message.channel.typing():
            result = await llm_service.chat_with_tools(
                content,
                user_id=user_id,
                guild_id=guild_id,
                channel_id=channel_id,
                history=history_dicts,
            )

        # Store in LangChain history
        history.add_user_message(content)
        history.add_ai_message(result.text)
        self._msg_counts[key] = self._msg_counts.get(key, 0) + 1
        self._dirty.add(key)
        self._guild_ids[key] = guild_id

        # Trim old messages
        while len(history.messages) > MAX_HISTORY:
            history.messages.pop(0)

        # Send response
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
            chunks = [result.text[i : i + MSG_LIMIT] for i in range(0, len(result.text), MSG_LIMIT)]
            for chunk in chunks:
                await message.channel.send(chunk)

    # ------------------------------------------------------------------
    # Background persist loop — summarize and flush every 5 minutes
    # ------------------------------------------------------------------

    @tasks.loop(seconds=PERSIST_INTERVAL)
    async def _persist_loop(self) -> None:
        await self._flush_all()

    @_persist_loop.before_loop
    async def _before_persist(self) -> None:
        await self.bot.wait_until_ready()

    async def _flush_all(self) -> None:
        """Summarize and persist all dirty conversations to Supabase."""
        if not self._dirty:
            return

        to_flush = self._dirty.copy()
        self._dirty.clear()

        count = 0
        for key in to_flush:
            history = self._histories.get(key)
            if not history or len(history.messages) < 2:
                continue
            # Parse user_id and channel_id from key
            user_id_str, channel_id_str = key.split(":", 1)
            guild_id = self._guild_ids.get(key)
            try:
                await self._persist_summary(
                    user_id_str, channel_id_str,
                    str(guild_id) if guild_id else None,
                    history, self._msg_counts.get(key, 0),
                )
                count += 1
            except Exception as e:
                logger.error(f"Failed to persist summary for {key}: {e}")
                self._dirty.add(key)

        if count:
            logger.info(f"Flushed {count} conversation summary/summaries to Supabase")

    async def _persist_summary(
        self,
        user_id: str,
        channel_id: str,
        guild_id: str | None,
        history: InMemoryChatMessageHistory,
        total_msg_count: int,
    ) -> None:
        """Summarize conversation and write to Supabase."""
        from services.memory_service import memory_service

        if not memory_service.available:
            return

        lines = []
        for msg in history.messages:
            role = "User" if msg.type == "human" else "Prime8"
            lines.append(f"{role}: {msg.content[:200]}")
        conversation_text = "\n".join(lines)

        existing = await asyncio.to_thread(
            memory_service.get_conversation_summary, user_id, channel_id,
        )
        existing_summary = (existing["summary"] if existing else "") or ""

        prompt = (
            "Summarize the following into a brief paragraph (max 200 words). "
            "Focus on key topics discussed, decisions made, and user preferences. "
            "This will be used as context in future conversations.\n\n"
        )
        if existing_summary:
            prompt += f"Previous context:\n{existing_summary}\n\n"
        prompt += f"Latest conversation:\n{conversation_text}"

        summary = await llm_service.chat(prompt)

        await asyncio.to_thread(
            memory_service.upsert_conversation_summary,
            user_id, channel_id, summary, total_msg_count, guild_id,
        )


async def setup(bot: commands.Bot):
    llm_service.initialize()
    await bot.add_cog(Chat(bot))
