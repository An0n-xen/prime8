"""Chat cog — responds to @mentions with LLM-powered replies."""

from __future__ import annotations

import asyncio

import discord
from discord.ext import commands, tasks

from services.llm_service import llm_service
from utils.logger import get_logger

logger = get_logger(__name__)

# Per user+channel conversation history (last N turns)
MAX_HISTORY = 10

# How often to flush dirty conversations to Supabase (seconds)
PERSIST_INTERVAL = 300  # 5 minutes

# Discord embed description limit
EMBED_DESC_LIMIT = 4096
# Discord message limit
MSG_LIMIT = 2000


def _history_key(user_id: int, channel_id: int) -> tuple[int, int]:
    """Key history by (user, channel) so conversations never bleed across users."""
    return (user_id, channel_id)


class Chat(commands.Cog):
    """Respond to mentions with AI-powered chat."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Keyed by (user_id, channel_id) — fully isolated per user per channel
        self._history: dict[tuple[int, int], list[dict]] = {}
        # Track total message count per user+channel for summary metadata
        self._msg_counts: dict[tuple[int, int], int] = {}
        # Track which conversations have new messages since last persist
        self._dirty: set[tuple[int, int]] = set()
        # Store guild_id per key for persist context
        self._guild_ids: dict[tuple[int, int], int | None] = {}

    async def cog_load(self) -> None:
        self._persist_loop.start()

    async def cog_unload(self) -> None:
        self._persist_loop.cancel()
        await self._flush_all()

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

        history = self._history.get(key, [])

        async with message.channel.typing():
            result = await llm_service.chat_with_tools(
                content,
                user_id=user_id,
                guild_id=guild_id,
                channel_id=channel_id,
                history=history,
            )

        # Update history
        history.append({"role": "user", "content": content})
        history.append({"role": "assistant", "content": result.text})
        self._msg_counts[key] = self._msg_counts.get(key, 0) + 1

        # Trim if over limit
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]

        self._history[key] = history
        self._dirty.add(key)
        self._guild_ids[key] = guild_id

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
    # Background persist loop — runs every 5 minutes
    # ------------------------------------------------------------------

    @tasks.loop(seconds=PERSIST_INTERVAL)
    async def _persist_loop(self) -> None:
        await self._flush_all()

    @_persist_loop.before_loop
    async def _before_persist(self) -> None:
        await self.bot.wait_until_ready()

    async def _flush_all(self) -> None:
        """Persist all dirty conversations to Supabase."""
        if not self._dirty:
            return

        # Snapshot and clear dirty set so new messages during flush don't get lost
        to_flush = self._dirty.copy()
        self._dirty.clear()

        count = 0
        for key in to_flush:
            history = self._history.get(key)
            if not history or len(history) < 2:
                continue
            user_id, channel_id = key
            guild_id = self._guild_ids.get(key)
            try:
                await self._persist_summary(
                    user_id, channel_id, guild_id,
                    history, self._msg_counts.get(key, 0),
                )
                count += 1
            except Exception as e:
                logger.error(f"Failed to persist summary for user {user_id}: {e}")
                # Re-mark as dirty so it retries next cycle
                self._dirty.add(key)

        if count:
            logger.info(f"Flushed {count} conversation summary/summaries to Supabase")

    async def _persist_summary(
        self,
        user_id: int,
        channel_id: int,
        guild_id: int | None,
        history: list[dict],
        total_msg_count: int,
    ) -> None:
        """Summarize conversation and write to Supabase."""
        from services.memory_service import memory_service

        if not memory_service.available:
            logger.warning("Memory service unavailable — skipping summary")
            return

        lines = []
        for msg in history:
            role = "User" if msg["role"] == "user" else "Prime8"
            lines.append(f"{role}: {msg['content'][:200]}")
        conversation_text = "\n".join(lines)

        existing = await asyncio.to_thread(
            memory_service.get_conversation_summary,
            str(user_id),
            str(channel_id),
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
            str(user_id),
            str(channel_id),
            summary,
            total_msg_count,
            str(guild_id) if guild_id else None,
        )


async def setup(bot: commands.Bot):
    llm_service.initialize()
    await bot.add_cog(Chat(bot))
