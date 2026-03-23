"""GitHub API client wrapping REST v3 and GraphQL v4 via httpx."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from config import settings as config
from utils.logger import get_logger

logger = get_logger(__name__)

REST_BASE = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"


class GitHubClient:
    def __init__(self):
        self._token = config.GITHUB_TOKEN
        self._client: httpx.AsyncClient | None = None
        self._rate_remaining: int = 5000
        self._rate_reset: float = 0
        self._search_remaining: int = 30
        self._search_reset: float = 0
        self._etag_cache: dict[str, tuple[str, dict[str, Any]]] = {}  # url -> (etag, data)

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    def _update_rate_limits(self, response: httpx.Response, is_search: bool = False):
        if is_search:
            self._search_remaining = int(response.headers.get("X-RateLimit-Remaining", self._search_remaining))
            self._search_reset = float(response.headers.get("X-RateLimit-Reset", self._search_reset))
        else:
            self._rate_remaining = int(response.headers.get("X-RateLimit-Remaining", self._rate_remaining))
            self._rate_reset = float(response.headers.get("X-RateLimit-Reset", self._rate_reset))

    async def _wait_for_rate_limit(self, is_search: bool = False):
        remaining = self._search_remaining if is_search else self._rate_remaining
        reset_at = self._search_reset if is_search else self._rate_reset

        if remaining <= 5:
            wait = max(reset_at - time.time(), 1)
            logger.warning(f"Rate limit near exhaustion, waiting {wait:.0f}s")
            await asyncio.sleep(min(wait, 60))

    async def rest_get(self, endpoint: str, params: dict[str, Any] | None = None, is_search: bool = False) -> dict[str, Any] | None:
        await self._wait_for_rate_limit(is_search)
        client = await self._get_client()

        url = f"{REST_BASE}{endpoint}"
        req_headers = {}

        # ETag conditional request
        cache_key = url + (json.dumps(params, sort_keys=True) if params else "")
        if cache_key in self._etag_cache:
            etag, _ = self._etag_cache[cache_key]
            req_headers["If-None-Match"] = etag

        response = await client.get(url, params=params, headers=req_headers)
        self._update_rate_limits(response, is_search)

        if response.status_code == 304:
            _, cached_data = self._etag_cache[cache_key]
            return cached_data

        if response.status_code == 200:
            data = response.json()
            if "ETag" in response.headers:
                self._etag_cache[cache_key] = (response.headers["ETag"], data)
            return data

        if response.status_code == 403 and "rate limit" in response.text.lower():
            logger.error("GitHub rate limit exceeded")
            return None

        logger.error(f"GitHub REST error {response.status_code}: {response.text[:200]}")
        return None

    async def graphql(self, query: str, variables: dict[str, str] | None = None) -> dict[str, Any] | None:
        await self._wait_for_rate_limit()
        client = await self._get_client()

        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = await client.post(GRAPHQL_URL, json=payload)
        self._update_rate_limits(response)

        if response.status_code == 200:
            result = response.json()
            if "errors" in result:
                logger.error(f"GraphQL errors: {result['errors']}")
                return None
            return result.get("data")

        logger.error(f"GitHub GraphQL error {response.status_code}: {response.text[:200]}")
        return None

    # --- High-level methods ---

    async def get_repo(self, owner: str, name: str) -> dict[str, Any] | None:
        return await self.rest_get(f"/repos/{owner}/{name}")

    async def search_trending(
        self,
        language: str = "",
        window_days: int = 7,
        min_stars: int = 50,
        per_page: int = 20,
    ) -> list[dict]:
        since = (datetime.now(UTC) - timedelta(days=window_days)).strftime("%Y-%m-%d")
        q = f"created:>{since} stars:>{min_stars}"
        if language:
            q += f" language:{language}"

        params = {"q": q, "sort": "stars", "order": "desc", "per_page": per_page}
        data = await self.rest_get("/search/repositories", params=params, is_search=True)
        if data and isinstance(data, dict) and "items" in data:
            return data["items"]  # type: ignore[no-any-return]
        return []

    async def batch_fetch_repos(self, repo_names: list[str]) -> list[dict]:
        if not repo_names:
            return []

        fragments = []
        for i, name in enumerate(repo_names[:50]):
            owner, repo = name.split("/", 1)
            fragments.append(
                f'repo{i}: repository(owner: "{owner}", name: "{repo}") {{'
                f"  nameWithOwner description stargazerCount forkCount"
                f"  openIssues: issues(states: OPEN) {{ totalCount }}"
                f"  watchers {{ totalCount }}"
                f"  primaryLanguage {{ name }}"
                f"  updatedAt"
                f"}}"
            )

        query = "{\n" + "\n".join(fragments) + "\n}"
        data = await self.graphql(query)
        if not data:
            return []

        repos = []
        for key in sorted(data.keys()):
            if data[key]:
                repos.append(data[key])
        return repos

    async def get_repo_stats_graphql(self, owner: str, name: str) -> dict | None:
        query = """
        query($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            nameWithOwner
            description
            stargazerCount
            forkCount
            openIssues: issues(states: OPEN) { totalCount }
            closedIssues: issues(states: CLOSED) { totalCount }
            watchers { totalCount }
            primaryLanguage { name }
            releases(first: 5, orderBy: {field: CREATED_AT, direction: DESC}) {
              nodes { tagName publishedAt }
            }
            defaultBranchRef {
              target {
                ... on Commit {
                  history(first: 1) { totalCount }
                }
              }
            }
            mentionableUsers(first: 1) { totalCount }
            updatedAt
            createdAt
            url
          }
        }
        """
        data = await self.graphql(query, {"owner": owner, "name": name})
        if data and "repository" in data:
            return data["repository"]
        return None

    async def get_repo_health_data(self, owner: str, name: str) -> dict | None:
        query = """
        query($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            nameWithOwner

            recentIssues: issues(first: 50, orderBy: {field: CREATED_AT, direction: DESC}, states: [OPEN, CLOSED]) {
              nodes {
                createdAt
                closedAt
                comments(first: 1) {
                  nodes { createdAt author { login } }
                }
              }
            }

            closedIssues90d: issues(states: CLOSED, first: 1) { totalCount }
            totalIssues90d: issues(first: 1) { totalCount }

            pullRequests(first: 30, orderBy: {field: CREATED_AT, direction: DESC}, states: MERGED) {
              nodes { createdAt mergedAt }
            }

            releases(first: 10, orderBy: {field: CREATED_AT, direction: DESC}) {
              nodes { publishedAt }
            }

            defaultBranchRef {
              target {
                ... on Commit {
                  history(first: 30) {
                    nodes { committedDate }
                  }
                }
              }
            }

            mentionableUsers(first: 1) { totalCount }
          }
        }
        """
        data = await self.graphql(query, {"owner": owner, "name": name})
        if data and "repository" in data:
            return data["repository"]
        return None

    async def get_stargazers_with_dates(self, owner: str, name: str, per_page: int = 100, pages: int = 5) -> list[dict[str, Any]]:
        """Fetch stargazer timestamps using the star+json accept header."""
        client = await self._get_client()
        stargazers: list[dict[str, Any]] = []

        for page in range(1, pages + 1):
            await self._wait_for_rate_limit()
            response = await client.get(
                f"{REST_BASE}/repos/{owner}/{name}/stargazers",
                params={"per_page": per_page, "page": page},
                headers={"Accept": "application/vnd.github.v3.star+json"},
            )
            self._update_rate_limits(response)

            if response.status_code != 200:
                break

            data = response.json()
            if not data:
                break

            stargazers.extend(data)

        return stargazers

    async def get_readme(self, owner: str, name: str) -> str | None:
        data = await self.rest_get(f"/repos/{owner}/{name}/readme")
        if data and "content" in data:
            import base64
            try:
                return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            except Exception:
                return None
        return None

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Module-level singleton
github_client = GitHubClient()
