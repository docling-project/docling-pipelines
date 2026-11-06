"""DuckDB implementation of DocumentSetStorage.

Writes PyArrow table data to a DuckDB table and returns an AttachmentRef
with the table name in the common ``name`` field and backend coordinates in
``details``.  The table name is derived from the document set name via
sanitize_table_name().
"""

from typing import Any

import pyarrow as pa

from docpipe.core.assets.common.domain.models.attachment_ref import AttachmentRef
from docpipe.core.assets.document_sets.adapters.duckdb.duckdb_utils import sanitize_table_name
from docpipe.core.assets.document_sets.domain.ports.data_store import DocumentSetStorage
from docpipe.core.assets.document_sets.domain.types import HealthCheckResult
from docpipe.core.assets.document_sets.factories.data_store_factory import DataStoreFactory
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.storage.interfaces.table_storage_port import TableStoragePort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@DataStoreFactory.register(name=OperatorConstants.DocumentSet.ADAPTER_DUCKDB, display_name="DuckDB")
class DuckDBDocumentSetStorage(DocumentSetStorage):
    """DuckDB implementation of the DocumentSetStorage port.

    Derives the physical table name from the document set name and returns a
    fully-populated AttachmentRef so the service layer never needs to know
    where or how the data is stored.

    Attributes:
        _storage: TableStoragePort backend for DuckDB operations.
        _database_path: Path to the DuckDB file; embedded in returned AttachmentRefs.
    """

    def __init__(self, *, table_storage: TableStoragePort, database_path: str) -> None:
        """Initialise with injected storage and the database path.

        Args:
            table_storage: TableStoragePort implementation (DuckDB-based).
            database_path: Path to the DuckDB file; stored so it can be embedded
                in returned AttachmentRefs.
        """
        self._storage = table_storage
        self._database_path = database_path
        logger.info("DuckDBDocumentSetStorage initialised with database_path: %s", database_path)

    def store(self, *, doc_set_name: str, data: pa.Table) -> AttachmentRef:
        """Write PyArrow table data to DuckDB and return an AttachmentRef.

        Creates the backing table if it does not exist, otherwise upserts on
        the ``id`` column.

        Args:
            doc_set_name: Logical document set name; used to derive table_name.
            data: PyArrow table to persist. Must contain an ``id`` column.

        Returns:
            AttachmentRef with backend_type="duckdb", name=table_name, and
            details containing database_path and table_name.

        Raises:
            DocpipeException: If the data is invalid or the write fails.
        """
        if "id" not in data.schema.names:
            raise DocpipeException(
                "Data must contain an 'id' column for upsert operations",
                status_code=400,
                error_code=ErrorCode.DOCUMENT_SET_SCHEMA_MISMATCH,
            )

        table_name = sanitize_table_name(doc_set_name)

        try:
            if not self._storage.table_exists(table_name=table_name):
                self._storage.create_table(table_name=table_name, schema=data.schema)
                logger.info("Created DuckDB table: %s", table_name)

            self._storage.upsert_data(table_name=table_name, data=data)
            logger.debug("Upserted %d rows into %s", len(data), table_name)
        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to store data: {e!s}",
                status_code=500,
                error_code=ErrorCode.DOCUMENT_SET_DATA_STORE_ERROR,
            ) from e

        return AttachmentRef(
            backend_type=OperatorConstants.DocumentSet.ADAPTER_DUCKDB,
            name=table_name,
            details={
                OperatorConstants.DocumentSet.DATABASE_PATH: self._database_path,
                "table_name": table_name,
            },
        )

    def load(self, *, attachment_ref: AttachmentRef, limit: int | None = None) -> pa.Table:
        """Read PyArrow table data from DuckDB.

        Args:
            attachment_ref: AttachmentRef containing table_name in details.
            limit: Maximum number of rows to return, or None for all.

        Returns:
            PyArrow table with the stored data.

        Raises:
            DocpipeException: If the table does not exist or the read fails.
        """
        table_name = attachment_ref.details["table_name"]
        try:
            if not self._storage.table_exists(table_name=table_name):
                raise DocpipeException(
                    f"Table '{table_name}' does not exist",
                    status_code=404,
                    error_code=ErrorCode.DOCUMENT_SET_TABLE_NOT_FOUND,
                )
            data = self._storage.read_data(table_name=table_name, limit=limit, offset=None)
            logger.debug("Loaded %d rows from %s", len(data), table_name)
            return data
        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to load data: {e!s}",
                status_code=500,
                error_code=ErrorCode.DOCUMENT_SET_DATA_STORE_ERROR,
            ) from e

    def delete(self, *, attachment_ref: AttachmentRef) -> bool:
        """Drop the DuckDB table described by attachment_ref.

        Args:
            attachment_ref: AttachmentRef containing table_name in details.

        Returns:
            True if deleted, False if the table was absent.

        Raises:
            DocpipeException: If the deletion fails.
        """
        table_name = attachment_ref.details["table_name"]
        try:
            if not self._storage.table_exists(table_name=table_name):
                logger.info("Table not found for deletion: %s", table_name)
                return False
            self._storage.delete_table(table_name=table_name)
            logger.info("Deleted DuckDB table: %s", table_name)
            return True
        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to delete table: {e!s}",
                status_code=500,
                error_code=ErrorCode.DOCUMENT_SET_DATA_STORE_ERROR,
            ) from e

    def get_metrics(self, *, attachment_ref: AttachmentRef) -> dict[str, int]:
        """Compute aggregate metrics via DuckDB SQL aggregation.

        Args:
            attachment_ref: AttachmentRef containing table_name in details.

        Returns:
            Dictionary with keys: total_documents, total_size_bytes, total_pages.

        Raises:
            DocpipeException: If the table does not exist or the query fails.
        """
        table_name = attachment_ref.details["table_name"]
        try:
            if not self._storage.table_exists(table_name=table_name):
                raise DocpipeException(
                    f"Table '{table_name}' does not exist",
                    status_code=404,
                    error_code=ErrorCode.DOCUMENT_SET_TABLE_NOT_FOUND,
                )

            column_result = self._storage.execute_query(
                query="SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                params=[table_name],
            )  # nosec B608 — table_name is a sanitized identifier derived from document set name, not user input
            column_names = [row["column_name"] for row in column_result.to_pylist()]

            select_clauses = ["COUNT(*) AS total_documents"]
            select_clauses.append(
                "COALESCE(SUM(size), 0) AS total_size_bytes" if "size" in column_names else "0 AS total_size_bytes"
            )
            select_clauses.append(
                "COALESCE(SUM(pages_processed), 0) AS total_pages"
                if "pages_processed" in column_names
                else "0 AS total_pages"
            )

            result_table = self._storage.execute_query(
                query=f"SELECT {', '.join(select_clauses)} FROM {table_name}"  # nosec B608 — table_name is a sanitized identifier, not user input
            )

            # Aggregates without GROUP BY always return exactly one row
            result = result_table.to_pylist()[0]
            metrics = {
                "total_documents": int(result["total_documents"]),
                "total_size_bytes": int(result["total_size_bytes"]),
                "total_pages": int(result["total_pages"]),
            }
            logger.debug("Computed metrics for %s: %s", table_name, metrics)
            return metrics
        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to compute metrics: {e!s}",
                status_code=500,
                error_code=ErrorCode.DOCUMENT_SET_DATA_STORE_ERROR,
            ) from e

    def exists(self, *, attachment_ref: AttachmentRef) -> bool:
        """Check whether the DuckDB table described by attachment_ref exists.

        Args:
            attachment_ref: AttachmentRef containing table_name in details.

        Returns:
            True if the table exists, False otherwise.

        Raises:
            DocpipeException: If the check fails.
        """
        try:
            return self._storage.table_exists(table_name=attachment_ref.details["table_name"])
        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to check table existence: {e!s}",
                status_code=500,
                error_code=ErrorCode.DOCUMENT_SET_DATA_STORE_ERROR,
            ) from e

    def health_check(self) -> HealthCheckResult:
        """Check DuckDB connectivity.

        Returns:
            HealthCheckResult indicating whether the backend is reachable.
        """
        try:
            self._storage.execute_query(query=OperatorConstants.DocumentSet.QUERY_CONNECTIVITY_TEST)
            return HealthCheckResult(
                healthy=True,
                message="Storage is healthy",
                details={OperatorConstants.DocumentSet.DATABASE_PATH: self._database_path},
            )
        except Exception as e:
            return HealthCheckResult(
                healthy=False,
                message=f"Health check failed: {e}",
                details={
                    OperatorConstants.DocumentSet.DATABASE_PATH: self._database_path,
                    OperatorConstants.DocumentSet.META_ERROR: str(e),
                },
            )

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
