# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Add deferred_execution_docs to node_stats

Revision ID: 20261109_004
Revises: 20261001_003
Create Date: 2026-11-09 00:00:00.000000

Adds a nullable ARRAY column used by node-level failure resumption to track documents that
are counted in scope at upstream nodes but deferred for execution at a downstream node.
Rows written before this migration read back as NULL and are mapped to an empty list.
"""

import os
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.inspection import inspect

# revision identifiers, used by Alembic.
revision: str = "20261109_004"
down_revision: str | Sequence[str] | None = "20261001_003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Schema name for opensource
schema_name = os.getenv("DOCPIPE_POSTGRES_SCHEMA", "docpipe_oss")


def upgrade() -> None:
    """Add deferred_execution_docs column to node_stats."""
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = [col["name"] for col in inspector.get_columns("node_stats", schema=schema_name)]

    if "deferred_execution_docs" not in columns:
        op.add_column(
            "node_stats",
            sa.Column("deferred_execution_docs", postgresql.ARRAY(sa.String()), nullable=True),
            schema=schema_name,
        )


def downgrade() -> None:
    """Remove deferred_execution_docs column from node_stats."""
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = [col["name"] for col in inspector.get_columns("node_stats", schema=schema_name)]

    if "deferred_execution_docs" in columns:
        op.drop_column("node_stats", "deferred_execution_docs", schema=schema_name)
