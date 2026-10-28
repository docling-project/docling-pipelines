# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Fixtures for the table storage contract tests.

Every test runs once per ``StorageFactory`` table backend. The PostgreSQL runs need
a real server and are skipped unless its settings are given and the server is
reachable. Dedicated ``DOCPIPE_TEST_*`` variables are used on purpose, so a
developer's regular ``DOCPIPE_POSTGRES_*`` settings never point the tests at a
real database.

Environment variables:
    DOCPIPE_TEST_POSTGRES_HOST      (default: localhost)
    DOCPIPE_TEST_POSTGRES_PORT      (default: 5432)
    DOCPIPE_TEST_POSTGRES_DB        (default: docpipe_test)
    DOCPIPE_TEST_POSTGRES_USER      (default: postgres)
    DOCPIPE_TEST_POSTGRES_PASSWORD  (required, unless DOCPIPE_TEST_POSTGRES_DSN is set)
    DOCPIPE_TEST_POSTGRES_DSN       (used when DOCPIPE_TEST_POSTGRES_PASSWORD is not set:
                                     a database URL, as for the other PostgreSQL integration tests)

Every PostgreSQL test gets its own throw-away schema, dropped on teardown.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from docpipe.storage.factory import StorageFactory
from docpipe.storage.interfaces.table_storage_port import TableStoragePort


def _postgres_settings() -> dict[str, Any] | None:
    password = os.getenv("DOCPIPE_TEST_POSTGRES_PASSWORD")
    if password:
        return {
            "host": os.getenv("DOCPIPE_TEST_POSTGRES_HOST", "localhost"),
            "port": int(os.getenv("DOCPIPE_TEST_POSTGRES_PORT", "5432")),
            "database": os.getenv("DOCPIPE_TEST_POSTGRES_DB", "docpipe_test"),
            "user": os.getenv("DOCPIPE_TEST_POSTGRES_USER", "postgres"),
            "password": password,
        }

    dsn = os.getenv("DOCPIPE_TEST_POSTGRES_DSN")
    if not dsn:
        return None
    url = make_url(dsn)
    return {
        "host": url.host or "localhost",
        "port": url.port or 5432,
        "database": url.database or "docpipe_test",
        "user": url.username or "postgres",
        "password": url.password or "",
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
        pytest.skip(
            "Neither DOCPIPE_TEST_POSTGRES_PASSWORD nor DOCPIPE_TEST_POSTGRES_DSN is set; "
            "skipping PostgreSQL storage tests"
        )
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
def postgres_schemas(postgres_settings: dict[str, Any]) -> Iterator[Callable[[], str]]:
    """Return a factory of unique schema names; every schema is dropped after the test."""
    schemas: list[str] = []

    def new_schema() -> str:
        schema = f"it_tables_{uuid.uuid4().hex[:12]}"
        schemas.append(schema)
        return schema

    yield new_schema

    admin = create_engine(_url(postgres_settings))
    try:
        with admin.begin() as connection:
            for schema in schemas:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        admin.dispose()


@pytest.fixture(params=["duckdb", "postgres"])
def backend(request: pytest.FixtureRequest) -> str:
    """Name of the table storage backend under test."""
    return str(request.param)


@pytest.fixture
def storage(backend: str, request: pytest.FixtureRequest, tmp_path: Any) -> Iterator[TableStoragePort]:
    """A table storage of the backend under test, created through the factory."""
    if backend == "duckdb":
        created = StorageFactory.create_table_storage(
            storage_type="duckdb", database_path=str(tmp_path / "contract.duckdb")
        )
    else:
        settings = request.getfixturevalue("postgres_settings")
        schema = request.getfixturevalue("postgres_schemas")()
        created = StorageFactory.create_table_storage(storage_type="postgres", schema=schema, postgres=settings)
    yield created
    created.close()
