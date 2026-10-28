# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for PostgresTableStorage, with a fake engine instead of a live database.

The SQL behavior against a real PostgreSQL server is covered by
``tests/integration/storage/test_table_storage_contract.py``.
"""

from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pyarrow as pa
import pytest

from docpipe.storage.exceptions import StorageConnectionError, StorageException, StorageValidationError
from docpipe.storage.factory import StorageFactory
from docpipe.storage.postgres.postgres_table_storage import PostgresTableStorage

_MODULE = "docpipe.storage.postgres.postgres_table_storage"


class _FakeResult:
    """Result of a fake statement, with the parts of a SQLAlchemy result the storage reads."""

    def __init__(self, *, rows: list[Any] | None = None, description: list[Any] | None = None, scalar: Any = None):
        self._rows = rows or []
        self.cursor = MagicMock(description=description or [])
        self._scalar = scalar
        self.returns_rows = description is not None

    def mappings(self) -> MagicMock:
        return MagicMock(all=MagicMock(return_value=self._rows))

    def fetchall(self) -> list[Any]:
        return self._rows

    def scalar(self) -> Any:
        return self._scalar


class _FakeEngine:
    """Engine that answers by SQL text and records every statement."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []
        self.columns: list[dict[str, str]] = []
        self.table_exists = True
        self.select_description: list[Any] = []
        self.select_rows: list[Any] = []
        self.fail_with: Exception | None = None
        self.disposed = False

    @contextmanager
    def connect(self):
        yield self

    begin = connect

    def dispose(self) -> None:
        self.disposed = True

    def execute(self, statement: Any, params: Any = None) -> _FakeResult:
        return self._respond(sql=str(statement), params=params)

    def exec_driver_sql(self, sql: str, params: Any = None) -> _FakeResult:
        return self._respond(sql=sql, params=params)

    def _respond(self, *, sql: str, params: Any) -> _FakeResult:
        self.statements.append((sql, params))
        if self.fail_with is not None:
            raise self.fail_with
        if "information_schema.columns" in sql:
            return _FakeResult(rows=self.columns)
        if "information_schema.tables" in sql:
            return _FakeResult(scalar=self.table_exists)
        if "COUNT(*)" in sql:
            return _FakeResult(scalar=3)
        if sql.lstrip().upper().startswith("SELECT") and "pg_advisory" not in sql and sql.strip() != "SELECT 1":
            return _FakeResult(rows=self.select_rows, description=self.select_description)
        return _FakeResult()

    def sql(self, fragment: str) -> list[tuple[str, Any]]:
        """Return the recorded statements that contain a fragment."""
        return [(sql, params) for sql, params in self.statements if fragment in sql]


@pytest.fixture
def engine(monkeypatch) -> _FakeEngine:
    fake = _FakeEngine()
    monkeypatch.setattr(
        f"{_MODULE}.get_postgres_connection_string",
        lambda **kwargs: "postgresql+psycopg2://user:password@localhost:5432/docpipe",  # pragma: allowlist secret
    )
    monkeypatch.setattr(f"{_MODULE}.create_postgres_engine", lambda **kwargs: fake)
    return fake


@pytest.fixture
def storage(engine) -> PostgresTableStorage:
    created = PostgresTableStorage(schema="entities")
    engine.statements.clear()
    return created


class TestPostgresTableStorageInit:
    """Connection, schema bootstrap and configuration errors."""

    def test_checks_the_connection_and_creates_the_schema(self, engine):
        PostgresTableStorage(schema="entities")

        assert engine.statements[0][0] == "SELECT 1"
        assert engine.sql("pg_advisory_xact_lock")[0][1] == {"schema": "entities"}
        assert engine.sql('CREATE SCHEMA IF NOT EXISTS "entities"')

    def test_default_schema_is_public(self, engine):
        assert PostgresTableStorage().schema == "public"

    def test_invalid_schema_is_rejected(self, engine):
        with pytest.raises(StorageValidationError, match="schema name"):
            PostgresTableStorage(schema="bad-schema")

    def test_missing_password_fails(self, monkeypatch):
        monkeypatch.setattr(f"{_MODULE}.get_postgres_connection_string", lambda **kwargs: None)

        with pytest.raises(StorageConnectionError, match="not configured"):
            PostgresTableStorage()

    def test_unreachable_database_fails_at_creation(self, engine):
        engine.fail_with = RuntimeError("connection refused")

        with pytest.raises(StorageConnectionError, match="connection refused"):
            PostgresTableStorage()

    def test_close_disposes_the_engine(self, storage, engine):
        storage.close()

        assert engine.disposed


class TestPostgresTableStorageHelpers:
    """Pure helpers: identifiers, types and placeholder translation."""

    @pytest.mark.parametrize("identifier", ["", "bad-name", "x" * 64])
    def test_invalid_identifiers(self, identifier):
        with pytest.raises(StorageValidationError):
            PostgresTableStorage._validate_identifier(identifier=identifier, kind="table name")

    @pytest.mark.parametrize(
        ("pa_type", "expected"),
        [
            (pa.string(), "TEXT"),
            (pa.int64(), "BIGINT"),
            (pa.int8(), "SMALLINT"),
            (pa.float64(), "DOUBLE PRECISION"),
            (pa.bool_(), "BOOLEAN"),
            (pa.timestamp("us"), "TIMESTAMP"),
            (pa.list_(pa.string()), "JSONB"),
            (pa.struct([("unit", pa.string())]), "JSONB"),
            (pa.null(), "TEXT"),
            (pa.decimal128(10, 2), "TEXT"),
        ],
    )
    def test_pyarrow_to_postgres_type(self, pa_type, expected):
        assert PostgresTableStorage._pyarrow_to_postgres_type(pa_type=pa_type) == expected

    @pytest.mark.parametrize(
        ("existing", "incoming", "compatible"),
        [
            ("bigint", pa.int64(), True),
            ("double precision", pa.int64(), True),
            ("bigint", pa.float64(), False),
            ("text", pa.int64(), False),
            ("bigint", pa.string(), False),
            ("jsonb", pa.string(), True),
            ("bigint", pa.null(), True),
        ],
    )
    def test_is_compatible_type(self, existing, incoming, compatible):
        assert PostgresTableStorage._is_compatible_type(existing=existing, incoming=incoming) is compatible

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("SELECT * FROM t WHERE id = ?", "SELECT * FROM t WHERE id = %s"),
            ("SELECT '100%' AS v WHERE a = ?", "SELECT '100%%' AS v WHERE a = %s"),
            ("SELECT 'what?' AS q, \"col?\" FROM t", "SELECT 'what?' AS q, \"col?\" FROM t"),
            ("SELECT 'it''s?' WHERE a = ?", "SELECT 'it''s?' WHERE a = %s"),
        ],
    )
    def test_to_driver_sql(self, query, expected):
        assert PostgresTableStorage._to_driver_sql(query=query) == expected

    def test_result_to_arrow_uses_the_driver_types(self):
        description = [("id", 25), ("count", 20), ("score", 1700), ("details", 3802), ("other", 9999)]
        rows = [("a", 1, Decimal("2.5"), {"unit": "EA", "tags": ["x"]}, "v")]

        table = PostgresTableStorage._result_to_arrow(description=description, rows=rows)

        assert table.schema.types == [pa.string(), pa.int64(), pa.float64(), pa.string(), pa.string()]
        assert table.to_pylist() == [
            {"id": "a", "count": 1, "score": 2.5, "details": '{"unit":"EA","tags":["x"]}', "other": "v"}
        ]

    def test_result_to_arrow_keeps_types_without_rows(self):
        table = PostgresTableStorage._result_to_arrow(description=[("id", 25), ("amount", 701)], rows=[])

        assert table.num_rows == 0
        assert table.schema.types == [pa.string(), pa.float64()]


class TestPostgresTableStorageFactory:
    """The factory takes the same flat settings for every backend."""

    def test_postgres_is_supported(self):
        assert "postgres" in StorageFactory.SUPPORTED_TABLE_TYPES

    def test_factory_passes_only_the_postgres_settings(self, engine):
        storage = StorageFactory.create_table_storage(
            storage_type="postgres", database_path="ignored.duckdb", schema="entities"
        )

        assert isinstance(storage, PostgresTableStorage)
        assert storage.schema == "entities"

    def test_factory_rejects_unknown_settings(self):
        with pytest.raises(ValueError, match="Unknown table storage settings: config"):
            StorageFactory.create_table_storage(storage_type="postgres", config={})


class TestPostgresTableStorageOperations:
    """Statements sent for table operations."""

    def test_create_table_qualifies_the_table(self, storage, engine):
        storage.create_table(table_name="invoice", schema=pa.schema([("id", pa.string()), ("amount", pa.float64())]))

        [(sql, _params)] = engine.sql("CREATE TABLE")
        assert 'CREATE TABLE IF NOT EXISTS "entities"."invoice"' in sql
        assert '"id" TEXT PRIMARY KEY' in sql
        assert '"amount" DOUBLE PRECISION' in sql

    def test_upsert_writes_all_rows_in_one_bulk_call(self, storage, engine):
        engine.columns = [
            {"column_name": "id", "data_type": "text"},
            {"column_name": "amount", "data_type": "double precision"},
            {"column_name": "details", "data_type": "jsonb"},
        ]
        data = pa.table(
            {
                "id": ["doc1", "doc2"],
                "amount": [10.5, 20.5],
                "details": [{"unit": "EA", "tags": ["a"]}, None],
            }
        )

        storage.upsert_data(table_name="invoice", data=data)

        [(sql, rows)] = engine.sql("INSERT INTO")
        assert 'INSERT INTO "entities"."invoice"' in sql
        assert 'ON CONFLICT ("id") DO UPDATE SET' in sql
        # JSONB values are sent as JSON text: psycopg2 cannot adapt a dict.
        assert rows == [
            {"id": "doc1", "amount": 10.5, "details": '{"unit":"EA","tags":["a"]}'},
            {"id": "doc2", "amount": 20.5, "details": None},
        ]

    def test_upsert_of_only_ids_does_nothing_on_conflict(self, storage, engine):
        engine.columns = [{"column_name": "id", "data_type": "text"}]

        storage.upsert_data(table_name="invoice", data=pa.table({"id": ["doc1"]}))

        [(sql, _rows)] = engine.sql("INSERT INTO")
        assert "DO NOTHING" in sql

    def test_upsert_adds_missing_columns_once(self, storage, engine):
        engine.columns = [{"column_name": "id", "data_type": "text"}]
        data = pa.table({"id": ["doc1"], "invoice_date": ["2026-10-07"]})

        storage.upsert_data(table_name="invoice", data=data)
        storage.upsert_data(table_name="invoice", data=data)

        [(alter_sql, _params)] = engine.sql("ALTER TABLE")
        assert 'ALTER TABLE "entities"."invoice" ADD COLUMN IF NOT EXISTS "invoice_date" TEXT' in alter_sql
        # The second upsert uses the cached columns instead of reading information_schema.
        [(columns_sql, columns_params)] = engine.sql("information_schema.columns")
        assert "table_schema = :table_schema" in columns_sql
        assert columns_params == {"table_schema": "entities", "table_name": "invoice"}

    def test_upsert_rejects_an_incompatible_column_type(self, storage, engine):
        engine.columns = [
            {"column_name": "id", "data_type": "text"},
            {"column_name": "amount", "data_type": "bigint"},
        ]

        with pytest.raises(StorageValidationError, match="Column amount of table invoice has type bigint"):
            storage.upsert_data(table_name="invoice", data=pa.table({"id": ["doc1"], "amount": ["5.0"]}))

        assert not engine.sql("INSERT INTO")

    def test_upsert_requires_an_id_column(self, storage):
        with pytest.raises(StorageValidationError, match="'id' column"):
            storage.upsert_data(table_name="invoice", data=pa.table({"name": ["x"]}))

    def test_upsert_into_a_missing_table_fails(self, storage, engine):
        engine.table_exists = False

        with pytest.raises(StorageException, match="does not exist"):
            storage.upsert_data(table_name="invoice", data=pa.table({"id": ["doc1"]}))

    def test_upsert_empty_table_does_not_write(self, storage, engine):
        storage.upsert_data(table_name="invoice", data=pa.table({"id": pa.array([], type=pa.string())}))

        assert not engine.sql("INSERT INTO")

    def test_read_data_is_ordered_and_paginated(self, storage, engine):
        engine.columns = [{"column_name": "id", "data_type": "text"}]
        engine.select_description = [("id", 25), ("amount", 701)]
        engine.select_rows = [("doc2", 20.5)]

        table = storage.read_data(table_name="invoice", limit=1, offset=1)

        [(sql, params)] = engine.sql('SELECT * FROM "entities"."invoice"')
        assert 'ORDER BY "id" LIMIT :limit OFFSET :offset' in sql
        assert params == {"limit": 1, "offset": 1}
        assert table.to_pylist() == [{"id": "doc2", "amount": 20.5}]

    def test_read_data_of_an_empty_table_keeps_column_types(self, storage, engine):
        engine.columns = [{"column_name": "id", "data_type": "text"}]
        engine.select_description = [("id", 25), ("amount", 701)]

        table = storage.read_data(table_name="invoice")

        assert table.num_rows == 0
        assert table.schema.types == [pa.string(), pa.float64()]

    def test_delete_table_drops_the_qualified_table(self, storage, engine):
        assert storage.delete_table(table_name="invoice") is True
        assert engine.sql('DROP TABLE IF EXISTS "entities"."invoice"')

    def test_delete_missing_table_returns_false(self, storage, engine):
        engine.table_exists = False

        assert storage.delete_table(table_name="invoice") is False
        assert not engine.sql("DROP TABLE")

    def test_get_row_count(self, storage, engine):
        assert storage.get_row_count(table_name="invoice") == 3
        assert engine.sql('SELECT COUNT(*) FROM "entities"."invoice"')

    def test_table_exists_filters_by_schema(self, storage, engine):
        assert storage.table_exists(table_name="invoice") is True

        [(sql, params)] = engine.sql("information_schema.tables")
        assert "table_schema = :table_schema" in sql
        assert params == {"table_schema": "entities", "table_name": "invoice"}

    def test_table_exists_raises_when_the_database_is_down(self, storage, engine):
        engine.fail_with = RuntimeError("server closed the connection")

        with pytest.raises(StorageConnectionError, match="server closed the connection"):
            storage.table_exists(table_name="invoice")

    def test_execute_query_translates_placeholders(self, storage, engine):
        engine.select_description = [("id", 25)]
        engine.select_rows = [("doc1",)]

        table = storage.execute_query(query="SELECT id FROM invoice WHERE id = ?", params=["doc1"])

        assert table.to_pylist() == [{"id": "doc1"}]
        assert engine.statements[0] == ('SET LOCAL search_path TO "entities", public', ())
        assert engine.statements[1] == ("SELECT id FROM invoice WHERE id = %s", ("doc1",))

    def test_execute_query_without_rows_returns_an_empty_table(self, storage, engine):
        table = storage.execute_query(query="UPDATE invoice SET amount = 0")

        assert table.num_rows == 0
        assert engine.statements[1] == ("UPDATE invoice SET amount = 0", ())

    def test_execute_query_failure(self, storage, engine):
        engine.fail_with = RuntimeError("syntax error")

        with pytest.raises(StorageException, match="Failed to execute query"):
            storage.execute_query(query="SELEC 1")


class TestPostgresTableStorageWidening:
    """Integer columns become DOUBLE PRECISION when float values arrive."""

    @pytest.mark.parametrize(
        ("existing", "incoming", "widen"),
        [
            ("bigint", pa.float64(), True),
            ("integer", pa.float32(), True),
            ("bigint", pa.int64(), False),
            ("double precision", pa.float64(), False),
            ("text", pa.float64(), False),
        ],
    )
    def test_needs_widening(self, existing, incoming, widen):
        assert PostgresTableStorage._needs_widening(existing=existing, incoming=incoming) is widen

    def test_upsert_widens_an_integer_column(self, storage, engine):
        engine.columns = [
            {"column_name": "id", "data_type": "text"},
            {"column_name": "amount", "data_type": "bigint"},
        ]

        storage.upsert_data(table_name="invoice", data=pa.table({"id": ["doc1"], "amount": [5.5]}))

        [(sql, _params)] = engine.sql("ALTER COLUMN")
        assert 'ALTER TABLE "entities"."invoice" ALTER COLUMN "amount" TYPE DOUBLE PRECISION' in sql
        [(_insert, rows)] = engine.sql("INSERT INTO")
        assert rows == [{"id": "doc1", "amount": 5.5}]

    def test_execute_query_without_rows_forgets_the_cached_columns(self, storage, engine):
        engine.columns = [{"column_name": "id", "data_type": "text"}]
        storage.upsert_data(table_name="invoice", data=pa.table({"id": ["doc1"]}))

        storage.execute_query(query="ALTER TABLE invoice ADD COLUMN note TEXT")
        storage.upsert_data(table_name="invoice", data=pa.table({"id": ["doc1"]}))

        # The second upsert reads the columns again, because the statement could have changed them.
        assert len(engine.sql("information_schema.columns")) == 2
