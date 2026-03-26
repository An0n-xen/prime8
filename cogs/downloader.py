"""Downloader cog — /download command for media from any URL."""

from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from services import download_service
from services.download_service import DISCORD_FILE_LIMIT
from utils.logger import get_logger
from utils.metrics import command_duration, command_invocations

logger = get_logger(__name__)


class Downloader(commands.Cog):
    """Download media from URLs using yt-dlp, gallery-dl, or direct HTTP."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="download", description="Download media from a URL (video, images, files)")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        url="The URL to download from",
        audio_only="Extract audio only (for video URLs)",
        compress="Compress video to fit Discord's 25MB limit if too large (default: False)",
    )
    async def download(
        self,
        interaction: discord.Interaction,
        url: str,
        audio_only: bool = False,
        compress: bool = False,
    ):
        start = time.monotonic()
        await interaction.response.defer(thinking=True)

        try:
            if audio_only:
                result = await download_service.download_audio(url)
            else:
                result = await download_service.download(url)

            if result.error:
                command_invocations.labels(command="download", status="error").inc()
                await interaction.followup.send(f"Download failed: {result.error}", ephemeral=True)
                return

            if not result.files:
                command_invocations.labels(command="download", status="error").inc()
                await interaction.followup.send("No files were downloaded.", ephemeral=True)
                return

            # Check which files are oversized
            oversized = [f for f in result.files if f.is_file() and f.stat().st_size > DISCORD_FILE_LIMIT]

            if oversized and compress:
                await interaction.edit_original_response(
                    content="Downloaded. Compressing large files to fit Discord's 25MB limit..."
                )
                result = await download_service.compress_oversized_files(result)
            elif oversized and not compress:
                # Without compress flag, drop oversized files entirely
                result.files = [f for f in result.files if f.is_file() and f.stat().st_size <= DISCORD_FILE_LIMIT]

            # Build embed
            embed = discord.Embed(
                title=result.title[:256],
                description=f"Downloaded via **{result.source}**",
                color=0x34A853,  # Google green
            )
            embed.add_field(
                name="Files",
                value=f"{len(result.files)} file(s)",
                inline=True,
            )

            if result.compressed:
                embed.add_field(name="Compressed", value="Video re-encoded to fit 25MB", inline=True)

            if oversized and not compress and not result.files:
                # All files were too large and user didn't opt into compression
                sizes = ", ".join(f"{f.stat().st_size / 1024 / 1024:.1f}MB" for f in oversized if f.exists())
                embed.description = (
                    f"Downloaded via **{result.source}** but all files exceed "
                    f"Discord's 25MB upload limit ({sizes}).\n\n"
                    f"Re-run with `compress: True` to re-encode video to fit."
                )
                command_invocations.labels(command="download", status="success").inc()
                await interaction.followup.send(embed=embed)
                return

            if oversized and not compress:
                skipped_count = len(oversized)
                embed.add_field(
                    name="Skipped",
                    value=f"{skipped_count} file(s) exceed 25MB. Use `compress: True` to re-encode.",
                    inline=False,
                )

            if not result.files:
                command_invocations.labels(command="download", status="error").inc()
                await interaction.followup.send("No downloadable files found.", ephemeral=True)
                return

            # Send files — Discord allows max 10 per message
            discord_files = [discord.File(fp, filename=fp.name) for fp in result.files if fp.is_file()]
            for i in range(0, len(discord_files), 10):
                batch = discord_files[i : i + 10]
                if i == 0:
                    await interaction.followup.send(embed=embed, files=batch)
                else:
                    await interaction.followup.send(files=batch)

            command_invocations.labels(command="download", status="success").inc()

        except Exception as e:
            logger.error(f"Download error for {url}: {e}")
            command_invocations.labels(command="download", status="error").inc()
            await interaction.followup.send(f"Download failed: {e}", ephemeral=True)

        finally:
            command_duration.labels(command="download").observe(time.monotonic() - start)
            # Clean up downloaded files
            if "result" in locals() and result.files:
                output_dir = result.files[0].parent
                download_service.cleanup(output_dir)


async def setup(bot: commands.Bot):
    await bot.add_cog(Downloader(bot))
