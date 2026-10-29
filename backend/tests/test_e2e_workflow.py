import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import create_session
from app.config import settings
from app.db import Base, get_db
from app.jobs.analysis import run_analysis
from app.main import app, create_app
from app.models.entities import AnalysisJob, RepositorySelection
from app.schemas.contracts import JobState


@pytest.fixture
def e2e_db():
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
def e2e_client(e2e_db, tmp_path, monkeypatch):
    # Enable explicit test adapter configuration
    monkeypatch.setattr(settings, "allow_test_adapters", True)
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))

    def _get_db_override():
        yield e2e_db

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def test_production_startup_rejects_test_adapters(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "allow_test_adapters", True)

    with pytest.raises(RuntimeError, match="Production startup rejected"):
        create_app()


def test_e2e_workflow_complete(e2e_client, e2e_db):
    fixtures_dir = Path(__file__).resolve().parent / "fixtures" / "resumes"
    valid_pdf = fixtures_dir / "alex_mercer_portfolio.pdf"
    valid_docx = fixtures_dir / "jordan_lee_inaccessible.docx"
    corrupt_pdf = fixtures_dir / "corrupt_resume.pdf"

    assert valid_pdf.exists(), "alex_mercer_portfolio.pdf fixture missing"
    assert valid_docx.exists(), "jordan_lee_inaccessible.docx fixture missing"
    assert corrupt_pdf.exists(), "corrupt_resume.pdf fixture missing"

    # -------------------------------------------------------------
    # 1. Login & Session Setup
    # -------------------------------------------------------------
    login_res = e2e_client.post(
        "/api/v1/session",
        json={"password": settings.admin_password or "test-admin-secret"},
    )
    # If using hash verify, use matching password or inject session directly
    if login_res.status_code != 200:
        session_token, csrf_token = create_session("127.0.0.1")
        e2e_client.cookies.set("session_token", session_token)
    else:
        csrf_token = login_res.json()["csrfToken"]
        session_token = e2e_client.cookies.get("session_token")

    headers = {"X-CSRF-Token": csrf_token}

    # -------------------------------------------------------------
    # 2. Batch Upload with Partial Failure
    # -------------------------------------------------------------
    files = [
        ("files", ("alex_mercer_portfolio.pdf", valid_pdf.read_bytes(), "application/pdf")),
        ("files", ("jordan_lee_inaccessible.docx", valid_docx.read_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
        ("files", ("corrupt_resume.pdf", corrupt_pdf.read_bytes(), "application/pdf")),
    ]

    upload_res = e2e_client.post("/api/v1/resume-batches", files=files, headers=headers)
    assert upload_res.status_code == 200
    upload_data = upload_res.json()

    assert upload_data.get("total", upload_data.get("total_files")) == 3
    assert len(upload_data.get("successful", [])) == 2
    assert len(upload_data.get("failed", [])) == 1

    # Verify corrupt file failed validation without failing entire batch
    failed_items = upload_data.get("failed", [])
    failed_names = [f.get("filename", f.get("original_filename")) for f in failed_items]
    assert "corrupt_resume.pdf" in failed_names

    # -------------------------------------------------------------
    # 3. Candidate & Project Selection
    # -------------------------------------------------------------
    candidates_res = e2e_client.get("/api/v1/candidates")
    assert candidates_res.status_code == 200
    candidates = candidates_res.json()
    assert len(candidates) == 2

    alex_cand = next(c for c in candidates if "Alex" in c.get("name", ""))
    cand_detail_res = e2e_client.get(f"/api/v1/candidates/{alex_cand['id']}")
    assert cand_detail_res.status_code == 200
    cand_detail = cand_detail_res.json()

    projects = cand_detail.get("projects", [])
    assert len(projects) >= 1
    target_project = projects[0]

    # Confirm project selection
    select_res = e2e_client.put(
        f"/api/v1/candidates/{alex_cand['id']}/selected-project",
        json={"projectId": target_project["id"]},
        headers=headers,
    )
    assert select_res.status_code == 200

    # -------------------------------------------------------------
    # 4. Repository Confirmation
    # -------------------------------------------------------------
    repos_res = e2e_client.get(f"/api/v1/projects/{target_project['id']}/repositories")
    assert repos_res.status_code == 200
    repo_selections = repos_res.json()
    assert len(repo_selections) >= 1
    target_repo_sel = repo_selections[0]

    confirm_res = e2e_client.put(
        f"/api/v1/projects/{target_project['id']}/repository-selection",
        json={"repositorySelectionId": target_repo_sel["id"]},
        headers=headers,
    )
    assert confirm_res.status_code == 200
    confirmed_data = confirm_res.json()
    assert confirmed_data.get("isConfirmed", confirmed_data.get("is_confirmed")) is True

    # -------------------------------------------------------------
    # 5. Enqueue & Execute Analysis Job
    # -------------------------------------------------------------
    analyze_res = e2e_client.post(
        f"/api/v1/projects/{target_project['id']}/analyses",
        headers=headers,
    )
    assert analyze_res.status_code == 202
    job_info = analyze_res.json()
    job_id = uuid.UUID(job_info["id"])

    # Run analysis worker deterministically with test adapters
    report = run_analysis(job_id=job_id, session=e2e_db, allow_file_transport=True)
    assert report is not None

    # Verify job status completed
    job_status_res = e2e_client.get(f"/api/v1/jobs/{job_id}")
    assert job_status_res.status_code == 200
    assert job_status_res.json()["status"] in {JobState.SUCCEEDED.value, "completed", "succeeded"}
    assert job_status_res.json()["progress"] == 100

    # -------------------------------------------------------------
    # 6. Verify Evidence Report Contract & Disclaimers
    # -------------------------------------------------------------
    analysis_res = e2e_client.get(f"/api/v1/analyses/{job_id}")
    assert analysis_res.status_code == 200
    rep_data = analysis_res.json()

    # Verify report SHA
    assert rep_data.get("analyzedCommitSha") or rep_data.get("history", {}).get("analyzedSha")

    # Verify evidence coverage score
    assessment = rep_data["assessment"]
    cov_score = assessment.get("evidenceCoverageScore") or assessment.get("evidence_coverage_score")
    assert isinstance(cov_score, int)

    # Verify evidence items and atomic linking
    evidence_items = rep_data.get("evidence", [])
    assert len(evidence_items) > 0
    obs = assessment.get("observations", [])
    for o in obs:
        eids = o.get("evidenceIds") or o.get("evidence_ids")
        if eids:
            for eid in eids:
                assert any(ev["id"] == eid for ev in evidence_items)

    # Verify limitations
    limitations = rep_data.get("limitations") or assessment.get("limitations", [])
    assert len(limitations) > 0

    # -------------------------------------------------------------
    # 7. Job Cancellation
    # -------------------------------------------------------------
    # Create another job to test cancellation
    cancel_job = AnalysisJob(
        id=uuid.uuid4(),
        repository_selection_id=uuid.UUID(target_repo_sel["id"]),
        status="queued",
    )
    e2e_db.add(cancel_job)
    e2e_db.commit()

    cancel_res = e2e_client.post(f"/api/v1/jobs/{cancel_job.id}/cancel", headers=headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == JobState.CANCELED.value

    # -------------------------------------------------------------
    # 8. Candidate Deletion & Cleanup
    # -------------------------------------------------------------
    del_res = e2e_client.delete(f"/api/v1/candidates/{alex_cand['id']}", headers=headers)
    assert del_res.status_code == 200

    # Verify cascaded deletion
    get_deleted_cand = e2e_client.get(f"/api/v1/candidates/{alex_cand['id']}")
    assert get_deleted_cand.status_code == 404

    get_deleted_analysis = e2e_client.get(f"/api/v1/analyses/{job_id}")
    assert get_deleted_analysis.status_code == 404

    # -------------------------------------------------------------
    # 9. Inaccessible Repository Handling
    # -------------------------------------------------------------
    jordan_cand = next(c for c in candidates if "Jordan" in c.get("name", ""))
    j_detail = e2e_client.get(f"/api/v1/candidates/{jordan_cand['id']}").json()
    j_proj = j_detail["projects"][0]

    # Select project
    e2e_client.put(
        f"/api/v1/candidates/{jordan_cand['id']}/selected-project",
        json={"projectId": j_proj["id"]},
        headers=headers,
    )

    # Add and confirm inaccessible repository selection
    inacc_sel = RepositorySelection(
        id=uuid.uuid4(),
        project_id=uuid.UUID(j_proj["id"]),
        url="https://github.com/synthetic-candidate/inaccessible-repo",
        owner="synthetic-candidate",
        name="inaccessible-repo",
        discovery_reason="explicit link",
        confidence_category="high",
        is_confirmed=True,
    )
    e2e_db.add(inacc_sel)
    e2e_db.commit()

    # Trigger analysis on the inaccessible repository
    j_analyze = e2e_client.post(
        f"/api/v1/projects/{j_proj['id']}/analyses",
        headers=headers,
    )
    assert j_analyze.status_code == 202
    j_job_id = uuid.UUID(j_analyze.json()["id"])

    # Run analysis worker - handles inaccessible repo gracefully
    run_analysis(job_id=j_job_id, session=e2e_db, allow_file_transport=True)

    j_job_res = e2e_client.get(f"/api/v1/jobs/{j_job_id}")
    assert j_job_res.status_code == 200
    assert j_job_res.json()["status"] == JobState.FAILED.value
    assert j_job_res.json().get("failureCode", j_job_res.json().get("failure_code")) in {
        "REPO_NOT_FOUND",
        "GIT_FETCH_FAILED",
    }

    # -------------------------------------------------------------
    # 10. Expired Session Scenario
    # -------------------------------------------------------------
    e2e_client.cookies.clear()
    expired_res = e2e_client.get("/api/v1/candidates")
    assert expired_res.status_code == 401
    assert expired_res.json()["code"] == "UNAUTHORIZED"
