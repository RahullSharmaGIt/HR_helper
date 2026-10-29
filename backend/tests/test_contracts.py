import uuid

import pytest
from pydantic import ValidationError

from app.schemas.contracts import (
    AnalysisReport,
    EvidenceItem,
    JobState,
    Measurement,
    ProjectSuggestion,
    RepositoryMatch,
)


def test_job_states() -> None:
    expected_states = {"queued", "running", "succeeded", "failed", "canceled"}
    assert {s.value for s in JobState} == expected_states


def test_unavailable_measurement_requires_reason() -> None:
    # Valid: unavailable with reason
    m = Measurement[int](value=None, reason="Commit history unavailable due to shallow clone")
    assert m.value is None
    assert m.reason == "Commit history unavailable due to shallow clone"

    # Valid: available value
    m2 = Measurement[int](value=42)
    assert m2.value == 42
    assert m2.reason is None

    # Invalid: unavailable with no reason
    with pytest.raises(ValidationError):
        Measurement[int](value=None, reason=None)

    # Invalid: unavailable with empty string
    with pytest.raises(ValidationError):
        Measurement[int](value=None, reason="")


def test_project_suggestion_round_trip() -> None:
    item_id = uuid.uuid4()
    data = {
        "id": str(item_id),
        "name": "Distributed Job Scheduler",
        "description": "Async job queue built with Redis and Python",
        "explicitGithubUrls": ["https://github.com/example/scheduler"],
        "sourcePage": 2,
    }
    suggestion = ProjectSuggestion.model_validate(data)
    assert suggestion.id == item_id
    assert suggestion.name == "Distributed Job Scheduler"
    assert suggestion.source_page == 2
    assert suggestion.explicit_github_urls == ["https://github.com/example/scheduler"]

    dumped = suggestion.model_dump(by_alias=True, mode="json")
    assert dumped["id"] == str(item_id)
    assert dumped["explicitGithubUrls"] == ["https://github.com/example/scheduler"]
    assert dumped["sourcePage"] == 2


def test_repository_match_round_trip() -> None:
    data = {
        "url": "https://github.com/alice/project-a",
        "owner": "alice",
        "name": "project-a",
        "discoveryReason": "Matched explicit URL from resume page 1",
        "confidenceCategory": "high",
    }
    match = RepositoryMatch.model_validate(data)
    assert match.url == "https://github.com/alice/project-a"
    assert match.owner == "alice"
    assert match.name == "project-a"
    assert match.confidence_category == "high"

    dumped = match.model_dump(by_alias=True)
    assert dumped["discoveryReason"] == "Matched explicit URL from resume page 1"


def test_evidence_item_round_trip() -> None:
    item_id = uuid.uuid4()
    data = {
        "id": str(item_id),
        "kind": "git_history",
        "summary": "Repository contains 24 commits spanning 3 months with single contributor",
        "sourceUrl": "https://github.com/alice/project-a/commits",
        "commitSha": "abc1234567890",
        "path": "src/main.py",
    }
    evidence = EvidenceItem.model_validate(data)
    assert evidence.id == item_id
    assert evidence.kind == "git_history"
    assert evidence.commit_sha == "abc1234567890"

    dumped = evidence.model_dump(by_alias=True, mode="json")
    assert dumped["id"] == str(item_id)
    assert dumped["sourceUrl"] == "https://github.com/alice/project-a/commits"


def test_analysis_report_round_trip() -> None:
    report_data = {
        "schemaVersion": "1.0.0",
        "repository": {
            "url": "https://github.com/alice/project-a",
            "owner": "alice",
            "name": "project-a",
            "stars": 12,
            "forks": 2,
        },
        "history": {
            "totalCommits": 48,
            "durationDays": 90,
            "authorCount": 1,
            "cyclomaticComplexity": {
                "value": None,
                "reason": "Not calculated for non-Python scripts",
            },
        },
        "similarity": {
            "topMatchScore": {
                "value": None,
                "reason": "Reference corpus did not contain matches for Haskell language",
            }
        },
        "assessment": {
            "notes": "Evidence shows sustained commit activity and original test suites.",
            "disclaimer": "This report states evidence and uncertainty. It does not prove authorship or rank candidates.",
        },
        "evidence": [
            {
                "kind": "commit_log",
                "summary": "Initial commit 2024-01-15 followed by weekly iterations.",
                "sourceUrl": "https://github.com/alice/project-a/commit/001",
            }
        ],
        "limitations": [
            "Cannot verify identity of git committer email.",
            "Reference similarity collection is limited to standard assignment archetypes.",
        ],
    }

    report = AnalysisReport.model_validate(report_data)
    assert report.schema_version == "1.0.0"
    assert len(report.evidence) == 1
    assert len(report.limitations) == 2
    assert report.repository["name"] == "project-a"

    dumped = report.model_dump(by_alias=True, mode="json")
    assert dumped["schemaVersion"] == "1.0.0"
    assert dumped["evidence"][0]["kind"] == "commit_log"
