import logging
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

import redis
from sqlalchemy.orm import Session

from app.config import settings
from app.db import transaction_scope
from app.models.entities import AnalysisJob, AnalysisResult, utc_now
from app.schemas.contracts import AnalysisReport, JobState
from app.services.github_client import (
    GitHubClient,
    GitHubRateLimitError,
    GitHubRepoNotFoundError,
    GitHubTransientError,
    normalize_github_repository_url,
)
from app.services.history_analyzer import analyze_history
from app.services.job_service import JobCanceledError
from app.services.reference_catalog import load_reference_catalog
from app.services.repository_fetcher import (
    GitFetchError,
    GitResourceLimitError,
    GitTimeoutError,
    fetch_repository,
)
from app.services.scoring import build_assessment
from app.services.similarity import build_reference_index, compare_repository

logger = logging.getLogger("analysis")


class FailureCode:
    METADATA_FETCH_FAILED = "METADATA_FETCH_FAILED"
    REPO_NOT_FOUND = "REPO_NOT_FOUND"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    GIT_FETCH_FAILED = "GIT_FETCH_FAILED"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    GIT_TIMEOUT = "GIT_TIMEOUT"
    HISTORY_ANALYSIS_FAILED = "HISTORY_ANALYSIS_FAILED"
    SIMILARITY_ANALYSIS_FAILED = "SIMILARITY_ANALYSIS_FAILED"
    ASSESSMENT_FAILED = "ASSESSMENT_FAILED"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"
    JOB_CANCELED = "JOB_CANCELED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


SENSITIVE_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9_]{36,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{82,}"),
    re.compile(r"bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"token\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"://[^:]+:[^@]+@"),  # Embedded credentials in URLs
]


def sanitize_diagnostic(message: str, max_length: int = 500) -> str:
    """Strips credentials, personal identifiers, and truncates diagnostic messages."""
    cleaned = str(message)
    for pattern in SENSITIVE_PATTERNS:
        cleaned = pattern.sub("[REDACTED_CREDENTIAL]", cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + " [TRUNCATED]"
    return cleaned


def _classify_failure_code(exception: Exception) -> str:
    if isinstance(exception, GitHubRepoNotFoundError):
        return FailureCode.REPO_NOT_FOUND
    if isinstance(exception, GitHubRateLimitError):
        return FailureCode.RATE_LIMIT_EXCEEDED
    if isinstance(exception, GitHubTransientError):
        return FailureCode.METADATA_FETCH_FAILED
    if isinstance(exception, GitResourceLimitError):
        return FailureCode.RESOURCE_LIMIT_EXCEEDED
    if isinstance(exception, GitTimeoutError):
        return FailureCode.GIT_TIMEOUT
    if isinstance(exception, GitFetchError):
        return FailureCode.GIT_FETCH_FAILED
    if isinstance(exception, JobCanceledError):
        return FailureCode.JOB_CANCELED
    return FailureCode.UNEXPECTED_ERROR


def _serialize_dataclass(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(by_alias=True)
    if hasattr(obj, "__dataclass_fields__"):
        return {f.name: _serialize_dataclass(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, list):
        return [_serialize_dataclass(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _serialize_dataclass(v) for k, v in obj.items()}
    if isinstance(obj, uuid.UUID):
        return str(obj)
    return obj


def _check_cancellation(job_id: uuid.UUID, session: Session, redis_client: Any = None) -> None:
    # 1. Redis flag check
    if redis_client is not None:
        try:
            if redis_client.get(f"cancel_job:{job_id}"):
                raise JobCanceledError(f"Analysis job {job_id} cancellation requested via Redis.")
        except JobCanceledError:
            raise
        except (redis.RedisError, OSError) as e:
            logger.debug("Redis cancellation lookup suppressed: %s", e)

    # 2. Database state check
    job = session.get(AnalysisJob, job_id)
    if job is None:
        raise JobCanceledError(f"Analysis job {job_id} was deleted; aborting execution.")
    if job.status == JobState.CANCELED.value:
        raise JobCanceledError(f"Analysis job {job_id} cancellation recorded in database.")


def _execute_analysis(
    session: Session,
    job_id: uuid.UUID,
    redis_client: Any = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    reference_catalog_path: Path | str | None = None,
    allow_file_transport: bool = False,
    github_client: Any = None,
) -> AnalysisReport | None:
    job = session.get(AnalysisJob, job_id)
    if not job:
        logger.error("Analysis job %s not found in database", job_id)
        return None

    if job.status == JobState.CANCELED.value:
        logger.info("Analysis job %s is already canceled; skipping", job_id)
        return None

    workspace_dir: Path | None = None
    allow_file_transport = allow_file_transport or settings.allow_test_adapters

    try:
        # Initial transition to running
        job.status = JobState.RUNNING.value
        job.stage = "metadata"
        job.progress = 10
        job.started_at = utc_now()
        session.flush()

        # ---------------------------------------------------------
        # Stage 1: Metadata
        # ---------------------------------------------------------
        _check_cancellation(job_id, session, redis_client)
        repo_url = job.selected_repository_url or job.repository_selection.url
        if not allow_file_transport:
            canonical_url = normalize_github_repository_url(repo_url)
            path_parts = canonical_url.removeprefix("https://github.com/").split("/")
            owner, repo_name = path_parts[0], path_parts[1]
        else:
            canonical_url = repo_url
            owner = job.repository_selection.owner if job.repository_selection else "test-owner"
            repo_name = job.repository_selection.name if job.repository_selection else "test-repo"

        gh = github_client or GitHubClient(redis_client=redis_client)
        metadata = gh.get_repository_metadata(owner, repo_name)

        job.progress = 25
        session.flush()

        # ---------------------------------------------------------
        # Stage 2: Fetch
        # ---------------------------------------------------------
        _check_cancellation(job_id, session, redis_client)
        job.stage = "fetch"
        job.progress = 30
        session.flush()

        manifest = fetch_repository(
            repository_url=canonical_url,
            job_id=job.id,
            runner=runner,
            allow_file_transport=allow_file_transport,
        )
        workspace_dir = Path(manifest.workspace_key)

        # Persist analyzed HEAD SHA
        job.analyzed_commit_sha = manifest.analyzed_head_sha
        job.progress = 50
        session.flush()

        # ---------------------------------------------------------
        # Stage 3: History Analysis
        # ---------------------------------------------------------
        _check_cancellation(job_id, session, redis_client)
        job.stage = "history"
        job.progress = 55
        session.flush()

        # Candidate aliases for optional heuristics
        candidate_aliases: list[str] | None = None
        if (
            job.repository_selection
            and job.repository_selection.project
            and job.repository_selection.project.candidate
        ):
            candidate_aliases = [job.repository_selection.project.candidate.name]

        history_result = analyze_history(
            repository=manifest,
            candidate_aliases=candidate_aliases,
            runner=runner,
        )

        job.progress = 70
        session.flush()

        # ---------------------------------------------------------
        # Stage 4: Similarity Comparison
        # ---------------------------------------------------------
        _check_cancellation(job_id, session, redis_client)
        job.stage = "similarity"
        job.progress = 75
        session.flush()

        catalog_path = (
            Path(reference_catalog_path)
            if reference_catalog_path
            else Path(__file__).resolve().parent.parent.parent / "reference_catalog.json"
        )
        catalog = load_reference_catalog(catalog_path)
        ref_index = build_reference_index(catalog)
        similarity_result = compare_repository(manifest, ref_index, runner=runner)

        job.progress = 85
        session.flush()

        # ---------------------------------------------------------
        # Stage 5: Assessment Construction
        # ---------------------------------------------------------
        _check_cancellation(job_id, session, redis_client)
        job.stage = "assessment"
        job.progress = 90
        session.flush()

        assessment_result = build_assessment(
            history=history_result,
            similarity=similarity_result,
            metadata=metadata,
        )

        # ---------------------------------------------------------
        # Stage 6: Persistence (Idempotent)
        # ---------------------------------------------------------
        _check_cancellation(job_id, session, redis_client)
        job.stage = "persistence"
        job.progress = 95
        session.flush()

        all_evidence = list(history_result.evidence) + list(similarity_result.evidence)
        all_limitations: list[str] = []
        for lim in (
            history_result.limitations
            + similarity_result.limitations
            + assessment_result.limitations
        ):
            if lim not in all_limitations:
                all_limitations.append(lim)

        report = AnalysisReport(
            schema_version="1.0.0",
            analyzed_commit_sha=job.analyzed_commit_sha,
            repository=metadata,
            history=_serialize_dataclass(history_result),
            similarity=_serialize_dataclass(similarity_result),
            assessment=_serialize_dataclass(assessment_result),
            evidence=all_evidence,
            limitations=all_limitations,
        )

        report_payload = report.model_dump(by_alias=True, mode="json")

        # Idempotent result persistence
        existing_result = (
            session.query(AnalysisResult).filter(AnalysisResult.job_id == job.id).first()
        )
        if existing_result:
            existing_result.report = report_payload
        else:
            analysis_result = AnalysisResult(
                id=uuid.uuid4(),
                job_id=job.id,
                report=report_payload,
            )
            session.add(analysis_result)

        job.status = JobState.SUCCEEDED.value
        job.stage = "persistence"
        job.progress = 100
        job.completed_at = utc_now()
        job.failure_code = None
        job.error_message = None
        session.flush()

        return report

    except JobCanceledError as e:
        logger.info("Job %s was canceled or deleted: %s", job_id, e)
        current_job = session.get(AnalysisJob, job_id)
        if current_job is not None:
            current_job.status = JobState.CANCELED.value
            current_job.stage = "canceled"
            current_job.failure_code = FailureCode.JOB_CANCELED
            current_job.error_message = sanitize_diagnostic(str(e))
            current_job.completed_at = utc_now()
            session.flush()
        return None

    except (GitHubTransientError, GitHubRateLimitError, GitTimeoutError) as e:
        # Transient failure: record diagnostic context and re-raise for bounded RQ Retry
        logger.warning("Transient failure during job %s stage '%s': %s", job_id, job.stage, e)
        job.failure_code = _classify_failure_code(e)
        job.error_message = sanitize_diagnostic(f"Transient error (retryable): {e}")
        session.flush()
        raise

    except Exception as e:  # noqa: BLE001
        # Non-transient failure: record structured code, do not re-raise so worker marks job terminal
        logger.error("Non-transient failure during job %s stage '%s': %s", job_id, job.stage, e)
        job.status = JobState.FAILED.value
        job.failure_code = _classify_failure_code(e)
        job.error_message = sanitize_diagnostic(str(e))
        job.completed_at = utc_now()
        session.flush()
        return None

    finally:
        # Always clean temporary workspaces
        if workspace_dir and workspace_dir.exists():
            try:
                shutil.rmtree(workspace_dir, ignore_errors=True)
                logger.info("Cleaned temporary workspace: %s", workspace_dir)
            except OSError as clean_err:
                logger.warning(
                    "Error cleaning workspace %s: %s",
                    workspace_dir,
                    clean_err,
                )


def run_analysis(
    job_id: str | uuid.UUID,
    session: Session | None = None,
    redis_client: Any = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    reference_catalog_path: Path | str | None = None,
    allow_file_transport: bool = False,
    github_client: Any = None,
) -> AnalysisReport | None:
    """Executes the end-to-end repository analysis pipeline.

    Stages: metadata -> fetch -> history -> similarity -> assessment -> persistence.
    Designed for execution by background RQ workers with support for standalone test doubles.
    """
    j_uuid = uuid.UUID(str(job_id))
    if session is not None:
        return _execute_analysis(
            session=session,
            job_id=j_uuid,
            redis_client=redis_client,
            runner=runner,
            reference_catalog_path=reference_catalog_path,
            allow_file_transport=allow_file_transport,
            github_client=github_client,
        )

    with transaction_scope() as sess:
        return _execute_analysis(
            session=sess,
            job_id=j_uuid,
            redis_client=redis_client,
            runner=runner,
            reference_catalog_path=reference_catalog_path,
            allow_file_transport=allow_file_transport,
            github_client=github_client,
        )
