import hashlib
import json
import logging
import re
import urllib.parse
from typing import Any

import httpx  # type: ignore[reportMissingImports]
import redis  # type: ignore[reportMissingImports]

from app.config import settings

logger = logging.getLogger("github_client")

RESERVED_GITHUB_NAMES = {
    "about",
    "collections",
    "customer-stories",
    "enterprise",
    "events",
    "features",
    "login",
    "notifications",
    "organizations",
    "pricing",
    "search",
    "security",
    "settings",
    "signup",
    "sponsors",
    "topics",
    "trending",
}

OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class GitHubError(Exception):
    """Base exception for GitHub API interactions."""


class GitHubRepoNotFoundError(GitHubError):
    """Repository not found or is private/unavailable."""


class GitHubRateLimitError(GitHubError):
    """GitHub API rate limit exceeded."""


class GitHubTransientError(GitHubError):
    """Temporary GitHub API failure or network error."""


def normalize_github_repository_url(value: str) -> str:
    """
    Validates and normalizes a public GitHub repository URL into canonical format:
    https://github.com/<owner>/<repo>

    Rejects:
    - Non-https schemes
    - Embedded credentials (user:pass)
    - Custom ports
    - Non-github hosts
    - Encoded path characters / directory traversal tricks
    - Extra repository path segments (/tree, /blob, /issues, etc.)
    - Incomplete URLs (e.g. user profile without repository)
    """
    if not value or not isinstance(value, str):
        raise ValueError("URL value must be a non-empty string.")

    cleaned = value.strip()
    parsed = urllib.parse.urlsplit(cleaned)

    # 1. Scheme check
    if parsed.scheme.lower() != "https":
        raise ValueError("Only canonical https:// URLs are accepted.")

    # 2. Credential rejection
    if parsed.username or parsed.password:
        raise ValueError("Embedded credentials in repository URLs are rejected.")

    # 3. Custom port rejection
    if parsed.port is not None:
        raise ValueError("Custom ports in repository URLs are rejected.")

    # 4. Hostname check
    host = (parsed.hostname or "").lower()
    if host not in {"github.com", "www.github.com"}:
        raise ValueError(f"Invalid host '{host}'. Only public github.com repositories are allowed.")

    # 5. Query / Fragment rejection
    if parsed.query or parsed.fragment:
        raise ValueError("Repository URLs must not contain query parameters or fragments.")

    # 6. Encoded character / path traversal rejection
    raw_path = parsed.path
    if "%" in raw_path or "\\" in raw_path:
        raise ValueError("Encoded characters and escape sequences are rejected.")

    # 7. Path segments check (must be exactly /owner/repo)
    segments = [s for s in raw_path.strip("/").split("/") if s]
    if len(segments) != 2:
        raise ValueError(
            f"Invalid repository path: expected exactly 2 segments (owner/repo), got {len(segments)}."
        )

    owner, repo = segments[0], segments[1]

    # Normalize .git suffix
    repo = repo.removesuffix(".git")

    # 8. Reserved owner check
    if owner.lower() in RESERVED_GITHUB_NAMES:
        raise ValueError(f"'{owner}' is a reserved GitHub system endpoint, not a user repository.")

    # 9. Format validation for owner and repo
    if not OWNER_PATTERN.match(owner):
        raise ValueError(f"Invalid GitHub account name format: '{owner}'.")

    if not REPO_PATTERN.match(repo) or repo in {".", ".."}:
        raise ValueError(f"Invalid repository name format: '{repo}'.")

    return f"https://github.com/{owner}/{repo}"


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        redis_client: redis.Redis | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.token = token or settings.github_token
        self.base_url = (base_url or settings.github_api_base).rstrip("/")
        self.timeout = timeout or settings.github_api_timeout_seconds
        self.transport = transport

        if redis_client is not None:
            self.redis = redis_client
        else:
            try:
                self.redis = redis.from_url(settings.redis_url, decode_responses=True)
                self.redis.ping()
            except (redis.RedisError, OSError):
                self.redis = None

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Resume-Project-Review-Platform/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _cache_get(self, key: str) -> dict[str, Any] | list[Any] | None:
        if not self.redis:
            return None
        try:
            cached = self.redis.get(key)
            if cached:
                return json.loads(cached)
        except (redis.RedisError, json.JSONDecodeError, TypeError) as e:
            logger.warning("Redis cache get error for key %s: %s", key, e)
        return None

    def _cache_set(
        self, key: str, value: Any, ttl: int = settings.github_cache_ttl_seconds
    ) -> None:
        if not self.redis:
            return
        try:
            self.redis.setex(key, ttl, json.dumps(value))
        except (redis.RedisError, TypeError) as e:
            logger.warning("Redis cache set error for key %s: %s", key, e)

    def get_repository_metadata(self, owner: str, repo: str) -> dict[str, Any]:
        """
        Retrieves public repository metadata (url, branch, visibility, forks, licenses, description).
        Never accesses source code or commit logs.
        """
        # Deterministic test adapter mode (only active when explicitly configured)
        if settings.allow_test_adapters:
            if owner == "synthetic-candidate" and repo == "portfolio-app":
                return {
                    "url": "https://github.com/synthetic-candidate/portfolio-app",
                    "owner": "synthetic-candidate",
                    "name": "portfolio-app",
                    "default_branch": "main",
                    "visibility": "public",
                    "is_fork": False,
                    "parent_url": None,
                    "source_url": None,
                    "license": "MIT",
                    "description": "Synthetic portfolio web application",
                    "stars_count": 24,
                    "forks_count": 2,
                }
            if owner == "synthetic-candidate" and repo == "inaccessible-repo":
                raise GitHubRepoNotFoundError("Repository synthetic-candidate/inaccessible-repo not found or is private.")

        cache_key = f"gh:repo:{owner.lower()}:{repo.lower()}"
        cached = self._cache_get(cache_key)
        if isinstance(cached, dict):
            return cached

        url = f"{self.base_url}/repos/{owner}/{repo}"
        headers = self._get_headers()

        retries = 2
        for attempt in range(retries):
            try:
                with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                    response = client.get(url, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    # Ensure public visibility
                    is_private = data.get("private", False)
                    visibility = data.get("visibility", "public")
                    if is_private or visibility != "public":
                        raise GitHubRepoNotFoundError(
                            f"Repository {owner}/{repo} is private or inaccessible."
                        )

                    metadata = {
                        "url": data.get("html_url") or f"https://github.com/{owner}/{repo}",
                        "owner": data.get("owner", {}).get("login", owner),
                        "name": data.get("name", repo),
                        "default_branch": data.get("default_branch", "main"),
                        "visibility": visibility,
                        "is_fork": bool(data.get("fork", False)),
                        "parent_url": data.get("parent", {}).get("html_url")
                        if data.get("fork")
                        else None,
                        "source_url": data.get("source", {}).get("html_url")
                        if data.get("fork")
                        else None,
                        "license": data.get("license", {}).get("spdx_id")
                        if data.get("license")
                        else None,
                        "description": data.get("description"),
                        "stars_count": data.get("stargazers_count", 0),
                        "forks_count": data.get("forks_count", 0),
                    }
                    self._cache_set(cache_key, metadata)
                    return metadata

                if response.status_code == 404:
                    raise GitHubRepoNotFoundError(
                        f"Repository {owner}/{repo} not found or is private."
                    )

                if response.status_code in {403, 429}:
                    remaining = response.headers.get("x-ratelimit-remaining")
                    if remaining == "0" or response.status_code == 429:
                        raise GitHubRateLimitError("GitHub API rate limit exceeded.")
                    raise GitHubRepoNotFoundError(
                        f"Access forbidden for repository {owner}/{repo}."
                    )

                if response.status_code >= 500:
                    if attempt < retries - 1:
                        continue
                    raise GitHubTransientError(f"GitHub server error: HTTP {response.status_code}")

                raise GitHubError(f"Unexpected GitHub API response: HTTP {response.status_code}")

            except httpx.TimeoutException as e:
                if attempt < retries - 1:
                    continue
                raise GitHubTransientError(f"GitHub API request timed out: {e}") from e
            except httpx.RequestError as e:
                if attempt < retries - 1:
                    continue
                raise GitHubTransientError(f"GitHub API network connection failed: {e}") from e

        raise GitHubTransientError("Failed to retrieve repository metadata after retries.")

    def search_repositories(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Searches public repositories using query terms. Capped at requested limit.
        """
        if not query.strip():
            return []

        # Deterministic test adapter mode
        if settings.allow_test_adapters:
            if any(term in query.lower() for term in ["portfolio", "app"]):
                return [{
                    "owner": "synthetic-candidate",
                    "name": "portfolio-app",
                    "url": "https://github.com/synthetic-candidate/portfolio-app",
                    "description": "Synthetic portfolio web application",
                    "stars_count": 24,
                }]
            return []

        query_hash = hashlib.sha256(f"{query}:{limit}".encode()).hexdigest()[:16]
        cache_key = f"gh:search:{query_hash}"
        cached = self._cache_get(cache_key)
        if isinstance(cached, list):
            return cached

        url = f"{self.base_url}/search/repositories"
        params = {"q": f"{query} is:public", "per_page": min(limit, 10), "sort": "stars"}
        headers = self._get_headers()

        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.get(url, params=params, headers=headers)

            if response.status_code == 200:
                items = response.json().get("items", [])
                results: list[dict[str, Any]] = []
                for item in items[:limit]:
                    results.append(
                        {
                            "url": item.get("html_url"),
                            "owner": item.get("owner", {}).get("login"),
                            "name": item.get("name"),
                            "default_branch": item.get("default_branch", "main"),
                            "visibility": item.get("visibility", "public"),
                            "is_fork": bool(item.get("fork", False)),
                            "parent_url": None,
                            "source_url": None,
                            "license": item.get("license", {}).get("spdx_id")
                            if item.get("license")
                            else None,
                            "description": item.get("description"),
                            "stars_count": item.get("stargazers_count", 0),
                            "forks_count": item.get("forks_count", 0),
                        }
                    )
                self._cache_set(cache_key, results)
                return results

            if response.status_code in {403, 429}:
                remaining = response.headers.get("x-ratelimit-remaining")
                if remaining == "0" or response.status_code == 429:
                    raise GitHubRateLimitError("GitHub search API rate limit exceeded.")
                raise GitHubError(f"GitHub search forbidden: HTTP {response.status_code}")

            if response.status_code >= 500:
                raise GitHubTransientError(
                    f"GitHub search server error: HTTP {response.status_code}"
                )

            return []

        except httpx.TimeoutException as e:
            raise GitHubTransientError(f"GitHub search request timed out: {e}") from e
        except httpx.RequestError as e:
            raise GitHubTransientError(f"GitHub search network connection failed: {e}") from e
