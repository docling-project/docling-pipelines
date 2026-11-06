# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""PostgresDocumentSetStorage against a real PostgreSQL server.

Uses the shared PostgreSQL fixtures from ``tests/integration/conftest.py`` and is
skipped without a test server.
"""

from collections.abc import Callable, Iterator
from typing import Any

import pyarrow as pa
import pytest
from sqlalchemy import create_engine, text

from docpipe.core.assets.document_sets.adapters.postgres.data_store import PostgresDocumentSetStorage
from docpipe.core.assets.document_sets.factories.data_store_factory import DataStoreFactory
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode

pytestmark = pytest.mark.integration


@pytest.fixture
def content_schema(postgres_schemas: Callable[..., str]) -> str:
    """A throw-away schema for the content tables."""
    return postgres_schemas("it_doc_sets_")


@pytest.fixture
def store(postgres_settings: dict[str, Any], content_schema: str) -> Iterator[PostgresDocumentSetStorage]:
    """A PostgreSQL document set store created through the factory, as the operator does."""
    created = DataStoreFactory.create(
        adapter_name="postgres",
        config={
            "database_path": "unused.duckdb",
            "content_schema": content_schema,
            # The metadata schema of the connection block is not used for content tables.
            "postgres": {**postgres_settings, "schema": "it_metadata_unused"},
        },
    )
    assert isinstance(created, PostgresDocumentSetStorage)
    yield created
    created._storage.close()


def test_store_load_metrics_and_delete(store: PostgresDocumentSetStorage, content_schema: str) -> None:
    data = pa.table({"id": ["b", "a"], "size": [200, 100], "pages_processed": [2, 1]})

    ref = store.store(doc_set_name="Invoices 2026", data=data)
    store.store(doc_set_name="Invoices 2026", data=pa.table({"id": ["a"], "size": [150], "pages_processed": [1]}))

    assert ref.backend_type == "postgres"
    assert ref.details == {"schema": content_schema, "table_name": "invoices_2026"}
    assert store.exists(attachment_ref=ref) is True
    assert store.load(attachment_ref=ref).to_pylist() == [
        {"id": "a", "size": 150, "pages_processed": 1},
        {"id": "b", "size": 200, "pages_processed": 2},
    ]
    assert store.load(attachment_ref=ref, limit=1).num_rows == 1
    assert store.get_metrics(attachment_ref=ref) == {"total_documents": 2, "total_size_bytes": 350, "total_pages": 3}
    assert store.health_check() == {
        "healthy": True,
        "message": "Storage is healthy",
        "details": {"schema": content_schema},
    }

    assert store.delete(attachment_ref=ref) is True
    assert store.exists(attachment_ref=ref) is False
    assert store.delete(attachment_ref=ref) is False
    with pytest.raises(DocpipeException) as exc_info:
        store.load(attachment_ref=ref)
    assert exc_info.value.error_code == ErrorCode.DOCUMENT_SET_TABLE_NOT_FOUND


def test_metrics_ignore_a_table_with_the_same_name_in_another_schema(
    store: PostgresDocumentSetStorage, postgres_url: str, postgres_schemas: Callable[..., str]
) -> None:
    ref = store.store(doc_set_name="Shared Name", data=pa.table({"id": ["1", "2"]}))
    other_schema = postgres_schemas("it_other_")
    engine = create_engine(postgres_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{other_schema}"'))
            connection.execute(
                text(f'CREATE TABLE "{other_schema}".shared_name (id TEXT, size BIGINT, pages_processed BIGINT)')
            )
    finally:
        engine.dispose()

    assert store.get_metrics(attachment_ref=ref) == {"total_documents": 2, "total_size_bytes": 0, "total_pages": 0}
