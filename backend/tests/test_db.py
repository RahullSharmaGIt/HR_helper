import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db import Base, transaction_scope
from app.models.entities import (
    AnalysisJob,
    AnalysisResult,
    Candidate,
    Project,
    RepositorySelection,
    Resume,
)


@pytest.fixture
def db_session():
    # In-memory SQLite for fast testing
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_models_round_trip(db_session):
    # 1. Candidate
    candidate = Candidate(name="Jane Doe", email="jane@example.com")
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)

    assert isinstance(candidate.id, uuid.UUID)
    assert candidate.name == "Jane Doe"

    # 2. Resume (storage_key generated, not original filename)
    storage_key = f"resumes/{uuid.uuid4()}.pdf"
    resume = Resume(
        candidate_id=candidate.id,
        original_filename="JaneDoe_CV.pdf",
        storage_key=storage_key,
        content_type="application/pdf",
        file_size_bytes=1024,
        raw_text="Experienced engineer specializing in distributed systems.",
    )
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(resume)

    assert resume.candidate_id == candidate.id
    assert resume.storage_key == storage_key
    assert resume.storage_key != resume.original_filename

    # 3. Project
    project = Project(
        candidate_id=candidate.id,
        name="Event Broker",
        description="High throughput event broker in Go",
        source_page=1,
        explicit_github_urls=["https://github.com/janedoe/event-broker"],
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    assert project.candidate_id == candidate.id
    assert project.explicit_github_urls == ["https://github.com/janedoe/event-broker"]

    # 4. RepositorySelection
    repo_selection = RepositorySelection(
        project_id=project.id,
        url="https://github.com/janedoe/event-broker",
        owner="janedoe",
        name="event-broker",
        discovery_reason="Explicit URL in resume",
        confidence_category="high",
        is_confirmed=True,
    )
    db_session.add(repo_selection)
    db_session.commit()
    db_session.refresh(repo_selection)

    assert repo_selection.is_confirmed is True

    # 5. AnalysisJob
    job = AnalysisJob(
        repository_selection_id=repo_selection.id,
        status="running",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    assert job.status == "running"

    # 6. AnalysisResult
    report_dict = {
        "schema_version": "1.0.0",
        "repository": {"name": "event-broker", "owner": "janedoe"},
        "history": {"commits": 15},
        "similarity": {"corpus_match": None, "reason": "No matches found"},
        "assessment": {"notes": "Original code verified"},
        "evidence": [],
        "limitations": ["Small corpus"],
    }
    result = AnalysisResult(
        job_id=job.id,
        report=report_dict,
    )
    db_session.add(result)
    db_session.commit()
    db_session.refresh(result)

    assert result.job_id == job.id
    assert result.report["repository"]["name"] == "event-broker"


def test_storage_key_unique_constraint(db_session):
    candidate = Candidate(name="John Smith")
    db_session.add(candidate)
    db_session.commit()

    shared_key = "unique-key-123"
    resume1 = Resume(
        candidate_id=candidate.id,
        original_filename="cv1.pdf",
        storage_key=shared_key,
        content_type="application/pdf",
    )
    resume2 = Resume(
        candidate_id=candidate.id,
        original_filename="cv2.pdf",
        storage_key=shared_key,
        content_type="application/pdf",
    )
    db_session.add(resume1)
    db_session.commit()

    db_session.add(resume2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_cascade_delete(db_session):
    candidate = Candidate(name="Alice")
    db_session.add(candidate)
    db_session.commit()

    project = Project(
        candidate_id=candidate.id,
        name="Demo",
        explicit_github_urls=[],
    )
    db_session.add(project)
    db_session.commit()

    repo = RepositorySelection(
        project_id=project.id,
        url="https://github.com/alice/demo",
        owner="alice",
        name="demo",
        discovery_reason="Found",
        confidence_category="medium",
    )
    db_session.add(repo)
    db_session.commit()

    # Delete candidate should cascade delete project and repo
    db_session.delete(candidate)
    db_session.commit()

    assert db_session.query(Project).filter_by(id=project.id).first() is None
    assert db_session.query(RepositorySelection).filter_by(id=repo.id).first() is None


def test_transaction_scope_commit_and_rollback():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)

    # Success commit
    with transaction_scope(session_factory=TestingSession) as session:
        session.add(Candidate(name="Commit User"))

    with TestingSession() as session:
        assert session.query(Candidate).filter_by(name="Commit User").first() is not None

    # Rollback on exception
    with (
        pytest.raises(RuntimeError),
        transaction_scope(session_factory=TestingSession) as session,
    ):
        session.add(Candidate(name="Rollback User"))
        raise RuntimeError("Forced failure")

    with TestingSession() as session:
        assert session.query(Candidate).filter_by(name="Rollback User").first() is None
