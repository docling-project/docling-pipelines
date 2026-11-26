# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""ACL Operator for extracting access control lists from documents.

This operator extracts ACL (Access Control List) information from documents
ingested by IngestSourceOperator. It uses provider-specific adapters to
retrieve effective permissions and adds an allowed_users column to the
PyArrow table.

The operator follows hexagonal architecture principles with:
- Domain models for ACL data structures
- Port interfaces for ACL extraction
- Adapter implementations for specific providers (SharePoint, S3, etc.)
- Factory pattern for adapter creation

Behavior:
- fail_on_error=true (default): All-or-nothing - fails completely if ANY file fails
- fail_on_error=false: Skips failed files (removes from output), continues processing
"""

import asyncio
import json
import time
from typing import Any

import pyarrow as pa

# Import adapters to trigger registration
import docpipe.core.operators.acl.adapters.outbound  # noqa: F401
from docpipe.core.constants.constants import (
    AttributeDataTypes,
    DocpipeConstants,
    ExecutionStatus,
    Metrics,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.acl.adapters.outbound.factories.acl_adapter_factory import (
    ACLAdapterFactory,
)
from docpipe.core.operators.acl.domain.models import ACLRequest, ACLResponse
from docpipe.core.operators.acl.ports.outbound.acl_extraction import ACLExtractionPort
from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.exceptions.docpipe_exceptions import (
    ConfigurationError,
    DocpipeException,
    FlowExecutionFailedException,
    FlowValidationException,
)
from docpipe.utils.data.transform import TransformUtils
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class ACLOperator(AbstractOperator):
    """Operator for extracting ACL information from documents.

    This operator processes documents from IngestSourceOperator and extracts
    effective access control lists using provider-specific adapters. It adds
    an allowed_users column containing a JSON array of user identities with
    access to each document.

    Behavior modes:
    - fail_on_error=true (default): All-or-nothing - fails completely if ANY document fails ACL extraction
    - fail_on_error=false: Skips failed documents (removes from output table), continues processing

    The operator supports:
    - Multiple providers (SharePoint, S3, Google Drive, etc.)
    - Statistics tracking (processed, failed, skipped documents)
    - Efficient batch processing

    Configuration:
        provider (required): Provider name (e.g., "sharepoint")
        provider_config (required): Provider-specific configuration dict
        credentials (required): Authentication credentials dict
        connection_params (required): Connection parameters dict
        fail_on_error (optional): Whether to fail on ANY error (default: true)

    Input:
        PyArrow table from IngestSourceOperator with columns:
        - id: Document identifier
        - name: Document name
        - source_id: Source-specific identifier
        - Other document metadata columns

    Output:
        Enhanced PyArrow table with additional column:
        - allowed_users: JSON array of user identities with access
        Note: If fail_on_error=false, failed documents are removed from output

    Example:
        {
            "operator": "acl",
            "config": {
                "provider": "sharepoint",
                "provider_config": {
                    "site_url": "https://contoso.sharepoint.com/sites/mysite"
                },
                "credentials": {
                    "client_id": "...",
                    "client_secret": "...",
                    "tenant_id": "..."
                },
                "connection_params": {
                    "timeout": 30,
                    "max_retries": 3
                },
                "fail_on_error": true
            }
        }
    """

    short_name: str = OperatorConstants.Operators.ACL_OPERATOR
    category: OperatorCategory = OperatorCategory.Extract
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the ACL Operator.

        Args:
            config: Configuration dictionary containing:
                - credentials: Authentication credentials for the provider
                  (``client_id``, ``client_secret``, ``tenant_id`` for SharePoint)
                - provider_config: Optional ACL-specific settings (optional)
                - fail_on_error: Whether to fail on ANY error (optional, default: true)

        Note:
            The provider name is read from the input PyArrow table metadata
            (from IngestSourceOperator) at runtime. Credentials are never read
            from document metadata.
        """
        super().__init__(config)

        # Operator's own credentials (never read from document metadata)
        self.credentials: Any = config.get(OperatorConstants.Config.CREDENTIALS, {})

        # Optional ACL-specific configuration
        self.provider_config: dict[str, Any] = config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})

        # Behavior configuration
        self.fail_on_error: bool = config.get(
            OperatorConstants.Config.FAIL_ON_ERROR, OperatorConstants.ACL.DEFAULT_FAIL_ON_ERROR
        )

        # Logging
        self.common_log_arguments: dict[str, Any] = {
            DocpipeConstants.JOB_ID: self.job_id,
            DocpipeConstants.JOB_RUN_ID: self.job_run_id,
        }

        logger.info(
            "Initialized ACLOperator with fail_on_error: %s",
            self.fail_on_error,
            extra=self.common_log_arguments,
        )

    @staticmethod
    def _required_credential_keys(*, provider: str) -> tuple[str, ...]:
        """Return the credential keys the given provider needs."""
        if provider == OperatorConstants.ACL.PROVIDER_SHAREPOINT:
            return ("client_id", "client_secret", "tenant_id")
        return ()

    def _resolve_credentials(self, *, provider: str) -> dict[str, Any]:
        """Build the credentials dict from the operator's own ``credentials`` config.

        Environment-variable references are expanded. Error messages name the
        offending keys only and never include credential values.

        Raises:
            FlowExecutionFailedException: If credentials are absent or incomplete
        """
        required = self._required_credential_keys(provider=provider)
        configured = self.credentials if isinstance(self.credentials, dict) else {}
        missing = [key for key in required if not configured.get(key)]
        if missing or (not required and not configured):
            raise FlowExecutionFailedException(
                f"ACL operator '{OperatorConstants.Config.CREDENTIALS}' config is missing required key(s) "
                f"for provider '{provider}': {', '.join(missing or ['credentials'])}. "
                "Set them in the ACL operator config; they are no longer read from document metadata."
            )

        resolved: dict[str, Any] = {}
        for key, value in configured.items():
            try:
                resolved[key] = resolve_env_var(value)
            except ValueError as e:
                raise FlowExecutionFailedException(
                    f"ACL operator credential '{key}' references an environment variable that is not set"
                ) from e
        return resolved

    def _extract_ingest_metadata(self, table: pa.Table) -> tuple[str, dict[str, Any], dict[str, Any]]:
        """Extract the provider from table metadata and credentials from operator config.

        Reads the first row's metadata column (JSON string from IngestSourceOperator)
        to extract the provider name. File paths from source_id are used directly
        for ACL lookups, so drive_id is not needed. Credentials come from this
        operator's own ``credentials`` config, not from document metadata.

        Args:
            table: Input PyArrow table from IngestSourceOperator

        Returns:
            Tuple of (provider, credentials, connection_params)

        Raises:
            FlowExecutionFailedException: If required metadata or credentials are missing
        """
        try:
            # Get first row's metadata column (JSON string)
            metadata_column = table.column(DocpipeConstants.METADATA).to_pylist()
            if not metadata_column:
                raise FlowExecutionFailedException(
                    "No metadata found in input table. ACL operator requires metadata from IngestSourceOperator."
                )

            first_doc_metadata_str = metadata_column[0]
            first_doc_metadata = (
                json.loads(first_doc_metadata_str)
                if isinstance(first_doc_metadata_str, str)
                else first_doc_metadata_str
            )

            # Extract provider from metadata
            provider = first_doc_metadata.get("provider", "")
            if not provider:
                raise FlowExecutionFailedException(
                    "Provider not found in metadata. IngestSourceOperator must include 'provider' field."
                )

            credentials = self._resolve_credentials(provider=provider)

            # Connection params can be empty - we'll use file paths from source_id directly
            connection_params: dict[str, Any] = {}

            logger.info(
                "Extracted provider from IngestSourceOperator metadata: provider=%s",
                provider,
                extra=self.common_log_arguments,
            )

            return provider, credentials, connection_params

        except json.JSONDecodeError as e:
            raise FlowExecutionFailedException(f"Failed to parse metadata JSON from input table: {e!s}") from e
        except KeyError as e:
            raise FlowExecutionFailedException(f"Required metadata column missing from input table: {e!s}") from e

    def _initialize_acl_adapter(
        self,
        *,
        provider: str,
        credentials: dict[str, Any],
        connection_params: dict[str, Any],
        provider_metadata: dict[str, Any],
    ) -> ACLExtractionPort:
        """Initialize the appropriate ACL adapter based on provider.

        Args:
            provider: Provider name (e.g., "sharepoint")
            credentials: Authentication credentials
            connection_params: Connection parameters
            provider_metadata: Provider-specific metadata

        Returns:
            The initialized ACL adapter for the configured provider

        Raises:
            FlowExecutionFailedException: If the provider is unsupported or initialization fails
        """
        try:
            adapter = ACLAdapterFactory.create_adapter(
                provider=provider,
                connection_params=connection_params,
                credentials=credentials,
                provider_metadata=provider_metadata,
            )

            logger.info(
                "Successfully initialized ACL adapter for provider: %s",
                provider,
                extra=self.common_log_arguments,
            )

            return adapter

        except ValueError as e:
            # Re-raise configuration errors as FlowExecutionFailedException
            raise FlowExecutionFailedException(
                f"Failed to initialize ACL adapter for provider '{provider}': {e!s}", status_code=400
            ) from e
        except (ConfigurationError, FlowValidationException, FlowExecutionFailedException, DocpipeException):
            # Re-raise Docpipe exceptions as-is
            raise
        except Exception as e:
            # Wrap unknown exceptions
            logger.exception("Unexpected error initializing ACL adapter: %s", e, extra=self.common_log_arguments)
            raise FlowExecutionFailedException(
                f"Failed to initialize ACL adapter for provider '{provider}': {e!s}"
            ) from e

    @staticmethod
    def get_required_features() -> list[str]:
        """Return list of required input features.

        Returns:
            List of required column names
        """
        return [OperatorConstants.Columns.PATH, OperatorConstants.Columns.SOURCE_ID]

    def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
        """Validate operator configuration.

        Note: The provider is extracted from input table metadata at runtime and credentials
        are checked when the operator runs, so neither is validated here.

        Args:
            errors: List to append validation errors
            warnings: List to append validation warnings
            available_features: List of available input features
        """
        super().validate(errors, warnings, available_features)

        # Validate provider_config if provided (optional ACL-specific settings)
        if self.should_validate_field(field_value=self.provider_config):
            if not isinstance(self.provider_config, dict):
                errors.append(
                    f"{OperatorConstants.Config.PROVIDER_CONFIG} must be a dict, got {type(self.provider_config)}"
                )

        # Validate fail_on_error
        if self.should_validate_field(field_value=self.fail_on_error):
            if not isinstance(self.fail_on_error, bool):
                errors.append(
                    f"{OperatorConstants.Config.FAIL_ON_ERROR} must be a boolean, got {type(self.fail_on_error)}"
                )

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Return operator metadata for UI and documentation.

        Returns:
            dict: Operator metadata including features and attributes
        """
        return {
            "secret_fields": [f"{OperatorConstants.Config.CREDENTIALS}.*"],
            OperatorConstants.Misc.SDK: True,
            OperatorConstants.Misc.CATEGORY: OperatorCategory.Extract.value,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: ACLOperator.is_available(),
            OperatorConstants.Misc.LABEL: "ACL Extraction",
            OperatorConstants.Config.DESCRIPTION: (
                "Extract access control lists (ACLs) from documents. "
                "Reads the provider from IngestSourceOperator metadata and authenticates with the "
                "credentials configured on this operator. "
                "Supports multiple providers (SharePoint, S3, Google Drive, etc.) "
                "and adds allowed_users column with effective permissions. "
                "Behavior: fail_on_error=true (default) fails on ANY error; "
                "fail_on_error=false skips failed files and continues."
            ),
            OperatorConstants.Config.FEATURES: {
                OperatorConstants.ACL.ALLOWED_USERS_COLUMN: {
                    OperatorConstants.Misc.NAME: "Allowed Users",
                    OperatorConstants.Config.DESCRIPTION: "JSON array of user identities with access to the document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: False,
                    OperatorConstants.Config.AVAILABLE_FOR_OPENSEARCH: True,
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                },
            },
            OperatorConstants.Config.ATTRIBUTES: {
                OperatorConstants.Config.CREDENTIALS: {
                    OperatorConstants.Misc.NAME: "Credentials",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Provider credentials (SharePoint: client_id, client_secret, tenant_id). "
                        "Never read from document metadata."
                    ),
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Config.SENSITIVE: True,
                },
                OperatorConstants.Config.PROVIDER_CONFIG: {
                    OperatorConstants.Misc.NAME: "Provider Configuration",
                    OperatorConstants.Config.DESCRIPTION: "Optional ACL-specific configuration parameters (e.g., resolve_inheritance, expand_groups)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                },
                OperatorConstants.Config.FAIL_ON_ERROR: {
                    OperatorConstants.Misc.NAME: "Fail on Error",
                    OperatorConstants.Config.DESCRIPTION: (
                        "If true (default), fails completely on ANY error. "
                        "If false, skips failed files (removes from output) and continues."
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.ACL.DEFAULT_FAIL_ON_ERROR,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                },
            },
        }

    def transform(self, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict[str, Any]]:
        """Transform the input table by adding ACL information.

        This method processes each document in the input table, extracts ACL
        information using the configured adapter, and adds an allowed_users
        column containing a JSON array of user identities.

        The provider is read from the first row's metadata column (populated by
        IngestSourceOperator); credentials come from this operator's own config.

        Uses batch processing with a single event loop for efficient concurrent
        ACL extraction across all documents.

        Behavior:
        - fail_on_error=true: Fails completely if ANY document fails ACL extraction
        - fail_on_error=false: Skips failed documents (removes from output table), continues

        Args:
            table: Input PyArrow table from IngestSourceOperator
            file_name: Optional file name (not used)

        Returns:
            Tuple of (list of output tables, metadata dict)

        Raises:
            FlowExecutionFailedException: If fail_on_error=true and ANY document fails
        """
        start_time = time.time()

        # Initialize metadata using base metadata structure
        metadata = self.create_base_metadata(total_docs_count=len(table))

        # Extract credentials and connection info from first row's metadata
        if not table:
            logger.warning("Empty table provided to ACL operator", extra=self.common_log_arguments)
            return [table], metadata

        # Extract provider and credentials from first document's metadata
        provider, credentials, connection_params = self._extract_ingest_metadata(table)

        logger.info(
            "Starting ACL extraction for %s documents using provider: %s, fail_on_error: %s",
            len(table),
            provider,
            self.fail_on_error,
            extra=self.common_log_arguments,
        )

        # Initialize ACL adapter with extracted credentials
        acl_adapter = self._initialize_acl_adapter(
            provider=provider,
            credentials=credentials,
            connection_params=connection_params,
            provider_metadata=self.provider_config,  # Use config for ACL-specific settings
        )

        # Extract document metadata from table
        doc_ids = table.column(OperatorConstants.Columns.ID).to_pylist()
        doc_names = table.column(OperatorConstants.Columns.PATH).to_pylist()
        source_ids = table.column(OperatorConstants.Columns.SOURCE_ID).to_pylist()
        metadata_column = table.column(OperatorConstants.Metadata.METADATA).to_pylist()

        # Step 1: Build ACL requests and track context
        acl_requests: list[ACLRequest] = []
        request_contexts: list[dict[str, Any]] = []

        for idx, (doc_id, doc_name, source_id, doc_metadata_str) in enumerate(
            zip(doc_ids, doc_names, source_ids, metadata_column, strict=True)
        ):
            # Check for missing metadata
            if not doc_id or not source_id:
                error_msg = f"Missing required metadata: {OperatorConstants.Columns.ID}={doc_id}, {OperatorConstants.Columns.SOURCE_ID}={source_id}"
                logger.error(
                    "Document at index %s missing required metadata",
                    idx,
                    extra=self.common_log_arguments,
                )

                if self.fail_on_error:
                    raise FlowExecutionFailedException(
                        f"ACL extraction failed: {error_msg}. Cannot extract ACLs without document identifiers."
                    )

                # Skip this document
                self.record_skipped_document(
                    metadata=metadata,
                    doc_id=str(doc_id) if doc_id else f"unknown_{idx}",
                    doc_name=str(doc_name) if doc_name else f"unknown_{idx}",
                    reason=error_msg,
                )
                continue

            # Parse document metadata from JSON string
            doc_metadata = {}
            if doc_metadata_str:
                try:
                    doc_metadata = json.loads(doc_metadata_str)
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to parse metadata for document %s, using empty dict",
                        doc_id,
                        extra=self.common_log_arguments,
                    )

            # Create ACL request with source_id as resource_path
            # The source_id contains the file path/URL that can be used directly
            # Pass document-specific metadata (contains item_id, document_library_id, etc.)
            acl_request = ACLRequest(
                resource_id=source_id,
                resource_path=source_id or "",  # Use source_id for path-based ACL lookup
                resource_type="file",
                provider=provider,
                provider_metadata=doc_metadata,  # Use document-specific metadata
                credentials=credentials,
                connection_params=connection_params,
                resolve_inheritance=True,
                expand_groups=True,
                normalize_identities=True,
            )

            acl_requests.append(acl_request)
            request_contexts.append(
                {
                    "idx": idx,
                    "doc_id": doc_id,
                    "doc_name": doc_name,
                }
            )

        # Step 2: Execute ONE async batch call for all requests
        if acl_requests:
            try:
                logger.info(
                    "Executing batch ACL extraction for %s documents",
                    len(acl_requests),
                    extra=self.common_log_arguments,
                )

                responses: list[ACLResponse] = asyncio.run(acl_adapter.extract_acls_batch(requests=acl_requests))

            except Exception as e:
                logger.exception("Batch ACL extraction failed: %s", e, extra=self.common_log_arguments)

                if self.fail_on_error:
                    raise FlowExecutionFailedException(f"Batch ACL extraction failed: {e!s}") from e

                # If fail_on_error=false, treat all as failed
                for context in request_contexts:
                    self.record_failed_document(
                        metadata=metadata,
                        doc_id=str(context["doc_id"]),
                        doc_name=str(context["doc_name"]),
                        reason=str(e),
                    )
                responses = []
        else:
            responses = []

        # Step 3: Process results synchronously
        successful_row_indices: list[int] = []
        allowed_users_list: list[list[str]] = []

        for context, acl_response in zip(request_contexts, responses, strict=False):
            idx = context["idx"]
            doc_id = context["doc_id"]
            doc_name = context["doc_name"]

            try:
                # Check if extraction succeeded
                if not acl_response.extraction_success:
                    error_msg = acl_response.extraction_error or "Unknown error"
                    logger.error(
                        "ACL extraction failed for document %s (%s): %s",
                        doc_id,
                        doc_name,
                        error_msg,
                        extra=self.common_log_arguments,
                    )

                    if self.fail_on_error:
                        raise FlowExecutionFailedException(
                            f"ACL extraction failed for document {doc_id} ({doc_name}): {error_msg}"
                        )

                    # Skip this document
                    self.record_failed_document(
                        metadata=metadata,
                        doc_id=str(doc_id),
                        doc_name=str(doc_name),
                        reason=error_msg,
                    )
                    continue

                # Convert allowed_users set to sorted list (not JSON string)
                # This allows OpenSearch to store it as a proper array field
                allowed_users_array = sorted(acl_response.allowed_users)
                allowed_users_list.append(allowed_users_array)
                successful_row_indices.append(idx)
                metadata[Metrics.External.PROCESSED_DOCS] += 1

                # Log warnings if any
                if acl_response.extraction_warnings:
                    for warning in acl_response.extraction_warnings:
                        logger.warning(
                            "ACL extraction warning for document %s: %s",
                            doc_id,
                            warning,
                            extra=self.common_log_arguments,
                        )

            except (FlowExecutionFailedException, FlowValidationException):
                # Re-raise flow exceptions as-is
                raise
            except DocpipeException as e:
                # Wrap other Docpipe exceptions with ACL context
                logger.exception(
                    "Docpipe exception processing document %s: %s",
                    doc_id,
                    e,
                    extra=self.common_log_arguments,
                )

                if self.fail_on_error:
                    raise FlowExecutionFailedException(f"ACL extraction failed for document {doc_id}: {e!s}") from e

                # Skip this document
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=str(doc_id),
                    doc_name=str(doc_name),
                    reason=str(e),
                )
            except Exception as e:
                # Wrap unknown exceptions
                logger.exception(
                    "Unexpected error processing document %s: %s",
                    doc_id,
                    e,
                    extra=self.common_log_arguments,
                )

                if self.fail_on_error:
                    raise FlowExecutionFailedException(f"ACL extraction failed for document {doc_id}: {e!s}") from e

                # Skip this document
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=str(doc_id),
                    doc_name=str(doc_name),
                    reason=str(e),
                )

        # Create output table with only successful rows
        try:
            if successful_row_indices:
                # Filter table to only successful rows
                filtered_table = table.take(successful_row_indices)

                # Add allowed_users column
                output_table = TransformUtils.add_column(
                    table=filtered_table,
                    name=OperatorConstants.ACL.ALLOWED_USERS_COLUMN,
                    content=allowed_users_list,
                )
            else:
                # No successful rows - create empty table with expected schema
                schema = table.schema.append(pa.field(OperatorConstants.ACL.ALLOWED_USERS_COLUMN, pa.string()))
                output_table = pa.Table.from_arrays([pa.array([], type=field.type) for field in schema], schema=schema)
        except Exception as e:
            logger.exception("Failed to create output table: %s", e, extra=self.common_log_arguments)
            raise FlowExecutionFailedException(
                f"Failed to create output table with {OperatorConstants.ACL.ALLOWED_USERS_COLUMN} column: {e!s}"
            ) from e

        # Calculate processing time
        processing_time = time.time() - start_time

        # Update node status based on failures
        if metadata[Metrics.External.FAILED_DOCS_COUNT] > 0:
            from docpipe.core.operators.operator_utils import OperatorUtils

            current_status = metadata[Metrics.External.NODE_STATUS]
            metadata[Metrics.External.NODE_STATUS] = OperatorUtils.merge_status(
                current_status if isinstance(current_status, ExecutionStatus) else ExecutionStatus(current_status),
                ExecutionStatus.COMPLETED_WITH_ERRORS,
            ).value
        elif metadata[Metrics.External.SKIPPED_DOCS_COUNT] > 0:
            from docpipe.core.operators.operator_utils import OperatorUtils

            current_status = metadata[Metrics.External.NODE_STATUS]
            metadata[Metrics.External.NODE_STATUS] = OperatorUtils.merge_status(
                current_status if isinstance(current_status, ExecutionStatus) else ExecutionStatus(current_status),
                ExecutionStatus.COMPLETED_WITH_WARNINGS,
            ).value

        # Log statistics
        logger.info(
            "ACL extraction completed: %s processed, %s failed, %s skipped in %.2f seconds",
            metadata[Metrics.External.PROCESSED_DOCS],
            metadata[Metrics.External.FAILED_DOCS_COUNT],
            metadata[Metrics.External.SKIPPED_DOCS_COUNT],
            processing_time,
            extra=self.common_log_arguments,
        )

        return [output_table], metadata
