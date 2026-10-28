"""Document Set Operator for storing PyArrow table data with metadata tracking.

This operator stores PyArrow table data in a document set using DuckDB storage,
with automatic metrics computation and support for incremental updates with
soft-delete cleanup.
"""

# Import to trigger adapter registration
from typing import Any

import pyarrow as pa

from docpipe.core.assets.common import adapters as common_adapters  # noqa: F401
from docpipe.core.assets.common.factories.attachment_repository_factory import AttachmentRepositoryFactory
from docpipe.core.assets.common.factories.repository_factory import RepositoryFactory
from docpipe.core.assets.document_sets import adapters  # noqa: F401
from docpipe.core.assets.document_sets.application.services.document_set_service import DocumentSetService
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet
from docpipe.core.assets.document_sets.factories import DataStoreFactory
from docpipe.core.constants.constants import AttributeDataTypes, DocpipeConstants, ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.exceptions.docpipe_exceptions import (
    DocpipeException,
    FlowExecutionFailedException,
    FlowValidationException,
)
from docpipe.storage.duck_db.duckdb_table_storage import DuckDBTableStorage
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class DocumentSetOperator(AbstractOperator):
    """Operator for storing PyArrow table data in document sets.

    This operator provides persistent storage for pipeline data using the document set
    infrastructure. It handles:
    - Creating or updating document sets
    - Storing PyArrow table data with schema evolution
    - Computing and tracking metrics (document count, size, pages)
    - Handling incremental updates with soft-delete cleanup
    - Pass-through of original data for downstream operators

    The operator uses dependency injection for services and follows the enterprise
    pattern with proper separation of concerns between storage, repository, and
    service layers.

    Attributes:
        short_name: Operator identifier for logging and metadata
        category: Operator category (Storage)
    """

    short_name: str = "document_set"
    category: OperatorCategory = OperatorCategory.Storage
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the Document Set operator.

        Args:
            config: Configuration dictionary containing:
                - document_set_name (required): Name of the document set
                - description (optional): Description of the document set
                - metadata (optional): Additional metadata as JSON
                - document_set_id (optional): Existing document set ID for updates
                - data_backend (optional): Data store backend (default: "duckdb")
                - database_path (optional): Database path (default: from constants)

        Note:
            Metadata and attachment backend type is resolved from
            docling-pipelines-config.yaml (assets_management.document_set_repository.type).
        """
        super().__init__(config)

        try:
            # Extract configuration parameters
            document_set_name = config.get(OperatorConstants.DocumentSet.DOCUMENT_SET_NAME)
            if not document_set_name:
                raise FlowValidationException(f"{OperatorConstants.DocumentSet.DOCUMENT_SET_NAME} is required")

            self.document_set_name: str = document_set_name
            self.description: str | None = config.get(OperatorConstants.Config.DESCRIPTION)
            self.metadata_config: dict | None = config.get(OperatorConstants.Metadata.METADATA)
            self.document_set_id: str | None = config.get(OperatorConstants.DocumentSet.DOCUMENT_SET_ID)

            # Database path
            db_path = (
                config.get(OperatorConstants.DocumentSet.DATABASE_PATH) or DocpipeConstants.DOCUMENT_SET_DEFAULT_DB_PATH
            )
            self.database_path: str = self._validate_database_path(database_path=db_path)

            # Validate database path
            DuckDBTableStorage.validate_database_path(db_path=self.database_path)

            # Data backend from operator config (operator-specific)
            self.data_backend: str = config.get(
                OperatorConstants.DocumentSet.DATA_BACKEND, OperatorConstants.DocumentSet.DEFAULT_DATA_BACKEND
            )

            logger.info(
                "Initialized DocumentSetOperator for: %s",
                self.document_set_name,
                extra=self.common_log_arguments,
            )
        except FlowValidationException:
            raise
        except Exception as e:
            raise FlowValidationException(f"Failed to initialize DocumentSetOperator: {e}") from e

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Return operator metadata for flow validation and documentation."""
        return {
            OperatorConstants.Misc.SDK: True,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: (DocumentSetOperator.is_available()),
            OperatorConstants.Misc.CATEGORY: DocumentSetOperator.category.value,
            OperatorConstants.Misc.LABEL: "Document Set",
            OperatorConstants.Config.DESCRIPTION: (
                "Stores PyArrow table data in a document set with metadata tracking"
            ),
            OperatorConstants.Config.ATTRIBUTES: {
                OperatorConstants.DocumentSet.DOCUMENT_SET_NAME: {
                    OperatorConstants.Misc.NAME: "Document Set Name",
                    OperatorConstants.Config.DESCRIPTION: "Unique name for the document set",
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Config.DEFAULT: None,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OperatorConstants.Config.DESCRIPTION: {
                    OperatorConstants.Misc.NAME: "Description",
                    OperatorConstants.Config.DESCRIPTION: "Description of the document set",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: None,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OperatorConstants.Metadata.METADATA: {
                    OperatorConstants.Misc.NAME: "Metadata",
                    OperatorConstants.Config.DESCRIPTION: "Additional metadata payload stored with the document set",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: None,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                },
                OperatorConstants.DocumentSet.DOCUMENT_SET_ID: {
                    OperatorConstants.Misc.NAME: "Document Set ID",
                    OperatorConstants.Config.DESCRIPTION: "Existing document set UUID for update flows",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: None,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OperatorConstants.DocumentSet.DATA_BACKEND: {
                    OperatorConstants.Misc.NAME: "Data Backend",
                    OperatorConstants.Config.DESCRIPTION: "Data store backend for PyArrow table data",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.DocumentSet.ADAPTER_DUCKDB,
                    OperatorConstants.Config.VALID_VALUES: [
                        OperatorConstants.DocumentSet.ADAPTER_DUCKDB,
                        OperatorConstants.DocumentSet.ADAPTER_FILESYSTEM,
                    ],
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OperatorConstants.DocumentSet.DATABASE_PATH: {
                    OperatorConstants.Misc.NAME: "Database Path",
                    OperatorConstants.Config.DESCRIPTION: "Database file path used by DuckDB-backed adapters",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: None,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
            },
        }

    @staticmethod
    def get_required_features() -> list[str]:
        """Return list of required columns in the input table.

        Returns:
            List containing required column names
        """
        return [OperatorConstants.Columns.ID]

    def transform(self, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict[str, Any]]:
        """Transform the input table by storing it in a document set.

        This method:
        1. Extracts storage type from operator params (set by orchestrator)
        2. Creates metadata repository using global storage type
        3. Creates data store using operator-specific data_backend
        4. Stores data with automatic schema evolution
        5. Returns original table unchanged (pass-through)

        Args:
            table: PyArrow table containing the data to store
            file_name: Optional file name (unused, for interface compatibility)

        Returns:
            Tuple of:
                - List containing the original table (pass-through)
                - Metadata dictionary with storage info and metrics
        """
        # Resolve backend type and config from docling-pipelines-config.yaml.
        # database_path from operator config overrides the YAML value.
        #
        # Both the metadata repository and the attachment repository use the same backend
        # and database_path — they must always be co-located.
        #
        # Factory calls are here rather than in __init__ because DuckDBKeyValueStorage and
        # DuckDBTableStorage are per-path singletons — repeated calls with the same
        # database_path return the cached instance at the cost of two dict lookups.
        repo_type_str, repo_config = RepositoryFactory.get_repository_config(
            asset_type_name=DocumentSet.get_config_key()
        )
        attachment_repo_config = {**repo_config, OperatorConstants.DocumentSet.DATABASE_PATH: self.database_path}

        logger.info(
            "Using metadata storage type: %s, data storage type: %s",
            repo_type_str,
            self.data_backend,
            extra=self.common_log_arguments,
        )

        metadata_repository = RepositoryFactory.create_repository(
            asset_type=DocumentSet,
            config_override={OperatorConstants.DocumentSet.DATABASE_PATH: self.database_path},
        )

        data_store = DataStoreFactory.create(
            adapter_name=self.data_backend,
            config={OperatorConstants.DocumentSet.DATABASE_PATH: self.database_path},
        )

        # Create attachment repository using same config as metadata repo
        attachment_repo = AttachmentRepositoryFactory.create(
            adapter_name=repo_type_str.lower(),
            config=attachment_repo_config,
        )

        # Create service with port interfaces
        service = DocumentSetService(
            metadata_repository=metadata_repository,
            data_store=data_store,
            attachment_repository=attachment_repo,
        )

        # Initialize metadata
        metadata: dict[str, Any] = self.create_base_metadata(
            total_docs_count=table.num_rows, node_status=ExecutionStatus.COMPLETED.value
        )

        # Add storage-specific metadata
        metadata[OperatorConstants.DocumentSet.META_DOCUMENT_SET_NAME] = self.document_set_name
        metadata[OperatorConstants.DocumentSet.META_DATABASE_PATH] = self.database_path
        metadata["data_storage_type"] = self.data_backend

        # Handle empty table
        if table.num_rows == 0:
            logger.warning("Empty table provided to DocumentSetOperator", extra=self.common_log_arguments)
            metadata[OperatorConstants.DocumentSet.META_STORED_DOCUMENTS] = 0
            return [table], metadata

        # Validate required columns
        if OperatorConstants.Columns.ID not in table.column_names:
            error_msg = f"Required column '{OperatorConstants.Columns.ID}' not found"
            metadata[Metrics.External.NODE_STATUS] = ExecutionStatus.FAILED.value
            metadata[OperatorConstants.DocumentSet.META_ERROR] = error_msg
            return [table], metadata

        try:
            # Get or create document set
            doc_set_id = self._get_or_create_document_set(service=service)
            metadata[OperatorConstants.DocumentSet.META_DOCUMENT_SET_ID] = doc_set_id

            logger.info(
                "Using document set: %s (ID: %s)", self.document_set_name, doc_set_id, extra=self.common_log_arguments
            )

            # Store data
            logger.info("Storing %d rows in document set", table.num_rows, extra=self.common_log_arguments)

            updated_doc_set = service.store_data(document_set_id=doc_set_id, data=table)

            # Update metadata with computed metrics
            metadata[OperatorConstants.DocumentSet.META_STORED_DOCUMENTS] = updated_doc_set.total_documents
            metadata[OperatorConstants.DocumentSet.META_TOTAL_SIZE_BYTES] = updated_doc_set.total_size_bytes
            metadata[OperatorConstants.DocumentSet.META_TOTAL_PAGES] = updated_doc_set.total_pages

            # Read the attachment ref to obtain the logical table name
            ref = attachment_repo.get(asset_id=doc_set_id)
            metadata[OperatorConstants.DocumentSet.META_TABLE_NAME] = ref.name if ref else None
            metadata[Metrics.External.PROCESSED_DOCS] = table.num_rows

            logger.info(
                "Successfully stored data. Total documents: %d, Size: %d bytes, Pages: %d",
                updated_doc_set.total_documents,
                updated_doc_set.total_size_bytes,
                updated_doc_set.total_pages,
                extra=self.common_log_arguments,
            )

        except DocpipeException as e:
            metadata[Metrics.External.NODE_STATUS] = ExecutionStatus.FAILED.value
            metadata[OperatorConstants.DocumentSet.META_ERROR] = str(e)
            raise FlowExecutionFailedException(f"Document set operation failed: {e}") from e
        except Exception as e:
            metadata[Metrics.External.NODE_STATUS] = ExecutionStatus.FAILED.value
            metadata[OperatorConstants.DocumentSet.META_ERROR] = str(e)
            raise FlowExecutionFailedException(f"Unexpected error in document set operator: {e}") from e

        # Return original table unchanged (pass-through)
        return [table], metadata

    def _get_or_create_document_set(self, *, service: DocumentSetService) -> str:
        """Get existing document set or create a new one.

        Args:
            service: Document set service instance

        Returns:
            Document set ID
        """
        if self.document_set_id:
            logger.info("Updating existing document set: %s", self.document_set_id, extra=self.common_log_arguments)
            doc_set = service.update_document_set(
                document_set_id=self.document_set_id, description=self.description, metadata=self.metadata_config
            )
            return doc_set.asset_id or ""

        logger.info("Getting or creating document set: %s", self.document_set_name, extra=self.common_log_arguments)
        doc_set = service.create_document_set(
            name=self.document_set_name,
            description=self.description,
            metadata=self.metadata_config,
        )
        return doc_set.asset_id or ""

    def _validate_database_path(self, *, database_path: str) -> str:
        """Validate and normalize database path to prevent path traversal.

        Args:
            database_path: Path to validate

        Returns:
            Validated and normalized absolute path

        Raises:
            FlowValidationException: If path is invalid or contains traversal attempts
        """
        from docpipe.utils.core.validation import validate_database_path

        try:
            return validate_database_path(database_path)
        except ValueError as exc:
            logger.warning("Database path validation failed: %s", exc, extra=self.common_log_arguments)
            raise FlowValidationException(f"Invalid database path: {exc}") from exc
