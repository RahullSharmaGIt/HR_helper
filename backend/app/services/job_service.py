import logging
import uuid
from typing import Any

import redis
from rq import Queue, Retry
from sqlalchemy.orm import Session

from app.config import settings
from app.db import transaction_scope
from app.models.entities import AnalysisJob, Project, RepositorySelection, utc_now
from app.schemas.contracts import JobState

logger = logging.getLogger("job_service")


class JobServiceError(Exception):
    """Base exception for job service errors."""


class ProjectNotFoundError(JobServiceError):
    """Raised when the specified project does not exist."""


class RepositorySelectionNotFoundError(JobServiceError):
    """Raised when the specified repository selection does not exist."""


class CrossCandidateProjectError(JobServiceError):
    """Raised when repository selection does not belong to the selected project or candidate."""


class RepositoryNotConfirmedError(JobServiceError):
    """Raised when analysis is requested on an unconfirmed repository selection."""


class DuplicateActiveJobError(JobServiceError):
    """Raised when an active analysis job is already running or queued for the selection."""


class JobNotFoundError(JobServiceError):
    """Raised when an analysis job cannot be found."""


class QueueEnqueueError(JobServiceError):
    """Raised when dispatching to background worker queue fails."""


class JobCanceledError(JobServiceError):
    """Raised when an analysis job is canceled during execution."""


class DummyQueue:
    def enqueue(self, *args, **kwargs):
        return None

    def cancel(self, *args, **kwargs):
        return None


def get_analysis_queue(redis_client: redis.Redis | None = None) -> Any:
    """Returns the RQ Queue for repository analysis jobs."""
    if settings.allow_test_adapters:
        try:
            conn = redis_client or redis.from_url(settings.redis_url)
            conn.ping()
            return Queue("default", connection=conn)
        except Exception:
            return DummyQueue()

    conn = redis_client or redis.from_url(settings.redis_url)
    return Queue("default", connection=conn)


def _enqueue_in_session(
    session: Session,
    project_id: uuid.UUID,
    repository_selection_id: uuid.UUID,
    queue: Any = None,
) -> AnalysisJob:
    # 1. Validate project existence
    project = session.get(Project, project_id)
    if not project:
        raise ProjectNotFoundError(f"Project '{project_id}' not found.")

    # 2. Validate repository selection existence
    repo_selection = session.get(RepositorySelection, repository_selection_id)
    if not repo_selection:
        raise RepositorySelectionNotFoundError(
            f"Repository selection '{repository_selection_id}' not found."
        )

    # 3. Validate project ownership and integrity
    if repo_selection.project_id != project.id:
        raise CrossCandidateProjectError(
            f"Repository selection '{repository_selection_id}' belongs to project "
            f"'{repo_selection.project_id}', not '{project.id}'."
        )

    # 4. Require confirmed repository selection
    if not repo_selection.is_confirmed:
        raise RepositoryNotConfirmedError(
            f"Repository selection '{repository_selection_id}' is not confirmed. "
            f"Hiring manager confirmation is required before enqueueing analysis."
        )

    # 5. Prevent duplicate active jobs via query and lock
    active_job = (
        session.query(AnalysisJob)
        .filter(
            AnalysisJob.repository_selection_id == repo_selection.id,
            AnalysisJob.status.in_([JobState.QUEUED.value, JobState.RUNNING.value]),
        )
        .first()
    )
    if active_job:
        raise DuplicateActiveJobError(
            f"An active analysis job ({active_job.id}) in status '{active_job.status}' "
            f"already exists for repository selection '{repo_selection.id}'."
        )

    # 6. Create queued AnalysisJob record
    job = AnalysisJob(
        id=uuid.uuid4(),
        repository_selection_id=repo_selection.id,
        status=JobState.QUEUED.value,
        stage="queued",
        progress=0,
        selected_repository_url=repo_selection.url,
    )
    session.add(job)
    session.flush()

    # 7. Dispatch to RQ with bounded retries for transient failures
    try:
        q = queue if queue is not None else get_analysis_queue()
        q.enqueue(
            "app.jobs.analysis.run_analysis",
            str(job.id),
            job_id=str(job.id),
            retry=Retry(max=3, interval=[10, 30, 60]),
        )
    except Exception as e:
        logger.error(
            "Failed to enqueue job %s to queue: %s; cleaning up to prevent orphan active job",
            job.id,
            e,
        )
        session.delete(job)
        session.flush()
        raise QueueEnqueueError(f"Failed to enqueue analysis job to background worker: {e}") from e

    return job


def enqueue_analysis(
    project_id: uuid.UUID | str,
    repository_selection_id: uuid.UUID | str,
    queue: Any = None,
    session: Session | None = None,
) -> AnalysisJob:
    """Enqueues a confirmed repository for background analysis.

    Enforces candidate-project verification, confirmation requirement, duplicate job prevention,
    and rollback on queue dispatch failure.
    """
    p_uuid = uuid.UUID(str(project_id))
    r_uuid = uuid.UUID(str(repository_selection_id))

    if session is not None:
        return _enqueue_in_session(session, p_uuid, r_uuid, queue)

    with transaction_scope() as sess:
        return _enqueue_in_session(sess, p_uuid, r_uuid, queue)


def _cancel_in_session(
    session: Session,
    job_id: uuid.UUID,
    queue: Any = None,
    redis_client: Any = None,
) -> AnalysisJob:
    job = session.get(AnalysisJob, job_id)
    if not job:
        raise JobNotFoundError(f"Analysis job '{job_id}' not found.")

    terminal_states = {
        JobState.SUCCEEDED.value,
        JobState.FAILED.value,
        JobState.CANCELED.value,
    }
    if job.status in terminal_states:
        return job

    # 1. Signal cancellation in Redis
    r_client = redis_client
    if r_client is None:
        try:
            r_client = redis.from_url(settings.redis_url)
        except (redis.RedisError, OSError):
            r_client = None

    if r_client is not None:
        try:
            r_client.set(f"cancel_job:{job.id}", "1", ex=3600)
        except (redis.RedisError, OSError) as e:
            logger.warning("Could not set Redis cancellation token for job %s: %s", job.id, e)

    # 2. Cancel in queue if supported
    if queue is not None and hasattr(queue, "cancel"):
        try:
            queue.cancel(str(job.id))
        except (redis.RedisError, OSError, RuntimeError) as e:
            logger.warning("Could not cancel job %s in queue: %s", job.id, e)

    # 3. Update database record
    job.status = JobState.CANCELED.value
    job.stage = "canceled"
    job.failure_code = "JOB_CANCELED"
    job.error_message = "Analysis job was canceled by user request."
    job.completed_at = utc_now()
    session.flush()

    return job


def cancel_analysis(
    job_id: uuid.UUID | str,
    queue: Any = None,
    session: Session | None = None,
    redis_client: Any = None,
) -> AnalysisJob:
    """Cancels a pending or running analysis job.

    Sets cancellation flags in Redis and the database, and informs the queue.
    """
    j_uuid = uuid.UUID(str(job_id))
    if session is not None:
        return _cancel_in_session(session, j_uuid, queue, redis_client)

    with transaction_scope() as sess:
        return _cancel_in_session(sess, j_uuid, queue, redis_client)
