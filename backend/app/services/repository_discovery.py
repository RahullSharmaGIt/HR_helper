import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.schemas.contracts import ConfidenceCategory, ProjectSuggestion, RepositoryMatch
from app.services.github_client import (
    GitHubClient,
    GitHubError,
    GitHubRateLimitError,
    GitHubRepoNotFoundError,
    GitHubTransientError,
    normalize_github_repository_url,
)

logger = logging.getLogger("repository_discovery")


def _sanitize_search_term(name: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _extract_tech_overlap(project_desc: str | None, repo_text: str) -> list[str]:
    if not project_desc:
        return []
    keywords = re.findall(r"\b[a-zA-Z0-9_.-]{3,}\b", project_desc.lower())
    stop_words = {
        "with", "from", "that", "this", "have", "been", "using", "built",
        "full", "stack", "system", "engine", "application", "platform",
        "developed", "implemented", "engineered", "project", "high",
        "production", "precision", "retrieval", "search", "seamless"
    }
    candidates = {k for k in keywords if k not in stop_words and len(k) > 3}
    repo_words = set(re.findall(r"\b[a-zA-Z0-9_.-]{3,}\b", repo_text.lower()))
    return list(candidates.intersection(repo_words))


def _enhance_with_gemini(
    project: ProjectSuggestion,
    candidates: list[dict[str, Any]],
    api_key: str,
) -> dict[str, tuple[str, str]]:
    """
    Optional Gemini Flash call to evaluate semantic relevance of discovered repos.
    Returns mapping: repo_url -> (confidence, reason).
    """
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        prompt = (
            f"You are matching a software developer candidate resume project to candidate GitHub repositories.\n"
            f"Resume Project Title: {project.name}\n"
            f"Resume Description & Technologies: {project.description or 'N/A'}\n\n"
            f"GitHub Repositories found:\n"
            + "\n".join(
                f"- URL: {c.get('url')} | Name: {c.get('owner')}/{c.get('name')} | Desc: {c.get('description', '')}"
                for c in candidates
            )
            + "\n\nFor each repository URL, evaluate if it matches this project."
            " Format your response strictly as JSON with key 'results' containing an array of objects: "
            "[{'url': '...', 'confidence': 'high'|'medium'|'low', 'reason': 'short explanation'}]"
        )
        resp = httpx.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=4.0)
        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            import json
            clean_json = re.search(r"\{.*\}", text, re.DOTALL)
            if clean_json:
                data = json.loads(clean_json.group(0))
                return {
                    r["url"]: (r.get("confidence", "low"), r.get("reason", "Matched via Gemini semantic analysis"))
                    for r in data.get("results", [])
                    if "url" in r
                }
    except Exception as e:
        logger.info("Gemini repository matching skipped or timed out: %s", e)
    return {}


def discover_repositories(
    project: ProjectSuggestion,
    github_client: GitHubClient | None = None,
) -> list[RepositoryMatch]:
    """
    Discovers candidate public GitHub repositories for a project suggestion.
    Prioritizes explicit resume URLs, falling back to public GitHub repository search.
    Returns at most 5 matches, marked with confidence categories and discovery reasons.
    Never infers or asserts candidate authorship/ownership.
    """
    client = github_client or GitHubClient()
    matches: list[RepositoryMatch] = []
    seen_urls: set[str] = set()

    # 1. Prioritize explicit repository URLs extracted from resume
    for raw_url in project.explicit_github_urls:
        if len(matches) >= 5:
            break
        try:
            canonical_url = normalize_github_repository_url(raw_url)
            if canonical_url in seen_urls:
                continue

            owner, repo = canonical_url.split("/")[-2], canonical_url.split("/")[-1]
            metadata = client.get_repository_metadata(owner, repo)

            page_suffix = f" (page {project.source_page})" if project.source_page else ""
            match = RepositoryMatch(
                url=metadata["url"],
                owner=metadata["owner"],
                name=metadata["name"],
                discovery_reason=f"Explicit repository link extracted from resume{page_suffix} (pending confirmation)",
                confidence_category=ConfidenceCategory.HIGH.value,
            )
            matches.append(match)
            seen_urls.add(canonical_url)
        except (GitHubRepoNotFoundError, ValueError) as e:
            logger.info("Explicit repository link %s is invalid or not public: %s", raw_url, e)
        except (GitHubRateLimitError, GitHubTransientError):
            raise

    # 2. Otherwise use GitHub repository search with project terms
    if not matches:
        search_query = _sanitize_search_term(project.name)
        if search_query:
            try:
                search_results = client.search_repositories(search_query, limit=10)

                # Optional Gemini semantic ranking if API key configured
                gemini_evals: dict[str, tuple[str, str]] = {}
                if settings.gemini_api_key:
                    gemini_evals = _enhance_with_gemini(project, search_results, settings.gemini_api_key)

                scored_candidates: list[tuple[int, RepositoryMatch]] = []

                for item in search_results:
                    repo_url = item["url"]
                    if repo_url in seen_urls:
                        continue

                    norm_project = project.name.lower().replace(" ", "-")
                    norm_repo = item["name"].lower()
                    repo_desc = item.get("description") or ""

                    # Check technology overlap
                    tech_overlap = _extract_tech_overlap(project.description, f"{norm_repo} {repo_desc}")

                    score = 0
                    if repo_url in gemini_evals:
                        conf_str, gemini_reason = gemini_evals[repo_url]
                        confidence = conf_str.lower()
                        reason = f"Gemini Match: {gemini_reason} (requires HR verification)"
                        score = 100 if confidence == "high" else (60 if confidence == "medium" else 15)
                    elif norm_project == norm_repo or norm_project == norm_repo.replace("-", ""):
                        confidence = ConfidenceCategory.MEDIUM.value
                        reason = (
                            f"Exact name match via public repository search for '{project.name}' "
                            f"(unconfirmed; requires HR verification)"
                        )
                        score = 80
                    elif len(tech_overlap) >= 2:
                        confidence = ConfidenceCategory.MEDIUM.value
                        reason = (
                            f"Tech stack match ({', '.join(tech_overlap[:3])}) via public search "
                            f"(unconfirmed; requires HR verification)"
                        )
                        score = 60
                    elif len(tech_overlap) == 1:
                        confidence = ConfidenceCategory.LOW.value
                        reason = (
                            f"Partial tech match ({tech_overlap[0]}) via public search "
                            f"(unconfirmed; requires HR verification)"
                        )
                        score = 30
                    else:
                        confidence = ConfidenceCategory.LOW.value
                        reason = (
                            f"Keyword match via public repository search for '{project.name}' "
                            f"(unconfirmed; requires HR verification)"
                        )
                        score = 10

                    match = RepositoryMatch(
                        url=repo_url,
                        owner=item["owner"],
                        name=item["name"],
                        discovery_reason=reason,
                        confidence_category=confidence,
                    )
                    scored_candidates.append((score, match))
                    seen_urls.add(repo_url)

                # Prioritize top scored candidate repositories
                scored_candidates.sort(key=lambda x: x[0], reverse=True)
                for _, m in scored_candidates:
                    if len(matches) >= 5:
                        break
                    matches.append(m)
            except (GitHubRateLimitError, GitHubTransientError):
                raise
            except (GitHubError, httpx.HTTPError) as e:
                logger.warning("Repository search encountered an unexpected issue: %s", e)

    return matches[:5]
