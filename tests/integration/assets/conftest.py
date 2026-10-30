# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Fixtures for PostgreSQL-backed asset repository integration tests.

These tests use the shared ``postgres_settings``, ``postgres_url`` and
``postgres_schemas`` fixtures from ``tests/integration/conftest.py``, and are
skipped without a test server. Every test gets its own throw-away PostgreSQL
schema, dropped on teardown.
"""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from docpipe.core.assets.common.adapters.repositories.postgres_storage_utils import PostgresStorageUtils


@pytest.fixture
def asset_schema(postgres_schemas: Callable[..., str]) -> Iterator[str]:
    """A unique PostgreSQL schema name, dropped (with its tables) after the test."""
    yield postgres_schemas("it_assets_")
    # Release the pooled connections before postgres_schemas drops the schema.
    PostgresStorageUtils.dispose_engines()


@pytest.fixture
def repo_config(postgres_settings: dict[str, Any], asset_schema: str) -> dict[str, Any]:
    """Repository config in the shape used under assets_management.<asset>_repository.config."""
    return {"postgres": {**postgres_settings, "schema": asset_schema}}


@pytest.fixture
def independent_engine(postgres_url: str) -> Iterator[Engine]:
    """A second engine with its own connection pool, standing in for another process."""
    engine = create_engine(postgres_url, pool_size=5, max_overflow=5)
    yield engine
    engine.dispose()
