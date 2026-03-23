"""GitHub Analytics cog — slash commands for trending, stats, growth, health, compare, watch, search."""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from services.ai_service import ai_service
from services.analytics_service import growth_calculator, health_scorer
from services.cache_service import cache_service
from services.database_service import database_service
from services.github_service import github_client
from utils.github_embeds import (
    compare_embed,
    growth_embed,
    health_embed,
    repo_stats_embed,
    search_results_embed,
    trending_embed,
    watchlist_embed,
)
from utils.logger import get_logger

logger = get_logger(__name__)


class GitHub(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await cache_service.connect()
        database_service.connect()
        logger.info("GitHub cog loaded (cache + database initialized)")

    async def cog_unload(self):
        await github_client.close()
        await cache_service.close()

    # --- /trending ---

    @app_commands.command(name="trending", description="Show trending GitHub repos")
    @app_commands.describe(
        language="Programming language filter (e.g. python, rust, go)",
        window="Time window: daily, weekly, or monthly",
    )
    @app_commands.choices(
        window=[
            app_commands.Choice(name="Daily", value="daily"),
            app_commands.Choice(name="Weekly", value="weekly"),
            app_commands.Choice(name="Monthly", value="monthly"),
        ]
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def trending(
        self,
        interaction: discord.Interaction,
        language: str = "",
        window: app_commands.Choice[str] | None = None,
    ):
        await interaction.response.defer()

        window_val = window.value if window else "weekly"
        window_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(window_val, 7)

        cache_key = cache_service.trending_key(language.lower(), window_val)
        cached, is_stale = await cache_service.get_or_fallback(cache_key)

        if cached:
            embed = trending_embed(cached, language, window_val, is_stale)  # type: ignore[arg-type]
            await interaction.followup.send(embed=embed)
            return

        repos = await github_client.search_trending(
            language=language.lower(),
            window_days=window_days,
        )

        if not repos:
            await interaction.followup.send("No trending repos found for those filters.")
            return

        await cache_service.set(cache_key, repos, "trending")
        embed = trending_embed(repos, language, window_val)
        await interaction.followup.send(embed=embed)

    # --- /stats ---

    @app_commands.command(name="stats", description="Show stats for a GitHub repo")
    @app_commands.describe(repo="Repository in owner/name format (e.g. fastapi/fastapi)")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def stats(self, interaction: discord.Interaction, repo: str):
        await interaction.response.defer()

        if "/" not in repo:
            await interaction.followup.send("Please use `owner/repo` format (e.g. `fastapi/fastapi`).")
            return

        owner, name = repo.split("/", 1)
        cache_key = cache_service.repo_meta_key(repo)
        cached = await cache_service.get(cache_key)

        if cached:
            growth = None
            snapshots = await asyncio.to_thread(database_service.get_snapshots, repo, 30)
            if snapshots:
                growth = growth_calculator.compute(snapshots)
            embed = repo_stats_embed(cached, growth)  # type: ignore[arg-type]
            await interaction.followup.send(embed=embed)
            return

        data = await github_client.get_repo_stats_graphql(owner, name)
        if not data:
            await interaction.followup.send(f"Could not find repo `{repo}`.")
            return

        await cache_service.set(cache_key, data, "repo_meta")

        growth = None
        snapshots = await asyncio.to_thread(database_service.get_snapshots, repo, 30)
        if snapshots:
            growth = growth_calculator.compute(snapshots)

        embed = repo_stats_embed(data, growth)
        await interaction.followup.send(embed=embed)

    # --- /growth ---

    @app_commands.command(name="growth", description="Show growth analytics for a repo")
    @app_commands.describe(
        repo="Repository in owner/name format",
        days="Number of days to analyze (default 30)",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def growth(self, interaction: discord.Interaction, repo: str, days: int = 30):
        await interaction.response.defer()

        if "/" not in repo:
            await interaction.followup.send("Please use `owner/repo` format.")
            return

        snapshots = await asyncio.to_thread(database_service.get_snapshots, repo, days)

        if len(snapshots) < 2:
            await interaction.followup.send(
                f"Not enough data for `{repo}`. It needs to be on a watchlist so snapshots are collected. "
                f"Use `/watch add {repo}` first."
            )
            return

        growth_data = growth_calculator.compute(snapshots)
        embed = growth_embed(repo, growth_data)
        await interaction.followup.send(embed=embed)

    # --- /health ---

    @app_commands.command(name="health", description="Show health report for a repo")
    @app_commands.describe(repo="Repository in owner/name format")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def health(self, interaction: discord.Interaction, repo: str):
        await interaction.response.defer()

        if "/" not in repo:
            await interaction.followup.send("Please use `owner/repo` format.")
            return

        owner, name = repo.split("/", 1)
        cache_key = cache_service.repo_health_key(repo)
        cached = await cache_service.get(cache_key)

        if cached:
            embed = health_embed(repo, cached)  # type: ignore[arg-type]
            await interaction.followup.send(embed=embed)
            return

        health_data = await github_client.get_repo_health_data(owner, name)
        if not health_data:
            await interaction.followup.send(f"Could not fetch health data for `{repo}`.")
            return

        result = health_scorer.compute(health_data)
        await cache_service.set(cache_key, result, "repo_health")
        embed = health_embed(repo, result)
        await interaction.followup.send(embed=embed)

    # --- /compare ---

    @app_commands.command(name="compare", description="Compare multiple GitHub repos side-by-side")
    @app_commands.describe(repos="Repos separated by spaces (e.g. fastapi/fastapi django/django)")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def compare(self, interaction: discord.Interaction, repos: str):
        await interaction.response.defer()

        repo_list = [r.strip() for r in repos.split() if "/" in r]
        if len(repo_list) < 2:
            await interaction.followup.send("Please provide at least 2 repos (e.g. `fastapi/fastapi django/django`).")
            return
        if len(repo_list) > 5:
            await interaction.followup.send("Maximum 5 repos for comparison.")
            return

        cache_key = cache_service.compare_key(repo_list)
        cached = await cache_service.get(cache_key)

        if cached:
            embed = compare_embed(cached)  # type: ignore[arg-type]
            await interaction.followup.send(embed=embed)
            return

        data = await github_client.batch_fetch_repos(repo_list)
        if not data:
            await interaction.followup.send("Could not fetch data for those repos.")
            return

        await cache_service.set(cache_key, data, "compare")
        embed = compare_embed(data)
        await interaction.followup.send(embed=embed)

    # --- /watch ---

    watch_group = app_commands.Group(
        name="watch",
        description="Manage your GitHub repo watchlist",
        allowed_installs=app_commands.AppInstallationType(guild=True, user=True),
        allowed_contexts=app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True),
    )

    @watch_group.command(name="add", description="Add a repo to your watchlist")
    @app_commands.describe(repo="Repository in owner/name format")
    async def watch_add(self, interaction: discord.Interaction, repo: str):
        await interaction.response.defer(ephemeral=True)

        if "/" not in repo:
            await interaction.followup.send("Please use `owner/repo` format.")
            return

        owner, name = repo.split("/", 1)
        check = await github_client.get_repo(owner, name)
        if not check:
            await interaction.followup.send(f"Repo `{repo}` not found on GitHub.")
            return

        await asyncio.to_thread(
            database_service.add_to_watchlist,
            str(interaction.user.id),
            repo,
        )
        await interaction.followup.send(f"Added `{repo}` to your watchlist.")

    @watch_group.command(name="remove", description="Remove a repo from your watchlist")
    @app_commands.describe(repo="Repository in owner/name format")
    async def watch_remove(self, interaction: discord.Interaction, repo: str):
        await interaction.response.defer(ephemeral=True)

        await asyncio.to_thread(
            database_service.remove_from_watchlist,
            str(interaction.user.id),
            repo,
        )
        await interaction.followup.send(f"Removed `{repo}` from your watchlist.")

    @watch_group.command(name="list", description="Show your watchlist")
    async def watch_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        entries = await asyncio.to_thread(
            database_service.get_watchlist,
            str(interaction.user.id),
        )
        embed = watchlist_embed(entries)
        await interaction.followup.send(embed=embed)

    @watch_group.command(name="threshold", description="Set breakout alert multiplier for a repo")
    @app_commands.describe(repo="Repository in owner/name format", multiplier="Breakout multiplier (e.g. 3.0, 5.0)")
    async def watch_threshold(self, interaction: discord.Interaction, repo: str, multiplier: float):
        await interaction.response.defer(ephemeral=True)

        if multiplier < 1.5 or multiplier > 20:
            await interaction.followup.send("Multiplier must be between 1.5 and 20.")
            return

        await asyncio.to_thread(
            database_service.set_watchlist_threshold,
            str(interaction.user.id),
            repo,
            multiplier,
        )
        await interaction.followup.send(f"Set breakout threshold for `{repo}` to {multiplier}x.")

    # --- /digest ---

    @app_commands.command(name="digest", description="Configure a scheduled digest")
    @app_commands.describe(schedule="Digest schedule: daily, weekly, or monthly")
    @app_commands.choices(
        schedule=[
            app_commands.Choice(name="Daily", value="daily"),
            app_commands.Choice(name="Weekly", value="weekly"),
            app_commands.Choice(name="Monthly", value="monthly"),
        ]
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def digest(self, interaction: discord.Interaction, schedule: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)

        await asyncio.to_thread(
            database_service.set_digest,
            str(interaction.user.id),
            "dm",
            schedule.value,
        )
        await interaction.followup.send(f"Digest set to **{schedule.value}**. You'll receive it via DM.")

    # --- /search ---

    @app_commands.command(name="search", description="Semantic search for GitHub repos (AI-powered)")
    @app_commands.describe(
        query="Natural language search query (e.g. 'real-time data streaming framework')",
        language="Filter by programming language",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def search(self, interaction: discord.Interaction, query: str, language: str = ""):
        await interaction.response.defer()

        if not ai_service.available:
            await interaction.followup.send("AI search is not available. The embedding model may not be loaded.")
            return

        results = await ai_service.search(
            query=query,
            n_results=10,
            language=language.lower() if language else None,
        )

        embed = search_results_embed(results, query)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GitHub(bot))
