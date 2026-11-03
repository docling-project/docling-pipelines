# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Shared fixtures for the PostgreSQL integration tests.

The PostgreSQL tests need a real server. They are skipped unless
``DOCPIPE_TEST_POSTGRES_PASSWORD`` is set and the server is reachable.
Dedicated ``DOCPIPE_TEST_*`` variables are used on purpose, so a developer's
regular ``DOCPIPE_POSTGRES_*`` settings never point the tests at a real database.

Environment variables:
    DOCPIPE_TEST_POSTGRES_HOST      (default: localhost)
    DOCPIPE_TEST_POSTGRES_PORT      (default: 5432)
    DOCPIPE_TEST_POSTGRES_DB        (default: docpipe_test)
    DOCPIPE_TEST_POSTGRES_USER      (default: postgres)
    DOCPIPE_TEST_POSTGRES_PASSWORD  (required)

Tests create their tables in throw-away schemas from ``postgres_schemas``, which
are dropped on teardown.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


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
    url = URL.create(
        "postgresql+psycopg2",
        username=settings["user"],
        password=settings["password"],
        host=settings["host"],
        port=settings["port"],
        database=settings["database"],
    )
    return url.render_as_string(hide_password=False)


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


@pytest.fixture(scope="session")
def postgres_url(postgres_settings: dict[str, Any]) -> str:
    """SQLAlchemy URL of the test server, built from ``postgres_settings``."""
    return _url(postgres_settings)


@pytest.fixture
def postgres_schemas(postgres_url: str) -> Iterator[Callable[..., str]]:
    """Return a factory of unique schema names; every schema is dropped after the test."""
    schemas: list[str] = []

    def new_schema(prefix: str = "it_") -> str:
        schema = f"{prefix}{uuid.uuid4().hex[:12]}"
        schemas.append(schema)
        return schema

    yield new_schema

    admin = create_engine(postgres_url)
    try:
        with admin.begin() as connection:
            for schema in schemas:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        admin.dispose()
