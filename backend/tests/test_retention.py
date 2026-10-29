import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base
from app.models.entities import (
    AnalysisJob,
    AnalysisResult,
    Candidate,
    Project,
    RepositorySelection,
    Resume,
)
from app.services.retention import (
    run_retention_cleanup,
)


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "storage_dir", str(storage_dir))
    return storage_dir


def create_mock_candidate(
    db: Session,
    storage_dir: Path,
    created_at: datetime,
    is_active_job: bool = False,
) -> tuple[Candidate, Path, Path]:
    candidate = Candidate(
        id=uuid.uuid4(),
        name="Test Candidate",
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(candidate)
    db.flush()

    # Uploaded resume file
    resume_file = storage_dir / f"resumes/{uuid.uuid4().hex}.pdf"
    resume_file.parent.mkdir(parents=True, exist_ok=True)
    resume_file.write_bytes(b"%PDF-1.4 mock content")

    resume = Resume(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        original_filename="sample_resume.pdf",
        storage_key=f"resumes/{resume_file.name}",
        content_type="application/pdf",
        created_at=created_at,
    )
    db.add(resume)

    project = Project(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        name="Portfolio Project",
        created_at=created_at,
    )
    db.add(project)
    db.flush()

    repo_sel = RepositorySelection(
        id=uuid.uuid4(),
        project_id=project.id,
        url="https://github.com/example/repo",
        owner="example",
        name="repo",
        discovery_reason="explicit link",
        confidence_category="high",
        is_confirmed=True,
        created_at=created_at,
    )
    db.add(repo_sel)
    db.flush()

    job_status = "running" if is_active_job else "completed"
    job = AnalysisJob(
        id=uuid.uuid4(),
        repository_selection_id=repo_sel.id,
        status=job_status,
        created_at=created_at,
    )
    db.add(job)
    db.flush()

    # Workspace directory
    workspace_dir = storage_dir / "workspaces" / f"job_{job.id}_test"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "test_file.txt").write_text("workspace content")

    if not is_active_job:
        result = AnalysisResult(
            id=uuid.uuid4(),
            job_id=job.id,
            report={"status": "reviewable"},
            created_at=created_at,
        )
        db.add(result)

    db.commit()
    return candidate, resume_file, workspace_dir


def test_retention_cutoff_evaluation(test_db, isolated_storage):
    now = datetime.now(UTC)
    old_date = now - timedelta(days=10)
    recent_date = now - timedelta(days=2)

    old_cand, old_file, old_ws = create_mock_candidate(test_db, isolated_storage, old_date)
    rec_cand, rec_file, rec_ws = create_mock_candidate(test_db, isolated_storage, recent_date)

    # Run dry-run with default 7 days
    summary = run_retention_cleanup(test_db, days=7, dry_run=True)

    assert summary.dry_run is True
    assert summary.candidates_deleted == 1
    assert summary.resumes_deleted == 1
    assert summary.workspaces_deleted == 1

    # Verify dry run did NOT delete database records or files
    assert test_db.get(Candidate, old_cand.id) is not None
    assert test_db.get(Candidate, rec_cand.id) is not None
    assert old_file.exists() is True
    assert rec_file.exists() is True
    assert old_ws.exists() is True
    assert rec_ws.exists() is True


def test_retention_execute_mode(test_db, isolated_storage):
    now = datetime.now(UTC)
    old_date = now - timedelta(days=12)
    recent_date = now - timedelta(days=1)

    old_cand, old_file, old_ws = create_mock_candidate(test_db, isolated_storage, old_date)
    rec_cand, rec_file, rec_ws = create_mock_candidate(test_db, isolated_storage, recent_date)

    summary = run_retention_cleanup(test_db, days=7, dry_run=False)

    assert summary.dry_run is False
    assert summary.candidates_deleted == 1
    assert summary.resumes_deleted == 1

    # Verify old candidate and assets were deleted
    assert test_db.get(Candidate, old_cand.id) is None
    assert old_file.exists() is False
    assert old_ws.exists() is False

    # Verify recent candidate and assets remain intact
    assert test_db.get(Candidate, rec_cand.id) is not None
    assert rec_file.exists() is True
    assert rec_ws.exists() is True


def test_retention_cancels_active_work(test_db, isolated_storage):
    now = datetime.now(UTC)
    old_date = now - timedelta(days=9)

    cand, resume_file, ws_dir = create_mock_candidate(
        test_db, isolated_storage, old_date, is_active_job=True
    )

    with patch("app.services.retention.cancel_analysis") as mock_cancel:
        summary = run_retention_cleanup(test_db, days=7, dry_run=False)
        assert summary.candidates_deleted == 1
        assert mock_cancel.called


def test_retention_cleanup_idempotency(test_db, isolated_storage):
    now = datetime.now(UTC)
    old_date = now - timedelta(days=8)

    create_mock_candidate(test_db, isolated_storage, old_date)

    # First run executes cleanup
    summary_1 = run_retention_cleanup(test_db, days=7, dry_run=False)
    assert summary_1.candidates_deleted == 1

    # Second run should find nothing to clean up and succeed idempotently
    summary_2 = run_retention_cleanup(test_db, days=7, dry_run=False)
    assert summary_2.candidates_deleted == 0
    assert summary_2.resumes_deleted == 0
    assert summary_2.jobs_cancelled == 0
    assert summary_2.workspaces_deleted == 0


def test_runnable_cleanup_script(tmp_path):
    # Test script execution with --dry-run on a temporary SQLite DB
    db_file = tmp_path / "test_retention.db"
    db_url = f"sqlite:///{db_file}"

    # Initialize tables in the test SQLite DB
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    cmd = [
        sys.executable,
        "scripts/cleanup.py",
        "--days",
        "7",
        "--dry-run",
    ]
    env = {
        **os.environ,
        "PYTHONPATH": "backend",
        "DATABASE_URL": db_url,
    }
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert result.returncode == 0
    assert "Retention cleanup completed" in result.stdout
    assert "[DRY-RUN]" in result.stdout
