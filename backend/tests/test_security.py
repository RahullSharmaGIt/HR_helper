import io
import logging
import uuid
import zipfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import create_session
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models.entities import (
    AnalysisJob,
    AnalysisResult,
    Candidate,
    Project,
    RepositorySelection,
    Resume,
)
from app.services.github_client import normalize_github_repository_url
from app.services.log_redaction import (
    SensitiveDataRedactionFilter,
    redact_sensitive_text,
)
from app.services.resumes import (
    safe_download_filename,
    validate_resume,
)


@pytest.fixture
def test_db_session():
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
def client(test_db_session, monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "storage_dir", str(storage_dir))

    def _get_test_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_test_db
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


def test_path_traversal_prevention(client, test_db_session):
    # 1. safe_download_filename sanitizes dangerous path characters
    assert safe_download_filename("../../../etc/passwd") == "passwd"
    assert safe_download_filename("..\\..\\windows\\system32\\cmd.exe") == "cmd.exe"
    assert safe_download_filename("normal_resume.pdf") == "normal_resume.pdf"
    assert safe_download_filename("...///...") == "resume.pdf"

    # 2. Prevent arbitrary file reads outside storage directory
    session_token, _ = create_session("127.0.0.1")
    cand = Candidate(id=uuid.uuid4(), name="Jane Doe")
    test_db_session.add(cand)
    test_db_session.flush()

    # Create resume record referencing path traversal key
    resume = Resume(
        id=uuid.uuid4(),
        candidate_id=cand.id,
        original_filename="secret.pdf",
        storage_key="../../etc/passwd",
        content_type="application/pdf",
    )
    test_db_session.add(resume)
    test_db_session.commit()

    client.cookies.set("session_token", session_token)
    res = client.get(f"/api/v1/resumes/{resume.id}/download")
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


def test_credential_bearing_repository_urls_rejected():
    with pytest.raises(ValueError, match="Embedded credentials in repository URLs are rejected"):
        normalize_github_repository_url("https://user:password@github.com/org/repo")

    with pytest.raises(ValueError, match="Embedded credentials in repository URLs are rejected"):
        normalize_github_repository_url("https://ghp_token123456789@github.com/org/repo")

    with pytest.raises(ValueError, match="Only canonical https:// URLs are accepted"):
        normalize_github_repository_url("http://github.com/org/repo")

    with pytest.raises(ValueError, match="Invalid host"):
        normalize_github_repository_url("https://gitlab.com/org/repo")


def test_oversized_archives_rejected():
    # 1. Zip bomb simulation for DOCX
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"0" * (settings.max_docx_uncompressed_bytes + 1024))
    oversized_docx = bio.getvalue()

    with pytest.raises(
        ValueError, match="DOCX archive exceeds maximum uncompressed expansion limit"
    ):
        validate_resume("malicious.docx", oversized_docx)

    # 2. Oversized total file size
    huge_pdf = b"%PDF-1.4 " + b"0" * (settings.max_upload_size_bytes + 10)
    with pytest.raises(ValueError, match="exceeds the maximum allowed limit"):
        validate_resume("huge.pdf", huge_pdf)


def test_canceled_and_deleted_jobs_isolation(client, test_db_session):
    session_token, csrf_token = create_session("127.0.0.1")
    client.cookies.set("session_token", session_token)
    headers = {"X-CSRF-Token": csrf_token}

    cand = Candidate(id=uuid.uuid4(), name="Alice Smith")
    test_db_session.add(cand)
    test_db_session.flush()

    proj = Project(id=uuid.uuid4(), candidate_id=cand.id, name="Project 1")
    test_db_session.add(proj)
    test_db_session.flush()

    repo_sel = RepositorySelection(
        id=uuid.uuid4(),
        project_id=proj.id,
        url="https://github.com/alice/project1",
        owner="alice",
        name="project1",
        discovery_reason="explicit",
        confidence_category="high",
        is_confirmed=True,
    )
    test_db_session.add(repo_sel)
    test_db_session.flush()

    job = AnalysisJob(
        id=uuid.uuid4(),
        repository_selection_id=repo_sel.id,
        status="completed",
    )
    test_db_session.add(job)
    test_db_session.flush()

    result = AnalysisResult(
        id=uuid.uuid4(),
        job_id=job.id,
        report={"evidenceCoverageScore": 85},
    )
    test_db_session.add(result)
    test_db_session.commit()

    # Retrieve analysis report before deletion
    res = client.get(f"/api/v1/analyses/{job.id}")
    assert res.status_code == 200
    assert res.json()["evidenceCoverageScore"] == 85

    # Delete candidate
    del_res = client.delete(f"/api/v1/candidates/{cand.id}", headers=headers)
    assert del_res.status_code == 200

    # Accessing deleted analysis report returns 404
    post_del_res = client.get(f"/api/v1/analyses/{job.id}")
    assert post_del_res.status_code == 404
    assert post_del_res.json()["code"] == "NOT_FOUND"


def test_expired_and_invalid_sessions(client):
    # Missing session cookie
    res = client.get("/api/v1/candidates")
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"

    # Expired / non-existent session cookie
    client.cookies.set("session_token", "expired-or-tampered-token")
    res2 = client.get("/api/v1/candidates")
    assert res2.status_code == 401
    assert res2.json()["code"] == "UNAUTHORIZED"


def test_structured_log_redaction():
    sample_text = (
        "Connecting with token ghp_1234567890abcdef1234567890abcdef and "
        "Authorization: Bearer mySecretBearerToken123. "
        "Cookie header session_token=abc123secretToken. "
        "Candidate contact is candidate.dev@example.org."
    )

    redacted = redact_sensitive_text(sample_text)
    assert "ghp_" not in redacted
    assert "[REDACTED_GITHUB_TOKEN]" in redacted
    assert "mySecretBearerToken123" not in redacted
    assert "[REDACTED_BEARER_TOKEN]" in redacted
    assert "abc123secretToken" not in redacted
    assert "[REDACTED_COOKIE]" in redacted
    assert "candidate.dev@example.org" not in redacted
    assert "[REDACTED_EMAIL]" in redacted

    # Test logging filter behavior
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="User login failed for admin@corp.com with key %s",
        args=("ghp_abcdef1234567890abcdef",),
        exc_info=None,
    )
    redaction_filter = SensitiveDataRedactionFilter()
    redaction_filter.filter(record)

    assert "[REDACTED_EMAIL]" in record.msg
    assert "[REDACTED_GITHUB_TOKEN]" in record.args[0]


def test_security_headers_and_cross_origin_rejection(client):
    # Verify security headers on responses
    res = client.get("/health")
    assert res.status_code == 200
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert "default-src 'self'" in res.headers.get("Content-Security-Policy", "")
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    # Reject unsupported cross-origin mutating request
    malicious_origin_res = client.post(
        "/api/v1/session",
        json={"password": "any-password"},
        headers={"Origin": "https://malicious-phishing-site.com"},
    )
    assert malicious_origin_res.status_code == 403
    assert malicious_origin_res.json()["code"] == "INVALID_ORIGIN"


def test_actionable_errors_without_stack_traces(test_db_session):
    def _get_test_db():
        yield test_db_session

    app.dependency_overrides[get_db] = _get_test_db
    try:
        session_token, _ = create_session("127.0.0.1")
        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set("session_token", session_token)

            # 1. Test 404 returns clean structured JSON without server traceback
            res = client.get(f"/api/v1/candidates/{uuid.uuid4()}")
            assert res.status_code == 404
            data = res.json()
            assert data["code"] == "NOT_FOUND"
            assert "message" in data
            assert "traceback" not in data
            assert "Traceback (most recent call last)" not in res.text

            # 2. Test 500 unhandled exception handler masks internal tracebacks
            with patch.object(
                test_db_session, "query", side_effect=RuntimeError("Secret database crash")
            ):
                res500 = client.get("/api/v1/candidates")
                assert res500.status_code == 500
                data500 = res500.json()
                assert data500["code"] == "INTERNAL_SERVER_ERROR"
                assert "Secret database crash" not in res500.text
                assert "traceback" not in data500
                assert "Traceback (most recent call last)" not in res500.text
    finally:
        app.dependency_overrides.clear()
