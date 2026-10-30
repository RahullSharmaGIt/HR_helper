import re
import uuid

from app.schemas.contracts import ProjectSuggestion
from app.services.resumes import PageContent, ResumeExtractionResult

GITHUB_REPO_REGEX = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"
)

EXCLUDED_GITHUB_OWNERS = {
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

PROJECT_SECTION_REGEX = re.compile(
    r"^(?:(?:key|selected|recent|personal|academic|open[- ]source|technical)\s+)?(?:projects|portfolio)\b",
    re.IGNORECASE,
)

STOP_SECTION_REGEX = re.compile(
    r"^(?:(?:technical|core|professional|key|relevant)?\s*skills|work\s+experience|experience|employment|education|certifications|publications|awards|languages|interests)\b",
    re.IGNORECASE,
)


DATE_ONLY_REGEX = re.compile(
    r"^(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d{0,4}|\d{1,2}/\d{4}|\d{4})\s*(?:[-–—]\s*(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d{0,4}|\d{1,2}/\d{4}|\d{4}|present))?$",
    re.IGNORECASE,
)


def extract_github_urls(text: str) -> list[str]:
    """
    Finds and sanitizes explicit GitHub repository URLs from text.
    """
    found_urls: list[str] = []
    seen = set()

    for match in GITHUB_REPO_REGEX.finditer(text):
        owner, repo = match.group(1), match.group(2)
        # Clean trailing punctuation
        repo = re.sub(r"[.,);>\]]+$", "", repo)
        repo = repo.removesuffix(".git")

        if not owner or not repo:
            continue
        if owner.lower() in EXCLUDED_GITHUB_OWNERS:
            continue

        clean_url = f"https://github.com/{owner}/{repo}"
        if clean_url not in seen:
            seen.add(clean_url)
            found_urls.append(clean_url)

    return found_urls


def _clean_project_title(line: str) -> str:
    cleaned = re.sub(r"https?://\S+", "", line)  # remove url
    cleaned = re.sub(r"^[*\-•–—∗◦▪▫\s]+", "", cleaned)  # remove leading bullets/symbols
    cleaned = re.sub(r"\s+[|•–—∗◦▪▫]\s+", " ", cleaned)  # remove separators
    cleaned = re.sub(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d{4}\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b\d{4}\s*[-–—]\s*(?:\d{4}|present)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(Live|GitHub|Demo|Code|Link)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_project_suggestions(
    input_data: str | list[PageContent] | ResumeExtractionResult,
) -> list[ProjectSuggestion]:
    """
    Extracts candidate project suggestions using deterministic heuristics.
    Returns a list of ProjectSuggestion models for HR confirmation.
    """
    pages: list[tuple[int | None, str]] = []

    if isinstance(input_data, ResumeExtractionResult):
        if input_data.is_scanned:
            return []
        pages = [(p.page_number, p.text) for p in input_data.pages]
    elif isinstance(input_data, list):
        pages = [(p.page_number, p.text) for p in input_data]
    elif isinstance(input_data, str):
        pages = [(1, input_data)]
    else:
        return []

    suggestions: list[ProjectSuggestion] = []
    seen_names: set[str] = set()

    for page_num, page_text in pages:
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        in_project_section = False
        current_project_name: str | None = None
        current_desc_lines: list[str] = []
        current_urls: list[str] = []

        def flush_project(target_page: int | None = page_num):
            nonlocal current_project_name, current_desc_lines, current_urls
            if current_project_name:
                name_key = current_project_name.lower()
                if name_key not in seen_names:
                    seen_names.add(name_key)
                    description = " ".join(current_desc_lines).strip() or None
                    if description and len(description) > 400:
                        description = description[:397] + "..."

                    suggestions.append(
                        ProjectSuggestion(
                            id=uuid.uuid4(),
                            name=current_project_name,
                            description=description,
                            explicit_github_urls=list(dict.fromkeys(current_urls)),
                            source_page=target_page,
                        )
                    )
            current_project_name = None
            current_desc_lines = []
            current_urls = []

        for line in lines:
            # Check for section boundaries
            if PROJECT_SECTION_REGEX.match(line):
                flush_project()
                in_project_section = True
                continue
            elif in_project_section and STOP_SECTION_REGEX.match(line):
                flush_project()
                in_project_section = False
                continue

            line_urls = extract_github_urls(line)

            if in_project_section:
                # Skip date-only lines (e.g. "Mar 2025", "2023 - 2024")
                if DATE_ONLY_REGEX.match(line):
                    continue

                is_bullet = line.startswith(("*", "-", "•", "–", "—", "∗", "◦", "▪", "▫", ">"))
                is_sentence = line.endswith((".", ";", ","))
                starts_lower = line[0].islower() if line else False
                starts_continuation = bool(
                    re.match(
                        r"^(?:and|with|for|via|by|to|in|of|or|from|using)\b", line, re.IGNORECASE
                    )
                )
                is_tech_line = bool(
                    re.match(
                        r"^(?:technologies|tech stack|tools|languages|frameworks|built with)\s*:",
                        line,
                        re.IGNORECASE,
                    )
                )

                # If current project already exists and has no URLs, and this line contains URLs,
                # attach to current project rather than starting a new one
                if current_project_name and line_urls and not current_urls:
                    current_urls.extend(line_urls)
                    desc_part = _clean_project_title(line)
                    if desc_part:
                        current_desc_lines.append(desc_part)
                    continue

                # Check for pipe-delimited project title: "Project Name | Tech Stack"
                title_candidate: str | None = None
                extra_desc: str | None = None

                if not is_bullet and "|" in line:
                    parts = line.split("|", 1)
                    t = _clean_project_title(parts[0])
                    if 2 <= len(t) <= 80:
                        title_candidate = t
                        extra_desc = parts[1].strip()
                elif (
                    not is_bullet
                    and not starts_lower
                    and not starts_continuation
                    and not is_tech_line
                    and not is_sentence
                ):
                    t = _clean_project_title(line)
                    if 2 <= len(t) <= 80:
                        title_candidate = t

                if title_candidate:
                    # If we already have a project in progress that has some description/URLs, flush it
                    if current_project_name and (current_desc_lines or current_urls):
                        flush_project()

                    if not current_project_name:
                        current_project_name = title_candidate
                        current_urls.extend(line_urls)
                        if extra_desc:
                            current_desc_lines.append(extra_desc)
                        continue

                # Otherwise it's a description or detail line for the current project
                if current_project_name:
                    cleaned_desc_line = re.sub(r"^[*\-•–—∗◦▪▫\s]+", "", line)
                    if cleaned_desc_line:
                        current_desc_lines.append(cleaned_desc_line)
                    if line_urls:
                        current_urls.extend(line_urls)

            else:
                # Outside project section: Look for explicit GitHub repo mentions
                if line_urls:
                    flush_project()
                    cleaned_name = _clean_project_title(line)
                    if not cleaned_name:
                        repo_part = line_urls[0].split("/")[-1]
                        cleaned_name = repo_part.replace("-", " ").replace("_", " ").title()

                    current_project_name = cleaned_name
                    current_urls.extend(line_urls)
                    flush_project()

        flush_project()

    return suggestions
