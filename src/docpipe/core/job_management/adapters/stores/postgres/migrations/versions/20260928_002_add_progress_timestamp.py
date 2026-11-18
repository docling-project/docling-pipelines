"""Add progress_timestamp to job_run_stats

Revision ID: 20260928_002
Revises: 20260422_001
Create Date: 2026-09-28 00:00:00.000000

Adds a progress_timestamp column to job_run_stats to track the timestamp of
the last measurable unit of forward progress, enabling external monitors to
distinguish between a dead worker (stale heartbeat) and a stalled/hung worker
(fresh heartbeat but stale progress).
"""

import os
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.inspection import inspect

# revision identifiers, used by Alembic.
revision: str = "20260928_002"
down_revision: str | Sequence[str] | None = "20260422_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Schema name for opensource
schema_name = os.getenv("DOCPIPE_POSTGRES_SCHEMA", "docpipe_oss")


def upgrade() -> None:
    """Add progress_timestamp column to job_run_stats."""
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = [col["name"] for col in inspector.get_columns("job_run_stats", schema=schema_name)]

    if "progress_timestamp" not in columns:
        op.add_column(
            "job_run_stats",
            sa.Column("progress_timestamp", sa.BigInteger(), nullable=False, server_default="0"),
            schema=schema_name,
        )


def downgrade() -> None:
    """Remove progress_timestamp column from job_run_stats."""
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = [col["name"] for col in inspector.get_columns("job_run_stats", schema=schema_name)]

    if "progress_timestamp" in columns:
        op.drop_column("job_run_stats", "progress_timestamp", schema=schema_name)
