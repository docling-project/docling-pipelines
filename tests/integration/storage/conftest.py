# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Fixtures for the table storage contract tests.

Every test runs once per ``StorageFactory`` table backend. The PostgreSQL runs use
the shared ``postgres_settings`` and ``postgres_schemas`` fixtures from
``tests/integration/conftest.py``, and are skipped without a test server.
"""

from collections.abc import Iterator
from typing import Any

import pytest

from docpipe.storage.factory import StorageFactory
from docpipe.storage.interfaces.table_storage_port import TableStoragePort


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
        schema = request.getfixturevalue("postgres_schemas")("it_tables_")
        created = StorageFactory.create_table_storage(storage_type="postgres", schema=schema, postgres=settings)
    yield created
    created.close()
