import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class ConfidenceCategory(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class Measurement[T](ContractModel):
    """
    Represents a measured value.
    Unavailable measurements MUST be represented as null with a reason, never zero.
    """

    value: T | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def check_unavailable_has_reason(self) -> "Measurement[T]":
        if self.value is None and not self.reason:
            raise ValueError(
                "Unavailable measurement must have a non-empty reason explaining why value is null."
            )
        return self


class ProjectSuggestion(ContractModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    description: str | None = None
    explicit_github_urls: list[str] = Field(default_factory=list)
    source_page: int | None = None


class RepositoryMatch(ContractModel):
    url: str
    owner: str
    name: str
    discovery_reason: str
    confidence_category: str  # e.g., 'high', 'medium', 'low'


class EvidenceItem(ContractModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    kind: str
    summary: str
    source_url: str | None = None
    commit_sha: str | None = None
    path: str | None = None


class AnalysisReport(ContractModel):
    schema_version: str = "1.0.0"
    analyzed_commit_sha: str | None = None
    repository: dict[str, Any]
    history: dict[str, Any]
    similarity: dict[str, Any]
    assessment: dict[str, Any]
    evidence: list[EvidenceItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ErrorResponse(ContractModel):
    code: str
    message: str
    request_id: str


class SessionCreateRequest(ContractModel):
    password: str


class SessionResponse(ContractModel):
    status: str = "ok"
    csrf_token: str


class BatchUploadItem(ContractModel):
    filename: str
    candidate_id: uuid.UUID | None = None
    status: str
    projects_count: int = 0
    error: str | None = None
    code: str | None = None


class BatchUploadResponse(ContractModel):
    total: int
    successful: list[BatchUploadItem] = Field(default_factory=list)
    failed: list[BatchUploadItem] = Field(default_factory=list)


class ResumeSummary(ContractModel):
    id: uuid.UUID
    original_filename: str
    content_type: str
    file_size_bytes: int | None = None
    created_at: str

    @field_validator("created_at", mode="before")
    @classmethod
    def coerce_created_at(cls, v: Any) -> str:
        if isinstance(v, datetime):
            return v.isoformat()
        if v is None:
            return datetime.now(UTC).isoformat()
        return str(v)


class ProjectSummary(ContractModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    name: str
    description: str | None = None
    is_selected: bool = False
    explicit_github_urls: list[str] = Field(default_factory=list)
    source_page: int | None = None
    created_at: str

    @field_validator("explicit_github_urls", mode="before")
    @classmethod
    def coerce_urls(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v if x is not None]
        return []

    @field_validator("created_at", mode="before")
    @classmethod
    def coerce_created_at(cls, v: Any) -> str:
        if isinstance(v, datetime):
            return v.isoformat()
        if v is None:
            return datetime.now(UTC).isoformat()
        return str(v)


class CandidateSummary(ContractModel):
    id: uuid.UUID
    name: str
    email: str | None = None
    selected_project_id: uuid.UUID | None = None
    resumes_count: int = 0
    projects_count: int = 0
    created_at: str
    updated_at: str

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def coerce_timestamps(cls, v: Any) -> str:
        if isinstance(v, datetime):
            return v.isoformat()
        if v is None:
            return datetime.now(UTC).isoformat()
        return str(v)


class CandidateDetailResponse(ContractModel):
    id: uuid.UUID
    name: str
    email: str | None = None
    selected_project_id: uuid.UUID | None = None
    resumes: list[ResumeSummary] = Field(default_factory=list)
    projects: list[ProjectSummary] = Field(default_factory=list)
    created_at: str
    updated_at: str

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def coerce_timestamps(cls, v: Any) -> str:
        if isinstance(v, datetime):
            return v.isoformat()
        if v is None:
            return datetime.now(UTC).isoformat()
        return str(v)


class SelectProjectRequest(ContractModel):
    project_id: uuid.UUID


class RepositorySelectionResponse(ContractModel):
    id: uuid.UUID
    project_id: uuid.UUID
    url: str
    owner: str
    name: str
    discovery_reason: str
    confidence_category: str
    is_confirmed: bool
    created_at: str


class ConfirmRepositoryRequest(ContractModel):
    repository_selection_id: uuid.UUID


class BenchmarkRepositorySummary(ContractModel):
    id: uuid.UUID
    repository_url: str
    owner: str
    name: str
    primary_language: str
    description: str | None = None
    license: str | None = None
    stars_count: int = 0
    default_branch: str = "main"
    pinned_commit_sha: str
    indexing_status: str
    failure_reason: str | None = None
    indexed_at: str | None = None
    fingerprints_count: int = 0


class BenchmarkProjectResponse(ContractModel):
    id: uuid.UUID
    category: str
    name: str
    description: str | None = None
    repository: BenchmarkRepositorySummary | None = None
    created_at: str
    updated_at: str


class AnalysisJobResponse(ContractModel):
    id: uuid.UUID
    repository_selection_id: uuid.UUID
    status: str
    stage: str | None = None
    progress: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    failure_code: str | None = None
    error_message: str | None = None
    selected_repository_url: str | None = None
    analyzed_commit_sha: str | None = None
    created_at: str
    updated_at: str
