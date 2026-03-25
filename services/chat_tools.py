"""Tool definitions for LLM function calling — wraps existing services."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_core.tools import tool

from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Gmail tools
# ---------------------------------------------------------------------------


@tool
async def list_emails(count: int = 10, query: str = "is:inbox") -> str:
    """List recent emails from the user's Gmail inbox.

    Args:
        count: Number of emails to fetch (1-20, default 10).
        query: Gmail search query (e.g. 'is:unread', 'from:boss@company.com').
    """
    return json.dumps({"error": "no user context"})


@tool
async def search_emails(query: str) -> str:
    """Search the user's Gmail with a query string.

    Args:
        query: Gmail search query (e.g. 'from:alice subject:invoice', 'is:unread newer_than:1d').
    """
    return json.dumps({"error": "no user context"})


# ---------------------------------------------------------------------------
# Calendar tools
# ---------------------------------------------------------------------------


@tool
async def list_meetings(days: int = 7, count: int = 10) -> str:
    """List upcoming calendar events.

    Args:
        days: How many days ahead to look (1-30, default 7).
        count: Max number of events to show (1-20, default 10).
    """
    return json.dumps({"error": "no user context"})


@tool
async def create_event(
    title: str,
    start: str,
    end: str,
    timezone: str = "UTC",
    attendees: str = "",
    location: str = "",
    description: str = "",
) -> str:
    """Create a new calendar event.

    Args:
        title: Event title.
        start: Start time in ISO format (e.g. '2026-03-25T10:00:00').
        end: End time in ISO format (e.g. '2026-03-25T11:00:00').
        timezone: Timezone (default UTC, e.g. 'Africa/Accra', 'America/New_York').
        attendees: Comma-separated email addresses to invite (optional).
        location: Event location (optional).
        description: Event description (optional).
    """
    return json.dumps({"error": "no user context"})


# ---------------------------------------------------------------------------
# GitHub tools
# ---------------------------------------------------------------------------


@tool
async def github_trending(language: str = "", window: str = "weekly") -> str:
    """Show trending GitHub repositories.

    Args:
        language: Programming language filter (e.g. 'python', 'rust', 'go'). Empty for all.
        window: Time window — 'daily', 'weekly', or 'monthly'.
    """
    from services.cache_service import cache_service
    from services.github_service import github_client

    window_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(window, 7)
    cache_key = cache_service.trending_key(language.lower(), window)
    cached, _ = await cache_service.get_or_fallback(cache_key)

    if cached:
        return _format_trending(cached)

    repos = await github_client.search_trending(
        language=language.lower(), window_days=window_days
    )
    if not repos:
        return "No trending repos found for those filters."

    await cache_service.set(cache_key, repos, "trending")
    return _format_trending(repos)


@tool
async def github_stats(repo: str) -> str:
    """Show stats for a GitHub repository.

    Args:
        repo: Repository in owner/name format (e.g. 'fastapi/fastapi').
    """
    from services.analytics_service import growth_calculator
    from services.cache_service import cache_service
    from services.database_service import database_service
    from services.github_service import github_client

    if "/" not in repo:
        return "Please use owner/repo format (e.g. 'fastapi/fastapi')."

    owner, name = repo.split("/", 1)
    cache_key = cache_service.repo_meta_key(repo)
    cached = await cache_service.get(cache_key)

    data = cached
    if not data:
        data = await github_client.get_repo_stats_graphql(owner, name)
        if not data:
            return f"Could not find repo `{repo}`."
        await cache_service.set(cache_key, data, "repo_meta")

    growth = None
    snapshots = await asyncio.to_thread(database_service.get_snapshots, repo, 30)
    if snapshots:
        growth = growth_calculator.compute(snapshots)

    return _format_stats(data, growth)


@tool
async def github_growth(repo: str, days: int = 30) -> str:
    """Show growth analytics for a GitHub repository.

    Args:
        repo: Repository in owner/name format.
        days: Number of days to analyze (default 30).
    """
    from services.analytics_service import growth_calculator
    from services.database_service import database_service

    if "/" not in repo:
        return "Please use owner/repo format."

    snapshots = await asyncio.to_thread(database_service.get_snapshots, repo, days)
    if len(snapshots) < 2:
        return f"Not enough data for `{repo}`. It needs to be on a watchlist first. Ask the user to add it."

    growth_data = growth_calculator.compute(snapshots)
    return _format_growth(repo, growth_data)


@tool
async def github_health(repo: str) -> str:
    """Show health report for a GitHub repository.

    Args:
        repo: Repository in owner/name format.
    """
    from services.analytics_service import health_scorer
    from services.cache_service import cache_service
    from services.github_service import github_client

    if "/" not in repo:
        return "Please use owner/repo format."

    owner, name = repo.split("/", 1)
    cache_key = cache_service.repo_health_key(repo)
    cached = await cache_service.get(cache_key)

    if cached:
        return _format_health(repo, cached)

    health_data = await github_client.get_repo_health_data(owner, name)
    if not health_data:
        return f"Could not fetch health data for `{repo}`."

    result = health_scorer.compute(health_data)
    await cache_service.set(cache_key, result, "repo_health")
    return _format_health(repo, result)


@tool
async def github_compare(repos: str) -> str:
    """Compare multiple GitHub repos side-by-side.

    Args:
        repos: Space-separated repos in owner/name format (e.g. 'fastapi/fastapi django/django'). 2-5 repos.
    """
    from services.cache_service import cache_service
    from services.github_service import github_client

    repo_list = [r.strip() for r in repos.split() if "/" in r]
    if len(repo_list) < 2:
        return "Please provide at least 2 repos."
    if len(repo_list) > 5:
        return "Maximum 5 repos for comparison."

    cache_key = cache_service.compare_key(repo_list)
    cached = await cache_service.get(cache_key)

    if cached:
        return _format_compare(cached)

    data = await github_client.batch_fetch_repos(repo_list)
    if not data:
        return "Could not fetch data for those repos."

    await cache_service.set(cache_key, data, "compare")
    return _format_compare(data)


@tool
async def github_search(query: str, language: str = "") -> str:
    """Semantic AI-powered search for GitHub repos in the indexed database.

    Args:
        query: Natural language search query (e.g. 'real-time data streaming framework').
        language: Filter by programming language (optional).
    """
    from services.ai_service import ai_service

    if not ai_service.available:
        return "AI search is not available. The embedding model may not be loaded."

    results = await ai_service.search(
        query=query,
        n_results=10,
        language=language.lower() if language else None,
    )

    if not results:
        return "No results found."

    lines = []
    for r in results[:5]:
        meta = r.get("metadata", {})
        sim = r.get("similarity", 0)
        name = r["repo_name"]
        url = f"https://github.com/{name}"
        lines.append(
            f"- [{name}]({url}) (similarity: {sim:.2f}, "
            f"stars: {meta.get('stars', '?')}, lang: {meta.get('language', '?')})"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Watchlist tools
# ---------------------------------------------------------------------------


@tool
async def watchlist_add(repo: str) -> str:
    """Add a repo to the user's GitHub watchlist for growth tracking.

    Args:
        repo: Repository in owner/name format.
    """
    return json.dumps({"error": "no user context"})


@tool
async def watchlist_remove(repo: str) -> str:
    """Remove a repo from the user's GitHub watchlist.

    Args:
        repo: Repository in owner/name format.
    """
    return json.dumps({"error": "no user context"})


@tool
async def watchlist_list() -> str:
    """Show the user's GitHub repo watchlist."""
    return json.dumps({"error": "no user context"})


# ---------------------------------------------------------------------------
# Memory tools
# ---------------------------------------------------------------------------


@tool
async def save_memory(content: str, category: str = "fact") -> str:
    """Save a fact, preference, or note about the user for future conversations.
    Only call this when the user shares something worth remembering long-term
    (e.g. their role, preferences, projects they work on). Do NOT save trivial
    or transient information.

    Args:
        content: The fact or preference to remember (e.g. 'Works with FastAPI and deploys on Hetzner').
        category: One of 'fact', 'preference', or 'note'.
    """
    return json.dumps({"error": "no user context"})


@tool
async def forget_memory(content: str) -> str:
    """Forget/delete a previously saved memory about the user. Use when the user
    asks you to forget something or corrects outdated information.

    Args:
        content: A keyword or phrase to match against saved memories (e.g. 'AWS' to remove a memory about AWS).
    """
    return json.dumps({"error": "no user context"})


# ---------------------------------------------------------------------------
# All tools list
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    list_emails,
    search_emails,
    list_meetings,
    create_event,
    github_trending,
    github_stats,
    github_growth,
    github_health,
    github_compare,
    github_search,
    watchlist_add,
    watchlist_remove,
    watchlist_list,
    save_memory,
    forget_memory,
]

# Tools that need user_id context to execute
USER_CONTEXT_TOOLS = {
    "list_emails",
    "search_emails",
    "list_meetings",
    "create_event",
    "watchlist_add",
    "watchlist_remove",
    "watchlist_list",
    "save_memory",
    "forget_memory",
}


# ---------------------------------------------------------------------------
# Execution with user context
# ---------------------------------------------------------------------------


async def execute_tool(
    tool_name: str, tool_args: dict[str, Any], user_id: int | None = None
) -> str:
    """Execute a tool by name, injecting user context where needed."""
    try:
        if tool_name in USER_CONTEXT_TOOLS and user_id is None:
            return "This action requires authentication. Please authenticate with `/auth` first."

        # user_id is guaranteed non-None for USER_CONTEXT_TOOLS after the guard above
        uid: int = user_id or 0

        if tool_name == "list_emails":
            return await _exec_list_emails(uid, **tool_args)
        elif tool_name == "search_emails":
            return await _exec_search_emails(uid, **tool_args)
        elif tool_name == "list_meetings":
            return await _exec_list_meetings(uid, **tool_args)
        elif tool_name == "create_event":
            return await _exec_create_event(uid, **tool_args)
        elif tool_name == "watchlist_add":
            return await _exec_watchlist_add(uid, **tool_args)
        elif tool_name == "watchlist_remove":
            return await _exec_watchlist_remove(uid, **tool_args)
        elif tool_name == "watchlist_list":
            return await _exec_watchlist_list(uid)
        elif tool_name == "save_memory":
            return await _exec_save_memory(uid, **tool_args)
        elif tool_name == "forget_memory":
            return await _exec_forget_memory(uid, **tool_args)
        else:
            # Non-user-context tools can be called directly
            tool_map = {t.name: t for t in ALL_TOOLS}
            if tool_name in tool_map:
                return await tool_map[tool_name].ainvoke(tool_args)
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        logger.error(f"Tool execution error ({tool_name}): {e}")
        return f"Error executing {tool_name}: {e}"


# ---------------------------------------------------------------------------
# User-context tool implementations
# ---------------------------------------------------------------------------


async def _exec_list_emails(
    user_id: int, count: int = 10, query: str = "is:inbox"
) -> str:
    from services import gmail_service

    messages = await gmail_service.list_messages(
        user_id, max_results=min(count, 20), query=query
    )
    if not messages:
        return "No emails found."
    lines = []
    for m in messages[:10]:
        link = m.get("link", "")
        subject = f"[{m['subject']}]({link})" if link else m["subject"]
        lines.append(
            f"- {subject} from {m['from_name']} ({m['from_email']})\n  {m['snippet'][:100]}"
        )
    return "\n".join(lines)


async def _exec_search_emails(user_id: int, query: str = "") -> str:
    from services import gmail_service

    messages = await gmail_service.list_messages(user_id, max_results=10, query=query)
    if not messages:
        return f"No emails found for query: {query}"
    lines = []
    for m in messages[:10]:
        link = m.get("link", "")
        subject = f"[{m['subject']}]({link})" if link else m["subject"]
        lines.append(f"- {subject} from {m['from_name']}\n  {m['snippet'][:100]}")
    return "\n".join(lines)


async def _exec_list_meetings(user_id: int, days: int = 7, count: int = 10) -> str:
    from services import calendar_service

    events = await calendar_service.list_upcoming_events(
        user_id, max_results=min(count, 20), days_ahead=min(days, 30)
    )
    if not events:
        return "No upcoming events found."
    lines = []
    for e in events:
        link = e.get("link", "")
        title = f"[{e['summary']}]({link})" if link else e["summary"]
        line = f"- {title} — {e['start']} to {e['end']}"
        if e.get("location"):
            line += f" @ {e['location']}"
        lines.append(line)
    return "\n".join(lines)


async def _exec_create_event(
    user_id: int,
    title: str = "",
    start: str = "",
    end: str = "",
    timezone: str = "UTC",
    attendees: str = "",
    location: str = "",
    description: str = "",
) -> str:
    from services import calendar_service

    if not title or not start or not end:
        return "Missing required fields: title, start, and end are required."

    attendee_list = (
        [e.strip() for e in attendees.split(",") if e.strip()] if attendees else None
    )

    created = await calendar_service.create_event(
        user_id,
        summary=title,
        start_time=start,
        end_time=end,
        timezone=timezone,
        attendees=attendee_list,
        description=description,
        location=location,
    )
    link = created.get("htmlLink", "")
    return f"Event **{title}** created successfully! {link}"


async def _exec_watchlist_add(user_id: int, repo: str = "") -> str:
    from services.database_service import database_service
    from services.github_service import github_client

    if "/" not in repo:
        return "Please use owner/repo format."

    owner, name = repo.split("/", 1)
    check = await github_client.get_repo(owner, name)
    if not check:
        return f"Repo `{repo}` not found on GitHub."

    await asyncio.to_thread(database_service.add_to_watchlist, str(user_id), repo)
    return f"Added `{repo}` to your watchlist."


async def _exec_watchlist_remove(user_id: int, repo: str = "") -> str:
    from services.database_service import database_service

    await asyncio.to_thread(database_service.remove_from_watchlist, str(user_id), repo)
    return f"Removed `{repo}` from your watchlist."


async def _exec_watchlist_list(user_id: int) -> str:
    from services.database_service import database_service

    entries = await asyncio.to_thread(database_service.get_watchlist, str(user_id))
    if not entries:
        return "Your watchlist is empty."
    lines = []
    for e in entries:
        name = e.get("repo_full_name", "?")
        url = f"https://github.com/{name}"
        lines.append(f"- [{name}]({url}) (threshold: {e.get('threshold', '?')}x)")
    return "\n".join(lines)


async def _exec_save_memory(
    user_id: int, content: str = "", category: str = "fact"
) -> str:
    from services.memory_service import memory_service

    if not content:
        return "No content provided to save."
    if category not in ("fact", "preference", "note"):
        category = "fact"
    await asyncio.to_thread(
        memory_service.save_user_memory, str(user_id), content, category
    )
    return f"Saved: {content}"


async def _exec_forget_memory(user_id: int, content: str = "") -> str:
    from services.memory_service import memory_service

    if not content:
        return "No content provided to match against."
    count = await asyncio.to_thread(
        memory_service.delete_user_memory, str(user_id), content
    )
    if count == 0:
        return f"No memories found matching '{content}'."
    return f"Removed {count} memory/memories matching '{content}'."


# ---------------------------------------------------------------------------
# Formatting helpers (text output for LLM consumption)
# ---------------------------------------------------------------------------


def _format_trending(repos: list[dict]) -> str:
    lines = []
    for r in repos[:10]:
        name = r.get("full_name") or r.get("repo", "?")
        stars = r.get("stars") or r.get("stargazers_count", "?")
        desc = (r.get("description") or "")[:80]
        lang = r.get("language", "")
        url = f"https://github.com/{name}"
        lines.append(f"- [{name}]({url}) ⭐ {stars} ({lang}) — {desc}")
    return "\n".join(lines) if lines else "No repos found."


def _format_stats(data: dict, growth: dict | None) -> str:
    name = data.get("full_name", "?")
    url = f"https://github.com/{name}"
    lines = [
        f"[{name}]({url})",
        f"Description: {data.get('description', 'N/A')}",
        f"Stars: {data.get('stars', '?')} | Forks: {data.get('forks', '?')} | Issues: {data.get('open_issues', '?')}",
        f"Language: {data.get('language', '?')}",
    ]
    if growth:
        lines.append(
            f"Growth (30d): stars {growth.get('star_delta', '?'):+}, "
            f"velocity {growth.get('daily_star_velocity', 0):.1f}/day"
        )
    return "\n".join(lines)


def _format_growth(repo: str, data: dict) -> str:
    url = f"https://github.com/{repo}"
    lines = [
        f"[{repo}]({url}) — Growth Analytics",
        f"Star delta: {data.get('star_delta', '?'):+}",
        f"Daily velocity: {data.get('daily_star_velocity', 0):.1f} stars/day",
        f"Fork delta: {data.get('fork_delta', '?'):+}",
    ]
    if data.get("trend"):
        lines.append(f"Trend: {data['trend']}")
    return "\n".join(lines)


def _format_health(repo: str, data: dict) -> str:
    url = f"https://github.com/{repo}"
    lines = [
        f"[{repo}]({url}) — Health Report",
        f"Overall score: {data.get('overall_score', '?')}/100",
    ]
    for category, score in data.get("categories", {}).items():
        lines.append(f"  {category}: {score}/100")
    if data.get("warnings"):
        lines.append("Warnings: " + ", ".join(data["warnings"]))
    return "\n".join(lines)


def _format_compare(data: list[dict]) -> str:
    lines = ["**Repo Comparison**\n"]
    for r in data:
        name = r.get("full_name") or r.get("repo", "?")
        stars = r.get("stars") or r.get("stargazers_count", "?")
        forks = r.get("forks") or r.get("forks_count", "?")
        lang = r.get("language", "?")
        url = f"https://github.com/{name}"
        lines.append(f"- [{name}]({url}): ⭐ {stars} | Forks: {forks} | Lang: {lang}")
    return "\n".join(lines)
