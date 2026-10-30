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
from app.services.project_extraction import EXCLUDED_GITHUB_OWNERS

logger = logging.getLogger("repository_discovery")

COMMON_TECH_STACK: set[str] = {
    "react",
    "reactjs",
    "nextjs",
    "next.js",
    "vue",
    "vuejs",
    "angular",
    "svelte",
    "tailwind",
    "tailwindcss",
    "bootstrap",
    "material-ui",
    "mui",
    "shadcn",
    "aceternity",
    "chakra",
    "styled-components",
    "framer-motion",
    "three.js",
    "threejs",
    "r3f",
    "matter.js",
    "gsap",
    "nodejs",
    "node.js",
    "node",
    "express",
    "expressjs",
    "fastapi",
    "flask",
    "django",
    "spring",
    "springboot",
    "nestjs",
    "graphql",
    "apollo",
    "trpc",
    "rest",
    "grpc",
    "typescript",
    "javascript",
    "python",
    "golang",
    "go",
    "rust",
    "java",
    "c++",
    "c#",
    "ruby",
    "rails",
    "php",
    "laravel",
    "scala",
    "kotlin",
    "swift",
    "dart",
    "flutter",
    "mongodb",
    "mongo",
    "postgres",
    "postgresql",
    "mysql",
    "sqlite",
    "redis",
    "cassandra",
    "prisma",
    "sqlalchemy",
    "typeorm",
    "hibernate",
    "mongoose",
    "zustand",
    "redux",
    "docker",
    "kubernetes",
    "k8s",
    "aws",
    "gcp",
    "azure",
    "firebase",
    "supabase",
    "razorpay",
    "stripe",
    "clerk",
    "nextauth",
    "auth0",
    "jwt",
    "oauth",
    "rabbitmq",
    "kafka",
    "celery",
    "socket.io",
    "webrtc",
    "websockets",
    "vite",
    "webpack",
    "turbopack",
    "electron",
    "react-native",
    "expo",
}


def _sanitize_search_term(name: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _extract_tech_overlap(project_desc: str | None, repo_text: str) -> list[str]:
    """
    Extracts overlapping technology keywords between project description and repo text.
    Strictly filters against COMMON_TECH_STACK to prevent generic English words
    (e.g. 'time', 'note', 'code') from generating false 'Tech stack match' classifications.
    """
    if not project_desc or not repo_text:
        return []

    desc_words = set(re.findall(r"[a-zA-Z0-9_.-]+", project_desc.lower()))
    repo_words = set(re.findall(r"[a-zA-Z0-9_.-]+", repo_text.lower()))

    # Filter strictly to verified developer technology keywords
    project_tech = {w for w in desc_words if w in COMMON_TECH_STACK}
    repo_tech = {w for w in repo_words if w in COMMON_TECH_STACK}

    return sorted(project_tech.intersection(repo_tech))


def extract_candidate_github_handle(
    raw_text: str | None, email: str | None = None
) -> str | None:
    """
    Extracts candidate's GitHub handle from resume raw text or email prefix.
    """
    if raw_text:
        matches = re.findall(
            r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_-]+)",
            raw_text,
            re.IGNORECASE,
        )
        for m in matches:
            clean = m.lower().strip()
            if clean not in EXCLUDED_GITHUB_OWNERS and len(clean) >= 2:
                return clean
    if email:
        prefix = email.split("@")[0].lower().strip()
        if re.match(r"^[a-zA-Z0-9_-]{3,25}$", prefix):
            return prefix
    return None


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
                    r["url"]: (
                        r.get("confidence", "low"),
                        r.get("reason", "Matched via Gemini semantic analysis"),
                    )
                    for r in data.get("results", [])
                    if "url" in r
                }
    except Exception as e:
        logger.info("Gemini repository matching skipped or timed out: %s", e)
    return {}


def discover_repositories(
    project: ProjectSuggestion,
    github_client: GitHubClient | None = None,
    limit: int = 10,
    candidate_handle: str | None = None,
) -> list[RepositoryMatch]:
    """
    Discovers candidate public GitHub repositories for a project suggestion.
    Prioritizes explicit resume URLs, candidate user repositories, and public search.
    Returns up to 'limit' matches, marked with confidence categories and discovery reasons.
    Never infers or asserts candidate authorship/ownership.
    """
    client = github_client or GitHubClient()
    matches: list[RepositoryMatch] = []
    seen_urls: set[str] = set()

    # 1. Prioritize explicit repository URLs extracted from resume
    for raw_url in project.explicit_github_urls:
        if len(matches) >= limit:
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
                candidate_specific_results: list[dict[str, Any]] = []
                if candidate_handle:
                    try:
                        user_query = f"user:{candidate_handle} {search_query}"
                        candidate_specific_results = client.search_repositories(user_query, limit=5)
                    except Exception as e:
                        logger.debug("Candidate user repo search bypassed: %s", e)

                public_search_results = client.search_repositories(search_query, limit=limit)

                # Combine results, prioritizing candidate's own account
                combined_items = candidate_specific_results + [
                    item
                    for item in public_search_results
                    if item.get("url") not in {c.get("url") for c in candidate_specific_results}
                ]

                # Optional Gemini semantic ranking if API key configured
                gemini_evals: dict[str, tuple[str, str]] = {}
                if settings.gemini_api_key:
                    gemini_evals = _enhance_with_gemini(
                        project, combined_items, settings.gemini_api_key
                    )

                scored_candidates: list[tuple[int, RepositoryMatch]] = []

                for item in combined_items:
                    repo_url = item["url"]
                    if repo_url in seen_urls:
                        continue

                    norm_project = project.name.lower().replace(" ", "-")
                    norm_repo = item["name"].lower()
                    repo_desc = item.get("description") or ""
                    owner = item.get("owner", "")
                    size_kb = item.get("size", 0)

                    # Check technology overlap
                    tech_overlap = _extract_tech_overlap(
                        project.description, f"{norm_repo} {repo_desc}"
                    )

                    score = 0
                    is_owner_match = bool(
                        candidate_handle and owner.lower() == candidate_handle.lower()
                    )

                    if repo_url in gemini_evals:
                        conf_str, gemini_reason = gemini_evals[repo_url]
                        confidence = conf_str.lower()
                        reason = f"Gemini Match: {gemini_reason} (requires HR verification)"
                        score = (
                            100 if confidence == "high" else (60 if confidence == "medium" else 15)
                        )
                    elif is_owner_match:
                        confidence = ConfidenceCategory.HIGH.value
                        reason = (
                            f"Candidate account match ({owner}/{item['name']}) for '{project.name}' "
                            f"(unconfirmed; requires HR verification)"
                        )
                        score = 100
                    elif norm_project == norm_repo or norm_project == norm_repo.replace("-", ""):
                        confidence = ConfidenceCategory.MEDIUM.value
                        reason = (
                            f"Exact name match via public repository search for '{project.name}' "
                            f"(unconfirmed; requires HR verification)"
                        )
                        score = 80
                    elif norm_project in norm_repo or norm_repo in norm_project:
                        if len(tech_overlap) >= 1:
                            confidence = ConfidenceCategory.MEDIUM.value
                            reason = (
                                f"Close name and tech match ({', '.join(tech_overlap[:2])}) for '{project.name}' "
                                f"(unconfirmed; requires HR verification)"
                            )
                            score = 70
                        else:
                            confidence = ConfidenceCategory.MEDIUM.value
                            reason = (
                                f"Close name match for '{project.name}' via public search "
                                f"(unconfirmed; requires HR verification)"
                            )
                            score = 60
                    elif len(tech_overlap) >= 2:
                        confidence = ConfidenceCategory.MEDIUM.value
                        reason = (
                            f"Tech stack match ({', '.join(tech_overlap[:3])}) via public search "
                            f"(unconfirmed; requires HR verification)"
                        )
                        score = 50
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

                    # Downrank empty repos (0 KB reported)
                    if size_kb == 0 and not repo_desc:
                        score = max(0, score - 20)
                        reason += " [Empty repository]"

                    match = RepositoryMatch(
                        url=repo_url,
                        owner=owner,
                        name=item["name"],
                        discovery_reason=reason,
                        confidence_category=confidence,
                    )
                    scored_candidates.append((score, match))
                    seen_urls.add(repo_url)

                # Prioritize top scored candidate repositories
                scored_candidates.sort(key=lambda x: x[0], reverse=True)
                for _, m in scored_candidates:
                    if len(matches) >= limit:
                        break
                    matches.append(m)
            except (GitHubRateLimitError, GitHubTransientError):
                raise
            except (GitHubError, httpx.HTTPError) as e:
                logger.warning("Repository search encountered an unexpected issue: %s", e)

    return matches[:limit]
