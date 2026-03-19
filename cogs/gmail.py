"""Gmail cog — /emails command."""

import discord
from utils.logger import get_logger
from discord import app_commands
from discord.ext import commands

from services import gmail_service
from utils.embeds import email_list_embed, email_embed
from utils.pagination import PaginatedView

logger = get_logger(__name__)


class Gmail(commands.Cog):
    """Interact with your Gmail inbox from Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="emails", description="List your recent Gmail messages")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        count="Number of emails to fetch (1-20, default 10)",
        query="Gmail search query (e.g. 'is:unread', 'from:boss@company.com')",
    )
    async def emails(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 1, 20] = 10,
        query: str = "is:inbox",
    ):
        await interaction.response.defer(thinking=True)

        try:
            messages = await gmail_service.list_messages(max_results=count, query=query)
        except Exception as e:
            logger.error(f"Gmail API error: {e}")
            return await interaction.followup.send(
                "❌ Failed to fetch emails. Make sure you've authenticated with Google.\n",
                ephemeral=True,
            )

        if not messages:
            return await interaction.followup.send("📭 No emails found for that query.")

        # If 5 or fewer, show summary embed. If more, paginate individual embeds.
        if len(messages) <= 5:
            embed = email_list_embed(messages, query=query)
            await interaction.followup.send(embed=embed)
        else:
            embeds = [email_embed(msg) for msg in messages]
            view = PaginatedView(embeds, author_id=interaction.user.id)
            await interaction.followup.send(embed=embeds[0], view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Gmail(bot))
