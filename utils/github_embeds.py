"""Discord embed builders for GitHub analytics."""

from __future__ import annotations

import discord

# GitHub brand-ish colors
GITHUB_DARK = 0x24292E
GITHUB_GREEN = 0x2EA043
GITHUB_ORANGE = 0xF78166
GITHUB_PURPLE = 0x8957E5
GITHUB_BLUE = 0x58A6FF
BREAKOUT_RED = 0xDA3633


def trending_embed(repos: list[dict], language: str, window: str, is_stale: bool = False) -> discord.Embed:
    lang_display = language.capitalize() if language else "All languages"
    embed = discord.Embed(
        title=f"\U0001f525 Trending {lang_display} repos \u2014 {window}",
        color=GITHUB_ORANGE,
    )

    medal = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}

    for i, repo in enumerate(repos[:10], 1):
        name = repo.get("full_name") or repo.get("nameWithOwner", "unknown")
        stars = repo.get("stargazers_count") or repo.get("stargazerCount", 0)
        description = (repo.get("description") or "No description")[:100]
        forks = repo.get("forks_count") or repo.get("forkCount", 0)
        lang = repo.get("language") or (repo.get("primaryLanguage") or {}).get("name", "")
        url = repo.get("html_url") or repo.get("url") or f"https://github.com/{name}"

        rank = medal.get(i, f"`#{i}`")
        lang_badge = f" \u2022 `{lang}`" if lang else ""

        embed.add_field(
            name=f"{rank} [{name}]({url})",
            value=f"\u2B50 `{stars:,}` \u2022 \U0001f500 `{forks:,}`{lang_badge}\n{description}",
            inline=False,
        )

    footer = f"Top {min(len(repos), 10)} repos \u2022 Data from GitHub"
    if is_stale:
        footer += " \u2022 \u26a0\ufe0f Stale data (rate limited)"
    embed.set_footer(text=footer)
    return embed


def repo_stats_embed(repo: dict, growth: dict | None = None) -> discord.Embed:
    name = repo.get("nameWithOwner", repo.get("full_name", "unknown"))
    description = repo.get("description", "No description")
    stars = repo.get("stargazerCount", repo.get("stargazers_count", 0))
    forks = repo.get("forkCount", repo.get("forks_count", 0))
    open_issues = repo.get("openIssues", {}).get("totalCount", 0) if isinstance(repo.get("openIssues"), dict) else repo.get("open_issues_count", 0)
    watchers = repo.get("watchers", {}).get("totalCount", 0) if isinstance(repo.get("watchers"), dict) else 0
    language = repo.get("primaryLanguage", {}).get("name", "") if isinstance(repo.get("primaryLanguage"), dict) else repo.get("language", "")
    url = repo.get("url", repo.get("html_url", ""))

    embed = discord.Embed(
        title=name,
        url=url,
        description=description[:2048] if description else None,
        color=GITHUB_BLUE,
    )

    embed.add_field(name="Stars", value=f"{stars:,}", inline=True)
    embed.add_field(name="Forks", value=f"{forks:,}", inline=True)
    embed.add_field(name="Open Issues", value=f"{open_issues:,}", inline=True)

    if language:
        embed.add_field(name="Language", value=language, inline=True)
    if watchers:
        embed.add_field(name="Watchers", value=f"{watchers:,}", inline=True)

    if growth:
        growth_text = (
            f"**1d:** {growth['growth_1d']:+,} | "
            f"**7d:** {growth['growth_7d']:+,} ({growth['rate_7d']:+.1f}%) | "
            f"**30d:** {growth['growth_30d']:+,} ({growth['rate_30d']:+.1f}%)"
        )
        embed.add_field(name="Growth", value=growth_text, inline=False)

        velocity_icon = {"accelerating": "^", "decelerating": "v", "steady": "="}
        icon = velocity_icon.get(growth["velocity_label"], "=")
        embed.add_field(
            name="Velocity",
            value=f"{growth['velocity']}x ({growth['velocity_label']}) {icon} | Avg {growth['daily_avg_7d']}/day",
            inline=False,
        )

    return embed


def growth_embed(repo_name: str, growth: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"Growth: {repo_name}",
        color=GITHUB_GREEN,
    )

    embed.add_field(name="Current Stars", value=f"{growth['current_stars']:,}", inline=True)
    embed.add_field(name="Daily Avg (7d)", value=f"{growth['daily_avg_7d']}/day", inline=True)
    embed.add_field(
        name="Velocity",
        value=f"{growth['velocity']}x ({growth['velocity_label']})",
        inline=True,
    )
    embed.add_field(name="1 Day", value=f"{growth['growth_1d']:+,}", inline=True)
    embed.add_field(name="7 Days", value=f"{growth['growth_7d']:+,} ({growth['rate_7d']:+.1f}%)", inline=True)
    embed.add_field(name="30 Days", value=f"{growth['growth_30d']:+,} ({growth['rate_30d']:+.1f}%)", inline=True)

    return embed


def health_embed(repo_name: str, health: dict) -> discord.Embed:
    overall = health["overall"]
    if overall >= 80:
        color = GITHUB_GREEN
    elif overall >= 50:
        color = GITHUB_ORANGE
    else:
        color = BREAKOUT_RED

    embed = discord.Embed(
        title=f"Health Report: {repo_name}",
        description=f"**Overall: {overall}/100**",
        color=color,
    )

    bar_labels = {
        "issue_response": "Issue Response",
        "issue_close_ratio": "Issue Close Ratio",
        "commit_frequency": "Commit Frequency",
        "pr_merge_time": "PR Merge Time",
        "release_cadence": "Release Cadence",
        "contributors": "Contributors",
    }

    for key, label in bar_labels.items():
        score = health["scores"].get(key, 0)
        detail = health["details"].get(key, "")
        filled = round(score / 10)
        bar = "\u2588" * filled + "\u2591" * (10 - filled)
        embed.add_field(
            name=f"{label}",
            value=f"`{bar}` {detail}",
            inline=False,
        )

    return embed


def compare_embed(repos: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="Repo Comparison",
        color=GITHUB_PURPLE,
    )

    for repo in repos:
        name = repo.get("nameWithOwner", repo.get("full_name", "unknown"))
        stars = repo.get("stargazerCount", repo.get("stargazers_count", 0))
        forks = repo.get("forkCount", repo.get("forks_count", 0))
        open_issues = repo.get("openIssues", {}).get("totalCount", 0) if isinstance(repo.get("openIssues"), dict) else 0
        lang = repo.get("primaryLanguage", {}).get("name", "") if isinstance(repo.get("primaryLanguage"), dict) else ""

        embed.add_field(
            name=name,
            value=(
                f"Stars: **{stars:,}** | Forks: **{forks:,}**\n"
                f"Issues: {open_issues:,}{f' | {lang}' if lang else ''}"
            ),
            inline=False,
        )

    embed.set_footer(text=f"Comparing {len(repos)} repositories")
    return embed


def breakout_alert_embed(repo_name: str, stars: int, breakout: dict) -> discord.Embed:
    embed = discord.Embed(
        title="BREAKOUT DETECTED",
        color=BREAKOUT_RED,
    )

    embed.add_field(name="Repository", value=repo_name, inline=False)
    embed.add_field(name="Total Stars", value=f"{stars:,}", inline=True)
    embed.add_field(
        name="Today's Gain",
        value=f"+{breakout['today_gain']:,} (normal avg: {breakout['rolling_avg']}/day)",
        inline=False,
    )
    embed.add_field(
        name="Spike",
        value=f"**{breakout['ratio']}x** the usual rate — {breakout['severity']}",
        inline=False,
    )

    return embed


def watchlist_embed(entries: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="Your Watchlist",
        color=GITHUB_DARK,
    )

    if not entries:
        embed.description = "Your watchlist is empty. Use `/watch add <owner/repo>` to start tracking."
        return embed

    for entry in entries:
        threshold = entry.get("alert_threshold", 3.0)
        notify_spike = entry.get("notify_on_spike", True)
        notify_release = entry.get("notify_on_release", True)
        flags = []
        if notify_spike:
            flags.append(f"spike ({threshold}x)")
        if notify_release:
            flags.append("releases")

        embed.add_field(
            name=entry["repo_full_name"],
            value=f"Alerts: {', '.join(flags) if flags else 'none'}",
            inline=False,
        )

    embed.set_footer(text=f"{len(entries)} repo(s) tracked")
    return embed


def search_results_embed(results: list[dict], query: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"Search: {query[:100]}",
        color=GITHUB_BLUE,
    )

    if not results:
        embed.description = "No matching repositories found."
        return embed

    for i, result in enumerate(results[:10], 1):
        name = result["repo_name"]
        similarity = result.get("similarity", 0)
        meta = result.get("metadata", {})
        stars = meta.get("stars", 0)
        lang = meta.get("language", "")
        doc = (result.get("document") or "")[:80]

        embed.add_field(
            name=f"{i}. {name} ({similarity:.0%} match)",
            value=f"**{stars:,}** stars{f' | {lang}' if lang else ''}\n{doc}",
            inline=False,
        )

    embed.set_footer(text=f"Top {min(len(results), 10)} semantic matches")
    return embed


def digest_embed(trending: list[dict], language: str = "", period: str = "daily") -> discord.Embed:
    embed = discord.Embed(
        title=f"{period.capitalize()} GitHub Digest",
        description=f"Top trending repos{f' in {language}' if language else ''}",
        color=GITHUB_GREEN,
    )

    for i, repo in enumerate(trending[:5], 1):
        name = repo.get("full_name") or repo.get("nameWithOwner", "unknown")
        stars = repo.get("stargazers_count") or repo.get("stargazerCount", 0)
        desc = (repo.get("description") or "")[:80]
        embed.add_field(
            name=f"{i}. {name} ({stars:,} stars)",
            value=desc or "No description",
            inline=False,
        )

    return embed
