"""Background jobs for GitHub analytics: snapshots, breakout detection, digests, health refresh."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from discord.ext import commands, tasks

from config import settings as config
from services.ai_service import ai_service
from services.analytics_service import breakout_detector, health_scorer
from services.cache_service import cache_service
from services.database_service import database_service
from services.github_service import github_client
from utils.github_embeds import breakout_alert_embed, digest_embed
from utils.logger import get_logger

logger = get_logger(__name__)


class GitHubNotifications(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.snapshot_collector.start()
        self.breakout_scanner.start()
        self.health_refresher.start()
        self.daily_digest_job.start()
        self.repo_indexer.start()
        logger.info("GitHub notification jobs started")

    async def cog_unload(self):
        self.snapshot_collector.cancel()
        self.breakout_scanner.cancel()
        self.health_refresher.cancel()
        self.daily_digest_job.cancel()
        self.repo_indexer.cancel()

    # --- Snapshot Collection (every 4 hours) ---

    @tasks.loop(hours=config.SNAPSHOT_INTERVAL_HOURS)
    async def snapshot_collector(self):
        try:
            watched = await asyncio.to_thread(database_service.get_all_watched_repos)
            if not watched:
                return

            # Deduplicate repo names
            unique_repos = list({w["repo_full_name"] for w in watched})
            logger.info(f"Collecting snapshots for {len(unique_repos)} repos")

            # Batch fetch in groups of 50
            for i in range(0, len(unique_repos), 50):
                batch = unique_repos[i : i + 50]
                data = await github_client.batch_fetch_repos(batch)

                for repo_data in data:
                    name = repo_data.get("nameWithOwner", "")
                    if not name:
                        continue
                    stars = repo_data.get("stargazerCount", 0)
                    forks = repo_data.get("forkCount", 0)
                    open_issues = repo_data.get("openIssues", {}).get("totalCount", 0)
                    watchers = repo_data.get("watchers", {}).get("totalCount", 0)

                    await asyncio.to_thread(
                        database_service.insert_snapshot,
                        name, stars, forks, open_issues, watchers,
                    )

                # Brief pause between batches for rate limiting
                if i + 50 < len(unique_repos):
                    await asyncio.sleep(2)

            logger.info(f"Snapshot collection complete: {len(unique_repos)} repos updated")
        except Exception as e:
            logger.error(f"Snapshot collection failed: {e}")

    @snapshot_collector.before_loop
    async def before_snapshot(self):
        await self.bot.wait_until_ready()

    # --- Breakout Detection (every 6 hours) ---

    @tasks.loop(hours=config.BREAKOUT_SCAN_HOURS)
    async def breakout_scanner(self):
        try:
            watched = await asyncio.to_thread(database_service.get_all_watched_repos)
            if not watched:
                return

            # Group by repo to get per-user thresholds
            repo_users: dict[str, list[dict]] = {}
            for w in watched:
                repo_users.setdefault(w["repo_full_name"], []).append(w)

            breakouts_found = 0
            for repo_name, users in repo_users.items():
                snapshots = await asyncio.to_thread(
                    database_service.get_snapshots, repo_name, 14,
                )
                if len(snapshots) < 3:
                    continue

                # Use lowest threshold among users watching this repo
                min_threshold = min(u.get("alert_threshold", config.DEFAULT_BREAKOUT_MULTIPLIER) for u in users)
                result = breakout_detector.check(snapshots, min_threshold)

                if result is None:
                    continue

                # Check if already alerted today
                already = await asyncio.to_thread(
                    database_service.was_alerted_today, repo_name, "breakout",
                )
                if already:
                    continue

                # Send alert via DM to each user watching this repo
                current_stars = snapshots[-1]["stars"]
                embed = breakout_alert_embed(repo_name, current_stars, result)

                for user_info in users:
                    user_threshold = user_info.get("alert_threshold", config.DEFAULT_BREAKOUT_MULTIPLIER)
                    if result["ratio"] >= user_threshold:
                        try:
                            user = await self.bot.fetch_user(int(user_info["discord_user_id"]))
                            await user.send(embed=embed)
                        except Exception as e:
                            logger.warning(f"Failed to DM user {user_info['discord_user_id']}: {e}")

                await asyncio.to_thread(
                    database_service.log_alert,
                    repo_name, "breakout", result,
                )
                breakouts_found += 1

            logger.info(f"Breakout scan complete: {breakouts_found} breakouts detected")
        except Exception as e:
            logger.error(f"Breakout scan failed: {e}")

    @breakout_scanner.before_loop
    async def before_breakout(self):
        await self.bot.wait_until_ready()

    # --- Health Refresh (every 12 hours) ---

    @tasks.loop(hours=12)
    async def health_refresher(self):
        try:
            watched = await asyncio.to_thread(database_service.get_all_watched_repos)
            if not watched:
                return

            unique_repos = list({w["repo_full_name"] for w in watched})
            logger.info(f"Refreshing health for {len(unique_repos)} repos")

            for repo_name in unique_repos:
                owner, name = repo_name.split("/", 1)
                health_data = await github_client.get_repo_health_data(owner, name)
                if health_data:
                    result = health_scorer.compute(health_data)
                    cache_key = cache_service.repo_health_key(repo_name)
                    await cache_service.set(cache_key, result, "repo_health")
                await asyncio.sleep(1)  # Rate limit courtesy

            logger.info("Health refresh complete")
        except Exception as e:
            logger.error(f"Health refresh failed: {e}")

    @health_refresher.before_loop
    async def before_health(self):
        await self.bot.wait_until_ready()

    # --- Daily Digest (runs every hour, checks if it's digest time) ---

    @tasks.loop(hours=1)
    async def daily_digest_job(self):
        try:
            now = datetime.now(UTC)
            digest_hour, digest_minute = map(int, config.DIGEST_TIME.split(":"))

            # Only run at the configured hour
            if now.hour != digest_hour:
                return

            # Daily digests
            daily_configs = await asyncio.to_thread(database_service.get_digests_by_schedule, "daily")
            if daily_configs:
                await self._send_digests(daily_configs, "daily")

            # Weekly on Sunday
            if now.weekday() == 6:
                weekly_configs = await asyncio.to_thread(database_service.get_digests_by_schedule, "weekly")
                if weekly_configs:
                    await self._send_digests(weekly_configs, "weekly")

        except Exception as e:
            logger.error(f"Digest job failed: {e}")

    async def _send_digests(self, configs: list[dict], period: str):
        for cfg in configs:
            languages = cfg.get("languages") or []
            language = languages[0] if languages else ""
            window_days = 7 if period == "daily" else 30

            repos = await github_client.search_trending(
                language=language,
                window_days=window_days,
                min_stars=cfg.get("min_stars", 50),
            )

            if repos:
                embed = digest_embed(repos, language, period)
                try:
                    user = await self.bot.fetch_user(int(cfg["discord_user_id"]))
                    await user.send(embed=embed)
                except Exception as e:
                    logger.warning(f"Failed to DM digest to user {cfg['discord_user_id']}: {e}")

    @daily_digest_job.before_loop
    async def before_digest(self):
        await self.bot.wait_until_ready()

    # --- Repo Indexer for AI search (every 6 hours) ---

    @tasks.loop(hours=6)
    async def repo_indexer(self):
        if not ai_service.available:
            return

        try:
            watched = await asyncio.to_thread(database_service.get_all_watched_repos)
            if not watched:
                return

            unique_repos = list({w["repo_full_name"] for w in watched})
            logger.info(f"Indexing {len(unique_repos)} repos for AI search")

            for repo_name in unique_repos:
                owner, name = repo_name.split("/", 1)

                repo_data = await github_client.get_repo_stats_graphql(owner, name)
                if not repo_data:
                    continue

                readme = await github_client.get_readme(owner, name)

                description = repo_data.get("description", "")
                stars = repo_data.get("stargazerCount", 0)
                lang = (repo_data.get("primaryLanguage") or {}).get("name", "")

                # Get health score if cached
                health_cache = await cache_service.get(cache_service.repo_health_key(repo_name))
                health_score = health_cache.get("overall", 0) if health_cache else 0

                await ai_service.index_repo(
                    repo_name=repo_name,
                    description=description,
                    readme=readme or "",
                    stars=stars,
                    language=lang,
                    health_score=health_score,
                )

                await asyncio.sleep(2)  # Rate limit + embedding time

            logger.info("Repo indexing complete")
        except Exception as e:
            logger.error(f"Repo indexer failed: {e}")

    @repo_indexer.before_loop
    async def before_indexer(self):
        await self.bot.wait_until_ready()
        # Initialize AI service lazily on first run
        if not ai_service.available:
            await ai_service.initialize()


async def setup(bot: commands.Bot):
    await bot.add_cog(GitHubNotifications(bot))
