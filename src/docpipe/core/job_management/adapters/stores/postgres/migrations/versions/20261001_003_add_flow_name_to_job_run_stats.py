"""Add flow_name to job_run_stats

Revision ID: 20261001_003
Revises: 20260928_002
Create Date: 2026-10-01 00:00:00.000000

Separates the human-readable flow name from the stable flow identifier.
Before this migration, flow_name was incorrectly stored in the flow_id column.
After this migration, flow_id holds the asset UUID (or job_id slug for CLI/Library
runs) and flow_name holds the snapshot of the name at run creation time.
"""

import os
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.inspection import inspect

# revision identifiers, used by Alembic.
revision: str = "20261001_003"
down_revision: str | Sequence[str] | None = "20260928_002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Schema name for opensource
schema_name = os.getenv("DOCPIPE_POSTGRES_SCHEMA", "docpipe_oss")


def upgrade() -> None:
    """Add flow_name column to job_run_stats."""
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = [col["name"] for col in inspector.get_columns("job_run_stats", schema=schema_name)]

    if "flow_name" not in columns:
        op.add_column(
            "job_run_stats",
            sa.Column("flow_name", sa.String(length=255), nullable=True),
            schema=schema_name,
        )


def downgrade() -> None:
    """Remove flow_name column from job_run_stats."""
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = [col["name"] for col in inspector.get_columns("job_run_stats", schema=schema_name)]

    if "flow_name" in columns:
        op.drop_column("job_run_stats", "flow_name", schema=schema_name)
