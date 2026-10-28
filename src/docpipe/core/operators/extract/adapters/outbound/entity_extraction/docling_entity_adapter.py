"""Docling-based entity extraction adapter.

This adapter implements entity extraction using Docling templates for structured
document processing. It extracts entities based on predefined document type templates.
Supports custom model configuration for both inline (HuggingFace) and API (Ollama, vLLM) models.
"""

import io
import json
from typing import Any

import pyarrow as pa
from pydantic import BaseModel

from docpipe.core.constants import OperatorConstants
from docpipe.core.constants.constants import DoclingClientConfigConstants
from docpipe.core.operators.extract.adapters.outbound.factories.entity_extraction_adapter_factory import (
    EntityExtractionAdapterFactory,
    register_entity_extraction_adapter,
)
from docpipe.core.operators.extract.ports.outbound.entity_extraction import EntityExtractionPort
from docpipe.core.operators.extract.services.entity_extraction_service import EntityExtractionService
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.integrations.docling.converter_pool import get_docling_pool, options_fingerprint
from docpipe.utils.document_class_utils import DocumentClassUtils
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

_EXTRACTOR_POOL_KEY_PREFIX = "DocumentExtractor:"


@register_entity_extraction_adapter
class DoclingEntityAdapter(EntityExtractionPort):
    """Template-based entity extraction adapter.

    This adapter uses Docling templates to extract structured entities from documents.
    It relies on document type classification to select the appropriate template and
    extract entities according to the template definition.

    Note: This is a placeholder implementation. Full template-based extraction would
    require integration with Docling's template extraction capabilities.

    Attributes:
        ADAPTER_NAME: Short identifier "template"
        ADAPTER_DISPLAY_NAME: Display name "Template"
    """

    ADAPTER_NAME = OperatorConstants.ExtractionModes.ENTITY_MODE_DOCLING
    ADAPTER_DISPLAY_NAME = "Docling"

    def __init__(self, *, config: dict[str, Any]) -> None:
        """Initialize the adapter with configuration.

        Args:
            config: Configuration dictionary
        """
        super().__init__(config=config)

    def validate(self, *, config: dict[str, Any]) -> None:
        """Validate adapter configuration.

        Validates both base configuration and vlm_pipeline for custom models.

        Args:
            config: Configuration dictionary to validate

        Raises:
            ValueError: If configuration is invalid
        """
        # Validate string parameters if present
        for param in ["doc_column", "output_column"]:
            value = config.get(param)
            if value is not None and not isinstance(value, str):
                msg = f"DoclingEntityAdapter '{param}' must be a string"
                raise ValueError(msg)

        # Validate vlm_pipeline if present
        vlm_pipeline = config.get(DoclingClientConfigConstants.VLM_PIPELINE)
        if vlm_pipeline is not None:
            if not isinstance(vlm_pipeline, dict):
                msg = f"'{DoclingClientConfigConstants.VLM_PIPELINE}' must be a dictionary"
                raise ValueError(msg)

            model_type = vlm_pipeline.get(DoclingClientConfigConstants.MODEL_TYPE)
            if model_type is not None:
                if not isinstance(model_type, str):
                    msg = f"'{DoclingClientConfigConstants.VLM_PIPELINE}.{DoclingClientConfigConstants.MODEL_TYPE}' must be a string"
                    raise ValueError(msg)
                if model_type != DoclingClientConfigConstants.MODEL_TYPE_INLINE:
                    msg = (
                        f"'{DoclingClientConfigConstants.VLM_PIPELINE}.{DoclingClientConfigConstants.MODEL_TYPE}'"
                        f" must be '{DoclingClientConfigConstants.MODEL_TYPE_INLINE}'."
                        " Note: API model is not supported by DocumentExtractor."
                    )
                    raise ValueError(msg)

                # Validate inline model config
                inline_config = vlm_pipeline.get(DoclingClientConfigConstants.INLINE_MODEL)
                if inline_config is None:
                    msg = (
                        f"'{DoclingClientConfigConstants.VLM_PIPELINE}.{DoclingClientConfigConstants.INLINE_MODEL}'"
                        f" is required when model_type is '{DoclingClientConfigConstants.MODEL_TYPE_INLINE}'"
                    )
                    raise ValueError(msg)
                if not isinstance(inline_config, dict):
                    msg = f"'{DoclingClientConfigConstants.VLM_PIPELINE}.{DoclingClientConfigConstants.INLINE_MODEL}' must be a dictionary"
                    raise ValueError(msg)
                if DoclingClientConfigConstants.REPO_ID not in inline_config:
                    msg = (
                        f"'{DoclingClientConfigConstants.VLM_PIPELINE}"
                        f".{DoclingClientConfigConstants.INLINE_MODEL}"
                        f".{DoclingClientConfigConstants.REPO_ID}' is required"
                    )
                    raise ValueError(msg)
                if not isinstance(inline_config[DoclingClientConfigConstants.REPO_ID], str):
                    msg = (
                        f"'{DoclingClientConfigConstants.VLM_PIPELINE}"
                        f".{DoclingClientConfigConstants.INLINE_MODEL}"
                        f".{DoclingClientConfigConstants.REPO_ID}' must be a string"
                    )
                    raise ValueError(msg)

        super().validate(config=config)

    def _init_adapter_config(self, *, config: dict[str, Any]) -> None:
        """Initialize docling-specific configuration including custom model options.

        Builds VLM extraction options once during initialization to avoid rebuilding
        for every document. Errors during build are logged but don't prevent adapter creation.

        Args:
            config: Configuration dictionary containing optional vlm_pipeline
        """
        self.vlm_pipeline = config.get(DoclingClientConfigConstants.VLM_PIPELINE)

        if self.vlm_pipeline:
            model_type = self.vlm_pipeline.get(DoclingClientConfigConstants.MODEL_TYPE)
            if model_type == DoclingClientConfigConstants.MODEL_TYPE_INLINE:
                logger.info(
                    "Configured DoclingEntityAdapter with inline model: %s",
                    self.vlm_pipeline.get(DoclingClientConfigConstants.INLINE_MODEL, {}).get(
                        DoclingClientConfigConstants.REPO_ID
                    ),
                )
        else:
            logger.info("Initialized DoclingEntityAdapter with default model configuration")

        # Build VLM extraction options once during initialization
        # Wrap in try-except to allow adapter creation even if VLM build fails
        self.extraction_format_options = None
        try:
            self.extraction_format_options = self._build_vlm_extraction_options(vlm_pipeline=self.vlm_pipeline)
        except (ImportError, ValueError) as e:
            logger.warning("Failed to build VLM extraction options during initialization: %s", e)

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        from docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_config import (
            DoclingEntityConfig,
        )

        return DoclingEntityConfig

    @classmethod
    def build_provider_config(cls, *, entity_extraction_config: dict[str, Any], doc_column: str) -> dict[str, Any]:
        """Build Docling-specific adapter config from the entity_extraction config block.

        Args:
            entity_extraction_config: Nested entity_extraction configuration dictionary
            doc_column: Document column name from text_extraction config

        Returns:
            Adapter-specific configuration dictionary
        """
        provider_config = entity_extraction_config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
        base = EntityExtractionAdapterFactory.build_common_config(
            entity_extraction_config=entity_extraction_config, doc_column=doc_column
        )
        vlm_pipeline = provider_config.get(DoclingClientConfigConstants.VLM_PIPELINE)
        if vlm_pipeline:
            base[DoclingClientConfigConstants.VLM_PIPELINE] = vlm_pipeline
        return base

    @staticmethod
    def _build_vlm_extraction_options(*, vlm_pipeline: Any) -> dict[Any, Any] | None:
        """Build VLM extraction format options from stored configuration.

        Returns:
            Dictionary mapping InputFormat to ExtractionFormatOption, or None if no custom config
        """
        if not vlm_pipeline:
            return None

        try:
            from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
            from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import VlmPipelineOptions
            from docling.datamodel.pipeline_options_vlm_model import InlineVlmOptions
            from docling.document_extractor import ExtractionFormatOption
            from docling.pipeline.extraction_vlm_pipeline import ExtractionVlmPipeline

            model_type = vlm_pipeline.get(DoclingClientConfigConstants.MODEL_TYPE)

            if model_type == DoclingClientConfigConstants.MODEL_TYPE_INLINE:
                inline_config = vlm_pipeline.get(DoclingClientConfigConstants.INLINE_MODEL, {})
                vlm_options = InlineVlmOptions(
                    repo_id=inline_config[DoclingClientConfigConstants.REPO_ID],
                    inference_framework=inline_config.get(
                        DoclingClientConfigConstants.INFERENCE_FRAMEWORK,
                        DoclingClientConfigConstants.DEFAULT_INFERENCE_FRAMEWORK,
                    ),
                    scale=inline_config.get(
                        DoclingClientConfigConstants.SCALE, DoclingClientConfigConstants.DEFAULT_SCALE
                    ),
                    temperature=inline_config.get(
                        DoclingClientConfigConstants.TEMPERATURE, DoclingClientConfigConstants.DEFAULT_TEMPERATURE
                    ),
                    max_new_tokens=inline_config.get(
                        DoclingClientConfigConstants.MAX_NEW_TOKENS, DoclingClientConfigConstants.DEFAULT_MAX_NEW_TOKENS
                    ),
                    load_in_8bit=inline_config.get(
                        DoclingClientConfigConstants.LOAD_IN_8BIT, DoclingClientConfigConstants.DEFAULT_LOAD_IN_8BIT
                    ),
                    torch_dtype=inline_config.get(
                        DoclingClientConfigConstants.TORCH_DTYPE, DoclingClientConfigConstants.DEFAULT_TORCH_DTYPE
                    ),
                    prompt=inline_config.get(
                        DoclingClientConfigConstants.PROMPT, DoclingClientConfigConstants.DEFAULT_PROMPT
                    ),
                    response_format=inline_config.get(
                        DoclingClientConfigConstants.RESPONSE_FORMAT,
                        DoclingClientConfigConstants.DEFAULT_RESPONSE_FORMAT,
                    ),
                )
            else:
                return None

            # Build pipeline options
            pipeline_options = VlmPipelineOptions(vlm_options=vlm_options)

            # Build extraction format options for both PDF and IMAGE formats
            return {
                InputFormat.PDF: ExtractionFormatOption(
                    pipeline_cls=ExtractionVlmPipeline,
                    pipeline_options=pipeline_options,
                    backend=PyPdfiumDocumentBackend,
                ),
                InputFormat.IMAGE: ExtractionFormatOption(
                    pipeline_cls=ExtractionVlmPipeline,
                    pipeline_options=pipeline_options,
                    backend=DoclingParseDocumentBackend,
                ),
            }

        except ImportError as e:
            logger.error("Failed to import Docling VLM classes. Install with: pip install docling[vlm]")
            logger.error("Error: %s", e)
            msg = "Docling VLM dependencies not available"
            raise ValueError(msg) from e
        except Exception as e:
            logger.error("Failed to build VLM extraction options: %s", e)
            msg = f"Invalid VLM configuration: {e}"
            raise ValueError(msg) from e

    def transform(self, *, table: pa.Table, metadata: dict[str, Any]) -> tuple[list[pa.Table], dict[str, Any]]:
        """Transform documents by extracting entities using Docling.

        This method delegates orchestration to EntityExtractionService while
        maintaining backward compatibility with the adapter interface.

        Args:
            table: PyArrow table with document information containing columns:
                - id: Document ID
                - name: Document name/filename
                - doc_content: Document text content (or binary_content for Docling)
                - document_type: Document type for schema selection (optional)
            metadata: Metadata dictionary to update

        Returns:
            Tuple of (list of transformed tables, metadata dictionary)
        """
        # Create custom service instance that overrides _prepare_document_tasks
        service = DoclingEntityExtractionService(
            adapter=self,
            config={
                OperatorConstants.Columns.DOC_COLUMN: self.doc_column,
                OperatorConstants.Columns.OUTPUT_COLUMN: self.output_column,
                OperatorConstants.Config.EXPAND_EXTRACTED_DATA: self.expand_extracted_data,
                OperatorConstants.Columns.DOC_ID_HASH: self.doc_id_hash_column,
                OperatorConstants.Config.CUSTOM_SCHEMA: self.custom_schema,
                "common_log_arguments": self.common_log_arguments,
            },
            max_workers=self.max_workers,
            job_run_id=self.job_run_id,
            node_id=self.node_id,
            node_name=self.node_name,
            batch_id=self.batch_id,
            global_config=self.global_config,
        )

        # Delegate to service for orchestration
        return service.transform(table=table, metadata=metadata)

    def extract_entities_single(
        self, *, doc_id: str, doc_name: str, content: str | bytes, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Extract entities from a single document using schema and optional custom model.

        Uses Docling's DocumentExtractor with optional custom VLM configuration.
        Supports both inline (HuggingFace) and API (Ollama, vLLM) models.

        Args:
            doc_id: Document identifier
            doc_name: Document name for logging
            content: Document text content (str) or binary content (bytes)
            schema: Optional schema dictionary for structured extraction

        Returns:
            Dictionary with extraction results:
            {
                "success": bool,
                "entities": dict,
                "metadata": dict,
                "error": str | None
            }
        """
        logger.info("Processing file with template: %s", doc_name)

        try:
            from docling.datamodel.base_models import InputFormat
            from docling_core.types.io import DocumentStream

            # Handle both str and bytes content
            content_bytes = content.encode("utf-8") if isinstance(content, str) else content

            # Create DocumentStream from binary content (no temporary file needed)
            doc_stream = DocumentStream(name=doc_name, stream=io.BytesIO(content_bytes))

            # Lease a DocumentExtractor for the VLM extraction options built once during
            # initialization. Extractors are pooled process-wide and keyed by the option
            # values, so the extraction pipeline (and its VLM weights) is initialised once
            # per configuration instead of once per document, and an extractor is never
            # used by two threads at the same time.
            format_options = self.extraction_format_options
            if format_options:
                logger.debug("Using custom VLM model for extraction: %s", doc_name)
            else:
                logger.debug("Using default model for extraction: %s", doc_name)

            pool_key = _EXTRACTOR_POOL_KEY_PREFIX + (
                options_fingerprint(format_options) if format_options else "default"
            )
            with get_docling_pool().lease(
                key=pool_key,
                factory=lambda: self._build_document_extractor(
                    allowed_formats=[InputFormat.IMAGE, InputFormat.PDF],
                    extraction_format_options=format_options,
                ),
            ) as extractor:
                # Extract directly from stream
                result = extractor.extract(source=doc_stream, template=schema or {})
                extraction_format_to_options = extractor.extraction_format_to_options

            # Convert pages to proper dict format
            pages_data = []
            for page in result.pages:
                extracted_data = page.extracted_data

                # If extracted_data is None but raw_text contains JSON, parse it
                if extracted_data is None and page.raw_text:
                    try:
                        extracted_data = json.loads(page.raw_text)
                    except json.JSONDecodeError:
                        # If not valid JSON, keep as None
                        pass

                page_dict = {
                    OperatorConstants.Extraction.PAGE_NO: page.page_no,
                    OperatorConstants.Columns.EXTRACTED_DATA: extracted_data,
                    OperatorConstants.Extraction.ERRORS: page.errors,
                }
                pages_data.append(page_dict)
            logger.info("Saved structured results for %s", doc_name)
            logger.debug("Extraction Format Options used: %s", extraction_format_to_options)
            logger.debug("Extracted Pages: %s", pages_data)
            return {
                OperatorConstants.Extraction.SUCCESS: True,
                OperatorConstants.Misc.ENTITIES: pages_data,
                OperatorConstants.Metadata.METADATA: {"page_count": len(pages_data)},
            }
        except ImportError as e:
            logger.error("DocumentExtractor not available. Install with: pip install docling[vlm]")
            logger.error("Error: %s", e)
            return {
                OperatorConstants.Extraction.SUCCESS: False,
                OperatorConstants.Extraction.ERROR: "DocumentExtractor not available",
            }
        except Exception as e:
            logger.error("Error extracting with template: %s", e)
            return {OperatorConstants.Extraction.SUCCESS: False, OperatorConstants.Extraction.ERROR: str(e)}

    @staticmethod
    def _build_document_extractor(
        *, allowed_formats: list[Any], extraction_format_options: dict[Any, Any] | None
    ) -> Any:
        """Construct a DocumentExtractor, passing custom format options only when configured.

        Raises:
            RuntimeError: If Docling's DocumentExtractor is not installed.
        """
        try:
            from docling.document_extractor import DocumentExtractor
        except ImportError as e:
            msg = "DocumentExtractor is not available. Install with: pip install 'docling[vlm]'"
            raise RuntimeError(msg) from e

        if extraction_format_options:
            return DocumentExtractor(
                allowed_formats=allowed_formats, extraction_format_options=extraction_format_options
            )
        return DocumentExtractor(allowed_formats=allowed_formats)

    def _prepare_document_tasks(
        self, table: Any, document_types: list[str], metadata: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Prepare document tasks with binary content for Docling processing.

        This override fetches binary content from the table instead of text content,
        using on-demand fetching to support both local files and cloud sources.
        It looks for columns in this order of preference:
        1. "binary_content" (pre-loaded)
        2. "path" or "source_id" (fetched on-demand from local or cloud)

        Args:
            table: PyArrow table containing document data
            document_types: List of document types corresponding to table rows
            metadata: Metadata dictionary for recording skipped documents

        Returns:
            List of task dictionaries with binary content
        """
        doc_tasks: list[dict[str, Any]] = OperatorUtils.prepare_document_content_fetch(
            table=table,
            global_config=self.global_config,
            supported_extensions=set(OperatorConstants.FileExtensions.DOCLING_ENTITY_EXTENSIONS_PDF_IMAGE_ONLY),
        )

        for doc_task in doc_tasks:
            row_idx = doc_task["idx"]
            doc_task.update({"document_type": document_types[row_idx] if document_types else None})
        return doc_tasks

    def _load_schema_templates(self, *, document_types: list[str], schema_templates: dict[str, dict]) -> None:
        """Load schema templates for given document types.

        Args:
            document_types: List of document types to load schemas for
            schema_templates: Dictionary to populate with loaded schemas
        """
        loaded_schemas = DocumentClassUtils.generate_docling_templates_for_types(document_types)
        schema_templates.update(loaded_schemas)


class DoclingEntityExtractionService(EntityExtractionService):
    """Custom entity extraction service for Docling adapter.

    This service extends EntityExtractionService to handle Docling-specific
    requirements, particularly binary content fetching for document processing.
    """

    def __init__(
        self,
        *,
        adapter: EntityExtractionPort,
        config: dict[str, Any],
        max_workers: int = 4,
        job_run_id: str | None = None,
        node_id: str | None = None,
        node_name: str | None = None,
        batch_id: str | None = None,
        global_config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the Docling entity extraction service.

        Args:
            adapter: EntityExtractionPort implementation for extraction
            config: Configuration dictionary containing extraction parameters
            max_workers: Number of parallel workers (default: 4)
            job_run_id: Job run identifier for progress tracking (optional)
            node_id: Node identifier for progress tracking (optional)
            node_name: Node name for progress tracking (optional)
            batch_id: Batch identifier for progress tracking (optional)
            global_config: Global configuration for on-demand binary fetching (optional)
        """
        super().__init__(
            adapter=adapter,
            config=config,
            max_workers=max_workers,
            job_run_id=job_run_id,
            node_id=node_id,
            node_name=node_name,
            batch_id=batch_id,
        )
        self.global_config = global_config or {}

    def _prepare_document_tasks(
        self, table: pa.Table, document_types: list[str], metadata: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Prepare document tasks with binary content for Docling processing.

        This override fetches binary content from the table instead of text content,
        using on-demand fetching to support both local files and cloud sources.

        Args:
            table: PyArrow table containing document data
            document_types: List of document types corresponding to table rows
            metadata: Metadata dictionary for recording skipped documents

        Returns:
            List of task dictionaries with binary content
        """
        doc_tasks: list[dict[str, Any]] = OperatorUtils.prepare_document_content_fetch(
            table=table,
            global_config=self.global_config,
            supported_extensions=set(OperatorConstants.FileExtensions.DOCLING_ENTITY_EXTENSIONS_PDF_IMAGE_ONLY),
        )

        for doc_task in doc_tasks:
            row_idx = doc_task["idx"]
            doc_task.update({"document_type": document_types[row_idx] if document_types else None})
        return doc_tasks

    def _load_schema_templates(self, *, document_types: list[str], schema_templates: dict[str, dict]) -> None:
        """Load Docling-specific schema templates for given document types.

        Args:
            document_types: List of document types to load schemas for
            schema_templates: Dictionary to populate with loaded schemas
        """
        loaded_schemas = DocumentClassUtils.generate_docling_templates_for_types(document_types)
        schema_templates.update(loaded_schemas)
