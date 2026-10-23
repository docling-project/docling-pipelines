"""Utility functions and helpers shared across docpipe operators."""

import datetime
import hashlib
import importlib.util
import io
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

import pyarrow as pa
import pyarrow.compute as pc
import re2 as re
from charset_normalizer import from_bytes
from pyarrow import Table

from docpipe.core.constants.constants import (
    AttributeDataTypes,
    DocsStructure,
    ExecutionStatus,
    Metrics,
    internal_metrics,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.job_management import NodeStats
from docpipe.core.job_management.domain.utils import normalize_node_stats_for_dto
from docpipe.exceptions.docpipe_exceptions import (
    FlowExecutionFailedException,
    FlowValidationException,
    ValidationAlert,
)
from docpipe.exceptions.error_messages import ValidationCodeMessages, ValidationMessage
from docpipe.integrations.docling.converter_pool import get_docling_pool, options_fingerprint
from docpipe.utils.infrastructure.logging import get_logger

status_codes = {
    ExecutionStatus.FAILED: 1,
    ExecutionStatus.COMPLETED_WITH_ERRORS: 2,
    ExecutionStatus.COMPLETED_WITH_WARNINGS: 3,
    ExecutionStatus.CANCELED: 4,
    ExecutionStatus.CANCELING: 5,
    ExecutionStatus.PAUSED: 6,
    ExecutionStatus.RESUMING: 7,
    ExecutionStatus.RUNNING: 8,
    ExecutionStatus.STARTING: 9,
    ExecutionStatus.QUEUED: 10,
    ExecutionStatus.COMPLETED: 1000,
}

hash_functions = hashlib.sha3_512
logger = get_logger()

# ---------------------------------------------------------------------------
# DocumentConverter pooling
# ---------------------------------------------------------------------------
# DocumentConverter (docling-parse 7.x) is not thread-safe: calling .convert()
# concurrently from multiple threads on the same instance causes segfaults on
# macOS (arm64) and is unreliable on Linux. Converters are therefore leased
# *exclusively* from a process-wide, bounded pool (see
# ``docpipe.integrations.docling.converter_pool``), keyed by a hash of the actual
# format_options values so that different pipeline configs (e.g. standard vs
# OCR-disabled, or two OCR engines) never share a converter. Pooled converters
# survive across worker threads, micro-batches and operator instances, so Docling
# model pipelines are initialised once per configuration instead of once per
# worker thread per batch.
try:
    _DOCLING_AVAILABLE = importlib.util.find_spec("docling") is not None
except ValueError:
    _DOCLING_AVAILABLE = "docling" in sys.modules

# Pre-instantiate DocLangDocDeserializer at module import time under Python's import lock.
# DocLangDocDeserializer is stateless pure-Python/Pydantic code and completely thread-safe.
_DOCLANG_DESERIALIZER: Any | None = None
try:
    from docling_core.transforms.deserializer.doclang import DocLangDocDeserializer

    _DOCLANG_DESERIALIZER = DocLangDocDeserializer()
except ImportError:
    pass

_CONVERTER_POOL_KEY_PREFIX = "DocumentConverter:"


def _converter_cache_key(converter_config: dict | None) -> str:
    """Return a stable cache key for a given DocumentConverter configuration.

    The key is a SHA-256 digest of the *values* of every format option (pipeline
    class, backend, pipeline options including nested OCR/accelerator/table options),
    so two configurations that differ in any setting get different keys while equal
    settings built independently (e.g. by different operator instances) share one.

    Args:
        converter_config: Dict optionally containing ``format_options`` key.

    Returns:
        ``"default"`` when no format options are given, otherwise a hex digest that
        uniquely identifies the configuration.
    """
    if not converter_config or OperatorConstants.Config.FORMAT_OPTIONS not in converter_config:
        return "default"
    return options_fingerprint(converter_config[OperatorConstants.Config.FORMAT_OPTIONS])


def _build_converter(converter_config: dict | None) -> Any:
    """Construct a new DocumentConverter for ``converter_config``.

    Raises:
        RuntimeError: If docling is not installed.
    """
    if not _DOCLING_AVAILABLE:
        msg = "docling is not installed. Install with: pip install 'docling-pipelines-slim[extract]'"
        raise RuntimeError(msg)

    from docling.document_converter import DocumentConverter

    if converter_config and OperatorConstants.Config.FORMAT_OPTIONS in converter_config:
        return DocumentConverter(format_options=converter_config[OperatorConstants.Config.FORMAT_OPTIONS])
    return DocumentConverter()


@contextmanager
def _lease_converter(converter_config: dict | None) -> Iterator[Any]:
    """Borrow a DocumentConverter for ``converter_config`` exclusively.

    The converter comes from the process-wide pool and is returned to it when the
    block exits, so no two threads ever call ``convert()`` on the same instance and
    the converter (with its initialised model pipelines) is reused by later calls.

    Args:
        converter_config: Optional dict with ``format_options`` for the converter.

    Yields:
        A ``DocumentConverter`` instance owned by the caller for the block's duration.

    Raises:
        RuntimeError: If docling is not installed.
    """
    if not _DOCLING_AVAILABLE:
        msg = "docling is not installed. Install with: pip install 'docling-pipelines-slim[extract]'"
        raise RuntimeError(msg)

    key = _CONVERTER_POOL_KEY_PREFIX + _converter_cache_key(converter_config)
    with get_docling_pool().lease(key=key, factory=lambda: _build_converter(converter_config)) as converter:
        yield converter


@contextmanager
def _use_converter(*, converter: Any, converter_config: dict | None) -> Iterator[Any]:
    """Yield ``converter`` when given, otherwise lease a pooled one for ``converter_config``."""
    if converter is not None:
        yield converter
        return
    with _lease_converter(converter_config) as leased:
        yield leased


def sanitize_doc_id_for_filename(doc_id: str) -> str:
    """
    Sanitize a document ID to create a valid filename.

    This function replaces forward slashes with underscores to handle cases where
    doc_id contains full paths (e.g., from COS ingestion like "folder/subfolder/file.txt").

    Parameters
    ----------
    doc_id : str
        The document identifier to sanitize

    Returns
    -------
    str
        Sanitized document ID safe for use in filenames

    Examples
    --------
    >>> sanitize_doc_id_for_filename("folder/subfolder/file.txt")
    'folder_subfolder_file.txt'
    >>> sanitize_doc_id_for_filename("simple_doc_id")
    'simple_doc_id'
    """
    return doc_id.replace("/", "_")


def is_asr_available() -> bool:
    """Check if ASR (Automatic Speech Recognition) dependencies are available.
    Returns:
        True if ASR dependencies are installed, False otherwise
    """
    try:
        from docling.datamodel.asr_model_specs import AsrModelType  # noqa: F401
        from docling.document_converter import AudioFormatOption  # noqa: F401
        from docling.pipeline.asr_pipeline import AsrPipeline  # noqa: F401

        return True
    except ImportError:
        return False


def get_supported_file_extensions() -> str:
    """Get comma-separated list of supported file extensions based on available dependencies.
    Returns base document formats always, and adds audio/video formats only if ASR is available.
    Returns:
        Comma-separated string of file extensions (e.g., "pdf,docx,mp3,wav")
    """

    # Base extensions always supported
    supported_extensions: list[str] = OperatorConstants.FileExtensions.BASE_EXTENSIONS

    # Add audio/video extensions only if ASR is available
    if is_asr_available():
        supported_extensions.extend(OperatorConstants.FileExtensions.AUDIO_VIDEO_EXTENSIONS)

    # Strip leading dots before joining (constants have dots, but return format should not)
    return ",".join(ext.lstrip(".") for ext in supported_extensions)


def resolve_env_var(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if value.startswith("${") and value.endswith("}"):
        env_var_name = value[2:-1]
        # Check if it has a default value syntax: ${VAR:default} or ${VAR:-default}
        if ":" in env_var_name:
            parts = env_var_name.split(":", 1)
            env_var_name = parts[0]
            default_value = parts[1].lstrip("-")  # Remove optional '-' after colon
            return os.getenv(env_var_name, default_value)
        resolved = os.getenv(env_var_name)
        if resolved is None:
            msg = f"Environment variable {env_var_name} is not set"
            raise ValueError(msg)
        return resolved
    if value.startswith("$"):
        env_var_name = value[1:]
        resolved = os.getenv(env_var_name)
        if resolved is None:
            msg = f"Environment variable {env_var_name} is not set"
            raise ValueError(msg)
        return resolved
    if value.isupper() and "_" in value:
        resolved = os.getenv(value)
        if resolved is not None:
            return resolved
    return value


# Field names that indicate secret material — used by _to_docpipe() to auto-tag sensitive: true.
SENSITIVE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "password",
        "api_key",
        "jwt_token",
        "token",
        "access_key",
        "secret_key",
        "client_id",
        "client_secret",
        "tenant_id",
        "credentials",
        "credentials_json",
        "credentials_path",
        "token_path",
        "service_account_json_path",
    }
)


def format_failed_docs_summary(*, failed_docs: list) -> str:
    """Build a human-readable failure summary from a list of failed-doc dicts.

    Each entry is expected to have keys: id, name, reason (all optional).
    Returns a string like ``" Failures: [doc.pdf: reason; doc2.pdf: reason]"``
    or an empty string when *failed_docs* is empty.
    """
    if not failed_docs:
        return ""
    reasons = "; ".join(
        f"{d.get('name', d.get('id', 'unknown'))}: {d.get('reason', 'unknown error')}" for d in failed_docs
    )
    return f" Failures: [{reasons}]"


class OperatorUtils:
    @staticmethod
    def determine_execution_status(*, processed_count: int, failed_count: int, skipped_count: int) -> str:
        """Determine final execution status based on processing results.

        This is a common utility function used by operators to determine the appropriate
        execution status based on document processing outcomes.

        Args:
            processed_count: Number of successfully processed documents
            failed_count: Number of failed documents
            skipped_count: Number of skipped documents

        Returns:
            Execution status string (FAILED, COMPLETED_WITH_ERRORS, COMPLETED_WITH_WARNINGS, or COMPLETED)

        Examples:
            >>> OperatorUtils.determine_execution_status(processed_count=0, failed_count=2, skipped_count=0)
            'Failed'
            >>> OperatorUtils.determine_execution_status(processed_count=1, failed_count=1, skipped_count=0)
            'CompletedWithErrors'
            >>> OperatorUtils.determine_execution_status(processed_count=2, failed_count=0, skipped_count=0)
            'Completed'
        """
        if failed_count > 0 and processed_count == 0:
            return str(ExecutionStatus.FAILED.value)
        if failed_count > 0:
            return str(ExecutionStatus.COMPLETED_WITH_ERRORS.value)
        if skipped_count > 0:
            return str(ExecutionStatus.COMPLETED_WITH_WARNINGS.value)
        return str(ExecutionStatus.COMPLETED.value)

    @staticmethod
    def validate_columns(
        table: pa.Table | list[str],
        required: list[str],
        operator_name: str,
        error_messages: list[ValidationMessage] | None = None,
    ) -> None:
        """
        Check if required columns exist in the provided available features or table.

        :param required: List of required columns
        :param operator_name: Name of the operator for error reporting
        :param error_messages: (optional) List of error messages
        :return: None
        """
        if isinstance(table, pa.Table):
            table = table.schema.names

        missing_features: list[str] = []
        missing_operators: list[str] = []

        result = True
        for r in required:
            if r not in table:
                missing_features.append(r)
        if len(missing_features) > 0:
            result = False
        if not result:
            missing_operators.extend(get_missing_operator(missing_features))

            if isinstance(table, list):
                message = ValidationMessage.create(
                    message=ValidationCodeMessages.MISSING_FEATURES.value.format(
                        operator_name=operator_name,
                        missing_features=missing_features,
                        missing_operators=missing_operators,
                    ),
                    message_code=ValidationCodeMessages.MISSING_FEATURES.name,
                    missing_features=missing_features,
                    missing_operators=missing_operators,
                )
            else:
                message = ValidationMessage.create(
                    message=ValidationCodeMessages.MISSING_COLUMNS.value.format(
                        operator_name=operator_name,
                        missing_features=missing_features,
                        missing_operators=missing_operators,
                    ),
                    message_code=ValidationCodeMessages.MISSING_COLUMNS.name,
                    missing_features=missing_features,
                    missing_operators=missing_operators,
                )
            if error_messages is not None:
                error_messages.append(message)
            else:
                raise FlowExecutionFailedException(message.message or str(message))

    @staticmethod
    def merge_status(old_stat: ExecutionStatus, new_stat: ExecutionStatus) -> ExecutionStatus:
        """
        Merge two job statuses by returning the one with the lower numeric code
        (higher severity).
        """
        if status_codes[old_stat] < status_codes[new_stat]:
            return old_stat
        return new_stat

    @staticmethod
    def get_feature(
        name: str,
        description: str,
        type: str,
        available_for_filter: bool = False,
        available_for_vector_db: bool = False,
        mandatory_for_vector_db: bool = False,
    ) -> dict[str, Any]:
        """Build a feature descriptor dict from the given attributes.

        Args:
            name: Column name.
            description: Human-readable description.
            type: Data type string.
            available_for_filter: Whether the feature can be used as a filter.
            available_for_vector_db: Whether the feature can be stored in a vector DB.
            mandatory_for_vector_db: Whether the feature is mandatory in a vector DB.

        Returns:
            Dict containing the feature descriptor."""
        return {
            OperatorConstants.Misc.NAME: name,
            OperatorConstants.Config.DESCRIPTION: description,
            OperatorConstants.Misc.TYPE: type,
            OperatorConstants.Config.AVAILABLE_FOR_FILTER: available_for_filter,
            OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: available_for_vector_db,
            OperatorConstants.Config.MANDATORY_FOR_VECTOR_DB: mandatory_for_vector_db,
        }

    @staticmethod
    def find_skipped_docs(input_table: pa.Table, output_table: pa.Table, reason: str) -> dict[str, Any]:
        """
        Compares two PyArrow tables to find documents that are in the input but not
        in the output, and returns them in a structured format.

        Args:
            input_table: The PyArrow Table with the initial set of documents.
                         Must contain both the ID and Name columns.
            output_table: The PyArrow Table with the processed documents.
            reason: A string explaining why these documents were skipped.

        Returns:
            A dictionary containing:
            - 'skipped_docs': A list of DocsStructure dictionaries for skipped items.
            - 'skipped_docs_count': The integer count of skipped items.
        """
        # 1. Use PyArrow compute to find IDs not in output (vectorized operation)
        output_ids = output_table.column(OperatorConstants.Misc.ID)
        input_ids = input_table.column(OperatorConstants.Misc.ID)

        # 2. Create boolean mask for rows where input ID is NOT in output IDs
        mask = pc.invert(pc.is_in(input_ids, output_ids))  # type: ignore[attr-defined]

        # 3. Filter input table to get only skipped rows
        skipped_table = input_table.filter(mask)

        # 4. Build result using PyArrow arrays directly (no to_pylist conversion)
        skipped_docs_list: list[DocsStructure] = []
        if skipped_table.num_rows > 0:
            # Access PyArrow arrays directly
            skipped_ids_array = skipped_table.column(OperatorConstants.Misc.ID)
            skipped_names_array = skipped_table.column(OperatorConstants.Misc.NAME)
            skipped_paths_array = (
                skipped_table.column("path")
                if "path" in skipped_table.column_names
                else pa.array([""] * skipped_table.num_rows)
            )

            # Build the list of skipped docs using to_pylist() + zip (one C→Python boundary crossing per column)
            skipped_ids = skipped_ids_array.to_pylist()
            skipped_names = skipped_names_array.to_pylist()
            skipped_paths = skipped_paths_array.to_pylist()
            skipped_docs_list = [
                {
                    "id": doc_id,
                    "name": doc_name,
                    "reason": reason,
                    "document_url": str(doc_path or ""),
                }
                for doc_id, doc_name, doc_path in zip(skipped_ids, skipped_names, skipped_paths, strict=True)
            ]

        return {
            Metrics.External.SKIPPED_DOCS: skipped_docs_list,
            Metrics.External.SKIPPED_DOCS_COUNT: len(skipped_docs_list),
        }

    @staticmethod
    def get_aggregated_flow_logs(job_id: str, jobrun_id: str) -> dict[str, Any]:
        """
        Private method to retrieve operator logs based on the execution environment.

        Args:
            job_id: The ID of the job.
            jobrun_id: The ID of the specific job run.

        Returns:
            A dictionary containing the operator logs.
        """
        from docpipe.utils.operators.logging import get_log_and_job_file_path

        _log_final_path, _, _, aggregated_job_log_path = get_log_and_job_file_path(job_id=job_id, jobrun_id=jobrun_id)

        if Path(aggregated_job_log_path).exists():
            with Path(aggregated_job_log_path).open() as file:
                aggregated_flow_logs = json.load(file)
        else:
            return {"message": "Logs are not available.!"}

        # Normalize node_stats before returning
        if isinstance(aggregated_flow_logs, dict) and "job_stats" in aggregated_flow_logs:
            job_stats = aggregated_flow_logs["job_stats"]
            if isinstance(job_stats, dict):
                normalize_node_stats_for_dto(job_stats_data=job_stats)
        return dict(aggregated_flow_logs)

    @staticmethod
    def determine_final_job_status(*, node_stats_list: dict[str, Any]) -> ExecutionStatus:
        """Determines the most severe job status from a list of node statuses."""
        if not node_stats_list:
            return ExecutionStatus.STARTING

        min_code = min(
            status_codes.get(
                ExecutionStatus(node.node_status if isinstance(node, NodeStats) else node["node_status"]),
                1000,
            )
            for node in node_stats_list.values()
            if (isinstance(node, NodeStats) and node.node_status)
            or (isinstance(node, dict) and node.get("node_status"))
        )

        for status, code in status_codes.items():
            if code == min_code:
                return status

        return ExecutionStatus.COMPLETED

    @staticmethod
    def get_unique_ids(
        tables: pa.Table | list[pa.Table] | dict[str, pa.Table] | None,
        id_col: str = OperatorConstants.Misc.ID,
    ) -> list[Any]:
        """Return a deduplicated list of document IDs from one or more tables.

        Args:
            tables: A single table, a list of tables, or a dict of tables.
            id_col: Column name to read IDs from.

        Returns:
            Ordered list of unique IDs."""
        if not tables:  # empty list
            return []

        # wrap single table as list
        if isinstance(tables, pa.Table):
            tables = [tables]
        elif isinstance(tables, dict):
            tables = list(tables.values())

        seen = set()
        unique_ids = []
        for table in tables:
            if id_col in table.column_names:
                for val in table.column(id_col).to_pylist():
                    if val not in seen:
                        seen.add(val)
                        unique_ids.append(val)
        return unique_ids

    @staticmethod
    def epoch_ms_to_iso8601_utc(epoch_ms: int | None) -> str | None:
        """
        Convert epoch time in milliseconds to ISO8601 UTC string format.

        Args:
            epoch_ms: Epoch time in milliseconds

        Returns:
             ISO8601 formatted datetime string with 'Z' timezone indicator,or None if conversion fails
        """
        if not epoch_ms:
            return None
        try:
            dt = datetime.datetime.fromtimestamp(epoch_ms / 1000, tz=datetime.UTC)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, TypeError, OverflowError) as e:
            logger.error("Failed to convert epoch milliseconds to ISO8601: %s", e)
            return None

    @staticmethod
    def is_operator_present_in_flow(flow_definition: dict[str, Any], operator: str) -> bool:
        """
        Check if any operator in the flow definition is an ACL operator.

        Args:
            flow_definition: The flow definition dictionary.
        Returns:
            True if an ACL operator is present, False otherwise.
        """
        if not flow_definition or not isinstance(flow_definition, dict):
            return False

        return any(node.get("operator") == operator for node in flow_definition.get("dag", []))

    @staticmethod
    def remove_rows(*, table: pa.Table, remove_row_idx: list[int]) -> pa.Table:
        """
        Removes the rows for the given list of indexes in remove_row_idx from the table
        """
        remove_set = set(remove_row_idx)
        indices_to_keep = [i for i in range(table.num_rows) if i not in remove_set]
        return table.take(pa.array(indices_to_keep, type=pa.int64()))

    @staticmethod
    def remove_all_rows(*, table: pa.Table, remove_row_id: list[Any]) -> pa.Table:
        """
        Removes all the rows for the given list of ID from the table.

        Uses PyArrow compute for efficient vectorized filtering.
        """
        if not remove_row_id:
            return table

        # Use PyArrow compute for direct vectorized filtering (much faster than
        # converting to dict, looping, and calling remove_rows)
        id_col = table[OperatorConstants.Columns.ID]
        failed_ids_array = pa.array(remove_row_id, type=id_col.type)

        # Create mask: True for rows to keep (not in failed_ids)
        keep_mask = pc.invert(pc.is_in(id_col, failed_ids_array))  # type: ignore[attr-defined]
        return table.filter(keep_mask)

    @staticmethod
    def find_doc_count(*, table: pa.Table) -> int:
        """Return the number of unique documents in a table.

        Args:
            table: The PyArrow table to count.

        Returns:
            Count of unique document names, or row count if name column is absent."""
        if not table:
            return 0
        if table.num_rows == 0:
            return 0
        if OperatorConstants.Columns.NAME in table.column_names:
            return len(table[OperatorConstants.Columns.NAME].unique())

        return table.num_rows

    @staticmethod
    def find_doc_count_from_tables(*, tables: list[pa.Table]) -> int:
        """Return the number of unique documents across multiple tables.

        Args:
            tables: List of PyArrow tables.

        Returns:
            Count of unique document names across all tables."""
        doc_names: set[str] = set()
        for table in tables:
            if table.num_rows > 0:
                doc_names.update(table[OperatorConstants.Columns.NAME].unique())
        return len(doc_names)

    @staticmethod
    def validate_link_name(*, link_name: str, existing_link_names: set[str], errors: list[str]) -> None:
        """Validate a link name for uniqueness and presence.

        Args:
            link_name: The link name to validate.
            existing_link_names: Set of already-registered lowercased link names.
            errors: List to append error messages to."""
        if not link_name:
            errors.append("Missing link name. Please provide a link name.")
            return
        key = link_name.lower()
        if key in existing_link_names:
            errors.append(f"Duplicate link name found: '{link_name}'. Link names must be unique.")
        else:
            existing_link_names.add(key)

    @staticmethod
    def doc_id_hash(*, content: str) -> str:
        """
        Uses the content and adds a column with unique hash
        """
        hash_fn = hash_functions
        hashed_value = hash_fn(content.encode())

        return hashed_value.hexdigest()

    @staticmethod
    def decode_binary_content(*, binary_content: bytes) -> str:
        """
        Decodes binary content into a string using detected encoding or defaults to UTF-8.

        Args:
            binary_content (bytes): The binary data to decode.

        Returns:
            str: Decoded string, using detected encoding or UTF-8 with replacements on failure.
        """
        detected_encoding = from_bytes(binary_content).best()
        if detected_encoding and detected_encoding.encoding:
            return str(detected_encoding)
        # pragma: no cover
        # Fallback to a default encoding if detection failsF
        return binary_content.decode("utf-8", errors="replace")

    @staticmethod
    def upsert_fields_in_schema(*, schema: pa.Schema, updates: dict[str, pa.DataType]) -> pa.Schema:
        """
        Returns a new schema with updated or added fields:
        - If a field exists in the schema and is in `updates`, its type is replaced.
        - If a field does not exist and is in `updates`, it is added.
        """
        existing_field_names = set(schema.names)
        updated_fields = []

        for field in schema:
            if field.name in updates:
                updated_fields.append(pa.field(field.name, updates[field.name]))
            else:
                updated_fields.append(field)

        for name, dtype in updates.items():
            if name not in existing_field_names:
                updated_fields.append(pa.field(name, dtype))

        return pa.schema(updated_fields)

    @staticmethod
    def remove_internal_metrics_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        """Extract internal metrics from metadata, mutating the dict in-place.

        Args:
            metadata: The metadata dict to strip internal keys from.

        Returns:
            Dict containing only the extracted internal keys."""
        internal_metadata = {}
        for key, value in list(metadata.items()):
            if key in internal_metrics:
                internal_metadata[key] = value
                del metadata[key]
        return internal_metadata

    @staticmethod
    def drop_features_from_table(output_features_to_drop: list[str], table: Table) -> Table:
        """

        Parameters
        ----------
        output_features_to_drop
        table

        Returns
        -------

        """
        # Get existing column names
        existing_columns = set(table.schema.names)
        # Filter to only columns that actually exist
        valid_columns_to_drop = [col for col in output_features_to_drop if col in existing_columns]
        # Drop only valid columns
        if valid_columns_to_drop:
            return table.drop_columns(valid_columns_to_drop)
        return table  # Return original table if no valid columns to drop

    @staticmethod
    def rename_features_and_save_original(
        *, updated_features: list[dict[str, Any]] | None = None, input_features: dict[str, Any] | Table | None = None
    ) -> Any | None:
        """Rename features in a table or feature dict and preserve the original name.

        Args:
            updated_features: List of rename-mapping dicts with 'old_feature' and 'new_feature'.
            input_features: A PyArrow Table or a feature dict to rename.

        Returns:
            Renamed PyArrow Table if input was a Table; None otherwise."""
        if not input_features or not updated_features:
            return None

        existing_features: set[str] | dict[str, Any] = (
            set(input_features.schema.names) if isinstance(input_features, Table) else input_features
        )

        rename_map = OperatorUtils._build_rename_map(
            updated_features=updated_features, existing_features=existing_features
        )

        OperatorUtils._validate_existing_features(rename_map, existing_features)

        if isinstance(input_features, Table):
            return OperatorUtils._rename_table(input_features, rename_map)

        if isinstance(input_features, dict):
            OperatorUtils._validate_dict_mandatory(rename_map, input_features)
            OperatorUtils._apply_dict_rename(input_features, rename_map)

        return None

    @staticmethod
    def _build_rename_map(
        *, updated_features: list[dict[str, Any]] | None = None, existing_features: set[str] | dict[str, Any]
    ) -> dict[str, str]:
        """Build an old->new name mapping from the updated_features list.

        Args:
            updated_features: List of rename-mapping dicts.
            existing_features: The current set or dict of feature names.

        Returns:
            Dict mapping old feature names to new feature names."""
        rename_map: dict[str, str] = {}
        seen_old: set[str] = set()
        seen_new: set[str] = set()

        if updated_features is None:
            return rename_map

        for idx, upd in enumerate(updated_features):
            OperatorUtils._validate_feature(upd, idx)

            old_name, new_name = (
                upd[OperatorConstants.Misc.OLD_FEATURE],
                upd[OperatorConstants.Misc.NEW_FEATURE],
            )

            OperatorUtils._check_duplicate(
                old_name=old_name,
                new_name=new_name,
                idx=idx,
                seen_old=seen_old,
                seen_new=seen_new,
                input_features=existing_features,
            )

            seen_old.add(old_name)
            seen_new.add(new_name)
            rename_map[old_name] = new_name

        return rename_map

    @staticmethod
    def _validate_feature(upd: dict[str, Any], idx: int) -> None:
        """Validate a single rename-mapping dict entry.

        Args:
            upd: The mapping dict to validate.
            idx: Index of the entry (for error messages).

        Raises:
            ValueError: If the entry is malformed."""
        if not isinstance(upd, dict):
            OperatorUtils._raise_value_error(
                f"Each item in updated_features must be a dict. Item at index {idx} is {type(upd)}"
            )

        old_name = upd.get(OperatorConstants.Misc.OLD_FEATURE)
        new_name = upd.get(OperatorConstants.Misc.NEW_FEATURE)

        if old_name is None or new_name is None:
            error = f"Each mapping dict must contain 'old_feature' and 'new_feature'. Got: {upd}"
            OperatorUtils._raise_value_error(error)

        if not isinstance(old_name, str) or not isinstance(new_name, str):
            error = (
                f"Both old_feature and new_feature must be strings. "
                f"Got types: old_feature={type(old_name)}, new_feature={type(new_name)} in {upd}"
            )
            OperatorUtils._raise_value_error(error)

    @staticmethod
    def _check_duplicate(
        *,
        old_name: str,
        new_name: str,
        idx: int,
        seen_old: set[str],
        seen_new: set[str],
        input_features: Any,
    ) -> None:
        """Check for duplicate old or new feature names in a rename mapping.

        Args:
            old_name: The old feature name being mapped.
            new_name: The new feature name.
            idx: Index of the current entry.
            seen_old: Set of already-seen old names.
            seen_new: Set of already-seen new names.
            input_features: Existing features for collision detection.

        Raises:
            ValueError: If a duplicate is detected."""
        if old_name in seen_old:
            OperatorUtils._raise_value_error(f"Duplicate mapping for old_feature '{old_name}' at index {idx}")

        if new_name in seen_new or new_name in seen_old or new_name in input_features:
            OperatorUtils._raise_value_error(
                f"Duplicate name for new feature '{new_name}'. trying to rename same as first occurrence' or feature name already exists'{old_name}'"
            )

    @staticmethod
    def _validate_existing_features(rename_map: dict[str, str], existing_features: set[str] | dict[str, Any]) -> None:
        """Assert that all old feature names in the rename map exist in the current feature set.

        Args:
            rename_map: Old->new feature name mapping.
            existing_features: Current set or dict of feature names.

        Raises:
            KeyError: If any old name is absent."""
        feature_set = existing_features if isinstance(existing_features, set) else set(existing_features.keys())
        missing_old = [old for old in rename_map if old not in feature_set]
        if missing_old:
            error = f"Cannot rename non-existing column(s): {missing_old}"
            logger.error(error, stack_info=True, exc_info=True)
            raise KeyError(error)

    @staticmethod
    def _rename_table(input_table: Table, rename_map: dict[str, str]) -> Table:
        """Apply a rename map to a PyArrow table's column names.

        Args:
            input_table: The table to rename.
            rename_map: Old->new column name mapping.

        Returns:
            A new table with renamed columns.

        Raises:
            ValueError: If renaming would produce duplicate column names."""
        new_names_ordered = [rename_map.get(name, name) for name in input_table.schema.names]

        if len(new_names_ordered) != len(set(new_names_ordered)):
            dup = {name for name in new_names_ordered if new_names_ordered.count(name) > 1}
            msg = f"After rename new column names would have duplicates: {dup}"
            raise ValueError(msg)
        try:
            return input_table.rename_columns(new_names_ordered)
        except Exception as e:
            logger.exception(str(e), stack_info=True)
            raise

    @staticmethod
    def _validate_dict_mandatory(rename_map: dict[str, str], input_features: dict[str, Any]) -> None:
        """Raise if any feature being renamed is marked as mandatory.

        Args:
            rename_map: Old->new feature name mapping.
            input_features: Feature dict to inspect.

        Raises:
            FlowValidationException: If a mandatory feature is targeted for rename."""
        mandatory_features = OperatorUtils.get_mandatory_features(
            check_features=list(rename_map.keys()), input_features=input_features
        )
        if mandatory_features:
            raise FlowValidationException(
                message="Invalid rename attempted",
                errors=[
                    ValidationAlert(
                        message_code=ValidationCodeMessages.RENAMING_MANDATORY_FEATURES.name,
                        message=ValidationCodeMessages.RENAMING_MANDATORY_FEATURES.value.format(
                            mandatory_features=mandatory_features
                        ),
                    )
                ],
            )

    @staticmethod
    def _apply_dict_rename(input_features: dict[str, Any], rename_map: dict[str, str]) -> None:
        """Apply a rename map to a feature dict in-place, preserving the original name.

        Args:
            input_features: The feature dict to mutate.
            rename_map: Old->new feature name mapping."""
        for old_name, new_name in rename_map.items():
            feature = input_features.pop(old_name, None)

            if feature is None:
                continue

            if OperatorConstants.Misc.ORIGINAL_FEATURE not in feature:
                feature[OperatorConstants.Misc.ORIGINAL_FEATURE] = old_name

            input_features[new_name] = feature

    @staticmethod
    def get_mandatory_features(*, check_features: list[str], input_features: dict[str, Any]) -> list[str]:
        """Return the list of features that are marked as mandatory.

        Args:
            check_features: Feature names to check.
            input_features: Feature dict containing tag metadata.

        Returns:
            List of mandatory feature names among check_features."""
        if not check_features or not input_features:
            return []

        return [
            feature
            for feature, value in input_features.items()
            if feature in check_features
            and OperatorConstants.Misc.MANDATORY in value.get(OperatorConstants.Misc.TAGS, [])
        ]

    @staticmethod
    def _raise_value_error(msg: str) -> None:
        """Log an error and raise a ValueError.

        Args:
            msg: The error message to log and raise.

        Raises:
            ValueError: Always."""
        logger.error(msg, stack_info=True, exc_info=True)
        raise ValueError(msg)

    @staticmethod
    def validate_filter_criteria(*, criteria_list: Any, criteria_json: Any) -> tuple[bool, bool]:
        """
        Validates filter criteria for operators that use criteria_list and criteria_json.

        Args:
            criteria_list: List of filter criteria strings
            criteria_json: Dictionary of filter criteria in JSON format. Can be either:
                          - Group format: {'logical_operator': 'AND'|'OR', 'criteria_list': [...]}
                          - Leaf format: {'variable': 'col', 'operator': '=', 'value': 'x'}

        Returns:
            Tuple of (criteria_valid, json_valid)
            - criteria_valid: Whether criteria_list has valid non-empty content
            - json_valid: Whether criteria_json has valid content (leaf condition or non-empty group with valid criteria)
        """
        # Check if criteria_list has valid non-empty content
        criteria_valid = isinstance(criteria_list, list) and any(c and c.strip() for c in criteria_list)

        # Check if criteria_json has valid content
        json_valid = OperatorUtils._validate_criteria_json(criteria_json=criteria_json)

        return criteria_valid, json_valid

    @staticmethod
    def _validate_criteria_json(*, criteria_json: Any) -> bool:
        """
        Recursively validates criteria_json structure (matches runtime behavior).

        Args:
            criteria_json: Dictionary of filter criteria in JSON format

        Returns:
            bool: True if criteria_json is valid (leaf condition or group with ALL valid conditions/nested groups)
        """
        if not criteria_json or not isinstance(criteria_json, dict):
            return False

        # Check if it's a leaf condition (has 'variable' and 'operator')
        if "variable" in criteria_json and "operator" in criteria_json:
            return True

        # Check if it's a group with criteria_list
        if "criteria_list" in criteria_json:
            json_criteria_list = criteria_json.get("criteria_list", [])
            if not isinstance(json_criteria_list, list) or len(json_criteria_list) == 0:
                return False

            # ALL items must be valid (either leaf conditions or nested groups)
            # Recursively validate each item to match runtime behavior
            return all(
                isinstance(item, dict) and OperatorUtils._validate_criteria_json(criteria_json=item)
                for item in json_criteria_list
            )

        return False

    @staticmethod
    def _resolve_doc_id(*, table: pa.Table, row_idx: int) -> str:
        """Resolve the document identifier for a single row."""
        if OperatorConstants.Columns.ID in table.column_names:
            return table[OperatorConstants.Columns.ID][row_idx].as_py()
        if OperatorConstants.Columns.PATH in table.column_names:
            return table[OperatorConstants.Columns.PATH][row_idx].as_py()
        return f"doc_{row_idx}"

    @staticmethod
    def _build_doc_metadata(
        *, table: pa.Table, row_idx: int, doc_name: str, metadata_list: list[str | None]
    ) -> dict[str, Any]:
        """Build the document metadata dict used for on-demand binary content fetching."""
        doc_metadata: dict[str, Any] = {"name": doc_name}

        if OperatorConstants.Columns.PATH in table.column_names:
            doc_metadata["path"] = table[OperatorConstants.Columns.PATH][row_idx].as_py()
        if "source_id" in table.column_names:
            doc_metadata["source_id"] = table["source_id"][row_idx].as_py()
        if "source" in table.column_names:
            doc_metadata["source"] = table["source"][row_idx].as_py()

        metadata_str = metadata_list[row_idx]
        if metadata_str:
            try:
                metadata_dict = json.loads(metadata_str)
                if "item_id" in metadata_dict:
                    doc_metadata["item_id"] = metadata_dict["item_id"]
                if "drive_id" in metadata_dict:
                    doc_metadata["drive_id"] = metadata_dict["drive_id"]
            except (json.JSONDecodeError, TypeError):
                pass

        return doc_metadata

    @staticmethod
    def _prepare_single_document(
        *,
        table: pa.Table,
        row_idx: int,
        global_config: dict[str, Any],
        supported_extensions: set[str] | None,
        metadata_list: list[str | None],
    ) -> dict[str, Any]:
        """Prepare fetch task dict for a single table row."""
        doc_id = OperatorUtils._resolve_doc_id(table=table, row_idx=row_idx)
        doc_name = (
            table[OperatorConstants.Columns.NAME][row_idx].as_py()
            if OperatorConstants.Columns.NAME in table.column_names
            else f"document_{row_idx}"
        )

        if supported_extensions:
            file_ext = Path(doc_name).suffix.lower()
            if file_ext not in supported_extensions:
                return {
                    "idx": row_idx,
                    "doc_id": doc_id,
                    "doc_name": doc_name,
                    "error": f"Unsupported file extension: {file_ext}",
                    "skip_reason": "unsupported_extension",
                }

        if OperatorConstants.Columns.BINARY_CONTENT in table.column_names:
            binary_content = table[OperatorConstants.Columns.BINARY_CONTENT][row_idx].as_py()
        else:
            # Import here to avoid circular dependency
            from docpipe.utils.operators.binary_content_fetcher import get_binary_content

            doc_metadata = OperatorUtils._build_doc_metadata(
                table=table, row_idx=row_idx, doc_name=doc_name, metadata_list=metadata_list
            )
            binary_content = get_binary_content(doc_metadata=doc_metadata, global_config=global_config)
            if binary_content is None:
                msg = f"Failed to fetch binary content for document {doc_name}"
                raise ValueError(msg)

        return {"idx": row_idx, "doc_id": doc_id, "doc_name": doc_name, "binary_content": binary_content}

    @staticmethod
    def prepare_document_content_fetch(
        *, table: pa.Table, global_config: dict[str, Any] | None = None, supported_extensions: set[str] | None = None
    ) -> list[dict[str, Any]]:
        """
        Prepare to fetch document content from a PyArrow table row using on-demand fetching.

        This method resolves document content using an on-demand fetching strategy:
        - If global_config contains 'ingest_source': Fetches from cloud provider on-demand
        - Otherwise: Reads from local filesystem (existing behavior)
        - Fallback: Uses 'binary_content' column if present (for backward compatibility)

        The on-demand fetching approach allows operators to defer binary content fetching until
        it's actually needed, supporting both cloud sources and local files.

        Args:
            table: PyArrow table containing document data with columns:
                - path: File path or source identifier (primary input)
                - source_id: Cloud source identifier (for cloud sources)
                - binary_content: Pre-loaded binary content (optional, for backward compatibility)
                - id: Document identifier (optional)
                - name: Document name (optional)
            global_config: Global configuration that may contain ingest_source parameters
                for cloud provider access (optional)
            supported_extensions: Optional set of supported file extensions (e.g., {'.pdf', '.docx'}).
                If provided, documents with unsupported extensions will be marked with error and skip_reason.

        Returns:
            List of dicts with keys: idx, doc_id, doc_name, binary_content or error
            If supported_extensions is provided and extension is unsupported, dict will contain:
                - error: Error message describing unsupported extension
                - skip_reason: "unsupported_extension" flag

        Raises:
            ValueError: If binary content cannot be fetched from any source

        """
        global_config = global_config or {}

        metadata_list: list[str | None] = (
            table[OperatorConstants.Metadata.METADATA].to_pylist()
            if OperatorConstants.Metadata.METADATA in table.column_names
            else [None] * table.num_rows
        )

        doc_tasks = []
        for row_idx in range(table.num_rows):
            doc_name = (
                table[OperatorConstants.Columns.NAME][row_idx].as_py()
                if OperatorConstants.Columns.NAME in table.column_names
                else f"document_{row_idx}"
            )
            doc_id = OperatorUtils._resolve_doc_id(table=table, row_idx=row_idx)
            try:
                doc_tasks.append(
                    OperatorUtils._prepare_single_document(
                        table=table,
                        row_idx=row_idx,
                        global_config=global_config,
                        supported_extensions=supported_extensions,
                        metadata_list=metadata_list,
                    )
                )
            except Exception as e:
                logger.exception("Error preparing document '%s' at index %s: %s", doc_name, row_idx, str(e))
                doc_tasks.append({"idx": row_idx, "doc_id": doc_id, "doc_name": doc_name, "error": str(e)})
        return doc_tasks

    @staticmethod
    def _resolve_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
        """Flatten Pydantic JSON Schema ``$defs``/``$ref``/``anyOf`` pointer indirection.

        Inlines every ``$ref``, collapses ``anyOf: [<type>, {type: null}]`` nullable
        wrappers (preserving sibling keys such as ``default`` and ``description``),
        and drops the top-level ``$defs`` block.

        Args:
            schema: Raw dict from ``model_json_schema()``.

        Returns:
            Copy of the schema with all pointer indirection resolved.
        """
        defs = schema.get("$defs", {})

        def _resolve(node: Any) -> Any:
            if not isinstance(node, dict):
                return node
            if "$ref" in node:
                ref_name = node["$ref"].split("/")[-1]
                return _resolve(defs.get(ref_name, node))
            if "anyOf" in node:
                non_null = [b for b in node["anyOf"] if b != {"type": "null"}]
                if len(non_null) == 1:
                    branch = _resolve(non_null[0])
                    if isinstance(branch, dict):
                        # Sibling keys (default, description, title) win over branch keys.
                        merged = {k: v for k, v in node.items() if k != "anyOf"}
                        for k, v in branch.items():
                            if k not in merged:
                                merged[k] = v
                        return {k: _resolve(v) for k, v in merged.items()}
                # Note: anyOf with 2+ non-null branches (e.g. int | str union types) is not
                # collapsed — _to_docpipe will produce a node with no 'type' key in that case.
            return {k: _resolve(v) for k, v in node.items()}

        return _resolve({k: v for k, v in schema.items() if k != "$defs"})

    # Maps JSON Schema primitive types to docpipe AttributeDataTypes values.
    _JSON_TYPE_TO_DOCPIPE: ClassVar[dict[str, str]] = {
        "string": AttributeDataTypes.STRING,
        "integer": AttributeDataTypes.INTEGER,
        "number": AttributeDataTypes.DOUBLE,
        "boolean": AttributeDataTypes.BOOLEAN,
        "array": AttributeDataTypes.LIST,
        "object": AttributeDataTypes.JSON,
    }

    @staticmethod
    def model_schema_to_docpipe(
        *,
        schema: dict[str, Any],
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Convert ``model_json_schema()`` output to docpipe metadata vocabulary.

        Resolves ``$ref``/``anyOf`` pointer indirection then translates the result
        to the keys ``OperatorFeature`` and the UI expect (``name``, ``type``,
        ``description``, ``default``, ``properties``, ``required``, ``valid_values``).

        Use ``overrides`` to inject docpipe-only keys that Pydantic never produces
        (e.g. ``tags``, ``available_for_filter``, ``min_value``). The caller can
        also mutate individual fields inside the returned ``properties`` dict after
        the call — the result is a plain dict.

        Args:
            schema: Raw dict from ``model_json_schema()``.
            overrides: Docpipe-only keys merged onto the top-level result after
                translation. Override values win on conflict.

        Returns:
            Dict in docpipe metadata vocabulary ready for embedding inside a
            ``providers`` entry of an operator ``get_metadata()`` response.
        """
        resolved = OperatorUtils._resolve_schema_refs(schema)
        result = OperatorUtils._to_docpipe(node=resolved, required_fields=set(), field_key="")
        if overrides:
            result.update(overrides)
        return result

    @staticmethod
    def _to_docpipe(*, node: Any, required_fields: set[str], field_key: str = "") -> Any:
        """Recursively translate a resolved JSON Schema node to docpipe vocabulary.

        Args:
            node: Resolved JSON Schema dict (no ``$ref`` or ``anyOf`` remaining).
            required_fields: Field names (JSON Schema property keys) declared required
                by the parent object's JSON Schema ``required`` array.
            field_key: The JSON Schema property key for this node as it appears in the
                parent's ``properties`` dict. Used to check membership in
                ``required_fields`` — must be the raw key, not the Pydantic title.

        Returns:
            Translated dict, or the original value unchanged for non-dict nodes.
        """
        if not isinstance(node, dict):
            return node

        docpipe: dict[str, Any] = {}

        if "title" in node:
            docpipe[OperatorConstants.Misc.NAME] = node["title"]

        if "type" in node:
            docpipe[OperatorConstants.Misc.TYPE] = OperatorUtils._JSON_TYPE_TO_DOCPIPE.get(node["type"], node["type"])

        for key in (OperatorConstants.Config.DESCRIPTION, OperatorConstants.Config.DEFAULT):
            if key in node:
                docpipe[key] = node[key]

        # Forward JSON Schema numeric range constraints
        if "minimum" in node:
            docpipe[OperatorConstants.Filtering.MIN_VALUE] = node["minimum"]
        if "maximum" in node:
            docpipe[OperatorConstants.Filtering.MAX_VALUE] = node["maximum"]

        # JSON Schema stores required fields as an array on the parent object node.
        # The check must use field_key (the raw JSON Schema property key, e.g.
        # "index_name") — NOT the Pydantic title (e.g. "Index Name") stored in
        # docpipe[NAME] — because required_fields contains property keys.
        if field_key and field_key in required_fields:
            docpipe[OperatorConstants.Config.REQUIRED] = True

        # Sensitive field detection for secrets/credentials (Vault integration)
        if field_key and (
            field_key.lower() in SENSITIVE_FIELD_NAMES
            or node.get("sensitive") is True
            or (isinstance(node.get("json_schema_extra"), dict) and node["json_schema_extra"].get("sensitive") is True)
        ):
            docpipe[OperatorConstants.Config.SENSITIVE] = True

        if OperatorConstants.Config.PROPERTIES in node:
            child_required = set(node.get(OperatorConstants.Config.REQUIRED, []))
            docpipe[OperatorConstants.Config.PROPERTIES] = {
                k: OperatorUtils._to_docpipe(node=v, required_fields=child_required, field_key=k)
                for k, v in node[OperatorConstants.Config.PROPERTIES].items()
            }

        if "enum" in node:
            docpipe[OperatorConstants.Config.VALID_VALUES] = node["enum"]

        # allow_extra_keys is True unless the schema explicitly forbids extra properties
        # (Pydantic extra="forbid" → additionalProperties: false).
        # extra="ignore" produces no additionalProperties key at all, and extra="allow"
        # produces additionalProperties: true — both should permit unknown keys.
        if node.get("additionalProperties") is not False:
            docpipe[OperatorConstants.Config.ALLOW_EXTRA_KEYS] = True

        return docpipe

    @staticmethod
    def get_optimal_workers(is_cpu_intensive: bool = False) -> int:
        """
        Determine optimal number of workers based on system resources.
        Cross-platform compatible: Works on Linux, Windows, and macOS.
        Returns:
            Optimal number of workers
        """
        import platform

        cpu_count = os.cpu_count() or 4
        system = platform.system()

        # For I/O-bound tasks (document extraction), use more workers than CPU count
        # For CPU-bound tasks (template extraction with VLM), use CPU count
        if is_cpu_intensive:
            # Template extraction is more CPU-intensive (uses VLM models)
            optimal = max(1, cpu_count - 1)  # Leave one CPU free for system
        else:
            # Basic extraction is more I/O-bound (file reading, PDF parsing)
            optimal = min(cpu_count * 2, 16)  # Cap at 16 to avoid excessive threads

        logger.info("Auto-detected optimal workers: %s (CPU count: %s, OS: %s)", optimal, cpu_count, system)
        return optimal

    @staticmethod
    def detect_extension_from_bytes(binary_content: bytes) -> str:
        """
        Detect the file extension from the magic bytes of binary content.
        Used when the document name / path has no extension (e.g. a cloud URL).
        Returns a dotted extension string such as '.pdf', '.docx', or '' if unknown.
        """
        if not binary_content:
            return ""

        # PDF: %PDF
        if binary_content[:4] == b"%PDF":
            return ".pdf"

        # ZIP-based Office formats (docx, xlsx, pptx) and plain ZIP
        if binary_content[:2] == b"PK":
            return OperatorUtils.detect_extension_zip_based_office_formats(binary_content)

        # Legacy OLE2 Office formats (doc, xls, ppt)
        if binary_content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            return ".doc"

        # PNG
        if binary_content[:8] == b"\x89PNG\r\n\x1a\n":
            return ".png"

        # JPEG
        if binary_content[:3] == b"\xff\xd8\xff":
            return ".jpg"

        # GIF
        if binary_content[:6] in (b"GIF87a", b"GIF89a"):
            return ".gif"

        # TIFF
        if binary_content[:4] in (b"II*\x00", b"MM\x00*"):
            return ".tiff"

        # HTML
        content_start = binary_content[:512].lstrip()
        if content_start[:9].lower() == b"<!doctype" or content_start[:5].lower() == b"<html":
            return ".html"

        # Plain text / markdown fallback — try decoding as UTF-8
        try:
            binary_content[:512].decode("utf-8")
            return ".txt"
        except UnicodeDecodeError:
            pass

        return ""

    @staticmethod
    def detect_extension_zip_based_office_formats(binary_content: bytes) -> str:
        # Inspect the central directory for known Office content-type markers
        """Detect the Office format of a ZIP-based document from its bytes.

        Args:
            binary_content: The binary content to inspect.

        Returns:
            Dotted extension string: '.docx', '.xlsx', or '.pptx'."""
        content_sample = binary_content[:2048]
        if b"word/" in content_sample:
            return ".docx"
        if b"xl/" in content_sample:
            return ".xlsx"
        if b"ppt/" in content_sample:
            return ".pptx"
        return ".docx"  # generic ZIP-based Office fallback

    # ------------------------------------------------------------------
    # DocLang format helpers
    # ------------------------------------------------------------------

    @staticmethod
    def doclang_to_markdown(text: str) -> str:
        """Convert DocLang XML to Markdown using the docling-native deserializer.

        Passes *text* through ``DocLangDocDeserializer().deserialize_str()``
        and returns the result of ``export_to_markdown()``.

        Fallback behaviour (two levels):

        1. **Import unavailable** — ``docling_core`` is part of the extraction
           stack and is absent in slim installs without the ``[extract]`` extra.
           When the import fails an ``ImportError`` is caught and a simple regex
           tag strip is performed instead.  The result is plain text rather than
           structured Markdown, which is acceptable for rule-based operators
           (language detection, readability, quality scoring) but loses heading
           and table structure.

        2. **Deserialisation failure** — if ``docling_core`` is present but
           cannot parse the content (malformed XML), the same regex fallback is
           used.

        Returns the input unchanged when it is not XML at all (i.e. already
        Markdown or empty string).

        Args:
            text: Raw string that may be DocLang XML, Markdown, or empty.

        Returns:
            Markdown string with no XML tags, or the original string if the
            input was not XML.
        """
        if not text or not text.lstrip().startswith("<"):
            return text

        try:
            deserializer = OperatorUtils.get_doclang_deserializer()
            if deserializer is not None:
                return deserializer.deserialize_str(text).export_to_markdown()
            raise ImportError("docling_core is not available")
        except ImportError:
            logger.warning(
                "docling_core is not available (slim install without [extract]); "
                "falling back to regex tag strip for DocLang content"
            )
            return re.sub(r"<[^>]+>", "", text)
        except Exception as e:
            logger.warning("DocLang deserialisation failed: %s; falling back to regex tag strip", e)
            return re.sub(r"<[^>]+>", "", text)

    @staticmethod
    def get_doclang_deserializer() -> Any | None:
        """Get the module-level pre-instantiated DocLangDocDeserializer instance."""
        return _DOCLANG_DESERIALIZER

    @staticmethod
    def get_markdown_content_col(
        table: "pa.Table",
        *,
        col_name: str,
        doc_format: str,
    ) -> list[Any]:
        """Return the document content as a list of markdown strings.

        If ``content_markdown`` is present in *table*, its values are returned directly
        without allocating a new table or deserializing DocLang XML.
        Otherwise, if *doc_format* is ``"doclang"``, the column values are converted
        from DocLang XML to markdown via :meth:`doclang_to_markdown`.
        If *doc_format* is not ``"doclang"``, the column's raw values are returned as-is.

        Args:
            table: Input ``pa.Table``.
            col_name: Name of the content column.
            doc_format: Value of the ``doc_format`` config key.

        Returns:
            A list of document content strings in markdown/plain-text format.
        """
        markdown_col = OperatorConstants.Columns.CONTENT_MARKDOWN
        if markdown_col in table.column_names:
            return table[markdown_col].to_pylist()

        if doc_format == OperatorConstants.DocFormat.DOCLANG and col_name in table.column_names:
            return [OperatorUtils.doclang_to_markdown(v or "") for v in table[col_name].to_pylist()]

        if col_name in table.column_names:
            return table[col_name].to_pylist()

        return []

    @staticmethod
    def strip_doclang_column(
        table: "pa.Table",
        *,
        col_name: str,
        doc_format: str,
    ) -> "pa.Table":
        """Return *table* with the named column stripped of DocLang XML tags.

        A no-op when *doc_format* is not ``"doclang"`` or *col_name* is not
        present in *table*. If ``content_markdown`` is already present in *table*
        (e.g. from upstream extraction with Markdown in additional formats),
        its array is reused directly to avoid deserializing DocLang XML.
        Otherwise, every value in the column is passed through
        :meth:`doclang_to_markdown` and the column is replaced in-place.

        Operators that bulk-strip a content column before delegating to a base
        class transform should call this method instead of inlining the
        strip / ``set_column`` idiom.

        Args:
            table: Input ``pa.Table``.
            col_name: Name of the column to strip.
            doc_format: Value of the ``doc_format`` config key.

        Returns:
            The original table (unchanged object) when stripping is not needed,
            or a new table with the named column replaced by plain-text values.
        """
        import pyarrow as pa

        if doc_format != OperatorConstants.DocFormat.DOCLANG or col_name not in table.column_names:
            return table

        col_idx = table.schema.get_field_index(col_name)
        markdown_col = OperatorConstants.Columns.CONTENT_MARKDOWN
        if markdown_col in table.column_names and col_name != markdown_col:
            return table.set_column(col_idx, col_name, table[markdown_col])

        stripped = [OperatorUtils.doclang_to_markdown(v or "") for v in table[col_name].to_pylist()]
        return table.set_column(col_idx, col_name, pa.array(stripped))

    @staticmethod
    def restore_doclang_column(
        output_table: "pa.Table",
        *,
        original_table: "pa.Table",
        col_name: str,
        processing_table: "pa.Table",
    ) -> "pa.Table":
        """Restore the original column in *output_table* after DocLang stripping.

        After an operator runs its logic on a *processing_table* (a stripped copy
        produced by :meth:`strip_doclang_column`), the output table's content
        column contains plain Markdown.  This method puts the original DocLang
        column back so that downstream operators receive the content unchanged.

        A no-op when ``processing_table is original_table`` (i.e. no stripping
        was performed — :meth:`strip_doclang_column` returns the same object when
        the format is not doclang).

        Args:
            output_table: Table returned by the operator's processing logic.
            original_table: The unmodified input table passed to ``transform()``.
            col_name: Name of the content column to restore.
            processing_table: The stripped table that was passed to the processing
                logic (returned by :meth:`strip_doclang_column`).

        Returns:
            *output_table* with the named column replaced by values from
            *original_table*, or *output_table* unchanged if no stripping was done.
        """
        if processing_table is original_table or col_name not in output_table.column_names:
            return output_table
        col_idx = output_table.schema.get_field_index(col_name)
        return output_table.set_column(col_idx, col_name, original_table[col_name])

    @staticmethod
    def _export_docling_formats(
        *,
        doc: Any,
        additional_formats: list[str],
        file_path: str,
    ) -> dict[str, str | None]:
        """Export a DoclingDocument into the requested additional format columns.

        Args:
            doc: A DoclingDocument instance to export from.
            additional_formats: List of format names to generate.
                Supported: 'html', 'json', 'text', 'doctags', 'doclang'.
            file_path: File path used only for log messages.

        Returns:
            Dict mapping column names to their exported string values.
        """
        export_fns: dict[str, Any] = {
            OperatorConstants.Extraction.OUTPUT_FORMAT_MARKDOWN: doc.export_to_markdown,
            OperatorConstants.Extraction.OUTPUT_FORMAT_TEXT: doc.export_to_text,
            OperatorConstants.Extraction.OUTPUT_FORMAT_HTML: doc.export_to_html,
            OperatorConstants.Extraction.OUTPUT_FORMAT_JSON: lambda: json.dumps(doc.export_to_dict()),
            OperatorConstants.Extraction.OUTPUT_FORMAT_DOCTAGS: doc.export_to_doctags,
            OperatorConstants.Extraction.OUTPUT_FORMAT_DOCLANG: doc.export_to_doclang,
        }

        exported: dict[str, str | None] = {}
        for fmt in additional_formats:
            fmt_lower = fmt.lower()
            column_name = OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING.get(fmt_lower)
            if column_name is None:
                logger.warning("Unknown format '%s' requested for %s, skipping", fmt, file_path)
                continue
            try:
                exported[column_name] = export_fns[fmt_lower]()
                logger.info("Generated %s format for %s", fmt_lower, file_path)
            except Exception as fmt_err:
                logger.warning("Failed to generate %s format for %s: %s", fmt_lower, file_path, fmt_err)
                exported[column_name] = None
        return exported

    @staticmethod
    def extract_text_file(
        *,
        file_path: str,
        binary_content: bytes,
        additional_formats: list[str] | None = None,
        doc_format: str = OperatorConstants.DocFormat.MARKDOWN,
    ) -> dict[str, Any]:
        """
        Extract content from plain text files (.txt, .md).

        When additional_formats is provided, builds a minimal DoclingDocument
        from the raw text to generate the requested format columns using native export_to_*() methods.

        Args:
            file_path: Path to the text file
            binary_content: Binary content of the file
            additional_formats: Optional list of additional formats to populate
                beyond the mandatory markdown/content column.
                Supported: 'html', 'json', 'text', 'doctags', 'doclang'.

        Returns:
            Dictionary with extraction results
        """
        if additional_formats is None:
            additional_formats = []

        try:
            # Decode text content
            try:
                raw_text = binary_content.decode("utf-8")
            except UnicodeDecodeError:
                # Try other encodings if UTF-8 fails
                try:
                    raw_text = binary_content.decode("latin-1")
                except Exception as e:
                    logger.error("Failed to decode text file %s: %s", file_path, str(e))
                    return {
                        OperatorConstants.Extraction.SUCCESS: False,
                        OperatorConstants.Extraction.ERROR: f"Failed to decode text: {e!s}",
                        OperatorConstants.Columns.DOC_COLUMN_DEFAULT: None,
                    }

            is_doclang_primary = doc_format == OperatorConstants.DocFormat.DOCLANG
            primary_content = raw_text
            if is_doclang_primary:
                try:
                    from docling_core.types.doc import DoclingDocument
                    from docling_core.types.doc.labels import DocItemLabel

                    doc = DoclingDocument(name=Path(file_path).name)
                    doc.add_text(label=DocItemLabel.TEXT, text=raw_text)
                    primary_content = doc.export_to_doclang()
                except Exception as doc_err:
                    logger.warning("Failed to export text file %s to doclang: %s", file_path, doc_err)

            logger.info("Completed extraction for text file: %s", file_path)

            result: dict[str, Any] = {
                OperatorConstants.Extraction.SUCCESS: True,
                OperatorConstants.Columns.DOC_COLUMN_DEFAULT: primary_content,
                OperatorConstants.Metadata.METADATA: {
                    "char_count": len(primary_content),
                    "is_text_file": True,
                },
            }

            if additional_formats:
                from docling_core.types.doc import DoclingDocument
                from docling_core.types.doc.labels import DocItemLabel

                doc = DoclingDocument(name=Path(file_path).name)
                doc.add_text(label=DocItemLabel.TEXT, text=raw_text)
                result.update(
                    OperatorUtils._export_docling_formats(
                        doc=doc,
                        additional_formats=additional_formats,
                        file_path=file_path,
                    )
                )

            return result
        except Exception as e:
            logger.error("Error processing text file %s: %s", file_path, str(e))
            return {
                OperatorConstants.Extraction.SUCCESS: False,
                OperatorConstants.Extraction.ERROR: str(e),
                OperatorConstants.Columns.DOC_COLUMN_DEFAULT: None,
            }

    @staticmethod
    def extract_content(
        *,
        file_path: str,
        binary_content: bytes,
        converter_config: dict[str, Any] | None = None,
        additional_formats: list[str] | None = None,
        converter: Any = None,
        doc_format: str = OperatorConstants.DocFormat.MARKDOWN,
    ) -> dict[str, Any]:
        """
        Common method for document extraction using Docling's DocumentConverter.

        This method handles the complete extraction workflow:
        1. File extension detection
        2. Temporary file creation (for audio/video) or DocumentStream conversion
        3. Document conversion
        4. Primary format export (markdown or doclang based on doc_format) and additional format export

        Args:
            file_path: Path to the document file (used for logging and extension detection)
            binary_content: Binary content of the document
            converter_config: Optional configuration for DocumentConverter initialization.
                             If provided, should contain 'format_options' key with format-specific settings.
                             Example: {'format_options': {InputFormat.PDF: PdfFormatOption(...)}}
            additional_formats: Optional list of additional formats to generate beyond the primary format.
                               Options: 'html', 'json', 'text', 'doctags', 'doclang', 'markdown'.
                               Each format creates a separate column in the output.
            converter: Optional pre-built DocumentConverter instance. When provided,
                       ``converter_config`` is ignored and the supplied converter is used
                       directly; the caller is then responsible for never using it from
                       two threads at once. When omitted (the normal case) a converter
                       for ``converter_config`` is leased exclusively from the
                       process-wide pool and returned after the conversion.
            doc_format: Target format for the primary content column (default: "markdown").

        Returns:
            Dictionary containing:
                - success: True if extraction succeeded
                - content: Extracted primary content (doclang XML or markdown based on doc_format)
                - content_html: HTML format (if 'html' in additional_formats)
                - content_json: JSON format (if 'json' in additional_formats)
                - content_text: Plain text format (if 'text' in additional_formats)
                - content_doctags: DocTags format (if 'doctags' in additional_formats)
                - content_doclang: DocLang format (if 'doclang' in additional_formats and doc_format != 'doclang')
                - content_markdown: Markdown format (if 'markdown' in additional_formats and doc_format == 'doclang')
                - metadata: Extraction metadata (char_count, page_count, formats)
                - error: Error message if extraction failed
        """
        if additional_formats is None:
            additional_formats = []

        is_doclang_primary = doc_format == OperatorConstants.DocFormat.DOCLANG
        primary_format_name = (
            OperatorConstants.Extraction.OUTPUT_FORMAT_DOCLANG
            if is_doclang_primary
            else OperatorConstants.Extraction.OUTPUT_FORMAT_MARKDOWN
        )

        # Filter out the primary format if user mistakenly included it in additional_formats
        additional_formats = [fmt for fmt in additional_formats if fmt.lower() != primary_format_name]

        # Build complete format list for logging (primary + additional)
        all_formats = [primary_format_name, *additional_formats]
        logger.info("Processing file with Docling (formats: %s): %s", all_formats, file_path)

        try:
            from docling.datamodel.base_models import FormatToExtensions, InputFormat
            from docling_core.types.io import DocumentStream

            # Determine the effective file extension
            file_suffix = Path(file_path).suffix.lower()
            if not file_suffix:
                file_suffix = OperatorUtils.detect_extension_from_bytes(binary_content)

            # Handle .txt files specially (Docling cannot process them)
            if file_suffix in [OperatorConstants.FileExtensions.EXT_TXT]:
                return OperatorUtils.extract_text_file(
                    file_path=file_path,
                    binary_content=binary_content,
                    additional_formats=additional_formats,
                    doc_format=doc_format,
                )

            # Create DocumentStream from binary content (no temporary file needed)
            audio_video_suffixes = {f".{extension.lower()}" for extension in FormatToExtensions[InputFormat.AUDIO]}
            doc_name = Path(file_path).name if file_path else f"document{file_suffix}"

            # Use the supplied converter when provided; otherwise lease a pooled converter
            # for this config exclusively for the duration of the conversion only.
            with _use_converter(converter=converter, converter_config=converter_config) as active_converter:
                if file_suffix in audio_video_suffixes:
                    current_path_file = Path.cwd() / doc_name
                    try:
                        current_path_file.write_bytes(binary_content)
                        result = active_converter.convert(current_path_file)
                    finally:
                        if current_path_file.exists():
                            current_path_file.unlink()
                else:
                    # Create DocumentStream from binary content (no temporary file needed)
                    doc_stream = DocumentStream(name=doc_name, stream=io.BytesIO(binary_content))
                    # Convert document directly from stream
                    result = active_converter.convert(doc_stream)

            # Generate content in all requested formats
            content_dict: dict[str, str | None] = {}
            formats_generated = []
            formats_failed = []

            # Export primary format directly
            try:
                if is_doclang_primary:
                    content_dict[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = result.document.export_to_doclang()
                else:
                    content_dict[OperatorConstants.Columns.DOC_COLUMN_DEFAULT] = result.document.export_to_markdown()
                formats_generated.append(primary_format_name)
                logger.info("Generated %s format for %s", primary_format_name, file_path)
            except Exception as e:
                logger.error("Failed to generate primary %s format for %s: %s", primary_format_name, file_path, e)
                return {
                    OperatorConstants.Extraction.SUCCESS: False,
                    OperatorConstants.Extraction.ERROR: f"Failed to generate primary {primary_format_name} format: {e}",
                    OperatorConstants.Columns.DOC_COLUMN_DEFAULT: None,
                }

            if additional_formats:
                exported = OperatorUtils._export_docling_formats(
                    doc=result.document,
                    additional_formats=additional_formats,
                    file_path=file_path,
                )
                content_dict.update(exported)
                for fmt in additional_formats:
                    col = OperatorConstants.Extraction.FORMAT_COLUMN_MAPPING.get(fmt)
                    if col and exported.get(col) is not None:
                        formats_generated.append(fmt)
                    else:
                        formats_failed.append(fmt)

            # Get character count from primary content
            primary_content = content_dict.get(OperatorConstants.Columns.DOC_COLUMN_DEFAULT, "")
            char_count = len(primary_content) if primary_content else 0

            # Get native page count from Docling result
            native_page_count = len(result.document.pages) if hasattr(result.document, "pages") else 0

            logger.info("Completed extraction for %s (formats: %s)", file_path, formats_generated)

            return {
                OperatorConstants.Extraction.SUCCESS: True,
                **content_dict,  # Spread all format columns
                OperatorConstants.Metadata.METADATA: {
                    "char_count": char_count,
                    "page_count": native_page_count,
                    "output_formats_requested": all_formats,
                    "output_formats_generated": formats_generated,
                    "output_formats_failed": formats_failed,
                },
            }

        except Exception as e:
            # Extract file extension for error context
            file_suffix = Path(file_path).suffix.lower() if file_path else "unknown"
            error_msg = str(e)
            logger.error("Error extracting content from %s: %s", file_path, error_msg)
            return {
                OperatorConstants.Extraction.SUCCESS: False,
                OperatorConstants.Extraction.ERROR: f"Extraction failed for {file_suffix}: {error_msg}",
                OperatorConstants.Columns.DOC_COLUMN_DEFAULT: None,
            }


def get_missing_operator(features: list[str]) -> set[str]:
    from docpipe.core.operators.operator_metadata import OperatorMetadata

    operator_metadata = OperatorMetadata()
    feature_operators_map = operator_metadata.get_feature_operators_map()
    operator_list: set[str] = set()
    for feature in features:
        oplist: list[str] = feature_operators_map.get(feature, [])
        # Temporary change to omit Extract Json operator name from validation failure logs
        if "Extract Json" in oplist:
            oplist.remove("Extract Json")
        operator_list.update(oplist)
    return operator_list
