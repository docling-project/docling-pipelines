# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Docling Serve remote extraction adapter.

This adapter implements remote document extraction using the Docling Serve API.
It delegates extraction to a remote Docling Serve instance, enabling distributed
processing and reducing local resource requirements.

Supports two docling-serve response formats:
- v1 (inline): {"document": {"md_content": "...", ...}, "processing_time": ...}
- v2 (artifacts): {"documents": [{"artifacts": [{"artifact_type": "markdown", "uri": "..."}]}], ...}
"""

import json
import logging
from pathlib import Path
from typing import Any, ClassVar

import requests
from pydantic import BaseModel

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.extract.adapters.outbound.factories.text_extraction_adapter_factory import (
    register_text_extraction_adapter,
)
from docpipe.core.operators.extract.ports.outbound.text_extraction import TextExtractionPort
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.integrations.docling.client import DoclingServeClient
from docpipe.utils.infrastructure.logging import get_logger

logger: logging.Logger = get_logger()


@register_text_extraction_adapter
class DoclingServeAdapter(TextExtractionPort):
    """Adapter for remote Docling Serve document extraction.

    This adapter connects to a remote Docling Serve API for document extraction.
    It supports:
    - Remote API-based extraction
    - Configurable OCR settings
    - Multiple PDF backends
    - Table and image extraction modes
    - Polling-based result retrieval
    - Automatic retry on failures

    Configuration:
        docling_serve_config: Dictionary containing:
            - base_url: Docling Serve API endpoint (default: "http://0.0.0.0:5001")
            - api_key: Optional API key for authentication
            - timeout: Request timeout in seconds (default: 300)
            - poll_interval: Polling interval in seconds (default: 2)
            - max_retries: Maximum retry attempts (default: 3)
            - verify_ssl: Enable SSL certificate verification (default: True)
                         Set to False only for internal testing with self-signed certificates
            - do_ocr: Enable OCR processing (default: True)
            - ocr_engine: OCR engine to use (optional)
            - ocr_languages: List of OCR languages (optional)
            - pdf_backend: PDF backend to use (default: "dlparse_v2")
            - table_mode: Table extraction mode (optional)
            - image_export_mode: Image export mode (optional)

    Attributes:
        ADAPTER_NAME: Short identifier "docling_serve"
        ADAPTER_DISPLAY_NAME: Human-readable name "Docling Serve"
    """

    ADAPTER_NAME = "docling_serve"
    ADAPTER_DISPLAY_NAME = "Docling Serve Extractor"

    # Maps format name → docling-serve v1 API response field name.
    # Paired with FORMAT_COLUMN_MAPPING (inherited from TextExtractionPort) this gives
    # both the source key (API response) and the destination key (PyArrow column).
    FORMAT_API_FIELD_MAPPING: ClassVar[dict[str, str]] = {
        OperatorConstants.Extraction.OUTPUT_FORMAT_HTML: OperatorConstants.Extraction.DOCLING_SERVE_HTML_CONTENT,
        OperatorConstants.Extraction.OUTPUT_FORMAT_JSON: OperatorConstants.Extraction.DOCLING_SERVE_JSON_CONTENT,
        OperatorConstants.Extraction.OUTPUT_FORMAT_TEXT: OperatorConstants.Extraction.DOCLING_SERVE_TEXT_CONTENT,
        OperatorConstants.Extraction.OUTPUT_FORMAT_DOCTAGS: OperatorConstants.Extraction.DOCLING_SERVE_DOCTAGS_CONTENT,
        OperatorConstants.Extraction.OUTPUT_FORMAT_DOCLANG: OperatorConstants.Extraction.DOCLING_SERVE_DOCLANG_CONTENT,
    }

    # Maps docling-serve v2 artifact_type → format name used in FORMAT_API_FIELD_MAPPING / additional_formats
    ARTIFACT_TYPE_TO_FORMAT: ClassVar[dict[str, str]] = {
        "markdown": OperatorConstants.Extraction.OUTPUT_FORMAT_MARKDOWN,
        "html": OperatorConstants.Extraction.OUTPUT_FORMAT_HTML,
        "json": OperatorConstants.Extraction.OUTPUT_FORMAT_JSON,
        "text": OperatorConstants.Extraction.OUTPUT_FORMAT_TEXT,
        "doctags": OperatorConstants.Extraction.OUTPUT_FORMAT_DOCTAGS,
        "doclang": OperatorConstants.Extraction.OUTPUT_FORMAT_DOCLANG,
    }

    def __init__(self, *, config: dict[str, Any]) -> None:
        """Initialize the adapter with configuration.

        Args:
            config: Configuration dictionary
        """
        super().__init__(config=config)

    def _init_adapter_config(self, *, config: dict[str, Any]) -> None:
        """Initialize Docling Serve-specific configuration.

        Args:
            config: Configuration dictionary containing docling_serve_config

        Raises:
            ValueError: If docling_serve_config is missing or invalid
        """
        docling_serve_config = config.get("docling_serve_config")
        if not docling_serve_config:
            raise ValueError("docling_serve_config is required for DoclingServeAdapter")

        # Extract connection parameters
        self.base_url = docling_serve_config.get("base_url", "http://0.0.0.0:5001")
        self.api_key = docling_serve_config.get(OperatorConstants.Config.API_KEY)
        self.timeout = docling_serve_config.get("timeout", 300)
        self.poll_interval = docling_serve_config.get("poll_interval", 2)
        self.max_retries = docling_serve_config.get("max_retries", 3)
        self.verify_ssl = docling_serve_config.get("verify_ssl", True)

        # Build processing options (additional_formats is read from top-level config by the port base class;
        # we pass it into processing_options so _build_options in the client can forward it to the API)
        self.processing_options: dict[str, Any] = {
            "pdf_backend": docling_serve_config.get("pdf_backend", "dlparse_v2"),
        }

        # Include doclang if doc_format is doclang.
        # Read from self.global_config (set by the base class from the same config dict) so
        # that doc_format injected by ExtractOperator into global_config is always visible here.
        formats_to_request = list(self.additional_formats)
        doc_format = self.global_config.get(OperatorConstants.DOC_FORMAT_KEY)
        if doc_format == OperatorConstants.DocFormat.DOCLANG and "doclang" not in formats_to_request:
            formats_to_request.append("doclang")

        if formats_to_request:
            self.processing_options["additional_formats"] = formats_to_request

        # OCR wiring — new canonical ocr block takes precedence over flat fields
        ocr_block = docling_serve_config.get("ocr")
        if ocr_block:
            self.processing_options["do_ocr"] = ocr_block.get("enabled", True)
            engine = ocr_block.get("engine", "rapidocr")
            # docling-serve expects ocr_preset for engine selection
            self.processing_options["ocr_preset"] = engine
            ocr_mode = ocr_block.get("mode")
            if ocr_mode and ocr_mode != "default":
                self.processing_options["ocr_mode"] = ocr_mode
            engine_options = ocr_block.get("engine_options") or {}
            if engine_options.get("lang"):
                self.processing_options["ocr_languages"] = engine_options["lang"]
        else:
            # Backward compatibility: honour flat fields
            self.processing_options["do_ocr"] = docling_serve_config.get("do_ocr", True)
            if "ocr_engine" in docling_serve_config:
                self.processing_options["ocr_preset"] = docling_serve_config["ocr_engine"]
            if "ocr_languages" in docling_serve_config:
                self.processing_options["ocr_languages"] = docling_serve_config["ocr_languages"]

        # Add remaining optional parameters if present
        if "table_mode" in docling_serve_config:
            self.processing_options["table_mode"] = docling_serve_config["table_mode"]
        if "image_export_mode" in docling_serve_config:
            self.processing_options["image_export_mode"] = docling_serve_config["image_export_mode"]

        logger.info(
            "Initialized DoclingServeAdapter with base_url: %s, timeout: %s, additional_formats: %s",
            self.base_url,
            self.timeout,
            self.additional_formats,
        )

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_config import (
            DoclingServeConfig,
        )

        return DoclingServeConfig

    def extract_single_document(self, *, file_path: str, binary_content: bytes, **kwargs: Any) -> dict[str, Any]:
        """Extract content from a single document using Docling Serve API.

        Sends the document to a remote Docling Serve instance for extraction.
        Polls for results and returns the extracted markdown content plus any additional formats.

        Args:
            file_path: Path to the document file (used for logging and filename preservation)
            binary_content: Binary content of the document
            **kwargs: Additional parameters (currently unused)

        Returns:
            Dictionary containing:
                - success: True if extraction succeeded
                - content: Extracted content as markdown (mandatory)
                - content_html: HTML format (if requested in additional_formats)
                - content_json: JSON format (if requested in additional_formats)
                - content_text: Plain text format (if requested in additional_formats)
                - content_doctags: DocTags format (if requested in additional_formats)
                - content_doclang: DocLang format (if requested in additional_formats)
                - metadata: Extraction metadata (processing_time, page_count, formats, etc.)
                - error: Error message if extraction failed
        """
        logger.info("Processing file with docling-serve (formats: md + %s): %s", self.additional_formats, file_path)

        try:
            file_suffix = Path(file_path).suffix.lower()
            if not file_suffix:
                file_suffix = OperatorUtils.detect_extension_from_bytes(binary_content)

            # Handle .txt specially (Docling cannot process them)
            if file_suffix in [OperatorConstants.FileExtensions.EXT_TXT]:
                return OperatorUtils.extract_text_file(
                    file_path=file_path,
                    binary_content=binary_content,
                    additional_formats=self.additional_formats,
                    doc_format=self.global_config.get(
                        OperatorConstants.DOC_FORMAT_KEY, OperatorConstants.DOC_FORMAT_DEFAULT
                    ),
                )

            # Extract filename from path to preserve extension for remote processing
            filename = Path(file_path).name

            # Initialize client and process document
            client = DoclingServeClient(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.timeout,
                poll_interval=self.poll_interval,
                max_retries=self.max_retries,
                verify_ssl=self.verify_ssl,
            )
            result = client.process_document(
                binary_content=binary_content,
                filename=filename,
                options=self.processing_options,
            )

            # Detect response format and extract content accordingly
            extra_metadata: dict[str, Any] = {}
            if "documents" in result:
                # v2 format: artifacts are presigned URIs that must be fetched
                result_dict, formats_generated = self._extract_from_v2_response(result=result, file_path=file_path)
            else:
                # v1 format: content is inline in the response body
                result_dict, formats_generated, extra_metadata = self._extract_from_v1_response(
                    result=result, file_path=file_path
                )

            # Build metadata, merging any extra fields from the response (e.g. page_count)
            markdown_text = result_dict.get(OperatorConstants.Columns.DOC_COLUMN_DEFAULT, "")
            metadata = {
                OperatorConstants.Extraction.DOCLING_SERVE_PROCESSING_TIME: result.get(
                    OperatorConstants.Extraction.DOCLING_SERVE_PROCESSING_TIME, 0
                ),
                "char_count": len(markdown_text) if markdown_text else 0,
                "formats": formats_generated,
                **extra_metadata,
            }
            result_dict[OperatorConstants.Metadata.METADATA] = metadata

            logger.info("Completed docling-serve extraction for %s (formats: %s)", file_path, formats_generated)
            return result_dict

        except Exception as e:
            logger.error("Error extracting with docling-serve from %s: %s", file_path, str(e))
            return {
                OperatorConstants.Extraction.SUCCESS: False,
                OperatorConstants.Extraction.ERROR: str(e),
                OperatorConstants.Columns.DOC_COLUMN_DEFAULT: None,
            }

    def _extract_from_v1_response(
        self, *, result: dict[str, Any], file_path: str
    ) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
        """Extract content from v1 inline response format.

        v1 response: {"document": {"md_content": "...", "html_content": "..."}, "processing_time": ...}

        Returns:
            Tuple of (result_dict, formats_generated, extra_metadata) where extra_metadata
            contains additional fields (e.g. page_count) to be merged into the final metadata dict.
        """
        # v1 servers cannot produce DocLang artifacts — fail immediately so the caller
        # receives a clear error rather than silently receiving Markdown in a column that
        # the rest of the pipeline expects to contain DocLang XML.
        doc_format = self.global_config.get(OperatorConstants.DOC_FORMAT_KEY, OperatorConstants.DOC_FORMAT_DEFAULT)
        if doc_format == OperatorConstants.DocFormat.DOCLANG:
            logger.error(
                "doc_format=doclang is not supported by v1 docling-serve servers. "
                "Upgrade to a v2 server or use doc_format=markdown.",
            )
            return (
                {
                    OperatorConstants.Extraction.SUCCESS: False,
                    OperatorConstants.Extraction.ERROR: (
                        "doc_format=doclang requires a v2 docling-serve server; "
                        "this server returned a v1 response with no doclang artifact."
                    ),
                    OperatorConstants.Columns.DOC_COLUMN_DEFAULT: None,
                },
                [],
                {},
            )

        document = result.get(OperatorConstants.Extraction.DOCLING_SERVE_DOCUMENT, {})
        logger.debug(
            "v1 response - document keys: %s",
            list(document.keys()) if isinstance(document, dict) else "not a dict",
        )

        result_dict: dict[str, Any] = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: document.get("md_content", ""),
        }
        formats_generated = [OperatorConstants.Extraction.OUTPUT_FORMAT_MARKDOWN]
        extra_metadata: dict[str, Any] = {}

        for fmt in self.additional_formats:
            if fmt in self.FORMAT_API_FIELD_MAPPING and fmt in OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING:
                api_field = self.FORMAT_API_FIELD_MAPPING[fmt]
                output_column = OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING[fmt]
                if api_field in document:
                    content = document.get(api_field, "")
                    if fmt == OperatorConstants.Extraction.OUTPUT_FORMAT_JSON and content:
                        content = json.dumps(content, indent=2) if content else ""
                    result_dict[output_column] = content
                    formats_generated.append(fmt)
                    logger.info("Generated %s format for %s", fmt, file_path)

        # Page count from json_content if present
        json_content = document.get("json_content", {})
        if json_content and isinstance(json_content, dict):
            pages = json_content.get(OperatorConstants.Extraction.DOCLING_SERVE_PAGES, {})
            if pages:
                extra_metadata[OperatorConstants.Metadata.PAGE_COUNT] = len(pages)

        return result_dict, formats_generated, extra_metadata

    def _extract_from_v2_response(self, *, result: dict[str, Any], file_path: str) -> tuple[dict[str, Any], list[str]]:
        """Extract content from v2 artifact URI response format.

        v2 response: {"documents": [{"artifacts": [{"artifact_type": "markdown", "uri": "..."}]}], ...}
        Content is not inline — each artifact must be fetched from its presigned URI.

        The extraction fails when the response has no documents, or when the primary
        artifact (Markdown, or DocLang with ``doc_format=doclang``) is missing, has no URI
        or cannot be fetched. Secondary artifacts never make an extraction successful on
        their own, and a secondary artifact that cannot be fetched is skipped.
        """
        documents = result.get("documents", [])
        logger.debug("v2 response - %d document(s) in result", len(documents))

        result_dict: dict[str, Any] = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "",
        }
        formats_generated: list[str] = []

        doc_format = self.global_config.get(OperatorConstants.DOC_FORMAT_KEY, OperatorConstants.DOC_FORMAT_DEFAULT)
        is_doclang_primary = doc_format == OperatorConstants.DocFormat.DOCLANG
        primary_format = (
            OperatorConstants.Extraction.OUTPUT_FORMAT_DOCLANG
            if is_doclang_primary
            else OperatorConstants.Extraction.OUTPUT_FORMAT_MARKDOWN
        )

        if not documents:
            logger.warning("v2 response contains no documents for %s", file_path)
            return self._v2_failure(error=f"docling-serve v2 response contains no documents for {file_path}"), []

        doc = documents[0]
        artifacts = doc.get("artifacts", [])
        logger.debug("v2 response - artifact types: %s", [a.get("artifact_type") for a in artifacts])

        # Determine which formats to fetch: primary format + any requested additional formats
        requested_formats = {primary_format} | set(self.additional_formats)
        # Why the primary artifact could not be used, for the error message.
        primary_error: str | None = None

        for artifact in artifacts:
            artifact_type = artifact.get("artifact_type", "")
            fmt = self.ARTIFACT_TYPE_TO_FORMAT.get(artifact_type)
            if fmt is None or fmt not in requested_formats:
                continue

            uri = artifact.get("uri", "")
            if not uri:
                logger.warning("v2 artifact '%s' has no URI for %s", artifact_type, file_path)
                if fmt == primary_format:
                    primary_error = f"the '{artifact_type}' artifact has no URI"
                continue

            logger.info("Fetching v2 artifact '%s' for %s", artifact_type, file_path)
            try:
                resp = requests.get(uri, timeout=60, verify=self.verify_ssl)
                resp.raise_for_status()
                content: str = resp.text
            except Exception as fetch_err:
                logger.warning("Failed to fetch v2 artifact '%s' for %s: %s", artifact_type, file_path, fetch_err)
                if fmt == primary_format:
                    primary_error = f"the '{artifact_type}' artifact could not be fetched: {fetch_err}"
                continue

            if fmt == primary_format:
                result_dict[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = content
                formats_generated.append(fmt)
            elif fmt in OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING:
                output_column = OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING[fmt]
                if fmt == OperatorConstants.Extraction.OUTPUT_FORMAT_JSON:
                    try:
                        content = json.dumps(json.loads(content), indent=2)
                    except (json.JSONDecodeError, ValueError):
                        pass
                result_dict[output_column] = content
                formats_generated.append(fmt)
                logger.info("Generated %s format for %s", fmt, file_path)

        if primary_format not in formats_generated:
            reason = primary_error or f"it has no '{primary_format}' artifact"
            logger.warning(
                "Primary format '%s' is missing from the v2 response for %s: %s", primary_format, file_path, reason
            )
            # Fail the document instead of letting empty content flow downstream.
            return (
                self._v2_failure(
                    error=f"docling-serve v2 response for {file_path} has no {primary_format} content: {reason}"
                ),
                formats_generated,
            )

        return result_dict, formats_generated

    @staticmethod
    def _v2_failure(*, error: str) -> dict[str, Any]:
        """Return the result of a v2 extraction that has no primary content."""
        return {
            OperatorConstants.Extraction.SUCCESS: False,
            OperatorConstants.Extraction.ERROR: error,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: None,
        }
