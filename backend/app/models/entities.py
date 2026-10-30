import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base

# Portable JSON type: JSONB on Postgres, JSON on SQLite
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


def utc_now() -> datetime:
    return datetime.now(UTC)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    selected_project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    resumes: Mapped[list["Resume"]] = relationship(
        "Resume", back_populates="candidate", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="candidate", cascade="all, delete-orphan"
    )


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    candidate: Mapped["Candidate"] = relationship("Candidate", back_populates="resumes")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explicit_github_urls: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    candidate: Mapped["Candidate"] = relationship("Candidate", back_populates="projects")
    repository_selections: Mapped[list["RepositorySelection"]] = relationship(
        "RepositorySelection",
        back_populates="project",
        cascade="all, delete-orphan",
    )


class RepositorySelection(Base):
    __tablename__ = "repository_selections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    discovery_reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_category: Mapped[str] = mapped_column(String(50), nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship("Project", back_populates="repository_selections")
    jobs: Mapped[list["AnalysisJob"]] = relationship(
        "AnalysisJob", back_populates="repository_selection", cascade="all, delete-orphan"
    )


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_selection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repository_selections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(50), default="queued", nullable=False, index=True)
    stage: Mapped[str | None] = mapped_column(String(50), default="queued", nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    selected_repository_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    analyzed_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    repository_selection: Mapped["RepositorySelection"] = relationship(
        "RepositorySelection", back_populates="jobs"
    )
    result: Mapped[Optional["AnalysisResult"]] = relationship(
        "AnalysisResult", back_populates="job", uselist=False, cascade="all, delete-orphan"
    )


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    report: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    job: Mapped["AnalysisJob"] = relationship("AnalysisJob", back_populates="result")


class BenchmarkProject(Base):
    __tablename__ = "benchmark_projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    repository: Mapped[Optional["BenchmarkRepository"]] = relationship(
        "BenchmarkRepository",
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )


class BenchmarkRepository(Base):
    __tablename__ = "benchmark_repositories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    benchmark_project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("benchmark_projects.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    repository_url: Mapped[str] = mapped_column(
        String(512), unique=True, nullable=False, index=True
    )
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_language: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stars_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    default_branch: Mapped[str] = mapped_column(String(100), default="main", nullable=False)
    pinned_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    indexing_status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["BenchmarkProject"] = relationship(
        "BenchmarkProject", back_populates="repository"
    )
    fingerprints: Mapped[list["BenchmarkFileFingerprint"]] = relationship(
        "BenchmarkFileFingerprint",
        back_populates="repository",
        cascade="all, delete-orphan",
    )


class BenchmarkFileFingerprint(Base):
    __tablename__ = "benchmark_file_fingerprints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    benchmark_repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("benchmark_repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=False)
    tokens_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fingerprints: Mapped[list[int]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    repository: Mapped["BenchmarkRepository"] = relationship(
        "BenchmarkRepository", back_populates="fingerprints"
    )


Index(
    "ix_bm_file_fingerprints_repo_path",
    BenchmarkFileFingerprint.benchmark_repository_id,
    BenchmarkFileFingerprint.file_path,
    unique=True,
)
Index("ix_resumes_candidate_created", Resume.candidate_id, Resume.created_at)
Index("ix_projects_candidate_created", Project.candidate_id, Project.created_at)
Index(
    "ix_repo_selections_project_confirmed",
    RepositorySelection.project_id,
    RepositorySelection.is_confirmed,
)
Index("ix_jobs_status_created", AnalysisJob.status, AnalysisJob.created_at)
Index(
    "uq_active_job_per_repo",
    AnalysisJob.repository_selection_id,
    unique=True,
    postgresql_where=text("status IN ('queued', 'running')"),
    sqlite_where=text("status IN ('queued', 'running')"),
)
