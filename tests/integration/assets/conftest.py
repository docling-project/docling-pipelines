"""Fixtures for PostgreSQL-backed asset repository integration tests.

These tests need a real PostgreSQL server. They are skipped unless
``DOCPIPE_TEST_POSTGRES_PASSWORD`` is set and the server is reachable.
Dedicated ``DOCPIPE_TEST_*`` variables are used on purpose so a developer's
regular ``DOCPIPE_POSTGRES_*`` settings never point the tests at a real database.

Environment variables:
    DOCPIPE_TEST_POSTGRES_HOST      (default: localhost)
    DOCPIPE_TEST_POSTGRES_PORT      (default: 5432)
    DOCPIPE_TEST_POSTGRES_DB        (default: docpipe_test)
    DOCPIPE_TEST_POSTGRES_USER      (default: postgres)
    DOCPIPE_TEST_POSTGRES_PASSWORD  (required)

Every test gets its own throw-away PostgreSQL schema, dropped on teardown.
"""

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from docpipe.core.assets.common.adapters.repositories.postgres_storage_utils import PostgresStorageUtils


def _postgres_settings() -> dict[str, Any] | None:
    password = os.getenv("DOCPIPE_TEST_POSTGRES_PASSWORD")
    if not password:
        return None
    return {
        "host": os.getenv("DOCPIPE_TEST_POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("DOCPIPE_TEST_POSTGRES_PORT", "5432")),
        "database": os.getenv("DOCPIPE_TEST_POSTGRES_DB", "docpipe_test"),
        "user": os.getenv("DOCPIPE_TEST_POSTGRES_USER", "postgres"),
        "password": password,
    }


def _url(settings: dict[str, Any]) -> str:
    return (
        f"postgresql+psycopg2://{settings['user']}:{settings['password']}"
        f"@{settings['host']}:{settings['port']}/{settings['database']}"
    )


@pytest.fixture(scope="session")
def postgres_settings() -> dict[str, Any]:
    """Connection settings for the test server; skips when unavailable."""
    settings = _postgres_settings()
    if settings is None:
        pytest.skip("DOCPIPE_TEST_POSTGRES_PASSWORD not set; skipping PostgreSQL integration tests")
    assert settings is not None  # pytest.skip() raises; narrows the type for mypy
    probe = create_engine(_url(settings), connect_args={"connect_timeout": 3})
    try:
        with probe.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not reachable at {settings['host']}:{settings['port']}: {exc}")
    finally:
        probe.dispose()
    return settings


@pytest.fixture
def asset_schema(postgres_settings: dict[str, Any]) -> Iterator[str]:
    """A unique PostgreSQL schema name, dropped (with its tables) after the test."""
    schema = f"it_assets_{uuid.uuid4().hex[:12]}"
    yield schema
    PostgresStorageUtils.dispose_engines()
    admin = create_engine(_url(postgres_settings))
    try:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        admin.dispose()


@pytest.fixture
def repo_config(postgres_settings: dict[str, Any], asset_schema: str) -> dict[str, Any]:
    """Repository config in the shape used under assets_management.<asset>_repository.config."""
    return {"postgres": {**postgres_settings, "schema": asset_schema}}


@pytest.fixture
def independent_engine(postgres_settings: dict[str, Any]) -> Iterator[Engine]:
    """A second engine with its own connection pool, standing in for another process."""
    engine = create_engine(_url(postgres_settings), pool_size=5, max_overflow=5)
    yield engine
    engine.dispose()
