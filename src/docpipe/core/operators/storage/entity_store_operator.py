# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Entity storage operator."""

import json
import re
from typing import Any

import pyarrow as pa

from docpipe.core.constants.constants import AttributeDataTypes, ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.storage.factory import StorageFactory
from docpipe.storage.interfaces.table_storage_port import TableStoragePort
from docpipe.types import FlowConfig, OperatorMetadata, OperatorOutputMetadata, TransformResult
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

ENTITIES_COLUMN = "entities_column"
DEFAULT_ENTITY_SCHEMA = "docpipe_entities"
DEFAULT_ENTITY_TABLE_PREFIX = "entity_"

_TABLE_NAME_RE = re.compile(r"^\w+$")
_TABLE_PREFIX_RE = re.compile(r"^\w*$")
_MAX_TABLE_NAME_LENGTH = 63
# Table names of other docpipe components, which entity tables must never replace.
_RESERVED_TABLE_PREFIXES = ("docpipe_", "pg_")
_RESERVED_TABLE_NAMES = frozenset({OperatorConstants.DocumentSet.TABLE_DOCUMENT_SETS_METADATA})


class EntityStoreOperator(AbstractOperator):
    """Store curated entities in DuckDB or PostgreSQL.

    Each key of the curated entities JSON object names an entity table. A JSON object
    is stored as one row, a list of objects as one row per object.
    """

    short_name = OperatorConstants.Operators.ENTITY_STORE_OPERATOR
    category = OperatorCategory.Storage
    owner = "docpipe"

    _SUPPORTED_BACKENDS = (OperatorConstants.Storage.BACKEND_DUCKDB, OperatorConstants.Storage.BACKEND_POSTGRES)

    def __init__(self, config: FlowConfig) -> None:
        super().__init__(config)

        self.data_backend = config.get(
            OperatorConstants.Storage.DATA_BACKEND,
            OperatorConstants.Storage.DEFAULT_DATA_BACKEND,
        )
        self.database_path = config.get(
            OperatorConstants.Storage.DATABASE_PATH,
            OperatorConstants.Storage.DEFAULT_DATABASE_PATH,
        )
        self.schema = config.get(OperatorConstants.Storage.SCHEMA, DEFAULT_ENTITY_SCHEMA)
        self.table_prefix = config.get(OperatorConstants.Storage.TABLE_PREFIX, DEFAULT_ENTITY_TABLE_PREFIX)
        self.entities_column = config.get(
            ENTITIES_COLUMN,
            OperatorConstants.Columns.TRANSFORMED_ENTITIES_COLUMN_NAME,
        )

        if self.data_backend not in self._SUPPORTED_BACKENDS:
            raise ValueError(
                f"Unsupported entity storage backend: '{self.data_backend}'. "
                f"Supported backends: {', '.join(self._SUPPORTED_BACKENDS)}"
            )

        if OperatorConstants.Storage.BACKEND_POSTGRES in config:
            # The flow configuration is stored with every run, so it must not hold credentials.
            raise ValueError(
                "PostgreSQL connection settings are not accepted in the operator configuration. "
                "Set them with the DOCPIPE_POSTGRES_* environment variables."
            )

        if not isinstance(self.table_prefix, str) or not _TABLE_PREFIX_RE.match(self.table_prefix):
            raise ValueError(f"Invalid table_prefix: '{self.table_prefix}'. Use only letters, digits and underscores.")

        # One storage block for every backend: the factory passes each backend its own settings.
        self.storage: TableStoragePort = StorageFactory.create_table_storage(
            storage_type=self.data_backend,
            database_path=self.database_path,
            schema=self.schema,
        )

    def transform(self, table: pa.Table) -> TransformResult:
        """Store curated entities and return the input table unchanged."""
        metadata: OperatorOutputMetadata = self.create_base_metadata(
            total_docs_count=table.num_rows,
        )

        if table.num_rows == 0:
            return [table], metadata

        rows_by_table: dict[str, list[dict[str, Any]]] = {}
        docs_by_table: dict[str, set[str]] = {}
        stored_docs: dict[str, str] = {}

        for row in table.to_pylist():
            doc_id = str(row.get("id", ""))
            doc_name = str(row.get("name", doc_id))

            try:
                entities_value = row.get(self.entities_column)

                if not entities_value:
                    self.record_skipped_document(
                        metadata=metadata,
                        doc_id=doc_id,
                        doc_name=doc_name,
                        reason=f"Column '{self.entities_column}' is empty",
                    )
                    continue

                entities = json.loads(entities_value) if isinstance(entities_value, str) else entities_value
                if not isinstance(entities, dict):
                    raise ValueError("Curated entities must be a JSON object")

                # Collect the rows of this document first, so a document that fails adds none.
                document_rows: dict[str, list[dict[str, Any]]] = {}
                for table_name, entity_data in entities.items():
                    entity_table = self._entity_table_name(table_prefix=self.table_prefix, table_name=table_name)
                    entity_rows = self._entity_rows(doc_id=doc_id, table_name=table_name, entity_data=entity_data)
                    document_rows.setdefault(entity_table, []).extend(entity_rows)

                for entity_table, entity_rows in document_rows.items():
                    rows_by_table.setdefault(entity_table, []).extend(entity_rows)
                    docs_by_table.setdefault(entity_table, set()).add(doc_id)
                stored_docs[doc_id] = doc_name

            except Exception as exc:
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason=str(exc),
                )

        write_errors = self._write_tables(rows_by_table=rows_by_table, docs_by_table=docs_by_table)

        for doc_id, doc_name in stored_docs.items():
            if doc_id in write_errors:
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason="; ".join(write_errors[doc_id]),
                )
            else:
                metadata[Metrics.External.PROCESSED_DOCS] += 1

        if metadata[Metrics.External.FAILED_DOCS_COUNT] > 0:
            metadata[Metrics.External.NODE_STATUS] = ExecutionStatus.COMPLETED_WITH_ERRORS
        else:
            metadata[Metrics.External.NODE_STATUS] = ExecutionStatus.COMPLETED

        return [table], metadata

    def _write_tables(
        self, *, rows_by_table: dict[str, list[dict[str, Any]]], docs_by_table: dict[str, set[str]]
    ) -> dict[str, list[str]]:
        """Write each entity table, and collect the errors per document.

        A table that cannot be written fails only the documents with rows in it;
        the other tables are still written.

        Args:
            rows_by_table: Entity rows per table.
            docs_by_table: Ids of the documents with rows in each table.

        Returns:
            Error messages per document id.
        """
        errors: dict[str, list[str]] = {}
        try:
            for table_name, rows in rows_by_table.items():
                # Handle empty entity arrays ([]) so they don't produce 0-column tables
                if not rows:
                    continue

                try:
                    entity_table = self._to_arrow_table(rows=rows)
                    if not self.storage.table_exists(table_name=table_name):
                        self.storage.create_table(table_name=table_name, schema=entity_table.schema)
                    self.storage.upsert_data(table_name=table_name, data=entity_table)
                except Exception as exc:
                    logger.warning(
                        "Failed to store entity table %s: %s",
                        table_name,
                        exc,
                        extra=self.common_log_arguments,
                    )
                    for doc_id in docs_by_table[table_name]:
                        errors.setdefault(doc_id, []).append(f"Failed to store table {table_name}: {exc}")
        finally:
            self.storage.close()
        return errors

    @staticmethod
    def _entity_table_name(*, table_prefix: str, table_name: str) -> str:
        """Return the storage table name for an entity table of the curated JSON.

        Args:
            table_prefix: Prefix of every entity table.
            table_name: Key of the curated entities JSON object.

        Returns:
            The prefixed table name.

        Raises:
            ValueError: If the name is not a valid table name or is reserved for other tables.
        """
        name = f"{table_prefix}{table_name}"
        if not _TABLE_NAME_RE.match(name) or len(name) > _MAX_TABLE_NAME_LENGTH:
            raise ValueError(
                f"Invalid entity table name: '{name}'. Use only letters, digits and underscores, "
                f"at most {_MAX_TABLE_NAME_LENGTH} characters."
            )
        if name.lower().startswith(_RESERVED_TABLE_PREFIXES) or name.lower() in _RESERVED_TABLE_NAMES:
            raise ValueError(f"Entity table name '{name}' is reserved for other tables")
        return name

    @staticmethod
    def _entity_rows(*, doc_id: str, table_name: str, entity_data: Any) -> list[dict[str, Any]]:
        """Return the storage rows of one entity table of a document.

        The row ``id`` combines the document id and the table name (and the index for a
        list). An entity's own ``id`` never replaces it; that value is kept as ``entity_id``,
        unless the entity has an ``entity_id`` field of its own, which is then kept instead.

        Args:
            doc_id: Document id.
            table_name: Key of the curated entities JSON object.
            entity_data: A JSON object, or a list of JSON objects.

        Returns:
            The rows; items of a list that are not objects are left out.
        """
        if isinstance(entity_data, dict):
            items = [(f"{doc_id}:{table_name}", entity_data)]
        elif isinstance(entity_data, list):
            items = [
                (f"{doc_id}:{table_name}:{index}", item)
                for index, item in enumerate(entity_data)
                if isinstance(item, dict)
            ]
        else:
            items = []

        return [
            {
                "id": key,
                **({"entity_id": item["id"]} if "id" in item else {}),
                # Spread last, so an entity's own entity_id field is kept.
                **{field: value for field, value in item.items() if field != "id"},
            }
            for key, item in items
        ]

    @staticmethod
    def _value_kind(*, value: Any) -> str:
        """Return the kind of a JSON value: bool, int, float, str or nested."""
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, dict | list):
            return "nested"
        return "str"

    @staticmethod
    def _to_arrow_table(*, rows: list[dict[str, Any]]) -> pa.Table:
        """Build the PyArrow table of one entity table, with one type per column.

        Documents can give one field different types. Integers and floats become
        floats; any other mix becomes strings, with JSON text for nested values. A
        column that is null in every row is left out, so it does not set the column
        type of the table before a document has a value for it.

        Args:
            rows: Entity rows.

        Returns:
            The rows as a PyArrow table.
        """
        columns: dict[str, list[Any]] = {}
        for field in dict.fromkeys(field for row in rows for field in row):
            values = [row.get(field) for row in rows]
            kinds = {EntityStoreOperator._value_kind(value=value) for value in values if value is not None}
            if not kinds:
                continue
            if kinds == {"int", "float"}:
                values = [None if value is None else float(value) for value in values]
            elif len(kinds) > 1:
                values = [
                    None
                    if value is None
                    else json.dumps(value, ensure_ascii=False)
                    if isinstance(value, dict | list)
                    else str(value)
                    for value in values
                ]
            columns[field] = values
        return pa.table(columns)

    @staticmethod
    def get_required_features() -> list[str]:
        """Return the curated entity column required by this operator."""
        return [OperatorConstants.Columns.TRANSFORMED_ENTITIES_COLUMN_NAME]

    @staticmethod
    def get_static_required_features() -> list[str]:
        """Return required features for operator discovery."""
        return [OperatorConstants.Columns.TRANSFORMED_ENTITIES_COLUMN_NAME]

    @staticmethod
    def get_metadata() -> OperatorMetadata:
        """Return metadata describing the entity storage operator."""
        return {
            "short_name": OperatorConstants.Operators.ENTITY_STORE_OPERATOR,
            "description": "Store curated entities in DuckDB or PostgreSQL.",
            "category": OperatorCategory.Storage.value,
            "owner": "docpipe",
            "attributes": {
                OperatorConstants.Storage.DATA_BACKEND: {
                    OperatorConstants.Misc.NAME: "Data Backend",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Database that stores the curated entities. The postgres backend connects "
                        "with the DOCPIPE_POSTGRES_* environment variables."
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Storage.DEFAULT_DATA_BACKEND,
                    OperatorConstants.Config.VALID_VALUES: list(EntityStoreOperator._SUPPORTED_BACKENDS),
                },
                OperatorConstants.Storage.DATABASE_PATH: {
                    OperatorConstants.Misc.NAME: "Database Path",
                    OperatorConstants.Config.DESCRIPTION: (
                        "DuckDB database file, or ':memory:' for an in-memory database. Used by the duckdb backend."
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Storage.DEFAULT_DATABASE_PATH,
                },
                OperatorConstants.Storage.SCHEMA: {
                    OperatorConstants.Misc.NAME: "Schema",
                    OperatorConstants.Config.DESCRIPTION: (
                        "PostgreSQL schema of the entity tables, created if needed. Used by the postgres backend."
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    OperatorConstants.Config.DEFAULT: DEFAULT_ENTITY_SCHEMA,
                },
                OperatorConstants.Storage.TABLE_PREFIX: {
                    OperatorConstants.Misc.NAME: "Table Prefix",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Prefix of every entity table name, which keeps entity tables apart "
                        "from other tables in the same database."
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    OperatorConstants.Config.DEFAULT: DEFAULT_ENTITY_TABLE_PREFIX,
                },
                ENTITIES_COLUMN: {
                    OperatorConstants.Misc.NAME: "Entities Column",
                    OperatorConstants.Config.DESCRIPTION: "Column that holds the curated entities of each document.",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Columns.TRANSFORMED_ENTITIES_COLUMN_NAME,
                },
            },
        }
