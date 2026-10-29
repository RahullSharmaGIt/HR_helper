import os
import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sqlalchemy.exc as sa_exc
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.jobs.analysis import FailureCode, run_analysis, sanitize_diagnostic
from app.models.entities import (
    AnalysisJob,
    AnalysisResult,
    Candidate,
    Project,
    RepositorySelection,
)
from app.schemas.contracts import JobState
from app.services.github_client import (
    GitHubRepoNotFoundError,
    GitHubTransientError,
)
from app.services.job_service import (
    CrossCandidateProjectError,
    DuplicateActiveJobError,
    JobNotFoundError,
    QueueEnqueueError,
    RepositoryNotConfirmedError,
    cancel_analysis,
    enqueue_analysis,
)


class MockQueue:
    def __init__(self, fail_enqueue: bool = False):
        self.enqueued: list[dict] = []
        self.canceled: list[str] = []
        self.fail_enqueue = fail_enqueue

    def enqueue(self, func, *args, **kwargs):
        if self.fail_enqueue:
            raise RuntimeError("Redis connection dropped during enqueue")
        job_id = kwargs.get("job_id") or str(uuid.uuid4())
        mock_job = MagicMock()
        mock_job.id = job_id
        self.enqueued.append(
            {
                "func": func,
                "args": args,
                "kwargs": kwargs,
                "job": mock_job,
            }
        )
        return mock_job

    def cancel(self, job_id: str):
        self.canceled.append(job_id)


class MockRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, val: str, ex: int | None = None) -> None:
        self.store[key] = str(val)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def candidate_data(db_session: Session) -> tuple[Candidate, Project, RepositorySelection]:
    candidate = Candidate(id=uuid.uuid4(), name="Alice Test", email="alice@example.com")
    project = Project(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        name="Portfolio Review",
        description="Candidate review platform",
    )
    repo_selection = RepositorySelection(
        id=uuid.uuid4(),
        project_id=project.id,
        url="https://github.com/alice/portfolio-review",
        owner="alice",
        name="portfolio-review",
        discovery_reason="Explicit resume link",
        confidence_category="high",
        is_confirmed=True,
    )
    db_session.add_all([candidate, project, repo_selection])
    db_session.commit()
    return candidate, project, repo_selection


@pytest.fixture
def synthetic_source_git_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "synthetic_source"
    repo_dir.mkdir()

    env = {
        "GIT_AUTHOR_NAME": "Alice Test",
        "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_AUTHOR_DATE": "2024-01-01T12:00:00Z",
        "GIT_COMMITTER_NAME": "Alice Test",
        "GIT_COMMITTER_EMAIL": "alice@example.com",
        "GIT_COMMITTER_DATE": "2024-01-01T12:00:00Z",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
    }

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, env=env)
    py_file = repo_dir / "calculator.py"
    py_file.write_text(
        "def compute_sum(a, b):\n    return a + b\n\ndef compute_diff(a, b):\n    return a - b\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-m", "Initial calculator implementation"],
        cwd=repo_dir,
        check=True,
        env=env,
    )
    return repo_dir


def test_enqueue_unconfirmed_repository_fails(
    db_session: Session,
    candidate_data: tuple[Candidate, Project, RepositorySelection],
):
    _, project, repo_selection = candidate_data
    repo_selection.is_confirmed = False
    db_session.commit()

    mock_q = MockQueue()
    with pytest.raises(
        RepositoryNotConfirmedError, match="confirmation is required before enqueueing"
    ):
        enqueue_analysis(project.id, repo_selection.id, queue=mock_q, session=db_session)

    assert len(mock_q.enqueued) == 0
    jobs_count = db_session.query(AnalysisJob).count()
    assert jobs_count == 0


def test_enqueue_mismatched_project_fails(
    db_session: Session,
    candidate_data: tuple[Candidate, Project, RepositorySelection],
):
    candidate, _, repo_selection = candidate_data
    other_project = Project(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        name="Other Project",
    )
    db_session.add(other_project)
    db_session.commit()

    mock_q = MockQueue()
    with pytest.raises(CrossCandidateProjectError, match="belongs to project"):
        enqueue_analysis(other_project.id, repo_selection.id, queue=mock_q, session=db_session)

    assert len(mock_q.enqueued) == 0


def test_enqueue_success_and_duplicate_active_job_prevention(
    db_session: Session,
    candidate_data: tuple[Candidate, Project, RepositorySelection],
):
    _, project, repo_selection = candidate_data
    mock_q = MockQueue()

    # 1. First enqueue succeeds
    job = enqueue_analysis(project.id, repo_selection.id, queue=mock_q, session=db_session)
    assert job is not None
    assert job.status == JobState.QUEUED.value
    assert job.stage == "queued"
    assert job.progress == 0
    assert job.selected_repository_url == repo_selection.url
    assert len(mock_q.enqueued) == 1

    # 2. Second enqueue on same selection raises DuplicateActiveJobError
    with pytest.raises(DuplicateActiveJobError, match="already exists"):
        enqueue_analysis(project.id, repo_selection.id, queue=mock_q, session=db_session)

    # 3. Direct DB insert of second active job triggers unique constraint
    second_job = AnalysisJob(
        id=uuid.uuid4(),
        repository_selection_id=repo_selection.id,
        status="running",
        stage="metadata",
    )
    db_session.add(second_job)
    with pytest.raises(sa_exc.IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_enqueue_queue_failure_rolls_back(
    db_session: Session,
    candidate_data: tuple[Candidate, Project, RepositorySelection],
):
    _, project, repo_selection = candidate_data
    failing_queue = MockQueue(fail_enqueue=True)

    with pytest.raises(QueueEnqueueError, match="Failed to enqueue analysis job"):
        enqueue_analysis(project.id, repo_selection.id, queue=failing_queue, session=db_session)

    # Verify no running or queued job is left in DB
    active_jobs = (
        db_session.query(AnalysisJob)
        .filter(
            AnalysisJob.repository_selection_id == repo_selection.id,
            AnalysisJob.status.in_([JobState.QUEUED.value, JobState.RUNNING.value]),
        )
        .all()
    )
    assert len(active_jobs) == 0


def test_cancel_analysis_flow(
    db_session: Session,
    candidate_data: tuple[Candidate, Project, RepositorySelection],
):
    _, project, repo_selection = candidate_data
    mock_q = MockQueue()
    mock_r = MockRedis()

    job = enqueue_analysis(project.id, repo_selection.id, queue=mock_q, session=db_session)

    # Cancel pending job
    canceled_job = cancel_analysis(job.id, queue=mock_q, session=db_session, redis_client=mock_r)
    assert canceled_job.status == JobState.CANCELED.value
    assert canceled_job.stage == "canceled"
    assert canceled_job.failure_code == "JOB_CANCELED"
    assert canceled_job.completed_at is not None
    assert str(job.id) in mock_q.canceled
    assert mock_r.get(f"cancel_job:{job.id}") == "1"

    # Canceling an already terminal job is a no-op
    repeat_cancel = cancel_analysis(job.id, queue=mock_q, session=db_session, redis_client=mock_r)
    assert repeat_cancel.status == JobState.CANCELED.value

    # Canceling non-existent job raises JobNotFoundError
    with pytest.raises(JobNotFoundError):
        cancel_analysis(uuid.uuid4(), session=db_session)


def test_run_analysis_success_end_to_end_and_idempotency(
    db_session: Session,
    candidate_data: tuple[Candidate, Project, RepositorySelection],
    synthetic_source_git_repo: Path,
):
    _, project, repo_selection = candidate_data
    mock_q = MockQueue()
    mock_r = MockRedis()

    job = enqueue_analysis(project.id, repo_selection.id, queue=mock_q, session=db_session)
    job.selected_repository_url = str(synthetic_source_git_repo)
    db_session.commit()

    # Mock GitHubClient
    mock_gh = MagicMock()
    mock_gh.get_repository_metadata.return_value = {
        "url": "https://github.com/alice/portfolio-review",
        "owner": "alice",
        "name": "portfolio-review",
        "default_branch": "main",
        "visibility": "public",
        "is_fork": False,
        "parent_url": None,
        "license": "MIT",
        "description": "Portfolio review platform",
    }

    # Execute run_analysis end-to-end
    report = run_analysis(
        job_id=job.id,
        session=db_session,
        redis_client=mock_r,
        allow_file_transport=True,
        github_client=mock_gh,
    )

    assert report is not None
    assert report.repository["name"] == "portfolio-review"
    assert "total_commits" in report.history
    assert "overlap_score" in report.similarity
    assert report.assessment["status"] in {"reviewable", "limited_evidence"}

    # Verify job record state in DB
    refreshed_job = db_session.get(AnalysisJob, job.id)
    assert refreshed_job.status == JobState.SUCCEEDED.value
    assert refreshed_job.stage == "persistence"
    assert refreshed_job.progress == 100
    assert refreshed_job.started_at is not None
    assert refreshed_job.completed_at is not None
    assert refreshed_job.analyzed_commit_sha is not None
    assert len(refreshed_job.analyzed_commit_sha) == 40
    assert refreshed_job.failure_code is None

    # Verify analysis result record
    result_record = db_session.query(AnalysisResult).filter(AnalysisResult.job_id == job.id).first()
    assert result_record is not None
    assert result_record.report["repository"]["owner"] == "alice"

    # Test idempotency: re-running does not fail on duplicate key and updates record cleanly
    repeat_report = run_analysis(
        job_id=job.id,
        session=db_session,
        redis_client=mock_r,
        allow_file_transport=True,
        github_client=mock_gh,
    )
    assert repeat_report is not None
    all_results = db_session.query(AnalysisResult).filter(AnalysisResult.job_id == job.id).all()
    assert len(all_results) == 1


def test_run_analysis_transient_failure_retries(
    db_session: Session,
    candidate_data: tuple[Candidate, Project, RepositorySelection],
):
    _, project, repo_selection = candidate_data
    mock_q = MockQueue()
    mock_r = MockRedis()

    job = enqueue_analysis(project.id, repo_selection.id, queue=mock_q, session=db_session)

    mock_gh = MagicMock()
    mock_gh.get_repository_metadata.side_effect = GitHubTransientError(
        "Temporary 503 Service Unavailable"
    )

    with pytest.raises(GitHubTransientError):
        run_analysis(
            job_id=job.id,
            session=db_session,
            redis_client=mock_r,
            github_client=mock_gh,
        )

    refreshed_job = db_session.get(AnalysisJob, job.id)
    assert refreshed_job.failure_code == FailureCode.METADATA_FETCH_FAILED
    assert "Transient error (retryable)" in refreshed_job.error_message


def test_run_analysis_non_transient_failure_terminates_and_cleans(
    db_session: Session,
    candidate_data: tuple[Candidate, Project, RepositorySelection],
):
    _, project, repo_selection = candidate_data
    mock_q = MockQueue()
    mock_r = MockRedis()

    job = enqueue_analysis(project.id, repo_selection.id, queue=mock_q, session=db_session)

    mock_gh = MagicMock()
    mock_gh.get_repository_metadata.side_effect = GitHubRepoNotFoundError(
        "Repository not found or private (Token: ghp_SECRET1234567890abcdef1234567890abcdef)"
    )

    # Does not raise exception for non-transient error
    result = run_analysis(
        job_id=job.id,
        session=db_session,
        redis_client=mock_r,
        github_client=mock_gh,
    )
    assert result is None

    refreshed_job = db_session.get(AnalysisJob, job.id)
    assert refreshed_job.status == JobState.FAILED.value
    assert refreshed_job.failure_code == FailureCode.REPO_NOT_FOUND
    assert refreshed_job.completed_at is not None

    # Verify credentials redacted
    assert "ghp_SECRET" not in refreshed_job.error_message
    assert "[REDACTED_CREDENTIAL]" in refreshed_job.error_message


def test_run_analysis_cancellation_during_pipeline(
    db_session: Session,
    candidate_data: tuple[Candidate, Project, RepositorySelection],
):
    _, project, repo_selection = candidate_data
    mock_q = MockQueue()
    mock_r = MockRedis()

    job = enqueue_analysis(project.id, repo_selection.id, queue=mock_q, session=db_session)

    # Signal cancel via Redis flag
    mock_r.set(f"cancel_job:{job.id}", "1")

    mock_gh = MagicMock()

    result = run_analysis(
        job_id=job.id,
        session=db_session,
        redis_client=mock_r,
        github_client=mock_gh,
    )
    assert result is None

    refreshed_job = db_session.get(AnalysisJob, job.id)
    assert refreshed_job.status == JobState.CANCELED.value
    assert refreshed_job.stage == "canceled"
    assert refreshed_job.failure_code == FailureCode.JOB_CANCELED
    assert refreshed_job.completed_at is not None
    # Stage 1 was never called
    mock_gh.get_repository_metadata.assert_not_called()


def test_sanitize_diagnostic():
    raw_error = (
        "Failed with token ghp_123456789012345678901234567890123456 "
        "and bearer eyJhbGciOiJIUzI1NiJ9.test and https://user:pass123@github.com"
    )
    cleaned = sanitize_diagnostic(raw_error)
    assert "ghp_" not in cleaned
    assert "eyJhbGciOiJIUzI1NiJ9" not in cleaned
    assert "pass123" not in cleaned
    assert "[REDACTED_CREDENTIAL]" in cleaned
