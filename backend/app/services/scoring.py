import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.history_analyzer import HistoryAnalysisResult
from app.services.similarity import SimilarityAnalysisResult

logger = logging.getLogger("scoring")

ASSESSMENT_VERSION = "1.0.0"

# Explicit weights for evidence coverage components (Sum = 1.00)
COVERAGE_WEIGHTS: dict[str, float] = {
    "history_availability": 0.30,
    "source_inspection": 0.25,
    "metadata_availability": 0.20,
    "reference_comparison": 0.25,
}


@dataclass
class CoverageComponent:
    score: int  # 0 to 100
    weight: float
    weighted_score: float
    status: str  # "complete", "partial", "unavailable"
    reason: str | None = None


@dataclass
class Observation:
    category: str
    statement: str
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class AssessmentResult:
    assessment_version: str
    status: str  # "reviewable", "limited_evidence", "insufficient_data"
    evidence_coverage_score: int  # 0–100, measures available evidence only
    coverage_components: dict[str, CoverageComponent]
    observations: list[Observation]
    limitations: list[str]
    suggested_interview_questions: list[str]


def _evaluate_history_coverage(history: HistoryAnalysisResult) -> CoverageComponent:
    weight = COVERAGE_WEIGHTS["history_availability"]
    if history.total_commits == 0:
        return CoverageComponent(
            score=0,
            weight=weight,
            weighted_score=0.0,
            status="unavailable",
            reason="Repository contains 0 reachable commits.",
        )

    if history.is_shallow or history.is_truncated:
        score = 60
        return CoverageComponent(
            score=score,
            weight=weight,
            weighted_score=round(score * weight, 2),
            status="partial",
            reason="History is shallow or truncated at traversal bounds.",
        )

    if history.total_commits < 3:
        score = 70
        return CoverageComponent(
            score=score,
            weight=weight,
            weighted_score=round(score * weight, 2),
            status="partial",
            reason="History contains fewer than 3 commits.",
        )

    return CoverageComponent(
        score=100,
        weight=weight,
        weighted_score=round(100 * weight, 2),
        status="complete",
    )


def _evaluate_source_coverage(similarity: SimilarityAnalysisResult) -> CoverageComponent:
    weight = COVERAGE_WEIGHTS["source_inspection"]
    analyzed_files = similarity.coverage_statistics.get("candidate_files_analyzed", 0)

    if analyzed_files == 0:
        return CoverageComponent(
            score=0,
            weight=weight,
            weighted_score=0.0,
            status="unavailable",
            reason="No source files in supported languages were analyzable.",
        )

    if analyzed_files < 3:
        score = 60
        return CoverageComponent(
            score=score,
            weight=weight,
            weighted_score=round(score * weight, 2),
            status="partial",
            reason=f"Only {analyzed_files} source file(s) inspected.",
        )

    return CoverageComponent(
        score=100,
        weight=weight,
        weighted_score=round(100 * weight, 2),
        status="complete",
    )


def _evaluate_metadata_coverage(metadata: dict[str, Any]) -> CoverageComponent:
    weight = COVERAGE_WEIGHTS["metadata_availability"]
    if not metadata:
        return CoverageComponent(
            score=0,
            weight=weight,
            weighted_score=0.0,
            status="unavailable",
            reason="Repository metadata could not be retrieved.",
        )

    fields_present = 0
    total_fields = 4
    for key in ("default_branch", "license", "description", "visibility"):
        if metadata.get(key) is not None:
            fields_present += 1

    ratio = fields_present / total_fields
    score = round(ratio * 100)
    status = "complete" if score >= 75 else "partial"

    return CoverageComponent(
        score=score,
        weight=weight,
        weighted_score=round(score * weight, 2),
        status=status,
        reason=None if score >= 75 else "Some repository metadata attributes are unset.",
    )


def _evaluate_reference_coverage(similarity: SimilarityAnalysisResult) -> CoverageComponent:
    weight = COVERAGE_WEIGHTS["reference_comparison"]
    ref_files = similarity.coverage_statistics.get("reference_files_indexed", 0)

    if similarity.overlap_score.value is None or ref_files == 0:
        return CoverageComponent(
            score=0,
            weight=weight,
            weighted_score=0.0,
            status="unavailable",
            reason=similarity.overlap_score.reason
            or "Reference catalog collection was empty or unavailable.",
        )

    return CoverageComponent(
        score=100,
        weight=weight,
        weighted_score=round(100 * weight, 2),
        status="complete",
    )


def build_assessment(
    history: HistoryAnalysisResult,
    similarity: SimilarityAnalysisResult,
    metadata: dict[str, Any],
    identity_confirmation: dict[str, Any] | None = None,
) -> AssessmentResult:
    """
    Produces an explainable, reproducible evidence assessment.
    The evidence coverage score strictly measures available data for review and never
    represents candidate quality, authorship likelihood, or hiring suitability.
    """
    # 1. Evaluate coverage components
    components = {
        "history_availability": _evaluate_history_coverage(history),
        "source_inspection": _evaluate_source_coverage(similarity),
        "metadata_availability": _evaluate_metadata_coverage(metadata),
        "reference_comparison": _evaluate_reference_coverage(similarity),
    }

    # Deterministic weighted total
    total_score = round(sum(c.weighted_score for c in components.values()))
    total_score = max(0, min(100, total_score))

    # 2. Determine review status
    if (
        total_score >= 70
        and components["history_availability"].score > 0
        and components["source_inspection"].score > 0
    ):
        status = "reviewable"
    elif total_score >= 35:
        status = "limited_evidence"
    else:
        status = "insufficient_data"

    observations: list[Observation] = []
    interview_questions: list[str] = []

    # Map evidence IDs for verifiable link
    history_ev_ids = [str(ev.id) for ev in history.evidence]
    similarity_ev_ids = [str(ev.id) for ev in similarity.evidence]

    # 3. Generate observations strictly supported by evidence IDs
    if history.evidence:
        first_ev_id = [history_ev_ids[0]]
        observations.append(
            Observation(
                category="git_history",
                statement=(
                    f"Repository history contains {history.total_commits} reachable commits "
                    f"spanning {history.duration_days or 'N/A'} days with {len(history.contributors)} contributor(s) "
                    f"and {history.merge_commits} merge commit(s)."
                ),
                evidence_ids=first_ev_id,
            )
        )

    # Fork observation (fork status alone never reduces candidate credibility)
    is_fork = bool(metadata.get("is_fork", False))
    parent_url = metadata.get("parent_url")
    if is_fork and parent_url:
        ev_id = history_ev_ids[:1] if history_ev_ids else []
        observations.append(
            Observation(
                category="fork_status",
                statement=(
                    f"Repository is a fork of upstream source '{parent_url}'. "
                    f"Analysis reflects repository state and commit history reachable from the default branch."
                ),
                evidence_ids=ev_id,
            )
        )
        interview_questions.append(
            f"This project is based on a fork of {parent_url}. Which features, refactorings, or modifications represent your primary additions?"
        )

    # Timestamp anomalies
    if history.timestamp_anomalies:
        ev_id = history_ev_ids[:1] if history_ev_ids else []
        observations.append(
            Observation(
                category="timestamp_integrity",
                statement=(
                    f"Detected {len(history.timestamp_anomalies)} timestamp anomalie(s) in history. "
                    f"Git timestamps are user-configurable and can be modified or created during bulk imports."
                ),
                evidence_ids=ev_id,
            )
        )
        interview_questions.append(
            "Some commits in the history display atypical timestamps (e.g. committer date preceding author date). Can you describe your Git workflow or tooling during this project?"
        )

    # Candidate alias matching observation (distinguish declared ownership from independent identity)
    if history.alias_match_stats:
        ev_id = history_ev_ids[:1] if history_ev_ids else []
        stats = history.alias_match_stats
        observations.append(
            Observation(
                category="alias_heuristic",
                statement=(
                    f"Optional user-supplied aliases matched {stats['matched_commits_count']} of "
                    f"{history.total_commits} reachable commits ({stats['matched_percentage']}%). "
                    f"Identity heuristic is strictly unverified and does not establish verified authorship."
                ),
                evidence_ids=ev_id,
            )
        )

    # Similarity observation
    if similarity.evidence and similarity.overlap_score.value is not None:
        first_sim_id = [similarity_ev_ids[0]]
        overlap_val = similarity.overlap_score.value
        observations.append(
            Observation(
                category="code_similarity",
                statement=(
                    f"Calculated {overlap_val}% syntactic winnowing fingerprint overlap against the configured reference collection. "
                    f"This reflects shared language patterns or assignment archetypes without asserting copying direction."
                ),
                evidence_ids=first_sim_id,
            )
        )

        if similarity.matched_paths:
            top_match = similarity.matched_paths[0]
            interview_questions.append(
                f"File '{top_match.candidate_path}' shares syntactic patterns with reference repository '{top_match.reference_url}'. "
                f"How did starter code, course materials, or libraries influence your architecture in this module?"
            )

    # Concrete commit interview question
    if history.evidence and len(history.evidence) >= 2:
        recent_ev = history.evidence[1]
        if recent_ev.commit_sha:
            interview_questions.append(
                f"In commit {recent_ev.commit_sha[:8]} ('{recent_ev.summary}'), what design trade-offs did you consider when making those changes?"
            )

    # General technical interview question
    if similarity.coverage_statistics.get("candidate_files_analyzed", 0) > 0:
        interview_questions.append(
            "Could you walk us through the overall architectural division of responsibilities across the primary source modules in this repository?"
        )

    # Explicit limitations
    limitations: list[str] = [
        "The evidence coverage score measures available data for review only; it does not measure candidate competence, skill, honesty, or hiring suitability.",
        "Git history and authorship identities can be edited, spoofed, or imported from prior template repositories.",
        "Fork status is a standard open-source collaboration model and does not diminish candidate credibility.",
        "Similarity results are restricted exclusively to the small configured reference collection and do not prove copying direction.",
        "Assessment outputs are intended to guide structured human technical interviews, not to automatically rank or reject candidates.",
    ]

    return AssessmentResult(
        assessment_version=ASSESSMENT_VERSION,
        status=status,
        evidence_coverage_score=total_score,
        coverage_components=components,
        observations=observations,
        limitations=limitations,
        suggested_interview_questions=interview_questions,
    )
