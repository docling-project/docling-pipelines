# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Contract tests for ``TableStoragePort``, run against every ``StorageFactory`` backend.

The same cases run on DuckDB and on a real PostgreSQL server, so the entity store
and the document set content store can rely on one behavior for both. See
``conftest.py`` for the PostgreSQL settings.
"""

import json
from typing import Any

import pyarrow as pa
import pytest

from docpipe.storage.exceptions import StorageConnectionError, StorageException, StorageValidationError
from docpipe.storage.factory import StorageFactory
from docpipe.storage.interfaces.table_storage_port import TableStoragePort

pytestmark = pytest.mark.integration

_INVOICES = pa.table(
    {
        "id": ["c", "a", "b"],
        "amount": [30.5, 10.5, 20.5],
        "count": [3, 1, 2],
        "paid": [True, False, True],
    }
)


def _create_invoices(storage: TableStoragePort) -> None:
    storage.create_table(table_name="invoice", schema=_INVOICES.schema)
    storage.upsert_data(table_name="invoice", data=_INVOICES)


def test_upsert_twice_is_idempotent(storage: TableStoragePort) -> None:
    _create_invoices(storage)
    storage.upsert_data(table_name="invoice", data=_INVOICES)

    assert storage.get_row_count(table_name="invoice") == 3


def test_upsert_updates_rows_with_the_same_id(storage: TableStoragePort) -> None:
    _create_invoices(storage)

    storage.upsert_data(table_name="invoice", data=pa.table({"id": ["a"], "amount": [99.0]}))

    rows = storage.read_data(table_name="invoice").to_pylist()
    assert rows[0] == {"id": "a", "amount": 99.0, "count": 1, "paid": False}


def test_create_table_twice_keeps_the_table(storage: TableStoragePort) -> None:
    _create_invoices(storage)

    storage.create_table(table_name="invoice", schema=pa.schema([("id", pa.string()), ("other", pa.string())]))

    assert storage.get_row_count(table_name="invoice") == 3
    assert "other" not in storage.read_data(table_name="invoice").column_names


def test_read_pages_are_ordered_by_id(storage: TableStoragePort) -> None:
    _create_invoices(storage)

    first = storage.read_data(table_name="invoice", limit=2, offset=0)
    second = storage.read_data(table_name="invoice", limit=2, offset=2)

    assert first.column("id").to_pylist() == ["a", "b"]
    assert second.column("id").to_pylist() == ["c"]


def test_read_types_are_the_same_on_every_backend(storage: TableStoragePort) -> None:
    _create_invoices(storage)

    assert storage.read_data(table_name="invoice").schema.types == [pa.string(), pa.float64(), pa.int64(), pa.bool_()]
    empty = storage.read_data(table_name="invoice", limit=0)
    assert empty.num_rows == 0
    assert empty.schema.types == [pa.string(), pa.float64(), pa.int64(), pa.bool_()]


def test_nested_values_are_read_back_as_json_text(storage: TableStoragePort) -> None:
    data = pa.table(
        {
            "id": ["a", "b"],
            "details": [{"unit": "EA", "tags": ["hardware", "sale"]}, None],
            "lines": [[{"sku": "X", "qty": 2}], []],
        }
    )
    storage.create_table(table_name="nested", schema=data.schema)

    storage.upsert_data(table_name="nested", data=data)
    storage.upsert_data(table_name="nested", data=data)

    stored = storage.read_data(table_name="nested")
    assert stored.schema.types == [pa.string(), pa.string(), pa.string()]
    [first, second] = stored.to_pylist()
    assert json.loads(first["details"]) == {"unit": "EA", "tags": ["hardware", "sale"]}
    assert json.loads(first["lines"]) == [{"sku": "X", "qty": 2}]
    assert second["details"] is None
    assert json.loads(second["lines"]) == []


def test_schema_evolution_adds_a_column(storage: TableStoragePort) -> None:
    _create_invoices(storage)

    storage.upsert_data(table_name="invoice", data=pa.table({"id": ["d"], "due_date": ["2026-10-21"]}))

    stored = storage.read_data(table_name="invoice")
    assert stored.column_names == ["id", "amount", "count", "paid", "due_date"]
    assert stored.column("due_date").to_pylist() == [None, None, None, "2026-10-21"]


def test_delete_table(storage: TableStoragePort) -> None:
    _create_invoices(storage)

    assert storage.delete_table(table_name="invoice") is True
    assert storage.table_exists(table_name="invoice") is False
    assert storage.delete_table(table_name="invoice") is False
    with pytest.raises(StorageException, match="does not exist"):
        storage.read_data(table_name="invoice")


def test_execute_query_takes_question_mark_placeholders(storage: TableStoragePort) -> None:
    _create_invoices(storage)

    by_id = storage.execute_query(query="SELECT id, amount FROM invoice WHERE id = ?", params=["b"])
    count = storage.execute_query(
        query="SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_name = ?", params=["invoice"]
    )
    literal = storage.execute_query(query="SELECT '100%' AS pct, 'a:b?' AS text_value")

    assert by_id.to_pylist() == [{"id": "b", "amount": 20.5}]
    assert count.column("n").to_pylist() == [1]
    assert literal.to_pylist() == [{"pct": "100%", "text_value": "a:b?"}]


def test_execute_query_writes_are_committed(storage: TableStoragePort) -> None:
    _create_invoices(storage)

    storage.execute_query(
        query="INSERT INTO invoice (id, amount, count, paid) VALUES (?, ?, ?, ?)", params=["d", 40.5, 4, False]
    )
    storage.execute_query(query="UPDATE invoice SET amount = ? WHERE id = ?", params=[11.0, "a"])

    rows = storage.read_data(table_name="invoice").to_pylist()
    assert storage.get_row_count(table_name="invoice") == 4
    assert rows[0] == {"id": "a", "amount": 11.0, "count": 1, "paid": False}
    assert rows[3] == {"id": "d", "amount": 40.5, "count": 4, "paid": False}


def test_integer_column_is_widened_for_float_values(storage: TableStoragePort) -> None:
    # A first run that only has integers creates the column as an integer column.
    storage.create_table(table_name="totals", schema=pa.schema([("id", pa.string()), ("amount", pa.int64())]))
    storage.upsert_data(table_name="totals", data=pa.table({"id": ["a"], "amount": [5]}))

    storage.upsert_data(table_name="totals", data=pa.table({"id": ["b"], "amount": [5.5]}))

    stored = storage.read_data(table_name="totals")
    assert stored.schema.field("amount").type == pa.float64()
    assert stored.column("amount").to_pylist() == [5.0, 5.5]


def test_same_table_name_in_two_schemas(backend: str, postgres_settings: dict[str, Any], postgres_schemas) -> None:
    if backend != "postgres":
        pytest.skip("Only the PostgreSQL backend has schemas")
    entities = StorageFactory.create_table_storage(
        storage_type="postgres", schema=postgres_schemas(), postgres=postgres_settings
    )
    content = StorageFactory.create_table_storage(
        storage_type="postgres", schema=postgres_schemas(), postgres=postgres_settings
    )
    try:
        entities.create_table(table_name="items", schema=pa.schema([("id", pa.string()), ("price", pa.float64())]))
        content.create_table(table_name="items", schema=pa.schema([("id", pa.string()), ("text", pa.string())]))

        entities.upsert_data(table_name="items", data=pa.table({"id": ["a"], "price": [1.5]}))
        content.upsert_data(table_name="items", data=pa.table({"id": ["a"], "text": ["hello"]}))

        assert entities.read_data(table_name="items").to_pylist() == [{"id": "a", "price": 1.5}]
        assert content.read_data(table_name="items").to_pylist() == [{"id": "a", "text": "hello"}]
        assert content.delete_table(table_name="items") is True
        assert entities.table_exists(table_name="items") is True
    finally:
        entities.close()
        content.close()


def test_incompatible_column_type_is_rejected(backend: str, storage: TableStoragePort) -> None:
    _create_invoices(storage)

    with pytest.raises(StorageException) as error:
        storage.upsert_data(table_name="invoice", data=pa.table({"id": ["a"], "count": ["many"]}))

    if backend == "postgres":
        # PostgreSQL checks the types before writing and names the column.
        assert isinstance(error.value, StorageValidationError)
        assert "Column count of table invoice has type bigint" in str(error.value)
    assert storage.read_data(table_name="invoice").to_pylist()[0]["count"] == 1


def test_unreachable_postgres_fails_when_the_storage_is_created(postgres_settings: dict[str, Any]) -> None:
    settings = {**postgres_settings, "port": 1}

    with pytest.raises(StorageConnectionError, match="Failed to connect"):
        StorageFactory.create_table_storage(storage_type="postgres", schema="unused", postgres=settings)
