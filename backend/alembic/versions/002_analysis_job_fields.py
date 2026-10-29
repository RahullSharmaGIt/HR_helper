"""add analysis job execution fields and active job index

Revision ID: 002
Revises: 001
Create Date: 2026-10-28 02:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "002_analysis_job_fields"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("analysis_jobs") as batch_op:
        batch_op.add_column(
            sa.Column("stage", sa.String(length=50), nullable=True, server_default="queued")
        )
        batch_op.add_column(
            sa.Column("progress", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("failure_code", sa.String(length=100), nullable=True))
        batch_op.add_column(
            sa.Column("selected_repository_url", sa.String(length=512), nullable=True)
        )
        batch_op.add_column(sa.Column("analyzed_commit_sha", sa.String(length=40), nullable=True))
        batch_op.create_index(
            "uq_active_job_per_repo",
            ["repository_selection_id"],
            unique=True,
            postgresql_where=sa.text("status IN ('queued', 'running')"),
            sqlite_where=sa.text("status IN ('queued', 'running')"),
        )


def downgrade() -> None:
    with op.batch_alter_table("analysis_jobs") as batch_op:
        batch_op.drop_index("uq_active_job_per_repo")
        batch_op.drop_column("analyzed_commit_sha")
        batch_op.drop_column("selected_repository_url")
        batch_op.drop_column("failure_code")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("started_at")
        batch_op.drop_column("progress")
        batch_op.drop_column("stage")
