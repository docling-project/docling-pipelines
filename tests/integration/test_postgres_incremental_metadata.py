# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Integration tests for PostgreSQL-based incremental metadata store against a real PostgreSQL instance.

Uses the shared PostgreSQL fixtures from ``tests/integration/conftest.py``, which run when
``DOCPIPE_TEST_POSTGRES_PASSWORD`` is set and skip gracefully otherwise.
"""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, inspect

from docpipe.core.incremental_metadata.adapters.stores.postgres.postgres_incremental_store import (
    PostgresIncrementalMetadataStore,
)
from docpipe.core.incremental_metadata.domain.models import IncrementalMetadataRecord

_MODULE = "docpipe.core.incremental_metadata.adapters.stores.postgres.postgres_incremental_store"
pytestmark = pytest.mark.integration


@pytest.fixture
def database(postgres_url: str, postgres_schemas) -> tuple[str, str]:
    return postgres_url, postgres_schemas("test_inc_meta_")


def _create_store(*, url: str, schema: str) -> PostgresIncrementalMetadataStore:
    with patch(f"{_MODULE}.get_postgres_connection_string", return_value=url):
        return PostgresIncrementalMetadataStore(config={"schema": schema})


def test_schema_isolation_and_crud(database: tuple[str, str]) -> None:
    url, schema = database
    store = _create_store(url=url, schema=schema)

    # Verify table was created in the custom schema, not public
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        tables = insp.get_table_names(schema=schema)
        assert "inc_update_metadata" in tables
    finally:
        engine.dispose()

    job_id = "job-schema-test"
    run_id = "run-1"
    records = [
        IncrementalMetadataRecord(job_id=job_id, doc_id="doc-1", name="file1.pdf", modified_time=1000),
        IncrementalMetadataRecord(job_id=job_id, doc_id="doc-2", name="file2.pdf", modified_time=2000),
    ]

    # Upsert
    store.upsert_records(job_id=job_id, job_run_id=run_id, records=records)

    # Read processed docs
    processed = store.get_processed_docs(job_id=job_id)
    assert len(processed) == 2
    assert processed["doc-1"]["modified_time"] == 1000
    assert processed["doc-2"]["modified_time"] == 2000

    # Mark missing (only doc-1 present -> doc-2 soft-deleted)
    deleted = store.mark_missing_docs_as_deleted(job_id=job_id, doc_ids=["doc-1"])
    assert deleted == {"doc-2"}

    soft_deleted = store.get_soft_deleted_doc_ids(job_id=job_id)
    assert soft_deleted == {"doc-2"}

    # Unmark soft-deleted
    store.unmark_soft_deleted_docs(job_id=job_id, doc_ids=["doc-2"])
    assert store.get_soft_deleted_doc_ids(job_id=job_id) == set()

    # Mark missing again and purge
    store.mark_missing_docs_as_deleted(job_id=job_id, doc_ids=["doc-1"])
    store.purge_soft_deleted_docs(job_id=job_id)
    assert store.get_soft_deleted_doc_ids(job_id=job_id) == set()
    assert list(store.get_processed_docs(job_id=job_id).keys()) == ["doc-1"]

    # Delete doc-1
    store.delete_docs(job_id=job_id, doc_ids=["doc-1"])
    assert store.get_processed_docs(job_id=job_id) == {}


def test_batch_duplicate_doc_ids(database: tuple[str, str]) -> None:
    url, schema = database
    store = _create_store(url=url, schema=schema)
    job_id = "job-dup-test"

    records = [
        IncrementalMetadataRecord(job_id=job_id, doc_id="doc-x", name="old.pdf", modified_time=100),
        IncrementalMetadataRecord(job_id=job_id, doc_id="doc-x", name="new.pdf", modified_time=200),
    ]

    # Should succeed without ON CONFLICT duplicate key error in a single statement
    store.upsert_records(job_id=job_id, job_run_id="run-dup", records=records)

    processed = store.get_processed_docs(job_id=job_id)
    assert processed["doc-x"]["modified_time"] == 200


def test_concurrent_upserts_no_unique_violation(database: tuple[str, str]) -> None:
    url, schema = database
    job_id = "job-concurrent-test"

    def _worker(worker_id: int) -> None:
        store = _create_store(url=url, schema=schema)
        records = [
            IncrementalMetadataRecord(
                job_id=job_id,
                doc_id=f"doc-{i}",
                name=f"file-{i}.pdf",
                modified_time=worker_id * 1000 + i,
            )
            for i in range(10)
        ]
        store.upsert_records(job_id=job_id, job_run_id=f"run-{worker_id}", records=records)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_worker, w) for w in range(4)]
        for f in futures:
            f.result()

    store = _create_store(url=url, schema=schema)
    processed = store.get_processed_docs(job_id=job_id)
    assert len(processed) == 10


def test_concurrent_bootstrap_safe(database: tuple[str, str]) -> None:
    url, schema = database

    def _init_store() -> PostgresIncrementalMetadataStore:
        return _create_store(url=url, schema=schema)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_init_store) for _ in range(3)]
        stores = [f.result() for f in futures]

    assert len(stores) == 3
