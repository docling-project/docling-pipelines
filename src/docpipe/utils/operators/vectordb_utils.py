"""Shared utilities for VectorDB adapters.

This module contains common functionality used across different VectorDB adapters
(OpenSearch, Milvus, etc.) to avoid code duplication and ensure consistent behavior.
"""

import hashlib
import json
from typing import Any, Generator

import pyarrow as pa

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


# "binary_vector" is accepted as an alias of the canonical TYPE_VECTOR_BINARY ("vector_binary").
_BINARY_VECTOR_TYPES: frozenset[str] = frozenset({OperatorConstants.Types.TYPE_VECTOR_BINARY, "binary_vector"})


def is_binary_vector_feature(*, feature_config: dict[str, Any]) -> bool:
    """Return True when a feature definition describes a packed-bit (binary) vector.

    This is the single source of truth for per-field binary classification. The feature's own
    type decides; index or metric configuration must never be used to infer it.

    Args:
        feature_config: Feature definition (as found in ``available_features``).

    Returns:
        True for ``type`` ``vector_binary`` / ``binary_vector`` or ``vector_type == "binary"``.
    """
    return (
        feature_config.get(OperatorConstants.Misc.TYPE) in _BINARY_VECTOR_TYPES
        or feature_config.get("vector_type") == "binary"
    )


def is_dense_or_binary_vector_feature(*, feature_config: dict[str, Any]) -> bool:
    """Return True for float (``vector``) or binary vector features."""
    return feature_config.get(OperatorConstants.Misc.TYPE) == OperatorConstants.Types.TYPE_VECTOR or (
        is_binary_vector_feature(feature_config=feature_config)
    )


def feature_mapping_lookup(
    mappings: list[dict[str, str]],
    feature_name: str,
    default: str | None = None,
) -> str | None:
    """Return the mapped_column_name for a given feature_name, or default if not found."""
    _fn = OperatorConstants.Misc.FEATURE_NAME
    _mc = OperatorConstants.Misc.MAPPED_COLUMN_NAME
    for entry in mappings:
        if entry.get(_fn) == feature_name:
            return entry.get(_mc, default)
    return default


def build_mapping_dict(mappings: list[dict[str, str]]) -> dict[str, str]:
    """Build a plain {feature_name: mapped_column_name} dict for O(1) repeated lookups.

    Use this at construction time when the same mapping list will be queried many times.
    """
    _fn = OperatorConstants.Misc.FEATURE_NAME
    _mc = OperatorConstants.Misc.MAPPED_COLUMN_NAME
    return {e[_fn]: e[_mc] for e in mappings if _fn in e and _mc in e}


def feature_mapping_items(
    mappings: list[dict[str, str]],
) -> Generator[tuple[str, str], None, None]:
    """Yield (feature_name, mapped_column_name) pairs from canonical list-of-dicts."""
    _fn = OperatorConstants.Misc.FEATURE_NAME
    _mc = OperatorConstants.Misc.MAPPED_COLUMN_NAME
    for e in mappings:
        if _fn in e and _mc in e:
            yield e[_fn], e[_mc]


def _json_size_default(obj: Any) -> int:
    """JSON ``default`` hook for size estimation: count raw bytes (binary vectors) by their length.

    Args:
        obj: Object the JSON encoder could not serialize.

    Returns:
        Length of the byte string.

    Raises:
        TypeError: The object is not bytes-like.
    """
    if isinstance(obj, (bytes, bytearray)):
        return len(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def calculate_batch_size_bytes(*, documents: list[dict[str, Any]]) -> int:
    """Calculate approximate size of documents in bytes.

    This utility function estimates the memory footprint of a batch of documents
    by serializing them to JSON and measuring the byte size. Used for batch
    size optimization across all VectorDB adapters.

    Args:
        documents: List of documents to measure

    Returns:
        Size in bytes, or 0 if calculation fails
    """
    try:
        return len(json.dumps(documents, default=_json_size_default).encode("utf-8"))
    except Exception:
        return 0


def detect_vector_dimension(*, table: pa.Table, embeddings_column: str) -> int | None:
    """
    Auto-detect vector dimension from the embeddings column in the PyArrow table.

    Handles both flat embeddings and nested (chunked) embeddings:
    - Flat float: [float1, float2, ..., floatN] -> dimension is length of list
    - Flat binary: bytes / bytearray -> dimension in bits is len(bytes) * 8
    - Nested float: [[emb1], [emb2], ...] -> dimension is length of first inner list
    - Nested binary: [b'...', b'...'] -> dimension in bits is len(b) * 8
    - Memmap files: Reads dimension from file metadata

    Args:
        table: PyArrow table containing embeddings
        embeddings_column: Name of the embeddings column

    Returns:
        Detected dimension or None if detection fails
    """
    if embeddings_column not in table.column_names:
        logger.debug("Embeddings column '%s' not found in table", embeddings_column)
        return None

    if table.num_rows == 0:
        logger.debug("Cannot detect dimension from empty table")
        return None

    try:
        from docpipe.core.constants.constants import DocpipeConstants

        embeddings_col: pa.ChunkedArray = table[embeddings_column]

        for idx in range(min(table.num_rows, 10)):  # Check first 10 rows
            embedding_value: Any = embeddings_col[idx].as_py()

            if embedding_value is None:
                continue

            # Handle raw bytes / bytearray for binary vector embeddings
            if isinstance(embedding_value, (bytes, bytearray)):
                bit_dim = len(embedding_value) * 8
                logger.info(
                    "Auto-detected binary vector dimension: %s bits (%s bytes)",
                    bit_dim,
                    len(embedding_value),
                )
                return bit_dim

            # Handle memmap file path references
            if isinstance(embedding_value, dict) and DocpipeConstants.EMBEDDINGS_MEMMAP_FILE in embedding_value:
                from docpipe.utils.core.memmap_file_utils import read_embedding_metadata

                embeddings_filepath = embedding_value[DocpipeConstants.EMBEDDINGS_MEMMAP_FILE]
                logger.debug("Reading dimension from memmap file metadata: %s", embeddings_filepath)

                # Get dimension directly from metadata
                dim = read_embedding_metadata(embeddings_filepath)
                logger.info("Auto-detected vector dimension: %s (from memmap file metadata)", dim)
                return dim

            if not isinstance(embedding_value, list):
                logger.warning("Embedding at row %s is not a list or bytes: %s", idx, type(embedding_value))
                continue

            if len(embedding_value) == 0:
                continue

            # Check if this is nested embeddings (chunked)
            if isinstance(embedding_value[0], list):
                # Nested structure: [[emb1], [emb2], ...]
                if len(embedding_value[0]) > 0:
                    nested_dimension: int = len(embedding_value[0])
                    logger.info("Auto-detected vector dimension: %s (from chunked embeddings)", nested_dimension)
                    return nested_dimension
            elif isinstance(embedding_value[0], (bytes, bytearray)):
                nested_bit_dim = len(embedding_value[0]) * 8
                logger.info(
                    "Auto-detected binary vector dimension: %s bits (%s bytes) (from chunked byte embeddings)",
                    nested_bit_dim,
                    len(embedding_value[0]),
                )
                return nested_bit_dim
            elif isinstance(embedding_value[0], (int, float)):
                # Flat structure: [float1, float2, ...]
                flat_dimension: int = len(embedding_value)
                logger.info("Auto-detected vector dimension: %s (from flat embeddings)", flat_dimension)
                return flat_dimension
            else:
                logger.warning(
                    "Unexpected embedding structure at row %s: first element is %s",
                    idx,
                    type(embedding_value[0]),
                )
                continue

        logger.warning("Could not find valid embeddings in first 10 rows for dimension detection")
        return None

    except Exception as e:
        logger.warning("Error detecting vector dimension: %s", e)
        return None


def detect_all_vector_dimensions(*, table: pa.Table, vector_columns: list[str]) -> dict[str, int]:
    """
    Detect dimensions for all specified vector columns in the table.

    Args:
        table: PyArrow table containing embeddings
        vector_columns: List of column names to detect dimensions for

    Returns:
        Dictionary mapping column names to their detected dimensions.
        Only includes columns where dimension was successfully detected.
    """
    dimension_mapping: dict[str, int] = {}

    for column_name in vector_columns:
        detected_dim = detect_vector_dimension(table=table, embeddings_column=column_name)
        if detected_dim is not None:
            dimension_mapping[column_name] = detected_dim
            logger.info("Detected dimension %s for column '%s'", detected_dim, column_name)
        else:
            logger.warning("Could not detect dimension for column '%s'", column_name)

    return dimension_mapping


def generate_composite_pk(*, file_id: str, chunk_content: str) -> str:
    """Generate a composite primary key from file identity and chunk content.

    The key is unique per file regardless of content, preventing collisions
    between different files with identical content.

    Args:
        file_id: The file identifier (e.g. file path from the id column).
                 Hashed to handle special characters and length constraints.
        chunk_content: The text content of the chunk. Hashed to produce a
                       stable, fixed-length content fingerprint.

    Returns:
        Composite PK string in the format ``{file_hash}_{content_hash}``
        where each hash is the full 128-character SHA3-512 hex digest
        -- unique per (file, chunk content) pair.
    """
    file_hash = hashlib.sha3_512(file_id.encode()).hexdigest()
    content_hash = hashlib.sha3_512(chunk_content.encode()).hexdigest()
    return f"{file_hash}_{content_hash}"


def generate_positional_pk(*, file_id: str, chunk_index: int) -> str:
    """Generate a positional primary key from file identity and chunk index.

    Decouples document identity from chunk content, allowing in-place upserts
    when chunk content changes. Used by the OpenSearch adapter.

    Args:
        file_id: The file identifier (e.g. file path from the id column).
                 Hashed to handle special characters and length constraints.
        chunk_index: Zero-based position of the chunk within the document.

    Returns:
        PK string in the format ``{file_hash}_chunk_{chunk_index}``
        -- stable across re-ingests regardless of content changes.
    """
    file_hash = hashlib.sha3_512(file_id.encode()).hexdigest()
    return f"{file_hash}_chunk_{chunk_index}"
