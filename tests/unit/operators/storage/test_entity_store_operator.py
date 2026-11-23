# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for EntityStoreOperator."""

from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import OperatorCategory
from docpipe.core.operators.storage.entity_store_operator import EntityStoreOperator


@pytest.fixture
def basic_config():
    """Basic configuration for EntityStoreOperator."""
    return {
        "data_backend": "duckdb",
        "database_path": ":memory:",
    }


@pytest.fixture
def sample_table():
    """Create a sample curated-entities table."""
    return pa.table(
        {
            "id": ["doc1", "doc2"],
            "name": ["invoice1.pdf", "invoice2.pdf"],
            "transformed_entities": [
                '{"Invoice": {"invoice_id": "INV-001"}}',
                '{"Invoice": {"invoice_id": "INV-002"}}',
            ],
        }
    )


class TestOperatorMetadata:
    """Test operator metadata and configuration."""

    def test_operator_metadata(self, basic_config):
        """Test operator metadata structure."""
        operator = EntityStoreOperator(basic_config)
        metadata = operator.get_metadata()

        assert metadata["short_name"] == "entity_store"
        assert metadata["category"] == OperatorCategory.Storage.value
        assert metadata["owner"] == "docpipe"
        assert "description" in metadata
        assert "attributes" in metadata

    def test_operator_attributes(self, basic_config):
        """Test operator configuration attributes."""
        operator = EntityStoreOperator(basic_config)
        attributes = operator.get_metadata()["attributes"]

        assert attributes["data_backend"]["default"] == "duckdb"
        assert attributes["data_backend"]["valid_values"] == ["duckdb", "postgres"]
        assert attributes["database_path"]["default"] == ":memory:"

    def test_operator_attributes_list_every_config_key(self, basic_config):
        """Every config key read by __init__ is declared, so the UI can show it."""
        attributes = EntityStoreOperator.get_metadata()["attributes"]

        assert set(attributes) == {"data_backend", "database_path", "schema", "table_prefix", "entities_column"}
        assert attributes["schema"]["default"] == "docpipe_entities"
        assert attributes["table_prefix"]["default"] == "entity_"
        assert attributes["entities_column"]["default"] == "transformed_entities"

    def test_operator_category(self, basic_config):
        """Test operator category."""
        operator = EntityStoreOperator(basic_config)

        assert operator.category == OperatorCategory.Storage

    def test_operator_short_name(self, basic_config):
        """Test operator short name."""
        operator = EntityStoreOperator(basic_config)

        assert operator.short_name == "entity_store"


class TestOperatorConfiguration:
    """Test operator configuration."""

    def test_default_configuration(self):
        """Test default backend and entity column."""
        with patch(
            "docpipe.core.operators.storage.entity_store_operator.StorageFactory.create_table_storage"
        ) as mock_factory:
            mock_factory.return_value = MagicMock()

            operator = EntityStoreOperator({})

        assert operator.data_backend == "duckdb"
        assert operator.database_path == ":memory:"
        assert operator.schema == "docpipe_entities"
        assert operator.table_prefix == "entity_"
        assert operator.entities_column == "transformed_entities"

        # One storage block for every backend; the factory picks the settings of each.
        mock_factory.assert_called_once_with(
            storage_type="duckdb",
            database_path=":memory:",
            schema="docpipe_entities",
        )

    def test_custom_entities_column(self):
        """Test custom entity column configuration."""
        config = {
            "entities_column": "curated_entities",
            "data_backend": "duckdb",
            "database_path": ":memory:",
        }

        with patch(
            "docpipe.core.operators.storage.entity_store_operator.StorageFactory.create_table_storage"
        ) as mock_factory:
            mock_factory.return_value = MagicMock()

            operator = EntityStoreOperator(config)

        assert operator.entities_column == "curated_entities"

    def test_invalid_backend(self):
        """Test unsupported storage backend."""
        with pytest.raises(ValueError, match="Unsupported entity storage backend"):
            EntityStoreOperator({"data_backend": "filesystem"})

    @pytest.mark.parametrize("table_prefix", ["bad-prefix", 5])
    def test_invalid_table_prefix(self, table_prefix):
        with pytest.raises(ValueError, match="Invalid table_prefix"):
            EntityStoreOperator({"table_prefix": table_prefix})


class TestOperatorFeatures:
    """Test operator feature requirements."""

    def test_get_required_features(self):
        """Test required pipeline features."""
        required = EntityStoreOperator.get_required_features()

        assert required == [OperatorConstants.Columns.TRANSFORMED_ENTITIES_COLUMN_NAME]

    def test_get_static_required_features(self):
        """Test static required pipeline features."""
        required = EntityStoreOperator.get_static_required_features()

        assert required == [OperatorConstants.Columns.TRANSFORMED_ENTITIES_COLUMN_NAME]

    def test_validate_success(self, basic_config):
        """Test validation with the required feature available."""
        operator = EntityStoreOperator(basic_config)
        errors: list[str] = []
        warnings: list[str] = []

        operator.validate(
            errors=errors,
            warnings=warnings,
            available_features=["id", "name", "transformed_entities"],
        )

        assert errors == []
        assert warnings == []

    def test_validate_missing_entities(self, basic_config):
        """Test validation when curated entities are unavailable."""
        operator = EntityStoreOperator(basic_config)
        errors: list[str] = []
        warnings: list[str] = []

        operator.validate(
            errors=errors,
            warnings=warnings,
            available_features=["id", "name"],
        )

        assert errors
        assert any("transformed_entities" in str(error) for error in errors)


class TestOperatorTransform:
    """Test operator transform behavior."""

    @patch("docpipe.core.operators.storage.entity_store_operator.StorageFactory.create_table_storage")
    def test_transform_is_pass_through(self, mock_factory, basic_config, sample_table):
        """Test that the operator returns the original table unchanged."""
        mock_factory.return_value = MagicMock()

        operator = EntityStoreOperator(basic_config)

        result_tables, metadata = operator.transform(sample_table)

        assert len(result_tables) == 1
        assert result_tables[0] is sample_table
        assert metadata[Metrics.External.TOTAL_DOCS] == 2
        assert metadata[Metrics.External.PROCESSED_DOCS] == 2
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0
        assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 0
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED.value

    @patch("docpipe.core.operators.storage.entity_store_operator.StorageFactory.create_table_storage")
    def test_transform_empty_table(self, mock_factory, basic_config):
        """Test transforming an empty table."""
        mock_factory.return_value = MagicMock()

        operator = EntityStoreOperator(basic_config)

        empty_table = pa.table(
            {
                "id": pa.array([], type=pa.string()),
                "transformed_entities": pa.array([], type=pa.string()),
            }
        )

        result_tables, metadata = operator.transform(empty_table)

        assert len(result_tables) == 1
        assert result_tables[0] is empty_table
        assert metadata[Metrics.External.TOTAL_DOCS] == 0
        assert metadata[Metrics.External.PROCESSED_DOCS] == 0
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED.value


class TestPostgresConfiguration:
    """Test PostgreSQL storage configuration."""

    @patch("docpipe.core.operators.storage.entity_store_operator.StorageFactory.create_table_storage")
    def test_postgres_backend(self, mock_factory):
        """The operator passes only non-secret settings; the connection comes from DOCPIPE_POSTGRES_*."""
        mock_factory.return_value = MagicMock()

        EntityStoreOperator({"data_backend": "postgres", "schema": "invoice_entities"})

        mock_factory.assert_called_once_with(
            storage_type="postgres",
            database_path=":memory:",
            schema="invoice_entities",
        )

    def test_postgres_credentials_are_rejected(self):
        """Connection settings in the flow configuration would be stored with every run."""
        config = {
            "data_backend": "postgres",
            "postgres": {"password": "test-password"},  # pragma: allowlist secret
        }

        with pytest.raises(ValueError, match="DOCPIPE_POSTGRES_"):
            EntityStoreOperator(config)


class TestEntityStorage:
    """Test storing curated entities."""

    def test_store_single_entity_table(self, basic_config):
        """Store a single entity object as one target-table row."""
        config = {
            **basic_config,
        }

        table = pa.table(
            {
                "id": ["doc1"],
                "name": ["invoice1.pdf"],
                "transformed_entities": ['{"Invoice": {"invoice_id": "INV-001", "vendor_name": "Acme Corp"}}'],
            }
        )

        with patch(
            "docpipe.core.operators.storage.entity_store_operator.StorageFactory.create_table_storage"
        ) as mock_factory:
            storage = MagicMock()
            storage.table_exists.return_value = False
            mock_factory.return_value = storage

            operator = EntityStoreOperator(config)
            result_tables, metadata = operator.transform(table)

        assert len(result_tables) == 1
        assert result_tables[0] is table

        storage.create_table.assert_called_once()
        storage.upsert_data.assert_called_once()

        stored_table = storage.upsert_data.call_args.kwargs["data"]

        assert stored_table.column_names == ["id", "invoice_id", "vendor_name"]
        assert stored_table["id"].to_pylist() == ["doc1:Invoice"]
        assert stored_table["invoice_id"].to_pylist() == ["INV-001"]
        assert stored_table["vendor_name"].to_pylist() == ["Acme Corp"]

        assert metadata[Metrics.External.PROCESSED_DOCS] == 1
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0


class TestEntityStorageDuckDB:
    """Test entity storage with the real DuckDB backend."""

    def test_store_single_entity_in_duckdb(self, tmp_path):
        """Store a single entity and read it back from DuckDB."""
        database_path = str(tmp_path / "entities.db")

        config = {
            "data_backend": "duckdb",
            "database_path": database_path,
        }

        table = pa.table(
            {
                "id": ["doc1"],
                "name": ["invoice1.pdf"],
                "transformed_entities": ['{"Invoice": {"invoice_id": "INV-001", "vendor_name": "Acme Corp"}}'],
            }
        )

        operator = EntityStoreOperator(config)
        result_tables, metadata = operator.transform(table)

        assert result_tables[0] is table
        assert metadata[Metrics.External.PROCESSED_DOCS] == 1
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0

        stored = operator.storage.read_data(table_name="entity_Invoice")

        assert stored.column("id").to_pylist() == ["doc1:Invoice"]
        assert stored.column("invoice_id").to_pylist() == ["INV-001"]
        assert stored.column("vendor_name").to_pylist() == ["Acme Corp"]


class TestEntityStorageArrays:
    """Test storing array-valued entity tables."""

    def test_store_entity_array(self, tmp_path):
        """Store multiple rows from an array-valued entity table."""
        config = {
            "data_backend": "duckdb",
            "database_path": str(tmp_path / "entities.db"),
        }

        table = pa.table(
            {
                "id": ["doc1"],
                "name": ["invoice1.pdf"],
                "transformed_entities": [
                    (
                        '{"Invoice_line_items": ['
                        '{"description": "Item A", "quantity": 2},'
                        '{"description": "Item B", "quantity": 1}'
                        "]}"
                    )
                ],
            }
        )

        operator = EntityStoreOperator(config)
        result_tables, metadata = operator.transform(table)

        assert result_tables[0] is table
        assert metadata[Metrics.External.PROCESSED_DOCS] == 1
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0

        stored = operator.storage.read_data(table_name="entity_Invoice_line_items")

        assert stored.column("id").to_pylist() == [
            "doc1:Invoice_line_items:0",
            "doc1:Invoice_line_items:1",
        ]
        assert stored.column("description").to_pylist() == ["Item A", "Item B"]
        assert stored.column("quantity").to_pylist() == [2, 1]


class TestEntityStorageMultipleDocuments:
    """Test storing entities from multiple documents."""

    def test_store_entities_from_multiple_documents(self, tmp_path):
        """Store entities from multiple documents without collisions."""
        config = {
            "data_backend": "duckdb",
            "database_path": str(tmp_path / "entities.db"),
        }

        table = pa.table(
            {
                "id": ["doc1", "doc2"],
                "name": ["invoice1.pdf", "invoice2.pdf"],
                "transformed_entities": [
                    '{"Invoice": {"invoice_id": "INV-001", "vendor_name": "Acme Corp"}}',
                    '{"Invoice": {"invoice_id": "INV-002", "vendor_name": "Beta Corp"}}',
                ],
            }
        )

        operator = EntityStoreOperator(config)
        result_tables, metadata = operator.transform(table)

        assert result_tables[0] is table
        assert metadata[Metrics.External.PROCESSED_DOCS] == 2
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0

        stored = operator.storage.read_data(table_name="entity_Invoice")

        assert stored.num_rows == 2
        assert stored.column("id").to_pylist() == [
            "doc1:Invoice",
            "doc2:Invoice",
        ]
        assert stored.column("invoice_id").to_pylist() == [
            "INV-001",
            "INV-002",
        ]
        assert stored.column("vendor_name").to_pylist() == [
            "Acme Corp",
            "Beta Corp",
        ]


class TestEntityStorageErrors:
    """Test entity storage error handling."""

    def test_malformed_json_records_failed_document(self):
        """Malformed entity JSON should fail the document without raising."""
        config = {
            "data_backend": "duckdb",
            "database_path": ":memory:",
        }

        table = pa.table(
            {
                "id": ["doc1"],
                "name": ["invoice1.pdf"],
                "transformed_entities": ["{invalid-json"],
            }
        )

        operator = EntityStoreOperator(config)
        result_tables, metadata = operator.transform(table)

        assert result_tables[0] is table
        assert metadata[Metrics.External.PROCESSED_DOCS] == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        assert metadata[Metrics.External.FAILED_DOCS] == [
            {
                "id": "doc1",
                "name": "invoice1.pdf",
                "reason": "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
                "document_url": "",
            }
        ]
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS

    def test_invalid_entity_shape_records_failed_document(self):
        """A non-object curated entity value should fail the document."""
        config = {
            "data_backend": "duckdb",
            "database_path": ":memory:",
        }

        table = pa.table(
            {
                "id": ["doc1"],
                "name": ["invoice1.pdf"],
                "transformed_entities": ['["not", "an", "object"]'],
            }
        )

        operator = EntityStoreOperator(config)
        result_tables, metadata = operator.transform(table)

        assert result_tables[0] is table
        assert metadata[Metrics.External.PROCESSED_DOCS] == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        assert metadata[Metrics.External.FAILED_DOCS][0]["id"] == "doc1"
        assert metadata[Metrics.External.FAILED_DOCS][0]["name"] == "invoice1.pdf"
        assert metadata[Metrics.External.FAILED_DOCS][0]["reason"] == ("Curated entities must be a JSON object")
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS


class TestEntityStorageSchemaEvolution:
    """Test storing entities whose fields evolve between documents."""

    def test_store_entities_with_different_fields(self, tmp_path):
        """Store documents with different entity fields in the same table."""
        config = {
            "data_backend": "duckdb",
            "database_path": str(tmp_path / "entities.db"),
        }

        table = pa.table(
            {
                "id": ["doc1", "doc2"],
                "name": ["invoice1.pdf", "invoice2.pdf"],
                "transformed_entities": [
                    '{"Invoice": {"invoice_id": "INV-001", "vendor_name": "Acme Corp"}}',
                    '{"Invoice": {"invoice_id": "INV-002", "vendor_name": "Beta Corp", "invoice_date": "2026-10-07"}}',
                ],
            }
        )

        operator = EntityStoreOperator(config)
        result_tables, metadata = operator.transform(table)

        assert result_tables[0] is table
        assert metadata[Metrics.External.PROCESSED_DOCS] == 2
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0

        stored = operator.storage.read_data(table_name="entity_Invoice")

        assert stored.num_rows == 2
        assert stored.column("id").to_pylist() == [
            "doc1:Invoice",
            "doc2:Invoice",
        ]
        assert stored.column("invoice_id").to_pylist() == [
            "INV-001",
            "INV-002",
        ]
        assert stored.column("vendor_name").to_pylist() == [
            "Acme Corp",
            "Beta Corp",
        ]
        assert stored.column("invoice_date").to_pylist() == [
            None,
            "2026-10-07",
        ]


def _entities_table(*documents: str) -> pa.Table:
    """Return an input table with one document per curated entities JSON string."""
    return pa.table(
        {
            "id": [f"doc{index}" for index in range(1, len(documents) + 1)],
            "name": [f"invoice{index}.pdf" for index in range(1, len(documents) + 1)],
            "transformed_entities": list(documents),
        }
    )


class TestEntityKeys:
    """The composite row id cannot be replaced by an entity's own id."""

    def test_entities_with_the_same_own_id_are_kept_apart(self, tmp_path):
        table = _entities_table(
            '{"Invoice": {"id": "INV-1", "amount": 10}}',
            '{"Invoice": {"id": "INV-1", "amount": 20}}',
        )
        operator = EntityStoreOperator({"database_path": str(tmp_path / "entities.db")})

        _tables, metadata = operator.transform(table)

        stored = operator.storage.read_data(table_name="entity_Invoice")
        assert metadata[Metrics.External.PROCESSED_DOCS] == 2
        assert stored.to_pylist() == [
            {"id": "doc1:Invoice", "amount": 10, "entity_id": "INV-1"},
            {"id": "doc2:Invoice", "amount": 20, "entity_id": "INV-1"},
        ]

    def test_list_items_get_an_index_in_their_id(self):
        rows = EntityStoreOperator._entity_rows(
            doc_id="doc1", table_name="Lines", entity_data=[{"id": 7, "sku": "A"}, "not an object", {"sku": "B"}]
        )

        assert rows == [
            {"id": "doc1:Lines:0", "sku": "A", "entity_id": 7},
            {"id": "doc1:Lines:2", "sku": "B"},
        ]

    def test_an_own_entity_id_field_is_kept(self):
        rows = EntityStoreOperator._entity_rows(
            doc_id="doc1", table_name="Invoice", entity_data={"id": "INV-1", "entity_id": "E-9", "amount": 10}
        )

        assert rows == [{"id": "doc1:Invoice", "entity_id": "E-9", "amount": 10}]


class TestEntityTableNames:
    """Entity table names are prefixed and must not collide with other tables."""

    def test_table_names_get_the_prefix(self):
        assert EntityStoreOperator._entity_table_name(table_prefix="entity_", table_name="Invoice") == "entity_Invoice"

    @pytest.mark.parametrize(
        ("table_prefix", "table_name", "message"),
        [
            ("", "docpipe_jobs", "reserved"),
            ("", "pg_stats", "reserved"),
            ("", "document_sets", "reserved"),
            ("entity_", "bad name", "Invalid entity table name"),
            ("entity_", "x" * 60, "Invalid entity table name"),
        ],
    )
    def test_invalid_or_reserved_table_names(self, table_prefix, table_name, message):
        with pytest.raises(ValueError, match=message):
            EntityStoreOperator._entity_table_name(table_prefix=table_prefix, table_name=table_name)

    @patch("docpipe.core.operators.storage.entity_store_operator.StorageFactory.create_table_storage")
    def test_a_reserved_table_name_fails_only_its_document(self, mock_factory):
        storage = MagicMock()
        storage.table_exists.return_value = True
        mock_factory.return_value = storage
        table = _entities_table('{"Invoice": {"amount": 1}}', '{"Invoice": {"amount": 2}}')

        _tables, metadata = EntityStoreOperator({"table_prefix": "docpipe_"}).transform(table)

        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 2
        assert "reserved" in metadata[Metrics.External.FAILED_DOCS][0]["reason"]
        storage.upsert_data.assert_not_called()


class TestEntityStorageWriteFailures:
    """A table that cannot be written fails only the documents with rows in it."""

    @patch("docpipe.core.operators.storage.entity_store_operator.StorageFactory.create_table_storage")
    def test_failed_table_fails_only_its_documents(self, mock_factory):
        storage = MagicMock()
        storage.table_exists.return_value = True

        def upsert(*, table_name, data):
            if table_name == "entity_Invoice":
                raise RuntimeError("column amount has an incompatible type")

        storage.upsert_data.side_effect = upsert
        mock_factory.return_value = storage
        table = _entities_table(
            '{"Invoice": {"amount": 1}, "Vendor": {"name": "Acme"}}',
            '{"Vendor": {"name": "Beta"}}',
        )

        _tables, metadata = EntityStoreOperator({}).transform(table)

        # doc1 has rows in the failed table; doc2 only in the table that was written.
        assert metadata[Metrics.External.PROCESSED_DOCS] == 1
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        [failed] = metadata[Metrics.External.FAILED_DOCS]
        assert failed["id"] == "doc1"
        assert "entity_Invoice" in failed["reason"]
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS
        written = [call.kwargs["table_name"] for call in storage.upsert_data.call_args_list]
        assert written == ["entity_Invoice", "entity_Vendor"]
        storage.close.assert_called_once()

    @patch("docpipe.core.operators.storage.entity_store_operator.StorageFactory.create_table_storage")
    def test_storage_is_closed_when_writing_fails(self, mock_factory):
        storage = MagicMock()
        storage.table_exists.side_effect = RuntimeError("database is down")
        mock_factory.return_value = storage

        _tables, metadata = EntityStoreOperator({}).transform(_entities_table('{"Invoice": {"amount": 1}}'))

        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        storage.close.assert_called_once()


class TestEntityValueTypes:
    """Documents can give one field different types; each column gets one type."""

    @pytest.mark.parametrize(
        ("values", "expected_type", "expected_values"),
        [
            ([1, 2.5], pa.float64(), [1.0, 2.5]),
            ([5, "5.0"], pa.string(), ["5", "5.0"]),
            ([True, 1], pa.string(), ["True", "1"]),
            ([{"unit": "EA"}, "EA"], pa.string(), ['{"unit": "EA"}', "EA"]),
            ([1, None], pa.int64(), [1, None]),
        ],
    )
    def test_mixed_values_get_a_common_type(self, values, expected_type, expected_values):
        rows = [{"id": f"doc{index}:T", "value": value} for index, value in enumerate(values)]

        table = EntityStoreOperator._to_arrow_table(rows=rows)

        assert table.schema.field("value").type == expected_type
        assert table.column("value").to_pylist() == expected_values

    def test_a_column_without_values_is_left_out(self):
        table = EntityStoreOperator._to_arrow_table(rows=[{"id": "a", "note": None}, {"id": "b", "note": None}])

        assert table.column_names == ["id"]

    def test_mixed_types_across_documents_are_stored(self, tmp_path):
        table = _entities_table('{"Invoice": {"amount": 5}}', '{"Invoice": {"amount": "5.0"}}')
        operator = EntityStoreOperator({"database_path": str(tmp_path / "entities.db")})

        _tables, metadata = operator.transform(table)

        assert metadata[Metrics.External.PROCESSED_DOCS] == 2
        stored = operator.storage.read_data(table_name="entity_Invoice")
        assert stored.column("amount").to_pylist() == ["5", "5.0"]
