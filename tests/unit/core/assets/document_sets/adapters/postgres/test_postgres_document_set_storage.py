# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for PostgresDocumentSetStorage.

The table operations are shared with DuckDBDocumentSetStorage and covered there;
these tests cover what is specific to PostgreSQL: the AttachmentRef coordinates,
the health check details, the factory registration and the configuration.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.assets.document_sets.adapters.postgres.data_store import PostgresDocumentSetStorage
from docpipe.core.assets.document_sets.factories.data_store_factory import DataStoreFactory
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.storage import StorageFactory

_SCHEMA = "docpipe_document_sets"


def _make_sut(*, storage: MagicMock | None = None) -> PostgresDocumentSetStorage:
    if storage is None:
        storage = MagicMock()
        storage.table_exists.return_value = False
    return PostgresDocumentSetStorage(table_storage=storage, schema=_SCHEMA)


class TestStoreAndHealthCheck:
    def test_store_returns_postgres_attachment_ref(self):
        """store() returns a ref with the content schema and table name."""
        storage = MagicMock()
        storage.table_exists.return_value = False

        ref = _make_sut(storage=storage).store(doc_set_name="My Docs", data=pa.table({"id": ["1"]}))

        assert ref.backend_type == "postgres"
        assert ref.name == "my_docs"
        assert ref.details == {"schema": _SCHEMA, "table_name": "my_docs"}
        storage.create_table.assert_called_once()
        storage.upsert_data.assert_called_once()

    def test_health_check_reports_the_schema(self):
        """A reachable backend is healthy and reports its schema."""
        result = _make_sut().health_check()

        assert result["healthy"] is True
        assert result["details"] == {"schema": _SCHEMA}

    def test_health_check_reports_failure_with_the_schema(self):
        """A failing backend is unhealthy, with the schema and the error in the details."""
        storage = MagicMock()
        storage.execute_query.side_effect = RuntimeError("connection refused")

        result = _make_sut(storage=storage).health_check()

        assert result["healthy"] is False
        assert result["details"]["schema"] == _SCHEMA
        assert "connection refused" in result["details"]["error"]


class TestFromConfig:
    def test_factory_creates_postgres_store_with_defaults(self):
        """Without content_schema the store uses docpipe_document_sets."""
        with patch.object(StorageFactory, "create_table_storage", return_value=MagicMock()) as create:
            store = DataStoreFactory.create(adapter_name="postgres", config={"database_path": "unused.duckdb"})

        assert isinstance(store, PostgresDocumentSetStorage)
        assert store._schema == _SCHEMA
        create.assert_called_once_with(storage_type="postgres", schema=_SCHEMA, postgres={})

    def test_from_config_uses_content_schema_and_connection_settings(self):
        """The metadata schema in the connection block is not used for the content tables."""
        config: dict[str, Any] = {
            "content_schema": "doc_set_content",
            "postgres": {"host": "db", "port": 5433, "user": "docpipe", "schema": "docpipe_assets"},
        }

        with patch.object(StorageFactory, "create_table_storage", return_value=MagicMock()) as create:
            store = PostgresDocumentSetStorage.from_config(config=config)

        assert store._schema == "doc_set_content"
        create.assert_called_once_with(
            storage_type="postgres",
            schema="doc_set_content",
            postgres={"host": "db", "port": 5433, "user": "docpipe"},
        )
        assert config["postgres"]["schema"] == "docpipe_assets"

    @pytest.mark.parametrize(
        ("config", "match"),
        [
            ({"content_schema": ""}, "content_schema"),
            ({"content_schema": "bad-name"}, "content_schema"),
            ({"content_schema": "x" * 64}, "content_schema"),
            ({"content_schema": 5}, "content_schema"),
            ({"postgres": "host=db"}, "postgres"),
        ],
    )
    def test_from_config_rejects_invalid_config(self, config, match):
        """Invalid settings fail before a connection is attempted."""
        with patch.object(StorageFactory, "create_table_storage") as create:
            with pytest.raises(DocpipeException, match=match) as exc_info:
                PostgresDocumentSetStorage.from_config(config=config)

        assert exc_info.value.status_code == 400
        create.assert_not_called()

    def test_validate_config_accepts_empty_config(self):
        """All settings are optional; the connection falls back to DOCPIPE_POSTGRES_*."""
        assert PostgresDocumentSetStorage.validate_config(config={}) == []
