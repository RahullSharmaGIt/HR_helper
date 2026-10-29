import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.auth import (
    check_exact_origin,
    check_login_throttling,
    create_session,
    destroy_session,
    get_client_ip,
    get_redis_client,
    record_login_failure,
    require_admin_session,
    require_csrf,
    reset_login_failures,
    verify_password,
)
from app.api.errors import APIException
from app.config import settings
from app.db import get_db
from app.models.entities import (
    AnalysisJob,
    AnalysisResult,
    Candidate,
    Project,
    RepositorySelection,
    Resume,
)
from app.schemas.contracts import (
    AnalysisJobResponse,
    BatchUploadItem,
    BatchUploadResponse,
    CandidateDetailResponse,
    CandidateSummary,
    ConfirmRepositoryRequest,
    ProjectSummary,
    RepositorySelectionResponse,
    ResumeSummary,
    SelectProjectRequest,
    SessionCreateRequest,
    SessionResponse,
)
from app.services.github_client import GitHubClient
from app.services.job_service import (
    DuplicateActiveJobError,
    cancel_analysis,
    enqueue_analysis,
)
from app.services.project_extraction import (
    extract_project_suggestions,
)
from app.services.repository_discovery import discover_repositories
from app.services.resumes import (
    extract_resume_text,
    safe_download_filename,
    store_resume,
    validate_batch_size,
    validate_resume,
)
from app.services.retention import delete_candidate_records_and_files

logger = logging.getLogger("api_routes")

api_router = APIRouter(prefix="/api/v1")


def _is_secure_cookie() -> bool:
    if settings.app_env in {"testing", "development"}:
        return False
    return settings.app_env == "production" or not settings.debug


# --------------------------------------------------------------------------
# 1. Session Management
# --------------------------------------------------------------------------
@api_router.post(
    "/session",
    response_model=SessionResponse,
    summary="Company admin login and session creation",
)
def create_auth_session(
    body: SessionCreateRequest,
    request: Request,
    response: Response,
) -> SessionResponse:
    check_exact_origin(request)
    client_ip = get_client_ip(request)
    r_client = get_redis_client()

    check_login_throttling(client_ip, r_client)

    if not verify_password(body.password, settings.admin_password_hash):
        record_login_failure(client_ip, r_client)
        raise APIException(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message="Invalid company admin password.",
        )

    reset_login_failures(client_ip, r_client)
    session_token, csrf_token = create_session(client_ip, r_client)

    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=_is_secure_cookie(),
        samesite="lax",
        path="/",
        max_age=settings.session_ttl_seconds,
    )
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=_is_secure_cookie(),
        samesite="lax",
        path="/",
        max_age=settings.session_ttl_seconds,
    )

    return SessionResponse(status="ok", csrf_token=csrf_token)


@api_router.get(
    "/session",
    response_model=SessionResponse,
    summary="Get current admin session status and CSRF token",
)
def get_auth_session(
    response: Response,
    session: dict[str, Any] = Depends(require_admin_session),
) -> SessionResponse:
    csrf_token = session.get("csrf_token", "")
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=_is_secure_cookie(),
        samesite="lax",
        path="/",
        max_age=settings.session_ttl_seconds,
    )
    return SessionResponse(status="ok", csrf_token=csrf_token)


@api_router.delete(
    "/session",
    summary="Company admin logout and session invalidation",
)
def delete_auth_session(
    request: Request,
    response: Response,
    session: dict[str, Any] = Depends(require_admin_session),
) -> dict[str, str]:
    session_token = request.cookies.get("session_token")
    if session_token:
        r_client = get_redis_client()
        destroy_session(session_token, r_client)

    response.delete_cookie(key="session_token", path="/")
    response.delete_cookie(key="csrf_token", path="/")
    return {"status": "ok"}


# --------------------------------------------------------------------------
# 2. Resume Batches Intake
# --------------------------------------------------------------------------
@api_router.post(
    "/resume-batches",
    response_model=BatchUploadResponse,
    summary="Upload and extract multiple candidate resumes safely",
)
async def upload_resume_batch(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _csrf: dict[str, Any] = Depends(require_csrf),
) -> BatchUploadResponse:
    try:
        validate_batch_size(len(files))
    except ValueError as e:
        raise APIException(
            status_code=400,
            code="INVALID_BATCH_SIZE",
            message=str(e),
        ) from e

    successful_items: list[BatchUploadItem] = []
    failed_items: list[BatchUploadItem] = []
    gh_client = GitHubClient()

    for upload in files:
        filename = upload.filename or "unknown.pdf"
        try:
            content = await upload.read()

            # 1. Strict format and signature validation
            mime_type, norm_ext = validate_resume(filename, content)

            # 2. Content-addressable storage
            storage_key = store_resume(content, norm_ext)
            file_size = len(content)

            # 3. Text extraction
            extraction = extract_resume_text(storage_key)

            # 4. Candidate record
            derived_name = Path(filename).stem.replace("_", " ").replace("-", " ").title()
            candidate = Candidate(
                id=uuid.uuid4(),
                name=derived_name,
            )
            db.add(candidate)
            db.flush()

            # 5. Resume record
            resume_record = Resume(
                id=uuid.uuid4(),
                candidate_id=candidate.id,
                original_filename=filename,
                storage_key=storage_key,
                content_type=upload.content_type or "application/octet-stream",
                file_size_bytes=file_size,
                raw_text=extraction.raw_text,
            )
            db.add(resume_record)

            # 6. Extract project suggestions and find repo candidates
            suggestions = extract_project_suggestions(extraction.pages)
            created_projects_count = 0

            for proj_sug in suggestions:
                proj = Project(
                    id=uuid.uuid4(),
                    candidate_id=candidate.id,
                    name=proj_sug.name,
                    description=proj_sug.description,
                    explicit_github_urls=proj_sug.explicit_github_urls,
                    source_page=proj_sug.source_page,
                    is_selected=False,
                )
                db.add(proj)
                db.flush()
                created_projects_count += 1

                # Initial repository discovery
                try:
                    matches = discover_repositories(proj_sug, gh_client)
                    for match in matches:
                        selection = RepositorySelection(
                            id=uuid.uuid4(),
                            project_id=proj.id,
                            url=match.url,
                            owner=match.owner,
                            name=match.name,
                            discovery_reason=match.discovery_reason,
                            confidence_category=match.confidence_category,
                            is_confirmed=False,
                        )
                        db.add(selection)
                except Exception as disc_err:
                    logger.warning(
                        "Initial repo discovery skipped for project %s: %s",
                        proj.id,
                        disc_err,
                    )

            db.commit()

            successful_items.append(
                BatchUploadItem(
                    filename=filename,
                    candidate_id=candidate.id,
                    status="succeeded",
                    projects_count=created_projects_count,
                )
            )

        except Exception as err:
            db.rollback()
            logger.warning("Failed processing file %s: %s", filename, err)
            failed_items.append(
                BatchUploadItem(
                    filename=filename,
                    status="failed",
                    error=str(err),
                    code="INTAKE_ERROR",
                )
            )

    return BatchUploadResponse(
        total=len(files),
        successful=successful_items,
        failed=failed_items,
    )


# --------------------------------------------------------------------------
# 3. Candidates Endpoints
# --------------------------------------------------------------------------
@api_router.get(
    "/candidates",
    response_model=list[CandidateSummary],
    summary="List all candidates",
)
def list_candidates(
    db: Session = Depends(get_db),
    _sess: dict[str, Any] = Depends(require_admin_session),
) -> list[CandidateSummary]:
    candidates = db.query(Candidate).order_by(Candidate.created_at.desc()).all()
    result = []
    for c in candidates:
        result.append(
            CandidateSummary(
                id=c.id,
                name=c.name,
                email=c.email,
                selected_project_id=c.selected_project_id,
                resumes_count=len(c.resumes),
                projects_count=len(c.projects),
                created_at=c.created_at.isoformat(),
                updated_at=c.updated_at.isoformat(),
            )
        )
    return result


@api_router.get(
    "/candidates/{candidate_id}",
    response_model=CandidateDetailResponse,
    summary="Get candidate details with projects and resumes",
)
def get_candidate(
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
    _sess: dict[str, Any] = Depends(require_admin_session),
) -> CandidateDetailResponse:
    c = db.get(Candidate, candidate_id)
    if not c:
        raise APIException(status_code=404, code="NOT_FOUND", message="Candidate not found.")

    resumes = [
        ResumeSummary(
            id=r.id,
            original_filename=r.original_filename,
            content_type=r.content_type,
            file_size_bytes=r.file_size_bytes,
            created_at=r.created_at.isoformat(),
        )
        for r in c.resumes
    ]

    projects = [
        ProjectSummary(
            id=p.id,
            candidate_id=p.candidate_id,
            name=p.name,
            description=p.description,
            is_selected=p.is_selected,
            explicit_github_urls=p.explicit_github_urls,
            source_page=p.source_page,
            created_at=p.created_at.isoformat(),
        )
        for p in c.projects
    ]

    return CandidateDetailResponse(
        id=c.id,
        name=c.name,
        email=c.email,
        selected_project_id=c.selected_project_id,
        resumes=resumes,
        projects=projects,
        created_at=c.created_at.isoformat(),
        updated_at=c.updated_at.isoformat(),
    )


@api_router.put(
    "/candidates/{candidate_id}/selected-project",
    response_model=CandidateDetailResponse,
    summary="Select one project for candidate review",
)
def select_candidate_project(
    candidate_id: uuid.UUID,
    body: SelectProjectRequest,
    db: Session = Depends(get_db),
    _csrf: dict[str, Any] = Depends(require_csrf),
) -> CandidateDetailResponse:
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise APIException(status_code=404, code="NOT_FOUND", message="Candidate not found.")

    project = db.get(Project, body.project_id)
    if not project or project.candidate_id != candidate.id:
        raise APIException(
            status_code=400,
            code="INVALID_PROJECT",
            message="Specified project does not belong to this candidate.",
        )

    for p in candidate.projects:
        p.is_selected = p.id == project.id

    candidate.selected_project_id = project.id
    db.commit()

    return get_candidate(candidate_id, db=db, _sess={})


# --------------------------------------------------------------------------
# 4. Projects & Repository Selection Endpoints
# --------------------------------------------------------------------------
@api_router.get(
    "/projects/{project_id}/repositories",
    response_model=list[RepositorySelectionResponse],
    summary="List candidate repositories for project",
)
def get_project_repositories(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    _sess: dict[str, Any] = Depends(require_admin_session),
) -> list[RepositorySelectionResponse]:
    project = db.get(Project, project_id)
    if not project:
        raise APIException(status_code=404, code="NOT_FOUND", message="Project not found.")

    selections = (
        db.query(RepositorySelection).filter(RepositorySelection.project_id == project_id).all()
    )

    return [
        RepositorySelectionResponse(
            id=s.id,
            project_id=s.project_id,
            url=s.url,
            owner=s.owner,
            name=s.name,
            discovery_reason=s.discovery_reason,
            confidence_category=s.confidence_category,
            is_confirmed=s.is_confirmed,
            created_at=s.created_at.isoformat(),
        )
        for s in selections
    ]


@api_router.put(
    "/projects/{project_id}/repository-selection",
    response_model=RepositorySelectionResponse,
    summary="Confirm the repository selection to be analyzed",
)
def confirm_repository_selection(
    project_id: uuid.UUID,
    body: ConfirmRepositoryRequest,
    db: Session = Depends(get_db),
    _csrf: dict[str, Any] = Depends(require_csrf),
) -> RepositorySelectionResponse:
    project = db.get(Project, project_id)
    if not project:
        raise APIException(status_code=404, code="NOT_FOUND", message="Project not found.")

    selection = db.get(RepositorySelection, body.repository_selection_id)
    if not selection or selection.project_id != project.id:
        raise APIException(
            status_code=400,
            code="INVALID_REPOSITORY_SELECTION",
            message="Repository selection does not belong to this project.",
        )

    # Confirm only one repository selection per project
    all_selections = (
        db.query(RepositorySelection).filter(RepositorySelection.project_id == project.id).all()
    )
    for s in all_selections:
        s.is_confirmed = s.id == selection.id

    db.commit()
    db.refresh(selection)

    return RepositorySelectionResponse(
        id=selection.id,
        project_id=selection.project_id,
        url=selection.url,
        owner=selection.owner,
        name=selection.name,
        discovery_reason=selection.discovery_reason,
        confidence_category=selection.confidence_category,
        is_confirmed=selection.is_confirmed,
        created_at=selection.created_at.isoformat(),
    )


# --------------------------------------------------------------------------
# 5. Analysis Enqueueing & Jobs Endpoints
# --------------------------------------------------------------------------
@api_router.post(
    "/projects/{project_id}/analyses",
    response_model=AnalysisJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue confirmed repository for analysis",
)
def create_analysis_job(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    _csrf: dict[str, Any] = Depends(require_csrf),
) -> AnalysisJobResponse:
    project = db.get(Project, project_id)
    if not project:
        raise APIException(status_code=404, code="NOT_FOUND", message="Project not found.")

    confirmed_sel = (
        db.query(RepositorySelection)
        .filter(
            RepositorySelection.project_id == project.id,
            RepositorySelection.is_confirmed.is_(True),
        )
        .first()
    )
    if not confirmed_sel:
        raise APIException(
            status_code=400,
            code="UNCONFIRMED_REPOSITORY",
            message=(
                "A repository selection must be confirmed by the hiring manager "
                "before enqueueing analysis."
            ),
        )

    try:
        job = enqueue_analysis(project.id, confirmed_sel.id, session=db)
        db.commit()
    except DuplicateActiveJobError as e:
        raise APIException(
            status_code=409,
            code="DUPLICATE_ACTIVE_JOB",
            message=str(e),
        ) from e
    except Exception as e:
        db.rollback()
        raise APIException(
            status_code=500,
            code="ENQUEUE_FAILED",
            message=f"Failed to enqueue analysis: {e}",
        ) from e

    return AnalysisJobResponse(
        id=job.id,
        repository_selection_id=job.repository_selection_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        failure_code=job.failure_code,
        error_message=job.error_message,
        selected_repository_url=job.selected_repository_url,
        analyzed_commit_sha=job.analyzed_commit_sha,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


@api_router.get(
    "/jobs/{job_id}",
    response_model=AnalysisJobResponse,
    summary="Get analysis job status and progress",
)
def get_analysis_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    _sess: dict[str, Any] = Depends(require_admin_session),
) -> AnalysisJobResponse:
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise APIException(status_code=404, code="NOT_FOUND", message="Analysis job not found.")

    return AnalysisJobResponse(
        id=job.id,
        repository_selection_id=job.repository_selection_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        failure_code=job.failure_code,
        error_message=job.error_message,
        selected_repository_url=job.selected_repository_url,
        analyzed_commit_sha=job.analyzed_commit_sha,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


@api_router.post(
    "/jobs/{job_id}/cancel",
    response_model=AnalysisJobResponse,
    summary="Cancel a queued or running analysis job",
)
def cancel_job_endpoint(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    _csrf: dict[str, Any] = Depends(require_csrf),
) -> AnalysisJobResponse:
    try:
        job = cancel_analysis(job_id, session=db)
        db.commit()
    except Exception as e:
        raise APIException(
            status_code=404,
            code="NOT_FOUND",
            message=str(e),
        ) from e

    return AnalysisJobResponse(
        id=job.id,
        repository_selection_id=job.repository_selection_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        failure_code=job.failure_code,
        error_message=job.error_message,
        selected_repository_url=job.selected_repository_url,
        analyzed_commit_sha=job.analyzed_commit_sha,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


# --------------------------------------------------------------------------
# 6. Analysis Results Endpoint
# --------------------------------------------------------------------------
@api_router.get(
    "/analyses/{analysis_id}",
    summary="Retrieve completed analysis report",
)
def get_analysis_result(
    analysis_id: uuid.UUID,
    db: Session = Depends(get_db),
    _sess: dict[str, Any] = Depends(require_admin_session),
) -> dict[str, Any]:
    # Look up by AnalysisResult.id or AnalysisResult.job_id
    result = (
        db.query(AnalysisResult)
        .filter((AnalysisResult.id == analysis_id) | (AnalysisResult.job_id == analysis_id))
        .first()
    )

    if result:
        return result.report

    # Check if job exists in pending state
    job = db.get(AnalysisJob, analysis_id)
    if job:
        raise APIException(
            status_code=409,
            code="ANALYSIS_PENDING",
            message=f"Analysis is not complete yet. Current status: '{job.status}', stage: '{job.stage}'.",
        )

    raise APIException(
        status_code=404,
        code="NOT_FOUND",
        message="Analysis report not found.",
    )


# --------------------------------------------------------------------------
# 7. Resume Download & Candidate Deletion (Cascades + Cleanup)
# --------------------------------------------------------------------------
@api_router.get(
    "/resumes/{resume_id}/download",
    summary="Download stored resume file securely",
)
def download_resume(
    resume_id: uuid.UUID,
    db: Session = Depends(get_db),
    _sess: dict[str, Any] = Depends(require_admin_session),
) -> FileResponse:
    resume = db.get(Resume, resume_id)
    if not resume:
        raise APIException(status_code=404, code="NOT_FOUND", message="Resume not found.")

    base_dir = Path(settings.storage_dir).resolve()
    file_path = (base_dir / resume.storage_key).resolve()

    # Prevent path traversal outside storage directory
    if not str(file_path).startswith(str(base_dir)) or not file_path.is_file():
        raise APIException(status_code=404, code="NOT_FOUND", message="Resume file not found on disk.")

    safe_name = safe_download_filename(resume.original_filename)
    return FileResponse(
        path=str(file_path),
        media_type=resume.content_type,
        filename=safe_name,
    )


@api_router.delete(
    "/candidates/{candidate_id}",
    summary="Delete candidate, cancel jobs, remove records, uploads, and workspaces",
)
def delete_candidate(
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
    _csrf: dict[str, Any] = Depends(require_csrf),
) -> dict[str, str]:
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise APIException(status_code=404, code="NOT_FOUND", message="Candidate not found.")

    delete_candidate_records_and_files(candidate, db)

    return {
        "status": "ok",
        "message": "Candidate and all associated data deleted successfully.",
    }
