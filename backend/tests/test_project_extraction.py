from app.services.project_extraction import (
    extract_github_urls,
    extract_project_suggestions,
)
from app.services.resumes import PageContent, ResumeExtractionResult


def test_extract_github_urls_filters_and_sanitizes():
    text = """
    Check out my projects:
    1. https://github.com/alice/distributed-broker.
    2. https://github.com/alice/task-queue/
    3. Non-repo links: https://github.com/topics/fastapi, https://github.com/features/actions
    4. Repo with git suffix: https://github.com/alice/sample-tool.git
    """
    urls = extract_github_urls(text)
    assert urls == [
        "https://github.com/alice/distributed-broker",
        "https://github.com/alice/task-queue",
        "https://github.com/alice/sample-tool",
    ]


def test_extract_projects_from_projects_section():
    resume_text = """
    John Candidate
    john@example.com

    WORK EXPERIENCE
    Software Engineer at Acme Corp (2020 - 2023)
    - Maintained backend microservices in Python.

    PROJECTS
    Distributed Cache Engine
    - Developed an in-memory key-value cache with LRU eviction and replication.
    - Repository: https://github.com/john/dist-cache

    Realtime Chat System
    - WebSocket based messaging platform built with FastAPI and Redis.
    - Source code available at https://github.com/john/chat-app

    EDUCATION
    BS in Computer Science, State University (2016 - 2020)
    """
    suggestions = extract_project_suggestions(resume_text)
    assert len(suggestions) == 2

    s1 = next(s for s in suggestions if "Cache" in s.name)
    assert s1.name == "Distributed Cache Engine"
    assert "in-memory key-value cache" in (s1.description or "")
    assert s1.explicit_github_urls == ["https://github.com/john/dist-cache"]
    assert s1.source_page == 1

    s2 = next(s for s in suggestions if "Chat" in s.name)
    assert s2.name == "Realtime Chat System"
    assert "FastAPI and Redis" in (s2.description or "")
    assert s2.explicit_github_urls == ["https://github.com/john/chat-app"]


def test_extract_inline_repo_without_projects_section():
    text = """
    Sarah Developer
    Created a custom metrics exporter: https://github.com/sarah/prometheus-custom-exporter
    """
    suggestions = extract_project_suggestions(text)
    assert len(suggestions) == 1
    assert suggestions[0].explicit_github_urls == [
        "https://github.com/sarah/prometheus-custom-exporter"
    ]
    assert suggestions[0].name != ""


def test_no_projects_found():
    text = """
    Alex Engineer
    EXPERIENCE
    Lead Architect at Big Corp (2018 - 2024)
    Managing cloud infrastructure and corporate intranets.

    EDUCATION
    MS Computer Science, 2018
    """
    suggestions = extract_project_suggestions(text)
    assert suggestions == []


def test_scanned_pdf_yields_no_suggestions():
    scanned_result = ResumeExtractionResult(
        storage_key="resumes/scanned.pdf",
        raw_text="",
        pages=[],
        is_scanned=True,
        scanned_reason="Scanned document detected",
    )
    suggestions = extract_project_suggestions(scanned_result)
    assert suggestions == []


def test_preserves_page_numbers_across_pages():
    pages = [
        PageContent(
            page_number=1,
            text="Alice Candidate\nWORK EXPERIENCE\nSenior Engineer\n",
        ),
        PageContent(
            page_number=2,
            text="PROJECTS\nLog Aggregator\nHigh-performance pipeline https://github.com/alice/log-agg\n",
        ),
        PageContent(
            page_number=3,
            text="PROJECTS\nQuery Engine\nSQL parsing tool https://github.com/alice/query-engine\n",
        ),
    ]
    suggestions = extract_project_suggestions(pages)
    assert len(suggestions) == 2

    s1 = next(s for s in suggestions if s.name == "Log Aggregator")
    assert s1.source_page == 2

    s2 = next(s for s in suggestions if s.name == "Query Engine")
    assert s2.source_page == 3
