# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Edge-case tests for EntityStoreOperator: empty entities and non-object entity values."""

from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.operators.storage.entity_store_operator import EntityStoreOperator

_FACTORY = "docpipe.core.operators.storage.entity_store_operator.StorageFactory.create_table_storage"


@pytest.fixture
def storage() -> MagicMock:
    """Return a mocked table storage that reports no existing tables."""
    mock = MagicMock()
    mock.table_exists.return_value = False
    return mock


@pytest.fixture
def operator(storage: MagicMock) -> EntityStoreOperator:
    """Return an operator wired to the mocked storage."""
    with patch(_FACTORY, return_value=storage):
        return EntityStoreOperator({"data_backend": "duckdb", "database_path": ":memory:"})


class TestEmptyEntities:
    """Documents without curated entities are skipped, not failed."""

    @pytest.mark.parametrize("value", [None, ""])
    def test_document_without_entities_is_skipped(
        self, operator: EntityStoreOperator, storage: MagicMock, value: str | None
    ) -> None:
        """An empty entities column records a skip with the column name and writes nothing."""
        table = pa.table(
            {
                "id": ["doc1"],
                "name": ["a.pdf"],
                "transformed_entities": pa.array([value], type=pa.string()),
            }
        )

        _, metadata = operator.transform(table)

        assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 1
        assert metadata[Metrics.External.PROCESSED_DOCS] == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0
        skipped = metadata[Metrics.External.SKIPPED_DOCS][0]
        assert skipped["id"] == "doc1"
        assert "transformed_entities" in skipped["reason"]
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED.value
        storage.create_table.assert_not_called()
        storage.upsert_data.assert_not_called()
        storage.close.assert_called_once()


class TestNonObjectEntityValues:
    """Entity values that hold no objects produce no rows and no tables."""

    def test_empty_list_creates_no_table(self, operator: EntityStoreOperator, storage: MagicMock) -> None:
        """An empty list is processed but no 0-column table is created."""
        table = pa.table({"id": ["doc1"], "name": ["a.pdf"], "transformed_entities": ['{"Items": []}']})

        _, metadata = operator.transform(table)

        assert metadata[Metrics.External.PROCESSED_DOCS] == 1
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0
        storage.create_table.assert_not_called()
        storage.upsert_data.assert_not_called()

    def test_scalar_entity_value_yields_no_rows(self, operator: EntityStoreOperator, storage: MagicMock) -> None:
        """A scalar entity value is ignored while object values of the same document are stored."""
        table = pa.table(
            {
                "id": ["doc1"],
                "name": ["a.pdf"],
                "transformed_entities": ['{"Total": 42, "Invoice": {"number": "INV-1"}}'],
            }
        )

        _, metadata = operator.transform(table)

        assert metadata[Metrics.External.PROCESSED_DOCS] == 1
        written = [c.kwargs["table_name"] for c in storage.upsert_data.call_args_list]
        assert written == ["entity_Invoice"]

    def test_entity_rows_for_scalar_is_empty(self) -> None:
        """_entity_rows returns no rows for a value that is neither an object nor a list."""
        assert EntityStoreOperator._entity_rows(doc_id="d", table_name="t", entity_data="text") == []
