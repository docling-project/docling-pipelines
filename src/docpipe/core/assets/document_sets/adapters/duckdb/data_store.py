# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""DuckDB implementation of DocumentSetStorage.

Writes PyArrow table data to a DuckDB table and returns an AttachmentRef
with the table name in the common ``name`` field and backend coordinates in
``details``.  The table name is derived from the document set name via
sanitize_table_name().
"""

from typing import Any

from docpipe.core.assets.document_sets.adapters.table_data_store import TableDocumentSetStorage
from docpipe.core.assets.document_sets.factories.data_store_factory import DataStoreFactory
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.storage.interfaces.table_storage_port import TableStoragePort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@DataStoreFactory.register(name=OperatorConstants.DocumentSet.ADAPTER_DUCKDB, display_name="DuckDB")
class DuckDBDocumentSetStorage(TableDocumentSetStorage):
    """DuckDB implementation of the DocumentSetStorage port.

    The table operations are shared with the other TableStoragePort backends
    in TableDocumentSetStorage.

    Attributes:
        _storage: TableStoragePort backend for DuckDB operations.
        _database_path: Path to the DuckDB file; embedded in returned AttachmentRefs.
    """

    BACKEND_TYPE = OperatorConstants.DocumentSet.ADAPTER_DUCKDB
    BACKEND_DISPLAY_NAME = "DuckDB"

    def __init__(self, *, table_storage: TableStoragePort, database_path: str) -> None:
        """Initialise with injected storage and the database path.

        Args:
            table_storage: TableStoragePort implementation (DuckDB-based).
            database_path: Path to the DuckDB file; stored so it can be embedded
                in returned AttachmentRefs.
        """
        super().__init__(table_storage=table_storage)
        self._database_path = database_path
        logger.info("DuckDBDocumentSetStorage initialised with database_path: %s", database_path)

    def _backend_details(self) -> dict[str, str]:
        """Return the DuckDB file path for AttachmentRef and health check details."""
        return {OperatorConstants.DocumentSet.DATABASE_PATH: self._database_path}

    @classmethod
    def from_config(cls, *, config: dict[str, Any]) -> "DuckDBDocumentSetStorage":
        """Create a DuckDBDocumentSetStorage from a config dict.

        Validates config, creates the TableStoragePort, and returns a fully
        initialised instance.

        Args:
            config: Must contain a non-empty ``database_path`` string.

        Returns:
            Configured DuckDBDocumentSetStorage instance.

        Raises:
            DocpipeException: If config is invalid or storage creation fails.
        """
        from docpipe.storage import StorageFactory

        errors = cls.validate_config(config=config)
        if errors:
            raise DocpipeException(
                "; ".join(errors),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        database_path = config[OperatorConstants.DocumentSet.DATABASE_PATH]
        table_storage = StorageFactory.create_table_storage(
            storage_type=OperatorConstants.DocumentSet.ADAPTER_DUCKDB,
            database_path=database_path,
        )
        return cls(table_storage=table_storage, database_path=database_path)

    @classmethod
    def validate_config(cls, *, config: dict[str, Any]) -> list[str]:
        """Validate DuckDB storage configuration.

        Args:
            config: Must contain a non-empty ``database_path`` string.

        Returns:
            List of validation error messages; empty if configuration is valid.
        """
        errors = []
        db_path_key = OperatorConstants.DocumentSet.DATABASE_PATH
        if db_path_key not in config:
            errors.append(f"Missing required configuration: '{db_path_key}'")
        elif not isinstance(config[db_path_key], str):
            errors.append(f"Configuration '{db_path_key}' must be a string")
        elif not config[db_path_key]:
            errors.append(f"Configuration '{db_path_key}' cannot be empty")
        return errors
