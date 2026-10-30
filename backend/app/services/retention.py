import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.entities import AnalysisJob, Candidate
from app.services.job_service import cancel_analysis

logger = logging.getLogger("retention")


@dataclass
class RetentionSummary:
    candidates_deleted: int = 0
    resumes_deleted: int = 0
    jobs_cancelled: int = 0
    workspaces_deleted: int = 0
    dry_run: bool = False
    cutoff_date: str = ""


def delete_candidate_records_and_files(candidate: Candidate, db: Session) -> dict[str, int]:
    """
    Deletes candidate database records and physical disk assets:
    1. Collects and cancels active (queued/running) jobs.
    2. Identifies upload files and job workspaces.
    3. Deletes candidate record (cascading to projects, repo selections, jobs, results).
    4. Removes upload files and workspaces on disk.
    """
    all_jobs: list[AnalysisJob] = []
    for project in candidate.projects:
        for repo_sel in project.repository_selections:
            all_jobs.extend(repo_sel.jobs)

    jobs_cancelled = 0
    for job in all_jobs:
        if job.status in {"queued", "running"}:
            try:
                cancel_analysis(job.id, session=db)
                jobs_cancelled += 1
            except Exception as e:
                logger.warning("Could not cancel job %s during deletion: %s", job.id, e)

    upload_paths: list[Path] = [
        Path(settings.storage_dir) / resume.storage_key for resume in candidate.resumes
    ]
    resumes_count = len(upload_paths)

    workspace_dirs: list[Path] = []
    workspaces_root = Path(settings.storage_dir) / "workspaces"
    if workspaces_root.exists():
        for job in all_jobs:
            for p in workspaces_root.glob(f"job_{job.id}_*"):
                workspace_dirs.append(p)

    # 3. Delete candidate from database (cascades)
    db.delete(candidate)
    db.commit()

    # 4. Clean up files on disk
    for path in upload_paths:
        try:
            if path.exists():
                path.unlink()
        except OSError as e:
            logger.warning("Failed to delete upload file %s: %s", path, e)

    workspaces_cleaned = 0
    for wdir in workspace_dirs:
        try:
            if wdir.exists():
                shutil.rmtree(wdir, ignore_errors=True)
                workspaces_cleaned += 1
        except OSError as e:
            logger.warning("Failed to delete workspace dir %s: %s", wdir, e)

    return {
        "resumes_deleted": resumes_count,
        "jobs_cancelled": jobs_cancelled,
        "workspaces_deleted": workspaces_cleaned,
    }


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def run_retention_cleanup(
    db: Session,
    days: int | None = None,
    dry_run: bool = False,
) -> RetentionSummary:
    """
    Enforces retention policy by identifying expired resumes and reports.
    Older than retention_days (default 7 days).
    Cancels active jobs, removes database records, uploads, and workspaces.
    Supports dry-run and execute modes.
    """
    retention_days = days if days is not None else settings.retention_days
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    candidates = db.query(Candidate).all()
    expired_candidates: list[Candidate] = []

    for c in candidates:
        is_expired = False
        cand_created = _to_utc(c.created_at)
        # Candidate created before cutoff
        if cand_created and cand_created <= cutoff:
            is_expired = True
        else:
            # Any resume older than cutoff
            for r in c.resumes:
                r_created = _to_utc(r.created_at)
                if r_created and r_created <= cutoff:
                    is_expired = True
                    break

            if not is_expired:
                # Any report / job older than cutoff
                for p in c.projects:
                    for rs in p.repository_selections:
                        for j in rs.jobs:
                            res_created = _to_utc(j.result.created_at) if j.result else None
                            j_created = _to_utc(j.created_at)
                            if (res_created and res_created <= cutoff) or (
                                j_created and j_created <= cutoff
                            ):
                                is_expired = True
                                break

        if is_expired:
            expired_candidates.append(c)

    if dry_run:
        total_resumes = 0
        total_jobs_cancelled = 0
        total_workspaces = 0
        workspaces_root = Path(settings.storage_dir) / "workspaces"

        for c in expired_candidates:
            total_resumes += len(c.resumes)
            for p in c.projects:
                for rs in p.repository_selections:
                    for j in rs.jobs:
                        if j.status in {"queued", "running"}:
                            total_jobs_cancelled += 1
                        if workspaces_root.exists():
                            for _ in workspaces_root.glob(f"job_{j.id}_*"):
                                total_workspaces += 1

        return RetentionSummary(
            candidates_deleted=len(expired_candidates),
            resumes_deleted=total_resumes,
            jobs_cancelled=total_jobs_cancelled,
            workspaces_deleted=total_workspaces,
            dry_run=True,
            cutoff_date=cutoff.isoformat(),
        )

    # Execute mode
    total_candidates_deleted = 0
    total_resumes_deleted = 0
    total_jobs_cancelled = 0
    total_workspaces_deleted = 0

    for c in expired_candidates:
        stats = delete_candidate_records_and_files(c, db)
        total_candidates_deleted += 1
        total_resumes_deleted += stats["resumes_deleted"]
        total_jobs_cancelled += stats["jobs_cancelled"]
        total_workspaces_deleted += stats["workspaces_deleted"]

    return RetentionSummary(
        candidates_deleted=total_candidates_deleted,
        resumes_deleted=total_resumes_deleted,
        jobs_cancelled=total_jobs_cancelled,
        workspaces_deleted=total_workspaces_deleted,
        dry_run=False,
        cutoff_date=cutoff.isoformat(),
    )
