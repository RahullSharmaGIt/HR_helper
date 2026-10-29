"""add candidate selected_project_id and project is_selected

Revision ID: 003_candidate_project_selection
Revises: 002_analysis_job_fields
Create Date: 2026-10-28 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003_candidate_project_selection"
down_revision: str | None = "002_analysis_job_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.add_column(sa.Column("selected_project_id", sa.Uuid(as_uuid=True), nullable=True))

    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(
            sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.text("false"))
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("is_selected")

    with op.batch_alter_table("candidates") as batch_op:
        batch_op.drop_column("selected_project_id")
