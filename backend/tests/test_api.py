import io
import json
import uuid
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import _LOCAL_SESSION_STORE, _LOCAL_THROTTLE_STORE
from app.config import settings
from app.db import Base, get_db
from app.jobs.analysis import run_analysis
from app.main import app, export_openapi
from app.models.entities import (
    AnalysisJob,
    AnalysisResult,
    Candidate,
    Project,
    RepositorySelection,
    Resume,
)
from app.schemas.contracts import JobState, RepositoryMatch


class MockQueue:
    def __init__(self):
        self.enqueued = []
        self.canceled = []

    def enqueue(self, func, *args, **kwargs):
        job_id = kwargs.get("job_id") or str(uuid.uuid4())
        mock_job = MagicMock()
        mock_job.id = job_id
        self.enqueued.append({"func": func, "args": args, "kwargs": kwargs, "job": mock_job})
        return mock_job

    def cancel(self, job_id: str):
        self.canceled.append(job_id)


@pytest.fixture
def test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(test_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def test_db_session(session_factory) -> Generator[Session, None, None]:
    session = session_factory()
    yield session
    session.expunge_all()
    session.close()


@pytest.fixture
def client(session_factory, test_db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db():
        sess = session_factory()
        try:
            yield sess
        finally:
            sess.close()

    app.dependency_overrides[get_db] = override_get_db
    _LOCAL_SESSION_STORE.clear()
    _LOCAL_THROTTLE_STORE.clear()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    _LOCAL_SESSION_STORE.clear()
    _LOCAL_THROTTLE_STORE.clear()


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    """Logs in and returns headers containing CSRF token and valid Origin."""
    res = client.post(
        "/api/v1/session",
        json={"password": "admin123"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert res.status_code == 200
    data = res.json()
    csrf_token = data["csrfToken"]
    return {
        "X-CSRF-Token": csrf_token,
        "Origin": "http://localhost:3000",
    }


def test_login_success_and_logout(client: TestClient):
    # 1. Login
    res = client.post(
        "/api/v1/session",
        json={"password": "admin123"},
        headers={"Origin": "http://localhost:3000", "X-Request-ID": "test-req-123"},
    )
    assert res.status_code == 200
    assert "csrfToken" in res.json()
    assert "session_token" in res.cookies
    assert res.headers.get("X-Request-ID") == "test-req-123"

    # 2. Logout
    logout_res = client.delete(
        "/api/v1/session",
        headers={"Origin": "http://localhost:3000"},
    )
    assert logout_res.status_code == 200
    assert logout_res.json() == {"status": "ok"}


def test_login_invalid_password(client: TestClient):
    res = client.post(
        "/api/v1/session",
        json={"password": "wrong-password"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert res.status_code == 401
    err = res.json()
    assert err["code"] == "INVALID_CREDENTIALS"
    assert "requestId" in err


def test_login_throttling(client: TestClient):
    for _ in range(5):
        res = client.post(
            "/api/v1/session",
            json={"password": "wrong-password"},
            headers={"Origin": "http://localhost:3000"},
        )
        assert res.status_code == 401

    # 6th attempt should be throttled
    throttled_res = client.post(
        "/api/v1/session",
        json={"password": "admin123"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert throttled_res.status_code == 429
    assert throttled_res.json()["code"] == "LOGIN_THROTTLED"


def test_authentication_required(client: TestClient):
    # Unauthenticated request to protected endpoint
    res = client.get("/api/v1/candidates")
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


def test_csrf_and_origin_checks(client: TestClient, auth_headers: dict[str, str]):
    candidate_id = uuid.uuid4()

    # 1. Missing CSRF Token
    res_no_csrf = client.delete(
        f"/api/v1/candidates/{candidate_id}",
        headers={"Origin": "http://localhost:3000"},
    )
    assert res_no_csrf.status_code == 403
    assert res_no_csrf.json()["code"] == "CSRF_TOKEN_INVALID"

    # 2. Invalid CSRF Token
    res_bad_csrf = client.delete(
        f"/api/v1/candidates/{candidate_id}",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": "invalid-token"},
    )
    assert res_bad_csrf.status_code == 403
    assert res_bad_csrf.json()["code"] == "CSRF_TOKEN_INVALID"

    # 3. Disallowed Origin
    res_bad_origin = client.delete(
        f"/api/v1/candidates/{candidate_id}",
        headers={
            "Origin": "https://malicious-external-site.com",
            "X-CSRF-Token": auth_headers["X-CSRF-Token"],
        },
    )
    assert res_bad_origin.status_code == 403
    assert res_bad_origin.json()["code"] == "INVALID_ORIGIN"


def test_resume_batches_intake(
    client: TestClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
):
    # 1. Empty batch
    res_empty = client.post(
        "/api/v1/resume-batches",
        files=[],
        headers=auth_headers,
    )
    assert res_empty.status_code in {400, 422}

    # 2. Valid PDF file
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (50, 72),
        "Jane Doe\nEmail: jane@example.com\n\nPROJECTS\n"
        "Distributed Task Queue: Implemented asynchronous worker system.\n"
        "https://github.com/janedoe/task-queue\n",
    )
    pdf_bytes = doc.tobytes()
    doc.close()

    # Mock discover_repositories to avoid live GitHub API in tests
    with patch("app.api.routes.discover_repositories") as mock_disc:
        mock_disc.return_value = [
            RepositoryMatch(
                url="https://github.com/janedoe/task-queue",
                owner="janedoe",
                name="task-queue",
                discovery_reason="Explicit resume link",
                confidence_category="high",
            )
        ]
        res_upload = client.post(
            "/api/v1/resume-batches",
            files=[
                ("files", ("jane_doe_resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")),
                (
                    "files",
                    ("corrupted_resume.pdf", io.BytesIO(b"not a valid pdf"), "application/pdf"),
                ),
            ],
            headers=auth_headers,
        )

    assert res_upload.status_code == 200
    data = res_upload.json()
    assert data["total"] == 2
    assert len(data["successful"]) == 1
    assert data["successful"][0]["filename"] == "jane_doe_resume.pdf"
    assert len(data["failed"]) == 1
    assert data["failed"][0]["filename"] == "corrupted_resume.pdf"


def test_full_workflow_candidates_projects_analyses(
    client: TestClient,
    auth_headers: dict[str, str],
    test_db_session: Session,
):
    # 1. Create candidate, project, and selection directly in test session
    candidate = Candidate(id=uuid.uuid4(), name="Bob Architect", email="bob@example.com")
    project = Project(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        name="Microservices Gateway",
        description="API gateway routing service",
        is_selected=False,
    )
    selection = RepositorySelection(
        id=uuid.uuid4(),
        project_id=project.id,
        url="https://github.com/bob/gateway",
        owner="bob",
        name="gateway",
        discovery_reason="Explicit link",
        confidence_category="high",
        is_confirmed=False,
    )
    test_db_session.add_all([candidate, project, selection])
    test_db_session.commit()

    # 2. GET /candidates
    res_candidates = client.get("/api/v1/candidates")
    assert res_candidates.status_code == 200
    candidates_list = res_candidates.json()
    assert len(candidates_list) == 1
    assert candidates_list[0]["name"] == "Bob Architect"

    # 3. GET /candidates/{id}
    res_detail = client.get(f"/api/v1/candidates/{candidate.id}")
    assert res_detail.status_code == 200
    assert len(res_detail.json()["projects"]) == 1

    # 4. PUT /candidates/{id}/selected-project
    res_sel_proj = client.put(
        f"/api/v1/candidates/{candidate.id}/selected-project",
        json={"projectId": str(project.id)},
        headers=auth_headers,
    )
    assert res_sel_proj.status_code == 200
    assert res_sel_proj.json()["selectedProjectId"] == str(project.id)

    # 5. GET /projects/{id}/repositories
    res_repos = client.get(f"/api/v1/projects/{project.id}/repositories")
    assert res_repos.status_code == 200
    repos = res_repos.json()
    assert len(repos) == 1
    assert repos[0]["isConfirmed"] is False

    # 6. POST /projects/{id}/analyses before confirmation fails with 400
    res_unconfirmed_enqueue = client.post(
        f"/api/v1/projects/{project.id}/analyses",
        headers=auth_headers,
    )
    assert res_unconfirmed_enqueue.status_code == 400
    assert res_unconfirmed_enqueue.json()["code"] == "UNCONFIRMED_REPOSITORY"

    # 7. PUT /projects/{id}/repository-selection to confirm selection
    res_confirm = client.put(
        f"/api/v1/projects/{project.id}/repository-selection",
        json={"repositorySelectionId": str(selection.id)},
        headers=auth_headers,
    )
    assert res_confirm.status_code == 200
    assert res_confirm.json()["isConfirmed"] is True

    # 8. POST /projects/{id}/analyses succeeds and returns 202 Accepted
    _mock_q = MockQueue()
    with patch("app.api.routes.enqueue_analysis") as mock_enqueue:
        job_id = uuid.uuid4()
        mock_job = AnalysisJob(
            id=job_id,
            repository_selection_id=selection.id,
            status=JobState.QUEUED.value,
            stage="queued",
            progress=0,
            selected_repository_url=selection.url,
        )
        test_db_session.add(mock_job)
        test_db_session.commit()
        mock_enqueue.return_value = mock_job

        res_enqueue = client.post(
            f"/api/v1/projects/{project.id}/analyses",
            headers=auth_headers,
        )

    assert res_enqueue.status_code == 202
    job_data = res_enqueue.json()
    assert job_data["status"] == "queued"
    assert job_data["id"] == str(job_id)

    # 9. GET /jobs/{id}
    res_job = client.get(f"/api/v1/jobs/{job_id}")
    assert res_job.status_code == 200
    assert res_job.json()["progress"] == 0

    # 10. GET /analyses/{id} before completion returns 409
    res_pending_report = client.get(f"/api/v1/analyses/{job_id}")
    assert res_pending_report.status_code == 409
    assert res_pending_report.json()["code"] == "ANALYSIS_PENDING"

    # 11. Complete analysis result and query GET /analyses/{id}
    result_record = AnalysisResult(
        id=uuid.uuid4(),
        job_id=job_id,
        report={
            "schemaVersion": "1.0.0",
            "repository": {"name": "gateway", "owner": "bob"},
            "history": {"totalCommits": 12},
            "similarity": {"overlapScore": {"value": None, "reason": "No catalog"}},
            "assessment": {"status": "reviewable", "evidenceCoverageScore": 75},
            "evidence": [],
            "limitations": ["Limited reference catalog."],
        },
    )
    test_db_session.add(result_record)
    test_db_session.commit()

    res_completed_report = client.get(f"/api/v1/analyses/{job_id}")
    assert res_completed_report.status_code == 200
    assert res_completed_report.json()["schemaVersion"] == "1.0.0"

    # 12. POST /jobs/{id}/cancel
    res_cancel = client.post(
        f"/api/v1/jobs/{job_id}/cancel",
        headers=auth_headers,
    )
    assert res_cancel.status_code == 200
    assert res_cancel.json()["status"] == "canceled"


def test_candidate_deletion_cascades_and_cleans_files(
    client: TestClient,
    auth_headers: dict[str, str],
    test_db_session: Session,
    tmp_path: Path,
):
    # Set storage_dir to tmp_path
    old_storage = settings.storage_dir
    settings.storage_dir = str(tmp_path)

    try:
        candidate = Candidate(id=uuid.uuid4(), name="Charlie Delete", email="charlie@example.com")
        storage_key = f"resume_{uuid.uuid4().hex}.pdf"
        dummy_file = tmp_path / storage_key
        dummy_file.write_text("dummy resume content")

        resume = Resume(
            id=uuid.uuid4(),
            candidate_id=candidate.id,
            original_filename="charlie.pdf",
            storage_key=storage_key,
            content_type="application/pdf",
        )
        cand_id = candidate.id
        res_id = resume.id
        test_db_session.add_all([candidate, resume])
        test_db_session.commit()

        assert dummy_file.exists()

        # Call DELETE /candidates/{id}
        res_delete = client.delete(
            f"/api/v1/candidates/{cand_id}",
            headers=auth_headers,
        )
        assert res_delete.status_code == 200
        assert res_delete.json()["status"] == "ok"

        # Verify DB cascade
        test_db_session.expunge_all()
        assert test_db_session.query(Candidate).filter_by(id=cand_id).first() is None
        assert test_db_session.query(Resume).filter_by(id=res_id).first() is None

        # Verify physical file deletion
        assert not dummy_file.exists()

    finally:
        settings.storage_dir = old_storage


def test_deletion_race_prevents_restoring_deleted_data(
    client: TestClient,
    auth_headers: dict[str, str],
    test_db_session: Session,
):
    candidate = Candidate(id=uuid.uuid4(), name="Race Candidate")
    project = Project(id=uuid.uuid4(), candidate_id=candidate.id, name="Race Project")
    selection = RepositorySelection(
        id=uuid.uuid4(),
        project_id=project.id,
        url="https://github.com/race/repo",
        owner="race",
        name="repo",
        discovery_reason="Race test",
        confidence_category="high",
        is_confirmed=True,
    )
    job = AnalysisJob(
        id=uuid.uuid4(),
        repository_selection_id=selection.id,
        status="running",
        stage="metadata",
        selected_repository_url=selection.url,
    )
    job_id = job.id
    candidate_id = candidate.id
    test_db_session.add_all([candidate, project, selection, job])
    test_db_session.commit()

    # 1. Delete candidate via API while job is supposedly running
    res_delete = client.delete(
        f"/api/v1/candidates/{candidate_id}",
        headers=auth_headers,
    )
    assert res_delete.status_code == 200

    # 2. Attempt to run background analysis on deleted job
    test_db_session.expunge_all()
    mock_gh = MagicMock()
    report = run_analysis(
        job_id=job_id,
        session=test_db_session,
        github_client=mock_gh,
    )

    # run_analysis must abort safely and return None without resurrecting records
    assert report is None
    test_db_session.expunge_all()
    assert test_db_session.query(AnalysisJob).filter_by(id=job_id).first() is None
    results = test_db_session.query(AnalysisResult).filter(AnalysisResult.job_id == job_id).all()
    assert len(results) == 0


def test_deterministic_openapi_export(tmp_path: Path):
    target = tmp_path / "openapi_test.json"
    exported_path = export_openapi(target)
    assert exported_path.exists()

    with open(exported_path, encoding="utf-8") as f:
        data = json.load(f)

    assert "openapi" in data
    assert "paths" in data
    assert "/api/v1/candidates" in data["paths"]
    assert "/api/v1/session" in data["paths"]
    assert "/api/v1/resume-batches" in data["paths"]
    assert "/api/v1/projects/{project_id}/analyses" in data["paths"]
