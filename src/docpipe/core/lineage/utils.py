"""Utility functions and helpers for OpenLineage integration."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

_CREDENTIALS_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "password",
        "token",
        "auth_token",
        "access_token",
        "credentials",
        "connection_params",
    }
)


_UNKNOWN = "unknown"


class LineageUtils:
    """Utility class providing static helper methods for lineage data transformation and validation."""

    @staticmethod
    def now() -> str:
        """Return current timestamp in ISO-8601 format with UTC timezone."""
        return datetime.now(tz=UTC).isoformat()

    @staticmethod
    def is_valid_uuid(value: str) -> bool:
        """Check whether a string is a valid UUID."""
        try:
            uuid.UUID(value)
            return True
        except ValueError:
            return False

    @staticmethod
    def to_camel_case(snake: str) -> str:
        """Convert ``snake_case`` to ``camelCase`` for facet field names.

        Examples::

            "processed_docs"          -> "processedDocs"
            "docs_before_filter"      -> "docsBeforeFilter"
            "chunks_indexed_successfully" -> "chunksIndexedSuccessfully"
            "node_status"             -> "nodeStatus"
            "nrows"                   -> "nrows"   (single word, unchanged)
        """
        parts = snake.split("_")
        return parts[0] + "".join(word.capitalize() for word in parts[1:])

    @staticmethod
    def strip_credentials(flow_def: Any) -> Any:
        """Recursively remove credential keys from a flow definition dict or list."""
        if isinstance(flow_def, dict):
            return {
                k: LineageUtils.strip_credentials(v) for k, v in flow_def.items() if k.lower() not in _CREDENTIALS_KEYS
            }
        if isinstance(flow_def, list):
            return [LineageUtils.strip_credentials(item) for item in flow_def]
        return flow_def

    @staticmethod
    def node_run_id(*, job_run_id: str, node_id: str) -> str:
        """Derive a deterministic UUID for a node run from the job run ID and node ID."""
        return str(
            uuid.uuid5(
                uuid.UUID(job_run_id) if LineageUtils.is_valid_uuid(job_run_id) else uuid.NAMESPACE_URL,
                node_id,
            )
        )

    @staticmethod
    def resolve_flow_id(*, flow_id: str, flow_def: dict[str, Any]) -> str:
        """Use flow_id directly; fall back to SHA-256 of credentials-stripped flow_def."""
        if flow_id:
            return flow_id
        stripped = LineageUtils.strip_credentials(flow_def)
        return hashlib.sha256(json.dumps(stripped, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def get_dataset_info(*, dataset_type: str, config: dict[str, Any], role: str | None = None) -> tuple[str, str]:
        """Return the OpenLineage ``(namespace, name)`` for a dataset of ``dataset_type``.

        Delegates to :func:`docpipe.core.lineage.dataset_naming.get_dataset_info`, the single place that
        decides dataset identity for sources and sinks alike. ``config`` holds the adapter's own field
        names; ``role`` (``"source"`` or ``"destination"``) only affects the unknown-provider fallback.
        """
        from docpipe.core.lineage.dataset_naming import get_dataset_info

        return get_dataset_info(dataset_type=dataset_type, config=config, role=role)

    @staticmethod
    def _merged_provider_config(*, config: dict[str, Any]) -> dict[str, Any]:
        """Flatten an operator config for ``get_dataset_info``.

        ``provider_config`` wins over the legacy ``connection_params``, which wins over top-level keys.
        """
        from docpipe.core.constants.operator_constants import OperatorConstants

        return {
            **config,
            **(config.get(OperatorConstants.Config.CONNECTION_PARAMS) or {}),
            **(config.get(OperatorConstants.Config.PROVIDER_CONFIG) or {}),
        }

    @staticmethod
    def derive_dataset_info_from_ingest(*, ingest_operator: dict[str, Any]) -> tuple[str, str]:
        """Pick the ingest operator's provider and config and name the dataset with ``get_dataset_info``."""
        from docpipe.core.constants.operator_constants import OperatorConstants

        config = ingest_operator.get(OperatorConstants.Config.CONFIG) or {}
        return LineageUtils.get_dataset_info(
            dataset_type=config.get(OperatorConstants.Config.PROVIDER, _UNKNOWN),
            config=LineageUtils._merged_provider_config(config=config),
            role="source",
        )

    @staticmethod
    def derive_dataset_info_from_sink(*, operator_def: dict[str, Any]) -> tuple[str, str] | None:
        """Name the external dataset a sink operator writes, or None if the operator is not a sink.

        Only picks the dataset type and config out of the operator definition (a storage sink nests them
        under ``destination_config``); the naming itself is ``get_dataset_info``.
        """
        from docpipe.core.constants.constants import LineageConstants
        from docpipe.core.constants.operator_constants import OperatorConstants

        # Compiled DAG nodes carry the kind under "operator"; raw flow JSON uses "type". "operator" wins.
        operator_type = operator_def.get(OperatorConstants.Misc.OPERATOR) or operator_def.get("type", "")
        config = operator_def.get(OperatorConstants.Config.CONFIG) or {}
        provider = config.get(OperatorConstants.Config.PROVIDER)

        if operator_type in (OperatorConstants.Operators.VECTORDB, "vector_db", "VectorDBOperator") or provider in (
            LineageConstants.PROVIDER_OPENSEARCH,
            LineageConstants.PROVIDER_MILVUS,
            LineageConstants.PROVIDER_QDRANT,
            LineageConstants.PROVIDER_WEAVIATE,
            LineageConstants.PROVIDER_PINECONE,
            LineageConstants.PROVIDER_CHROMA,
        ):
            return LineageUtils.get_dataset_info(
                dataset_type=provider or LineageConstants.PROVIDER_OPENSEARCH,
                config=LineageUtils._merged_provider_config(config=config),
                role="destination",
            )

        if (
            operator_type in (OperatorConstants.Operators.STORAGE_OUTPUT, "storage", "StorageOutputOperator")
            or "destination_config" in config
        ):
            destination = config.get("destination_config") or {}
            return LineageUtils.get_dataset_info(
                dataset_type=destination.get(OperatorConstants.Config.PROVIDER, LineageConstants.PROVIDER_FILESYSTEM),
                config=LineageUtils._merged_provider_config(config=destination),
                role="destination",
            )

        if operator_type in (OperatorConstants.Operators.DOCUMENT_SET, "document_set_operator", "DocumentSetOperator"):
            return LineageUtils.get_dataset_info(dataset_type=OperatorConstants.Operators.DOCUMENT_SET, config=config)

        return None

    @staticmethod
    def derive_ingest_dataset_name(*, ingest_operator: dict[str, Any]) -> str:
        """Derive a human-readable dataset name from the ingest operator config.

        Produces names like ``tests/fixtures`` or ``my-bucket``
        so the lineage graph shows a meaningful source rather than a UUID.
        """
        _, name = LineageUtils.derive_dataset_info_from_ingest(ingest_operator=ingest_operator)
        return name
