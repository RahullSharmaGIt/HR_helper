import httpx
import pytest

from app.schemas.contracts import ConfidenceCategory, ProjectSuggestion
from app.services.github_client import (
    GitHubClient,
    GitHubRateLimitError,
    GitHubRepoNotFoundError,
    normalize_github_repository_url,
)
from app.services.repository_discovery import discover_repositories

# ---------------------------------------------------------------------------
# URL Normalization & Security Tests
# ---------------------------------------------------------------------------


def test_normalize_valid_repository_url():
    url = "https://github.com/octocat/Hello-World"
    assert normalize_github_repository_url(url) == "https://github.com/octocat/Hello-World"


def test_normalize_git_suffix():
    url = "https://github.com/octocat/Hello-World.git"
    assert normalize_github_repository_url(url) == "https://github.com/octocat/Hello-World"


def test_reject_http_scheme():
    with pytest.raises(ValueError, match="Only canonical https:// URLs"):
        normalize_github_repository_url("http://github.com/octocat/Hello-World")


def test_reject_credentials():
    with pytest.raises(ValueError, match="Embedded credentials"):
        normalize_github_repository_url("https://user:pass@github.com/octocat/Hello-World")


def test_reject_custom_port():
    with pytest.raises(ValueError, match="Custom ports"):
        normalize_github_repository_url("https://github.com:8443/octocat/Hello-World")


def test_reject_arbitrary_host():
    with pytest.raises(ValueError, match="Only public github.com repositories"):
        normalize_github_repository_url("https://gitlab.com/octocat/Hello-World")

    with pytest.raises(ValueError, match="Only public github.com repositories"):
        normalize_github_repository_url("https://github.com.evil.com/octocat/Hello-World")


def test_reject_encoded_path_tricks():
    with pytest.raises(ValueError, match="Encoded characters and escape sequences"):
        normalize_github_repository_url("https://github.com/octocat/%2e%2e/Hello-World")


def test_reject_extra_path_segments():
    with pytest.raises(ValueError, match="expected exactly 2 segments"):
        normalize_github_repository_url("https://github.com/octocat/Hello-World/tree/main")

    with pytest.raises(ValueError, match="expected exactly 2 segments"):
        normalize_github_repository_url("https://github.com/octocat/Hello-World/issues/1")


def test_reject_single_segment_profile():
    with pytest.raises(ValueError, match="expected exactly 2 segments"):
        normalize_github_repository_url("https://github.com/octocat")


def test_reject_reserved_github_endpoints():
    with pytest.raises(ValueError, match="reserved GitHub system endpoint"):
        normalize_github_repository_url("https://github.com/features/actions")


# ---------------------------------------------------------------------------
# GitHub Client & HTTP Mocking Tests
# ---------------------------------------------------------------------------


def test_github_client_get_metadata_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/alice/task-broker"
        return httpx.Response(
            200,
            json={
                "html_url": "https://github.com/alice/task-broker",
                "name": "task-broker",
                "owner": {"login": "alice"},
                "default_branch": "main",
                "visibility": "public",
                "fork": False,
                "license": {"spdx_id": "MIT"},
                "description": "Distributed task queue in Go",
                "stargazers_count": 42,
                "forks_count": 5,
            },
        )

    transport = httpx.MockTransport(handler)
    client = GitHubClient(base_url="https://api.github.com", transport=transport)
    meta = client.get_repository_metadata("alice", "task-broker")

    assert meta["url"] == "https://github.com/alice/task-broker"
    assert meta["owner"] == "alice"
    assert meta["name"] == "task-broker"
    assert meta["license"] == "MIT"
    assert meta["visibility"] == "public"
    assert meta["is_fork"] is False


def test_github_client_repo_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    transport = httpx.MockTransport(handler)
    client = GitHubClient(base_url="https://api.github.com", transport=transport)

    with pytest.raises(GitHubRepoNotFoundError, match="not found or is private"):
        client.get_repository_metadata("alice", "private-repo")


def test_github_client_rate_limiting():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0"},
            json={"message": "API rate limit exceeded"},
        )

    transport = httpx.MockTransport(handler)
    client = GitHubClient(base_url="https://api.github.com", transport=transport)

    with pytest.raises(GitHubRateLimitError, match="rate limit exceeded"):
        client.get_repository_metadata("alice", "task-broker")


def test_github_client_redis_caching():
    class FakeRedis:
        def __init__(self):
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def setex(self, key, ttl, value):
            self.store[key] = value

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "html_url": "https://github.com/alice/cached-repo",
                "name": "cached-repo",
                "owner": {"login": "alice"},
                "visibility": "public",
            },
        )

    transport = httpx.MockTransport(handler)
    fake_redis = FakeRedis()
    client = GitHubClient(
        base_url="https://api.github.com",
        transport=transport,
        redis_client=fake_redis,
    )

    # First call - hits network
    res1 = client.get_repository_metadata("alice", "cached-repo")
    assert call_count == 1
    assert res1["name"] == "cached-repo"

    # Second call - served from cache
    res2 = client.get_repository_metadata("alice", "cached-repo")
    assert call_count == 1
    assert res2["name"] == "cached-repo"


# ---------------------------------------------------------------------------
# Repository Discovery Tests
# ---------------------------------------------------------------------------


def test_discover_repositories_explicit_link_prioritized():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/alice/dist-queue":
            return httpx.Response(
                200,
                json={
                    "html_url": "https://github.com/alice/dist-queue",
                    "name": "dist-queue",
                    "owner": {"login": "alice"},
                    "visibility": "public",
                },
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    transport = httpx.MockTransport(handler)
    client = GitHubClient(base_url="https://api.github.com", transport=transport)

    project = ProjectSuggestion(
        name="Distributed Queue",
        explicit_github_urls=["https://github.com/alice/dist-queue"],
        source_page=1,
    )

    matches = discover_repositories(project, github_client=client)
    assert len(matches) == 1
    m = matches[0]
    assert m.url == "https://github.com/alice/dist-queue"
    assert m.confidence_category == ConfidenceCategory.HIGH.value
    assert "Explicit repository link extracted from resume" in m.discovery_reason


def test_discover_repositories_search_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "html_url": "https://github.com/dev1/cache-engine",
                            "name": "cache-engine",
                            "owner": {"login": "dev1"},
                            "visibility": "public",
                        },
                        {
                            "html_url": "https://github.com/dev2/redis-cache-helper",
                            "name": "redis-cache-helper",
                            "owner": {"login": "dev2"},
                            "visibility": "public",
                        },
                    ]
                },
            )
        raise AssertionError(f"Unexpected path: {request.url.path}")

    transport = httpx.MockTransport(handler)
    client = GitHubClient(base_url="https://api.github.com", transport=transport)

    project = ProjectSuggestion(
        name="Cache Engine",
        explicit_github_urls=[],  # No explicit URLs
    )

    matches = discover_repositories(project, github_client=client)
    assert len(matches) == 2

    # Exact name match
    assert matches[0].name == "cache-engine"
    assert matches[0].confidence_category == ConfidenceCategory.MEDIUM.value
    assert "Exact name match" in matches[0].discovery_reason

    # Keyword match
    assert matches[1].name == "redis-cache-helper"
    assert matches[1].confidence_category == ConfidenceCategory.LOW.value
    assert "Keyword match" in matches[1].discovery_reason


def test_discover_repositories_max_five_results():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "html_url": f"https://github.com/dev/proj-{i}",
                            "name": f"proj-{i}",
                            "owner": {"login": "dev"},
                            "visibility": "public",
                        }
                        for i in range(10)
                    ]
                },
            )
        raise AssertionError("Unexpected request")

    transport = httpx.MockTransport(handler)
    client = GitHubClient(base_url="https://api.github.com", transport=transport)

    project = ProjectSuggestion(name="Big Project", explicit_github_urls=[])
    matches = discover_repositories(project, github_client=client)

    assert len(matches) == 5
