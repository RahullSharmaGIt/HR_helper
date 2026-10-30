"""Add benchmark catalog tables

Revision ID: 004_benchmark_catalog
Revises: 003_candidate_project_selection
Create Date: 2026-10-30 05:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "004_benchmark_catalog"
down_revision: str | None = "003_candidate_project_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "benchmark_projects",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("category", name="uq_benchmark_projects_category"),
    )
    op.create_index("ix_benchmark_projects_category", "benchmark_projects", ["category"])

    op.create_table(
        "benchmark_repositories",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("benchmark_project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("repository_url", sa.String(length=512), nullable=False),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("primary_language", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("license", sa.String(length=100), nullable=True),
        sa.Column("stars_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("default_branch", sa.String(length=100), nullable=False, server_default="main"),
        sa.Column("pinned_commit_sha", sa.String(length=40), nullable=False),
        sa.Column(
            "indexing_status", sa.String(length=50), nullable=False, server_default="pending"
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["benchmark_project_id"], ["benchmark_projects.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("benchmark_project_id", name="uq_benchmark_repositories_project_id"),
        sa.UniqueConstraint("repository_url", name="uq_benchmark_repositories_url"),
    )
    op.create_index(
        "ix_benchmark_repositories_project_id", "benchmark_repositories", ["benchmark_project_id"]
    )
    op.create_index("ix_benchmark_repositories_url", "benchmark_repositories", ["repository_url"])
    op.create_index(
        "ix_benchmark_repositories_status", "benchmark_repositories", ["indexing_status"]
    )

    op.create_table(
        "benchmark_file_fingerprints",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("benchmark_repository_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=50), nullable=False),
        sa.Column("tokens_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fingerprints", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["benchmark_repository_id"], ["benchmark_repositories.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_bm_file_fingerprints_repo_id",
        "benchmark_file_fingerprints",
        ["benchmark_repository_id"],
    )
    op.create_index(
        "ix_bm_file_fingerprints_file_path", "benchmark_file_fingerprints", ["file_path"]
    )
    op.create_index(
        "ix_bm_file_fingerprints_repo_path",
        "benchmark_file_fingerprints",
        ["benchmark_repository_id", "file_path"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("benchmark_file_fingerprints")
    op.drop_table("benchmark_repositories")
    op.drop_table("benchmark_projects")
