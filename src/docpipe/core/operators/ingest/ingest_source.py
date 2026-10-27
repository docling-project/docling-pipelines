"""Validate source configuration and ingest documents through provider adapters."""

import asyncio
import hashlib
import importlib
import itertools
import json
import pathlib
from typing import TYPE_CHECKING, Any, Iterator, cast

import pyarrow as pa
from langchain_core.documents import Document

from docpipe.core.constants.constants import (
    AttributeDataTypes,
    DocpipeConstants,
    Metrics,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.event_streaming.models import InputEvent
from docpipe.core.incremental_metadata import get_incremental_update_service
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.ingest.ingest_utils import (
    get_filter_extensions,
    is_doc_previously_processed,
)
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.exceptions.error_messages import ValidationCodeMessages, ValidationMessage
from docpipe.integrations.rest_client import RestClient, RestClientConfig, RestMethod
from docpipe.utils.infrastructure.logging import get_logger

if TYPE_CHECKING:
    # Runtime import is intentionally avoided: langchain_core.document_loaders transitively imports
    # langchain_text_splitters, which eagerly loads torch/transformers/spacy/nltk (several seconds).
    from langchain_core.document_loaders import BaseLoader

# Microsoft Graph API Constants
MICROSOFT_LOGIN_URL = "https://login.microsoftonline.com"
MICROSOFT_GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
MICROSOFT_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
MICROSOFT_OAUTH_TOKEN_PATH = "/oauth2/v2.0/token"  # nosec B105 - URL path segment, not a credential


class MicrosoftGraphLoader:
    """
    Duck-typed LangChain-compatible loader (``lazy_load`` / ``load``) for Microsoft SharePoint
    and OneDrive using the Microsoft Graph API with app-only (client credentials) authentication.

    This bypasses LangChain's O365-based loaders which require delegated (user) auth
    and call /me/drives/ endpoints that are incompatible with app-only tokens.

    It deliberately does not subclass ``langchain_core.document_loaders.BaseLoader``: importing
    that module costs several seconds of unrelated ML-framework imports at operator-registry load.
    """

    def __init__(
        self,
        drive_id: str,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        folder_path: str | None = None,
        recursive: bool = True,
        max_download_workers: int = 8,
    ):
        self.drive_id = drive_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.folder_path = folder_path
        self.recursive = recursive
        self.max_download_workers = max_download_workers
        self._token = None

        # Initialize RestClient with appropriate configuration for Microsoft Graph API
        rest_config = RestClientConfig(
            timeout=60,  # Graph API can be slow for large files
            retry_backoff_factor=2.0,
        )
        self._rest_client = RestClient(
            config=rest_config,
            base_url=MICROSOFT_GRAPH_API_BASE,
        )

        # Reuse a single download client for direct download URLs.
        # Creating a new RestClient per file adds a full HTTPS handshake per download.
        download_config = RestClientConfig(
            timeout=120,
            max_retries=3,
            retry_backoff_factor=2.0,
            verify_ssl=True,
        )
        self._download_client = RestClient(config=download_config)

    def _get_token(self) -> str:
        """Acquire an app-only access token via MSAL client credentials flow."""
        if self._token:
            return self._token
        try:
            import msal
        except ImportError:
            msg = "msal package not found. Install with: pip install msal"
            raise ImportError(msg) from None
        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=f"{MICROSOFT_LOGIN_URL}/{self.tenant_id}",
            client_credential=self.client_secret,
        )
        result = app.acquire_token_for_client(scopes=[MICROSOFT_GRAPH_SCOPE])

        if not isinstance(result, dict):
            msg = f"Unexpected response type: {type(result).__name__}"
            raise TypeError(msg)

        access_token = result.get("access_token")
        if not access_token:
            msg = f"Failed to acquire Microsoft Graph token: {result.get('error')} - {result.get('error_description')}"
            raise ValueError(msg)

        self._token = access_token
        return access_token

    def _process_items(self, *, items: list[dict], files: list[dict]) -> list[str]:
        """Separate folders from files and return folder IDs to recurse into."""
        folder_ids = []
        for item in items:
            if "folder" in item:
                folder_ids.append(item["id"])
            else:
                files.append(item)
        return folder_ids

    def _list_files(self, folder_item_id: str | None = None) -> list[dict]:
        """Recursively list all files in the drive (or a specific folder)."""
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"}

        if folder_item_id:
            endpoint = f"/drives/{self.drive_id}/items/{folder_item_id}/children"
        else:
            endpoint = f"/drives/{self.drive_id}/root/children"

        files: list[dict] = []
        while endpoint:
            data = self._rest_client.call_rest_json(
                method=RestMethod.GET,
                url=endpoint,
                headers=headers,
            )

            folder_ids = self._process_items(items=data.get("value", []), files=files)
            if self.recursive:
                for folder_id in folder_ids:
                    files.extend(self._list_files(folder_item_id=folder_id))

            next_link = data.get("@odata.nextLink")
            endpoint = next_link.replace(MICROSOFT_GRAPH_API_BASE, "") if next_link else None  # type: ignore[assignment]

        return files

    def _download_file(self, item: dict) -> bytes:
        """Download file content from Graph API.

        Reuses ``self._download_client`` (created once in ``__init__``) instead of
        creating a new RestClient per file, which avoids a full HTTPS handshake
        overhead for every document.
        """
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        download_url = item.get("@microsoft.graph.downloadUrl")

        if not download_url:
            # Fallback: fetch via Graph API endpoint (follows redirect automatically)
            endpoint = f"/drives/{self.drive_id}/items/{item['id']}/content"
            response = self._rest_client.call_rest(
                method=RestMethod.GET,
                url=endpoint,
                headers=headers,
                expected_status_codes=[200, 302],  # 302 for redirects
            )
            return response.content

        # Direct download URL — reuse the shared client (no base_url needed)
        response = self._download_client.call_rest(
            method=RestMethod.GET,
            url=download_url,
        )
        return response.content

    def _download_item(self, item: dict) -> Document:
        """Download a single item and return a Document (used by thread pool)."""
        try:
            binary_content = self._download_file(item)
            metadata = {
                "source": item.get("name", ""),
                "drive_id": self.drive_id,
                "item_id": item.get("id", ""),
                "size": item.get("size", 0),
                "last_modified": item.get("lastModifiedDateTime", ""),
                "web_url": item.get("webUrl", ""),
                "mime_type": item.get("file", {}).get("mimeType", ""),
                "has_binary_content": True,
            }
            doc = Document(page_content="", metadata=metadata)
            doc._binary_content = binary_content  # type: ignore[attr-defined]
            return doc
        except Exception as e:
            logger.exception("Failed to download file %s: %s", item.get("name", ""), e)
            return Document(
                page_content="",
                metadata={
                    "source": item.get("name", ""),
                    "error": str(e),
                    "drive_id": self.drive_id,
                    "item_id": item.get("id", ""),
                },
            )

    def lazy_load(self) -> Iterator[Document]:
        """Lazily load documents from the Microsoft Graph API drive.

        Downloads are parallelized with a ThreadPoolExecutor so that
        ``max_download_workers`` files are fetched concurrently instead of one
        at a time, reducing total wall-clock time proportionally.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Resolve folder path to an item ID if specified
        folder_item_id = None
        if self.folder_path:
            token = self._get_token()
            headers = {"Authorization": f"Bearer {token}"}
            path = self.folder_path.strip("/")
            endpoint = f"/drives/{self.drive_id}/root:/{path}"

            try:
                data = self._rest_client.call_rest_json(
                    method=RestMethod.GET,
                    url=endpoint,
                    headers=headers,
                )
                folder_item_id = data.get("id")
            except Exception as e:
                msg = f"Folder path '{self.folder_path}' not found in drive '{self.drive_id}': {e!s}"
                raise ValueError(msg) from e

        files = self._list_files(folder_item_id=folder_item_id)

        # Download files in parallel — sequential downloads are the primary bottleneck
        # for SharePoint/OneDrive ingest when processing large libraries.
        with ThreadPoolExecutor(max_workers=self.max_download_workers) as pool:
            future_to_item = {pool.submit(self._download_item, item): item for item in files}
            for future in as_completed(future_to_item):
                yield future.result()

    def load(self) -> list[Document]:
        """Load."""
        return list(self.lazy_load())


# Configuration keys
PROVIDER_KEY: str = "provider"
PROVIDER_CONFIG_KEY: str = "provider_config"
MAX_FILES_KEY: str = "max_files"
MAX_FILES_DEFAULT_VALUE: int = 100
INCLUDE_FILTER_KEY: str = "include_filter"
EXCLUDE_FILTER_KEY: str = "exclude_filter"
ADAPTER_MANAGED_PROVIDERS: frozenset[str] = frozenset(
    {"s3", "ibm_cos", "sharepoint", "onedrive", "google_drive", "box_driver", "dropbox", "filesystem", "web"}
)

logger = get_logger()

# Import factory and adapters AFTER MicrosoftGraphLoader class definition to avoid circular imports
from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import (  # noqa: E402, I001
    SourceAdapterFactory,
)

# Import adapters to trigger registration via @register_source_adapter decorator
import docpipe.core.operators.ingest.adapters.outbound.sources  # noqa: E402, F401


class IngestSourceOperator(AbstractOperator):
    """
    Ingest operator for loading documents using LangChain loaders.

    This operator provides a unified interface for ingesting documents from various sources
    including S3, IBM COS, SharePoint, OneDrive, Google Drive, and custom loaders.

    Supports:
    - Multiple cloud storage providers (S3, IBM COS, Google Drive, OneDrive, SharePoint)
    - Custom loader integration via dynamic import
    - File filtering by extension (include/exclude)
    - File count limits
    - Incremental updates (skip previously processed files)
    - Proper metadata tracking and error handling
    """

    short_name: str = "ingest_source"
    category: OperatorCategory = OperatorCategory.Ingest
    owner = DocpipeConstants.OWNER_DOCPIPE

    def validate(self, *, errors: list[Any], warnings: list[str], available_features: list[str]) -> None:
        """
        Validate operator configuration including adapter-specific requirements.

        This method validates:
        1. Required features (via parent class)
        2. Provider-specific configuration (for adapter-managed providers)

        Args:
            errors: List to append validation errors
            warnings: List to append validation warnings
            available_features: List of available input features
        """
        # Call parent validation for required features
        super().validate(errors=errors, warnings=warnings, available_features=available_features)

        if not self.provider:
            errors.append(
                ValidationMessage(
                    message=ValidationCodeMessages.INGEST_PROVIDER_MISSING.value,
                    message_code=ValidationCodeMessages.INGEST_PROVIDER_MISSING.name,
                )
            )
            return

        # Validate adapter configuration for adapter-managed providers.
        # Skip when provider_config contains vault references — either still a
        # vault:// string (execution path) or already replaced with the
        # {"__vault_mock__": True} sentinel by the flow validator sanitizer.
        # In both cases the real values are unavailable here and will be
        # resolved at execution time.
        from docpipe.integrations.secrets.secret_provider import is_vault_reference

        provider_config_has_vault = any(
            is_vault_reference(v) for v in self.provider_config.values() if isinstance(v, str)
        ) or self.provider_config.get("__vault_mock__")
        if self.provider in ADAPTER_MANAGED_PROVIDERS and not provider_config_has_vault:
            try:
                # Attempt to build adapter config to trigger Pydantic validation
                # This will catch missing required fields like secret_key
                _, _ = self._build_adapter_config(self.provider)
            except Exception as e:
                # Extract meaningful error message from Pydantic validation errors
                error_msg = str(e)
                # Format Pydantic validation errors more clearly
                if "validation error" in error_msg.lower():
                    # Extract field-specific errors from Pydantic
                    errors.append(f"Configuration validation failed for provider '{self.provider}': {error_msg}")
                else:
                    errors.append(f"Invalid configuration for provider '{self.provider}': {error_msg}")

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the LangChain-based ingest operator.

        Expected parameters:
        - provider: The storage provider (s3, ibm_cos, sharepoint, onedrive, google_drive, custom)
        - provider_config: All provider-specific parameters including credentials
        - max_files: Maximum number of files to ingest
        - include_filter: Comma-separated list of file extensions to include
        - ignore_hidden_files: Skip files starting with '.' (default: True)
        - exclude_filter: Comma-separated list of file extensions to exclude
        - force_ingest: Force re-ingestion of previously processed documents
        """
        super().__init__(config)
        provider = config.get(PROVIDER_KEY)
        if provider is not None and not isinstance(provider, str):
            msg = "Provider must be a string."
            raise ValueError(msg)
        self.provider: str = provider.strip().lower() if provider is not None else ""
        self.max_files: int = config.get(MAX_FILES_KEY, MAX_FILES_DEFAULT_VALUE)
        self.provider_config: dict[str, Any] = dict(config.get(PROVIDER_CONFIG_KEY) or {})

        # Get supported extensions
        from docpipe.core.operators.operator_utils import get_supported_file_extensions

        supported_extensions_str = get_supported_file_extensions()
        self.supported_extensions: list[str] = [
            f".{ext}" if not ext.startswith(".") else ext for ext in supported_extensions_str.split(",")
        ]

        # Parse and validate included/excluded extensions
        self.included_extensions: list[str] | None = get_filter_extensions(config.get(INCLUDE_FILTER_KEY))
        self.excluded_extensions: list[str] | None = get_filter_extensions(config.get(EXCLUDE_FILTER_KEY))

        # Default to supported extensions if no include filter specified
        if self.included_extensions is None:
            self.included_extensions = self.supported_extensions

        self.force_ingest: bool = config.get(DocpipeConstants.FORCE_INGEST, False)
        self.doc_id_hash: str = config.get(
            OperatorConstants.Columns.DOC_ID_HASH, OperatorConstants.Columns.DOC_ID_HASH_DEFAULT
        )
        self.ignore_hidden_files: bool = config.get("ignore_hidden_files", True)
        self.common_log_arguments: dict[str, Any] = {
            DocpipeConstants.JOB_ID: self.job_id,
            DocpipeConstants.JOB_RUN_ID: self.job_run_id,
        }
        self.previously_processed_docs_dict: dict[str, Any] | None = None

        # Validate extensions
        self._validate_extensions()

        self.input_event: InputEvent | None = None
        input_event = config.get("input_event")
        if input_event is not None:
            self.input_event = InputEvent.model_validate(input_event)
            self.force_ingest = True

    def _validate_extensions(self) -> None:
        """
        Validate that included and excluded extensions are subsets of supported extensions.

        Raises:
            ValueError: If unsupported extensions are specified
        """
        # Validate included_extensions are subset of supported extensions
        if self.included_extensions:
            unsupported = set(self.included_extensions) - set(self.supported_extensions)
            if unsupported:
                msg = (
                    f"Unsupported file extensions in include_filter: {', '.join(sorted(unsupported))}. "
                    f"Supported extensions: {', '.join(sorted(self.supported_extensions))}"
                )
                raise ValueError(msg)

        # Validate excluded_extensions are subset of supported extensions
        if self.excluded_extensions:
            unsupported = set(self.excluded_extensions) - set(self.supported_extensions)
            if unsupported:
                msg = (
                    f"Unsupported file extensions in exclude_filter: {', '.join(sorted(unsupported))}. "
                    f"Supported extensions: {', '.join(sorted(self.supported_extensions))}"
                )
                raise ValueError(msg)

    def transform(self, table: pa.Table | None) -> tuple[list[pa.Table], dict[str, Any]]:
        """
        Operator-specific logic to load documents using LangChain loaders.

        Args:
            table: Input PyArrow table (can be None for initial ingestion)

        Returns:
            Tuple of (list of output tables, metadata dictionary)
        """

        if not self.provider:
            raise ValueError(ValidationCodeMessages.INGEST_PROVIDER_MISSING.value)

        incremental_service = get_incremental_update_service()
        job_id_for_tracking: str = self.context_id or self.job_id or ""

        self.previously_processed_docs_dict = (
            None if self.force_ingest else incremental_service.get_all_processed_docs(job_id=job_id_for_tracking)
        )

        # Initialize metadata
        metadata: dict[str, Any] = self.create_base_metadata(total_docs_count=0)

        # Process documents
        doc_data: list[dict[str, Any]] = self.process_documents(metadata)

        # Create output table
        output_table: pa.Table
        if doc_data:
            output_table = pa.Table.from_pylist(doc_data)
        else:
            # Create empty table with expected schema
            output_table = pa.Table.from_pydict(
                {
                    "id": [],
                    "name": [],
                    "document_format": [],
                    "metadata": [],
                    "source_id": [],
                    "path": [],
                    "modified_time": [],
                },
                schema=pa.schema(
                    [
                        ("id", pa.string()),
                        ("name", pa.string()),
                        ("document_format", pa.string()),
                        ("metadata", pa.string()),
                        ("source_id", pa.string()),
                        ("path", pa.string()),
                        ("modified_time", pa.int64()),
                    ]
                ),
            )

        # Update metadata
        metadata[Metrics.External.TOTAL_DOCS] = (
            len(doc_data) + metadata[Metrics.External.SKIPPED_DOCS_COUNT] + metadata[Metrics.External.FAILED_DOCS_COUNT]
        )
        metadata[Metrics.External.PROCESSED_DOCS] = len(doc_data)

        # Determine node status using common utility
        metadata[Metrics.External.NODE_STATUS] = OperatorUtils.determine_execution_status(
            processed_count=metadata[Metrics.External.PROCESSED_DOCS],
            failed_count=metadata[Metrics.External.FAILED_DOCS_COUNT],
            skipped_count=metadata[Metrics.External.SKIPPED_DOCS_COUNT],
        )

        return [output_table], metadata

    def _process_doc_batch(
        self,
        *,
        batch: list[Document],
        total_fetched: int,
        metadata: dict[str, Any],
        doc_data: list[dict[str, Any]],
        max_limit: int,
    ) -> int:
        """Process a batch of documents up to max_limit total processed docs."""
        processed_in_batch = 0
        current_total = len(doc_data)
        for idx, doc in enumerate(batch):
            if current_total >= max_limit:
                logger.info("Reached max files limit: %d", max_limit, extra=self.common_log_arguments)
                break
            global_idx = total_fetched - len(batch) + idx
            processed_doc = self.process_document(doc, global_idx, metadata)
            if processed_doc:
                doc_data.append(processed_doc)
                current_total += 1
                processed_in_batch += 1
        return processed_in_batch

    def _get_document_iterator(self) -> Iterator[Document]:
        """Get document iterator from loader, supporting lazy_load if available."""
        loader: BaseLoader = self._get_loader()
        if hasattr(loader, "lazy_load"):
            return cast(Iterator[Document], loader.lazy_load())
        return iter(loader.load())

    def process_documents(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Process documents from the configured LangChain loader or new adapter.

        Implements batch-fetch logic: fetches documents in batches of max_files,
        processes them, and continues fetching until max_files newly processed
        documents are reached or no more documents are available.

        For adapters: Uses async generator pattern for true memory efficiency,
        processing documents as they're yielded instead of loading all into memory.

        Args:
            metadata: Metadata dictionary for tracking

        Returns:
            List of document dictionaries
        """
        doc_data: list[dict[str, Any]] = []
        total_fetched = 0

        try:
            logger.info("Loading documents from %s", self.provider, extra=self.common_log_arguments)
            if SourceAdapterFactory.is_registered(self.provider):
                return self._process_documents_from_adapter(metadata)
            documents = self._get_document_iterator()

            while len(doc_data) < self.max_files:
                batch = list(itertools.islice(documents, self.max_files))
                if not batch:
                    logger.info(
                        "No more documents available. Total fetched: %d, processed: %d",
                        total_fetched,
                        len(doc_data),
                        extra=self.common_log_arguments,
                    )
                    break

                total_fetched += len(batch)
                logger.info(
                    "Fetched batch of %d documents (total fetched: %d)",
                    len(batch),
                    total_fetched,
                    extra=self.common_log_arguments,
                )
                self._process_doc_batch(
                    batch=batch,
                    total_fetched=total_fetched,
                    metadata=metadata,
                    doc_data=doc_data,
                    max_limit=self.max_files,
                )

            logger.info(
                "Fetched %d documents, processed %d new documents from %s",
                total_fetched,
                len(doc_data),
                self.provider,
                extra=self.common_log_arguments,
            )

        except Exception as e:
            logger.error("Error loading documents from %s: %s", self.provider, e, extra=self.common_log_arguments)
            self.record_failed_document(
                metadata=metadata,
                doc_id="loader_error",
                doc_name=self.provider,
                reason=f"Failed to load documents: {e!s}",
            )

        return doc_data

    @staticmethod
    def _domain_doc_to_langchain(domain_doc: Any) -> Document:
        """Convert a domain Document to a LangChain Document with metadata."""
        langchain_doc = Document(
            page_content="",
            metadata={
                "source": domain_doc.source_url,
                "name": domain_doc.name,
                "id": domain_doc.id,
                "last_modified": domain_doc.modified_time.isoformat() if domain_doc.modified_time else None,
                "size": domain_doc.size,
                "mimetype": domain_doc.mimetype,
                "extension": domain_doc.extension,
                "has_binary_content": True,
                **domain_doc.metadata,
            },
        )
        langchain_doc._binary_content = domain_doc.content  # type: ignore[attr-defined]
        return langchain_doc

    def _run_async_generator_in_sync_context(self, async_coro: Any) -> None:
        """Run an async coroutine safely in synchronous execution context."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(async_coro)
        else:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, async_coro)
                future.result()

    def _process_documents_from_adapter(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Process documents from adapter using async generator for memory efficiency.

        This method preserves the async generator pattern from adapters, processing
        documents as they're yielded instead of loading all into memory first.
        Implements batch-fetch logic with incremental processing support.

        Args:
            metadata: Metadata dictionary for tracking

        Returns:
            List of processed document dictionaries

        Raises:
            ValueError: If provider is not registered or configuration is invalid
        """
        adapter, config = self._build_adapter_config(self.provider)
        doc_data: list[dict[str, Any]] = []
        total_fetched = 0

        async def process_async_generator():
            nonlocal total_fetched
            batch: list[Document] = []

            async for domain_doc in adapter.fetch_documents(config):  # type: ignore[misc]
                batch.append(self._domain_doc_to_langchain(domain_doc))
                total_fetched += 1

                if len(batch) >= self.max_files:
                    logger.info(
                        "Fetched batch of %d documents (total fetched: %d)",
                        len(batch),
                        total_fetched,
                        extra=self.common_log_arguments,
                    )
                    self._process_doc_batch(
                        batch=batch,
                        total_fetched=total_fetched,
                        metadata=metadata,
                        doc_data=doc_data,
                        max_limit=self.max_files,
                    )
                    batch.clear()
                    if len(doc_data) >= self.max_files:
                        return

            if batch and len(doc_data) < self.max_files:
                logger.info(
                    "Fetched final batch of %d documents (total fetched: %d)",
                    len(batch),
                    total_fetched,
                    extra=self.common_log_arguments,
                )
                self._process_doc_batch(
                    batch=batch,
                    total_fetched=total_fetched,
                    metadata=metadata,
                    doc_data=doc_data,
                    max_limit=self.max_files,
                )

        self._run_async_generator_in_sync_context(process_async_generator())

        logger.info(
            "Fetched %d documents, processed %d new documents from %s",
            total_fetched,
            len(doc_data),
            self.provider,
            extra=self.common_log_arguments,
        )

        return doc_data

    def _build_adapter_config(self, provider: str):
        """
        Build provider-specific configuration from operator parameters.

        This method delegates configuration building to the appropriate adapter,
        following the Open/Closed Principle. Each adapter knows how to construct
        its own configuration from operator parameters.

        Args:
            provider: The provider name (e.g., "filesystem", "google_drive")

        Returns:
            Tuple of (adapter instance, provider-specific configuration object)

        Raises:
            ValueError: If provider is not supported or configuration is invalid
        """
        # Create adapter instance to access its config builder
        adapter = SourceAdapterFactory.create(provider)

        # Delegate configuration building to the adapter, passing the unified
        # provider_config dict.
        config = adapter.build_config_from_operator_params(
            provider_config=self.provider_config,
            included_extensions=self.included_extensions,
            max_files=self.max_files,
        )

        if self.input_event is not None:
            # Bind after environment resolution, then validate without rebuilding provider settings.
            event_config = config.model_dump()
            adapter.bind_file_reference(provider_config=event_config, file_reference=self.input_event.file_reference)
            config = type(config).model_validate(event_config)

        # Return both adapter and config to avoid creating adapter twice
        return adapter, config

    @staticmethod
    def _extract_file_extension(*, doc_metadata: dict[str, Any], doc_name: str) -> str:
        """Extract and normalize file extension from metadata or document name."""
        file_extension: str = doc_metadata.get("extension", "")
        if not file_extension:
            file_extension = pathlib.Path(doc_name).suffix.lower()
        if file_extension and not file_extension.startswith("."):
            file_extension = f".{file_extension}"
        return file_extension

    @staticmethod
    def _parse_modified_time(raw_time: int | float | str | None) -> int | float:
        """Preserve numeric timestamps for comparison, or parse an ISO string."""
        if isinstance(raw_time, (int, float)):
            return raw_time
        if isinstance(raw_time, str):
            try:
                from dateutil import parser

                return int(parser.parse(raw_time).timestamp())
            except Exception:
                return 0
        return 0

    def _should_skip_extension(self, *, file_extension: str, source: str, metadata: dict[str, Any]) -> bool:
        """Check if document should be skipped based on extension filters."""
        if self.excluded_extensions and file_extension in self.excluded_extensions:
            logger.info("Skipping document based on exclusion filter: %s", source, extra=self.common_log_arguments)
            self.record_skipped_document(
                metadata=metadata, doc_id=source, doc_name=source, reason="File extension in exclusion list"
            )
            return True

        if self.included_extensions and file_extension not in self.included_extensions:
            logger.info("Skipping document based on inclusion filter: %s", source, extra=self.common_log_arguments)
            self.record_skipped_document(
                metadata=metadata, doc_id=source, doc_name=source, reason="File extension not in inclusion list"
            )
            return True

        return False

    def process_document(self, doc: Document, idx: int, metadata: dict[str, Any]) -> dict[str, Any] | None:
        """
        Process a single LangChain document.

        Args:
            doc: LangChain Document object
            idx: Document index
            metadata: Metadata dictionary for tracking

        Returns:
            Processed document dictionary or None if skipped/failed
        """
        try:
            source: str = doc.metadata.get("source", f"unknown_{idx}")
            doc_name: str = doc.metadata.get("name", source)

            file_extension = self._extract_file_extension(doc_metadata=doc.metadata, doc_name=doc_name)
            if self._should_skip_extension(file_extension=file_extension, source=source, metadata=metadata):
                return None

            doc_id: str = hashlib.md5(source.encode(), usedforsecurity=False).hexdigest()
            modified_time = self._parse_modified_time(doc.metadata.get("last_modified", 0))

            if self.previously_processed_docs_dict and is_doc_previously_processed(
                previously_processed_docs_dict=self.previously_processed_docs_dict,
                doc_id=doc_id,
                modified_time=modified_time,
            ):
                logger.info("Skipping already processed document: %s", source, extra=self.common_log_arguments)
                self.record_skipped_document(
                    metadata=metadata, doc_id=doc_id, doc_name=source, reason="Document already processed"
                )
                return None

            document_format: str = file_extension if file_extension else doc.metadata.get("extension", "")
            source_id = doc.metadata.get("source_id", source)

            processed_doc: dict[str, Any] = {
                "id": doc_id,
                "name": doc_name,
                "document_format": document_format,
                "metadata": json.dumps(doc.metadata),
                "source_id": source_id,
                "path": source,
                "modified_time": modified_time if isinstance(modified_time, int) else 0,
            }

            logger.info(
                "Successfully processed document: %s (format: %s)",
                source,
                document_format,
                extra=self.common_log_arguments,
            )
            return processed_doc

        except Exception as e:
            logger.error("Error processing document %s: %s", idx, e, extra=self.common_log_arguments)
            self.record_failed_document(
                metadata=metadata,
                doc_id=str(idx),
                doc_name=doc.metadata.get("source", f"unknown_{idx}"),
                reason=f"Processing error: {e!s}",
            )
            return None

    # REMOVED: extract_content() method - binary loading now handled by downstream operators
    # REMOVED: _get_binary_content() method - no longer needed
    # REMOVED: _check_adapter_binary_content() method - no longer needed
    # REMOVED: _fallback_to_page_content() method - no longer needed
    # Note: Adapters still attach _binary_content to documents, but we don't extract it here.
    # The 'path' field in the output table allows downstream operators to load binary on-demand.

    def _is_hidden_path(self, key: str) -> bool:
        """Check if any path component is hidden (starts with .)."""
        path_parts: list[str] = key.split("/")
        return any(part.startswith(".") and part not in [".", ".."] for part in path_parts)

    def _get_loader(self) -> "BaseLoader":
        """
        Factory method to initialize the correct LangChain loader.

        Note: Providers using hexagonal architecture adapters (S3, SharePoint, OneDrive, Google Drive, Web)
        should not call this method. They are handled via _process_documents_from_adapter().
        """

        # 1. Amazon S3 / IBM COS (S3 Compatible), Microsoft SharePoint, OneDrive, Google Drive , Box & Web
        # These providers now use the hexagonal architecture adapter
        if self.provider in ADAPTER_MANAGED_PROVIDERS:
            msg = (
                f"{self.provider} provider should use _process_documents_from_adapter(). "
                "This provider is registered with SourceAdapterFactory and should be handled automatically."
            )
            raise ValueError(msg)

        # 2. Custom / FileNet / Other
        # This allows users to provide a python path to ANY loader class
        if self.provider == "custom":
            loader_path = self.provider_config.get("loader_class_path")
            if not loader_path:
                msg = "Provider is 'custom' but 'loader_class_path' is missing."
                raise ValueError(msg)

            # Dynamic Import: "my_package.loaders.FileNetLoader"
            module_name: str
            class_name: str
            module_name, class_name = loader_path.rsplit(".", 1)
            module: Any = importlib.import_module(module_name)
            loader_class: Any = getattr(module, class_name)

            # Initialize with all provider_config params
            init_kwargs: dict[str, Any] = dict(self.provider_config)
            return loader_class(**init_kwargs)

        msg = f"Provider '{self.provider}' is not supported."
        raise ValueError(msg)

    @staticmethod
    def _get_provider_schemas() -> dict[str, Any]:
        """Return provider-specific connection field schemas in docpipe metadata vocabulary."""
        from docpipe.core.operators.ingest.adapters.outbound.sources.box.config import BoxSourceConfig
        from docpipe.core.operators.ingest.adapters.outbound.sources.dropbox.config import DropboxSourceConfig
        from docpipe.core.operators.ingest.adapters.outbound.sources.filesystem.config import FilesystemSourceConfig
        from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.config import GoogleDriveSourceConfig
        from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.config import OneDriveSourceConfig
        from docpipe.core.operators.ingest.adapters.outbound.sources.s3.config import S3SourceConfig
        from docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.config import SharePointSourceConfig
        from docpipe.core.operators.ingest.adapters.outbound.sources.web.config import WebPageSourceConfig

        s3_schema = OperatorUtils.model_schema_to_docpipe(schema=S3SourceConfig.model_json_schema())
        return {
            "filesystem": OperatorUtils.model_schema_to_docpipe(schema=FilesystemSourceConfig.model_json_schema()),
            "s3": s3_schema,
            "ibm_cos": s3_schema,
            "google_drive": OperatorUtils.model_schema_to_docpipe(schema=GoogleDriveSourceConfig.model_json_schema()),
            "onedrive": OperatorUtils.model_schema_to_docpipe(schema=OneDriveSourceConfig.model_json_schema()),
            "sharepoint": OperatorUtils.model_schema_to_docpipe(schema=SharePointSourceConfig.model_json_schema()),
            "box_driver": OperatorUtils.model_schema_to_docpipe(schema=BoxSourceConfig.model_json_schema()),
            "dropbox": OperatorUtils.model_schema_to_docpipe(schema=DropboxSourceConfig.model_json_schema()),
            "web": OperatorUtils.model_schema_to_docpipe(schema=WebPageSourceConfig.model_json_schema()),
        }

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """
        Get metadata about the operator including features and attributes.

        Returns operator metadata for the LangChain loader ingest mode.
        """
        metadata_features: dict[str, dict[str, Any]] = {
            OperatorConstants.Columns.ID: {
                OperatorConstants.Columns.NAME: "Document ID",
                OperatorConstants.Config.DESCRIPTION: "Document identifier",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
            },
            OperatorConstants.Columns.NAME: {
                OperatorConstants.Columns.NAME: "Document Name",
                OperatorConstants.Config.DESCRIPTION: "The source name or file name of the document",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
            },
            "path": {
                OperatorConstants.Columns.NAME: "Source Path",
                OperatorConstants.Config.DESCRIPTION: "The source identifier (URL, file path, etc.) for the document",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: False,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
            },
            OperatorConstants.Metadata.DOCUMENT_FORMAT: {
                OperatorConstants.Columns.NAME: "Document Format",
                OperatorConstants.Config.DESCRIPTION: "File format/extension of the document (e.g., .pdf, .xlsx)",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: False,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
            },
            "metadata": {
                OperatorConstants.Columns.NAME: "Document Metadata",
                OperatorConstants.Config.DESCRIPTION: "JSON-serialized metadata from the source document",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: False,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
            },
            "source_id": {
                OperatorConstants.Columns.NAME: "Source ID",
                OperatorConstants.Config.DESCRIPTION: "The source identifier (file path, URL, etc.)",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: False,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
            },
            OperatorConstants.Metadata.MODIFIED_TIME: {
                OperatorConstants.Columns.NAME: "Modified Time",
                OperatorConstants.Config.DESCRIPTION: "Last modified timestamp of the source document (Unix epoch time)",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: False,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_INT64,
            },
            OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: {
                OperatorConstants.Columns.NAME: "Hash ID",
                OperatorConstants.Config.DESCRIPTION: "Hash ID of the document",
                OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                OperatorConstants.Misc.IS_PRIMARY: True,
                OperatorConstants.Misc.TAGS: [
                    OperatorConstants.Misc.MANDATORY,
                    OperatorConstants.Misc.PRIMARY,
                ],
            },
        }

        return {
            OperatorConstants.Misc.SDK: True,
            OperatorConstants.Misc.CATEGORY: IngestSourceOperator.category.value,
            OperatorConstants.Misc.LABEL: "Remote Source Ingest",
            OperatorConstants.Config.DESCRIPTION: "Ingest documents from remote storage sources (S3, IBM COS, SharePoint, OneDrive, Google Drive, Box, Dropbox, filesystem, web).",
            OperatorConstants.Config.FEATURES: metadata_features,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: IngestSourceOperator.is_available(),
            OperatorConstants.Config.ATTRIBUTES: {
                PROVIDER_KEY: {
                    OperatorConstants.Columns.NAME: "Provider",
                    OperatorConstants.Config.DESCRIPTION: "Storage provider (s3, ibm_cos, sharepoint, onedrive, google_drive, box_driver, dropbox, filesystem, web, custom)",
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    OperatorConstants.Config.VALID_VALUES: sorted(ADAPTER_MANAGED_PROVIDERS | {"custom"}),
                },
                PROVIDER_CONFIG_KEY: {
                    OperatorConstants.Columns.NAME: "Provider Configuration",
                    OperatorConstants.Config.DESCRIPTION: (
                        "All provider-specific parameters in a single dict, including connection details "
                        "and credentials."
                    ),
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Config.PROVIDERS: IngestSourceOperator._get_provider_schemas(),
                },
                MAX_FILES_KEY: {
                    OperatorConstants.Columns.NAME: "Max Files",
                    OperatorConstants.Config.DESCRIPTION: "Maximum number of files to ingest",
                    OperatorConstants.Config.DEFAULT: MAX_FILES_DEFAULT_VALUE,
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                INCLUDE_FILTER_KEY: {
                    OperatorConstants.Columns.NAME: "Include File Type",
                    OperatorConstants.Config.DESCRIPTION: "File types to be included (comma-separated extensions)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.LIST,
                },
                EXCLUDE_FILTER_KEY: {
                    OperatorConstants.Columns.NAME: "Exclude File Type",
                    OperatorConstants.Config.DESCRIPTION: "File types to be excluded (comma-separated extensions)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.LIST,
                },
                DocpipeConstants.FORCE_INGEST: {
                    OperatorConstants.Columns.NAME: "Force Ingest",
                    OperatorConstants.Config.DESCRIPTION: "Force re-ingestion of previously processed documents",
                    OperatorConstants.Config.DEFAULT: False,
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                },
                "ignore_hidden_files": {
                    OperatorConstants.Columns.NAME: "Ignore Hidden Files",
                    OperatorConstants.Config.DESCRIPTION: "Skip files starting with '.' (hidden files)",
                    OperatorConstants.Config.DEFAULT: True,
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                },
            },
        }
