"""Entity extraction port interface.

This module defines the port interface for entity extraction operations following
hexagonal architecture principles. The port defines the contract that adapters
must implement for entity extraction.

The actual orchestration logic (parallel processing, task submission, result
aggregation) should be delegated to EntityExtractionService in the application layer.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

import pyarrow as pa
from pydantic import BaseModel

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.infrastructure.logging import get_logger

logger: logging.Logger = get_logger()


class EntityExtractionPort(ABC):
    """Port interface for entity extraction adapters.

    This interface defines the contract that all entity extraction adapters must
    implement. Adapters provide the specific extraction logic (e.g., Ollama, Docling,
    LiteLLM), while the EntityExtractionService handles orchestration.

    Design Philosophy:
        Port = Interface Contract
        Adapter = Specific Extraction Implementation
        Service = Orchestration + Parallel Processing

    Attributes:
        ADAPTER_NAME: Short identifier for the adapter (e.g., "ollama", "docling", "litellm")
        ADAPTER_DISPLAY_NAME: Human-readable adapter name (e.g., "Ollama", "Docling", "LiteLLM")
        max_workers: Number of parallel workers for processing
        doc_column: Column name containing document text
        output_column: Column name for storing extracted entities
        expand_extracted_data: Whether to expand entities into individual columns
        custom_schema: Custom schema for entity extraction
        doc_id_hash_column: Column name for document hash IDs
        job_run_id: Job run identifier for progress tracking
        node_id: Node identifier for progress tracking
        node_name: Node name for progress tracking
        batch_id: Batch identifier for progress tracking
    """

    ADAPTER_NAME: str = "base"
    ADAPTER_DISPLAY_NAME: str = "Base Adapter"
    requires_binary_content: bool = False

    def __init__(self, *, config: dict[str, Any]) -> None:
        """Initialize the entity extraction port with configuration.

        Args:
            config: Configuration dictionary containing:
                - max_workers: Number of parallel workers (default: 4)
                - doc_column: Column name for document text (default: "doc_content")
                - output_column: Column name for entities (default: "entities")
                - expand_extracted_data: Expand entities into columns (default: False)
                - custom_schema: Custom schema for entity extraction (optional)
                - doc_id_hash: Column name for document hash IDs (default: "doc_id_hash")
                - ingest_source: Ingest source configuration for on-demand binary fetching (optional)
                - job_run_id: Job run identifier for progress tracking (optional)
                - node_id: Node identifier for progress tracking (optional)
                - node_name: Node name for progress tracking (optional)
                - batch_id: Batch identifier for progress tracking (optional)
                - Additional adapter-specific configuration
        """
        self.max_workers = config.get(OperatorConstants.Config.MAX_WORKERS, 4)
        self.doc_column = config.get(OperatorConstants.Columns.DOC_COLUMN, OperatorConstants.Columns.DOC_COLUMN_DEFAULT)
        self.output_column = config.get(OperatorConstants.Columns.OUTPUT_COLUMN, OperatorConstants.Misc.ENTITIES)
        self.expand_extracted_data = config.get(OperatorConstants.Config.EXPAND_EXTRACTED_DATA, False)
        self.doc_id_hash_column = config.get(
            OperatorConstants.Columns.DOC_ID_HASH, OperatorConstants.Columns.DOC_ID_HASH_DEFAULT
        )
        self.custom_schema = config.get(OperatorConstants.Config.CUSTOM_SCHEMA, {})
        self.common_log_arguments = config.get("common_log_arguments", {})

        # Store full config for on-demand binary fetching (includes ingest_source if present)
        self.global_config = config

        # Job tracking context for progress updates
        from docpipe.core.constants.constants import DocpipeConstants

        self.job_run_id = config.get(DocpipeConstants.JOB_RUN_ID)
        self.node_id = config.get(DocpipeConstants.NODE_ID)
        self.node_name = config.get(DocpipeConstants.NODE_NAME)
        self.batch_id = config.get(DocpipeConstants.BATCH_ID)

        logger.info(
            "Initialized %s with job_run_id=%s, node_id=%s, batch_id=%s",
            self.__class__.__name__,
            self.job_run_id,
            self.node_id,
            self.batch_id,
            extra=self.common_log_arguments,
        )

        # Validate configuration before initializing adapter-specific config
        self.validate(config=config)
        # Subclasses should initialize their adapter-specific configuration
        self._init_adapter_config(config=config)

    def validate(self, *, config: dict[str, Any]) -> None:
        """Validate adapter configuration.

        Subclasses should override this method to implement adapter-specific
        validation logic. The base implementation validates common parameters.

        Args:
            config: Full configuration dictionary

        Raises:
            ValueError: If configuration is invalid
        """
        # Validate boolean flags if present
        expand_extracted_data = config.get(OperatorConstants.Config.EXPAND_EXTRACTED_DATA)
        if expand_extracted_data is not None and not isinstance(expand_extracted_data, bool):
            raise ValueError("Entity extraction 'expand_extracted_data' must be a boolean")

    @abstractmethod
    def _init_adapter_config(self, *, config: dict[str, Any]) -> None:
        """Initialize adapter-specific configuration.

        Subclasses must override this method to set up their specific configuration
        parameters (e.g., Ollama model settings, template configuration, API keys).

        Args:
            config: Full configuration dictionary
        """
        ...

    @staticmethod
    @abstractmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        ...

    @classmethod
    @abstractmethod
    def build_provider_config(cls, *, entity_extraction_config: dict[str, Any], doc_column: str) -> dict[str, Any]:
        """Build adapter-specific config from the nested entity_extraction config block.

        Called by the factory before instantiation. Returns a dict that is merged
        into full_config alongside global_config and max_workers.

        Args:
            entity_extraction_config: Nested entity_extraction configuration dictionary
            doc_column: Document column name from text_extraction config

        Returns:
            Adapter-specific configuration dictionary
        """

    @abstractmethod
    def transform(self, *, table: pa.Table, metadata: dict[str, Any]) -> tuple[list[pa.Table], dict[str, Any]]:
        """Transform documents by extracting entities.

        This method orchestrates the entity extraction process. Adapters should
        delegate the orchestration logic to EntityExtractionService and implement
        only the adapter-specific extraction logic in extract_entities_single().

        Args:
            table: PyArrow table with document information containing columns:
                - id: Document ID
                - name: Document name/filename
                - doc_content: Document text content
                - document_type: Document type for schema selection (optional)
            metadata: Metadata dictionary to update

        Returns:
            Tuple of (list of transformed tables, metadata dictionary)
        """
        ...

    @abstractmethod
    def extract_entities_single(
        self, *, doc_id: str, doc_name: str, content: str | bytes, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Extract entities from a single document.

        This is the adapter-specific extraction logic that runs in parallel workers.
        Each adapter implements its own extraction mechanics here.

        Args:
            doc_id: Document identifier
            doc_name: Document name for logging
            content: Document text content or binary content
            schema: Optional schema dictionary for structured extraction

        Returns:
            Dictionary with extraction results:
            {
                "success": bool,              # Extraction success indicator
                "entities": dict,             # Extracted entities as dictionary
                "error": str | None,          # Error message if failed
                "doc_content": str | None     # Optional extracted text content
            }
        """
        ...
