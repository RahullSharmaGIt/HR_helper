import uuid

import pytest

from app.schemas.contracts import EvidenceItem, Measurement
from app.services.history_analyzer import ContributorSummary, HistoryAnalysisResult
from app.services.scoring import (
    COVERAGE_WEIGHTS,
    AssessmentResult,
    build_assessment,
)
from app.services.similarity import PathMatchDetail, SimilarityAnalysisResult


@pytest.fixture
def mock_history_result():
    ev1 = EvidenceItem(
        id=uuid.uuid4(),
        kind="git_history",
        summary="Analyzed 15 reachable commits spanning 20 days",
        source_url="https://github.com/alice/project/commits",
        commit_sha="abcdef1234567890abcdef1234567890abcdef12",
    )
    ev2 = EvidenceItem(
        id=uuid.uuid4(),
        kind="git_history",
        summary="Initial core implementation of task broker",
        source_url="https://github.com/alice/project/commit/1234567890abcdef1234567890abcdef12345678",
        commit_sha="1234567890abcdef1234567890abcdef12345678",
    )
    return HistoryAnalysisResult(
        total_commits=15,
        merge_commits=2,
        first_commit_date="2024-01-01T10:00:00Z",
        last_commit_date="2024-01-20T15:00:00Z",
        duration_days=20.0,
        contributors=[
            ContributorSummary("Alice Dev", "a***e@example.com", 14, 93.3, False),
            ContributorSummary("dependabot[bot]", "d********t@github.com", 1, 6.7, True),
        ],
        bot_commits_count=1,
        alias_match_stats={
            "supplied_aliases": ["alice"],
            "matched_commits_count": 14,
            "matched_percentage": 93.3,
            "matching_contributor_names": ["Alice Dev"],
        },
        is_shallow=False,
        is_truncated=False,
        truncation_reasons=[],
        timestamp_anomalies=[],
        has_mailmap=False,
        evidence=[ev1, ev2],
        limitations=["Git timestamps can be edited."],
    )


@pytest.fixture
def mock_similarity_result():
    ev_sim = EvidenceItem(
        id=uuid.uuid4(),
        kind="similarity",
        summary="Candidate file 'queue.py' shares 25% syntactic patterns with reference 'broker.py'",
        source_url="https://github.com/reference-org/ref/commit/1111111111111111111111111111111111111111",
        commit_sha="1111111111111111111111111111111111111111",
        path="queue.py",
    )
    return SimilarityAnalysisResult(
        overlap_score=Measurement[float](value=25.0),
        matched_paths=[
            PathMatchDetail(
                candidate_path="queue.py",
                reference_url="https://github.com/reference-org/ref",
                reference_commit_sha="1111111111111111111111111111111111111111",
                reference_path="broker.py",
                matched_fingerprints=5,
                total_candidate_fingerprints=20,
                overlap_ratio=0.25,
            )
        ],
        reference_commit_links=[
            "https://github.com/reference-org/ref/commit/1111111111111111111111111111111111111111"
        ],
        coverage_statistics={
            "candidate_files_analyzed": 6,
            "candidate_tokens_analyzed": 1200,
            "reference_files_indexed": 3,
        },
        algorithm_version="winnowing-v1.0",
        algorithm_configuration={"k": 12, "w": 6},
        evidence=[ev_sim],
        limitations=["Similarity does not prove copying."],
    )


@pytest.fixture
def mock_metadata():
    return {
        "url": "https://github.com/alice/project",
        "owner": "alice",
        "name": "project",
        "default_branch": "main",
        "visibility": "public",
        "is_fork": False,
        "license": "MIT",
        "description": "Distributed async task queue in Python",
    }


def test_coverage_weights_sum_to_one():
    total_weight = sum(COVERAGE_WEIGHTS.values())
    assert abs(total_weight - 1.0) < 1e-6


def test_build_assessment_complete_evidence(
    mock_history_result, mock_similarity_result, mock_metadata
):
    assessment = build_assessment(mock_history_result, mock_similarity_result, mock_metadata)

    assert isinstance(assessment, AssessmentResult)
    assert assessment.status == "reviewable"
    assert assessment.evidence_coverage_score == 100
    assert len(assessment.observations) >= 2
    assert len(assessment.suggested_interview_questions) >= 2

    # Observations must reference evidence IDs
    for obs in assessment.observations:
        assert len(obs.evidence_ids) > 0

    # Ensure disclaimers on limitations
    assert any("does not measure candidate competence" in lim for lim in assessment.limitations)


def test_build_assessment_missing_data_insufficient():
    empty_history = HistoryAnalysisResult(
        total_commits=0,
        merge_commits=0,
        first_commit_date=None,
        last_commit_date=None,
        duration_days=None,
        contributors=[],
        bot_commits_count=0,
        alias_match_stats=None,
        is_shallow=False,
        is_truncated=False,
        truncation_reasons=[],
        timestamp_anomalies=[],
        has_mailmap=False,
        evidence=[],
        limitations=["Empty repo"],
    )
    empty_sim = SimilarityAnalysisResult(
        overlap_score=Measurement[float](value=None, reason="No source files"),
        matched_paths=[],
        reference_commit_links=[],
        coverage_statistics={"candidate_files_analyzed": 0, "reference_files_indexed": 0},
        algorithm_version="winnowing-v1.0",
        algorithm_configuration={},
        evidence=[],
        limitations=[],
    )

    assessment = build_assessment(empty_history, empty_sim, metadata={})
    assert assessment.status == "insufficient_data"
    assert assessment.evidence_coverage_score < 35
    assert assessment.coverage_components["history_availability"].status == "unavailable"
    assert assessment.coverage_components["source_inspection"].status == "unavailable"


def test_fork_with_substantial_changes(mock_history_result, mock_similarity_result, mock_metadata):
    mock_metadata["is_fork"] = True
    mock_metadata["parent_url"] = "https://github.com/upstream/parent-broker"

    assessment = build_assessment(mock_history_result, mock_similarity_result, mock_metadata)

    # Fork status alone must not lower score or credibility
    assert assessment.evidence_coverage_score == 100
    assert assessment.status == "reviewable"

    fork_obs = next((o for o in assessment.observations if o.category == "fork_status"), None)
    assert fork_obs is not None
    assert "https://github.com/upstream/parent-broker" in fork_obs.statement

    assert any(
        "fork of https://github.com/upstream/parent-broker" in q
        for q in assessment.suggested_interview_questions
    )


def test_timestamp_anomalies_and_imported_history(
    mock_history_result, mock_similarity_result, mock_metadata
):
    mock_history_result.timestamp_anomalies = [
        "Commit abc has committer timestamp earlier than author timestamp."
    ]

    assessment = build_assessment(mock_history_result, mock_similarity_result, mock_metadata)

    ts_obs = next((o for o in assessment.observations if o.category == "timestamp_integrity"), None)
    assert ts_obs is not None
    assert "atypical timestamps" in " ".join(assessment.suggested_interview_questions)


def test_sparse_reference_coverage_shows_unavailable_reason(mock_history_result, mock_metadata):
    sparse_sim = SimilarityAnalysisResult(
        overlap_score=Measurement[float](
            value=None, reason="Reference catalog is empty; comparison unavailable."
        ),
        matched_paths=[],
        reference_commit_links=[],
        coverage_statistics={"candidate_files_analyzed": 5, "reference_files_indexed": 0},
        algorithm_version="winnowing-v1.0",
        algorithm_configuration={},
        evidence=[],
        limitations=[],
    )

    assessment = build_assessment(mock_history_result, sparse_sim, mock_metadata)
    ref_comp = assessment.coverage_components["reference_comparison"]
    assert ref_comp.status == "unavailable"
    assert ref_comp.score == 0
    assert "Reference catalog is empty" in (ref_comp.reason or "")
    assert assessment.evidence_coverage_score == 75  # 100 - 25% weight


def test_assessment_determinism(mock_history_result, mock_similarity_result, mock_metadata):
    a1 = build_assessment(mock_history_result, mock_similarity_result, mock_metadata)
    a2 = build_assessment(mock_history_result, mock_similarity_result, mock_metadata)

    assert a1.evidence_coverage_score == a2.evidence_coverage_score
    assert a1.status == a2.status
    assert len(a1.observations) == len(a2.observations)
    assert [o.statement for o in a1.observations] == [o.statement for o in a2.observations]
    assert a1.suggested_interview_questions == a2.suggested_interview_questions
