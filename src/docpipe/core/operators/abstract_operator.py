# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Abstract base class and supporting types for all docpipe operators."""

from abc import ABCMeta
from enum import StrEnum
from typing import Any

import pyarrow as pa
from data_processing.transform import AbstractTableTransform

from docpipe.core.constants.constants import (
    DocpipeConstants,
    DocsStructure,
    ExecutionStatus,
    Metrics,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.models.session_info import get_session_info
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.types import FlowConfig, OperatorMetadata, OperatorOutputMetadata, TransformResult
from docpipe.utils.infrastructure import get_telemetry_service
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class OperatorCategory(StrEnum):
    """Enum of supported operator categories."""

    Extract = "Extract"
    Ingest = "Ingest"
    Functional = "Functional"
    Quality = "Quality"
    VectorDB = "VectorDB"
    Storage = "Storage"


class _ConfigResolvingMeta(ABCMeta):
    """Resolves the node's ``vault://`` references before any operator constructor runs.

    Subclass constructors call ``super().__init__(config)`` and then keep reading their
    own ``config`` argument, so a resolver call inside ``AbstractOperator.__init__`` alone
    could not hand them the resolved values. Resolving here, once, covers direct
    construction, the Python executor, and every custom operator (design D1). The
    executor resolves first; its result is marked so this pass makes no second request.
    """

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        from docpipe.integrations.secrets.node_config import prepare_operator_config

        if "config" in kwargs:
            kwargs["config"] = prepare_operator_config(operator_class=cls, config=kwargs["config"])
        elif args and isinstance(args[0], dict):
            args = (prepare_operator_config(operator_class=cls, config=args[0]), *args[1:])
        return super().__call__(*args, **kwargs)


class AbstractOperator(AbstractTableTransform, metaclass=_ConfigResolvingMeta):  # type: ignore[misc]
    """Base class for all docpipe operators.

    Extends ``AbstractTableTransform`` from data-prep-toolkit and enforces
    the docpipe operator contract: ``short_name``, ``category``, ``owner``,
    ``transform()``, and ``get_metadata()``."""

    short_name: str
    category: OperatorCategory
    owner: str | None = None  # None indicates custom operator; specific value (e.g., "docpipe") for built-ins

    def __init__(self, config: FlowConfig) -> None:
        super().__init__(config)
        session_info = get_session_info()
        self.name = config.get(OperatorConstants.Misc.NAME)
        self.id = config.get(OperatorConstants.Misc.ID)
        self.job_id = config.get(DocpipeConstants.JOB_ID, session_info.job_id)
        self.job_run_id = config.get(DocpipeConstants.JOB_RUN_ID, session_info.job_run_id)
        self.context_id = config.get(DocpipeConstants.CONTEXT_ID, self.job_id)
        self.output_features_to_drop = config.get(DocpipeConstants.OUTPUT_FEATURES_TO_DROP, [])
        self.updated_features = config.get(DocpipeConstants.UPDATED_FEATURES, [])
        self.validating_flow = config.get(DocpipeConstants.VALIDATING_FLOW, False)
        self.doc_column: str = config.get(
            OperatorConstants.Columns.DOC_COLUMN, OperatorConstants.Columns.DOC_COLUMN_DEFAULT
        )
        self.doc_format: str = config.get(OperatorConstants.DOC_FORMAT_KEY, OperatorConstants.DOC_FORMAT_DEFAULT)
        self.common_log_arguments = {
            DocpipeConstants.JOB_ID: self.job_id,
            DocpipeConstants.JOB_RUN_ID: self.job_run_id,
        }
        # Initialize telemetry service for operator tracing
        self._telemetry = get_telemetry_service()

    def _create_operator_span(self, *, operation_name: str | None = None) -> Any:
        """Create a telemetry span for operator execution.

        This method creates an OTEL span with operator metadata as attributes.
        Operators can use this to wrap their transform() method for automatic tracing.

        Args:
            operation_name: Optional custom operation name. Defaults to operator short_name.

        Returns:
            Span object if telemetry is enabled, None otherwise.

        Example:
            def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
                span = self._create_operator_span()
                try:
                    # Operator logic here
                    result = ...
                    return result
                except Exception as e:
                    self._telemetry.record_exception(e, span=span)
                    raise
                finally:
                    self._telemetry.end_span(span)
        """
        if not hasattr(self, "_telemetry"):
            return None

        operation = operation_name or self.short_name

        return self._telemetry.start_span(
            name=f"operator.{operation}",
            attributes={
                "operator.name": self.name,
                "operator.id": self.id,
                "operator.short_name": self.short_name,
                "operator.category": str(self.category),
                "job.id": self.job_id,
                "job_run.id": self.job_run_id,
            },
        )

    def _record_operator_metrics(
        self,
        *,
        span: Any,
        metadata: dict[str, Any] | None = None,
        duration_ms: float | None = None,
        success: bool = True,
    ) -> None:
        """Record operator execution metrics in the current span and as OTEL metrics.

        Args:
            span: The span to record metrics in
            metadata: Optional metadata dict containing execution metrics
            duration_ms: Execution duration in milliseconds for the metrics histogram
            success: Whether the operator execution succeeded
        """
        if not hasattr(self, "_telemetry"):
            return

        if span is not None and metadata:
            # Record document processing metrics as span attributes
            if Metrics.External.PROCESSED_DOCS in metadata:
                self._telemetry.set_span_attribute(
                    "operator.processed_docs",
                    metadata[Metrics.External.PROCESSED_DOCS],
                    span=span,
                )
            if Metrics.External.FAILED_DOCS_COUNT in metadata:
                self._telemetry.set_span_attribute(
                    "operator.failed_docs",
                    metadata[Metrics.External.FAILED_DOCS_COUNT],
                    span=span,
                )
            if Metrics.External.SKIPPED_DOCS_COUNT in metadata:
                self._telemetry.set_span_attribute(
                    "operator.skipped_docs",
                    metadata[Metrics.External.SKIPPED_DOCS_COUNT],
                    span=span,
                )
            if Metrics.External.TOTAL_DOCS in metadata:
                self._telemetry.set_span_attribute(
                    "operator.total_docs",
                    metadata[Metrics.External.TOTAL_DOCS],
                    span=span,
                )
            if Metrics.External.NODE_STATUS in metadata:
                self._telemetry.set_span_attribute(
                    "operator.status",
                    metadata[Metrics.External.NODE_STATUS],
                    span=span,
                )

        # Record OTEL metrics if duration is provided
        if duration_ms is not None:
            self._telemetry.record_operator_execution(
                operator_name=self.short_name,
                category=str(self.category),
                duration_ms=duration_ms,
                success=success,
            )

    def transform(self, table: pa.Table) -> TransformResult:
        """Transform the input table and return output tables with execution metadata.

        Subclasses must implement this method. The return tuple is
        (list[pa.Table], OperatorOutputMetadata).
        """
        raise NotImplementedError

    @staticmethod
    def is_available() -> bool:
        """Return True if the operator's optional dependencies are satisfied.

        Returns:
            True by default; subclasses override for optional-dep checks."""
        return True

    def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
        # The concrete subclasses validates the parameters passed to the operators from the flow definition
        """Validate operator configuration against available pipeline features.

        Args:
            errors: List to append validation error messages to.
            warnings: List to append validation warning messages to.
            available_features: Feature names produced by upstream operators."""
        OperatorUtils.validate_columns(available_features, self.get_required_features(), self.short_name, errors)

    @staticmethod
    def get_required_features() -> list[str]:
        # The concrete subclasses will retrieve the required features.
        """Return the list of upstream feature columns required by this operator.

        Returns:
            Empty list by default; subclasses override as needed."""
        return []

    @staticmethod
    def get_static_required_features() -> list[str]:
        # Static companion to get_required_features() for operator discovery without instantiation.
        """Return required features without instantiating the operator.

        Used for operator discovery and flow validation before runtime.

        Returns:
            Empty list by default."""
        return []

    @staticmethod
    def get_metadata() -> OperatorMetadata:
        # Returns operator metadata including owner
        """Return operator metadata for registry and UI rendering.

        Returns:
            Dict containing at minimum 'short_name', 'description', and 'owner'.
            ``secret_fields`` lists the dotted config keys that may hold a
            ``vault://`` reference; an operator that declares none accepts no
            references (see ``docpipe.core.operators.secret_fields``)."""
        return {"secret_fields": []}

    def should_validate_field(self, *, field_value: Any) -> bool:
        # Always validate during execution phase
        """Determine whether a config field should be validated at this stage.

        Args:
            field_value: The field value to check.

        Returns:
            True during execution phase; False when only validating the flow."""
        if not self.validating_flow:
            return True
        return False

    @staticmethod
    def create_base_metadata(
        *, total_docs_count: int, node_status: str = ExecutionStatus.COMPLETED.value
    ) -> OperatorOutputMetadata:
        # Create base metadata structure with all required fields initialized.
        """Initialise a metadata dict with all required counters set to zero.

        Args:
            total_docs_count: Total number of documents entering the operator.
            node_status: Initial node status string.

        Returns:
            Metadata dict with total_docs, processed, failed, skipped counters."""
        return {
            Metrics.External.TOTAL_DOCS: total_docs_count,
            Metrics.External.PROCESSED_DOCS: 0,
            Metrics.External.FAILED_DOCS_COUNT: 0,
            Metrics.External.FAILED_DOCS: [],
            Metrics.External.SKIPPED_DOCS_COUNT: 0,
            Metrics.External.SKIPPED_DOCS: [],
            Metrics.External.NODE_STATUS: node_status.value
            if isinstance(node_status, ExecutionStatus)
            else node_status,
        }

    @staticmethod
    def record_failed_document(
        *,
        metadata: dict[str, Any],
        doc_id: str,
        doc_name: str,
        reason: str,
    ) -> None:
        # Record a failed document in metadata.
        """Append a failed-document entry to metadata.

        Args:
            metadata: The metadata dict to update.
            doc_id: Document identifier.
            doc_name: Document name.
            reason: Reason for failure."""
        metadata[Metrics.External.FAILED_DOCS_COUNT] += 1
        metadata[Metrics.External.FAILED_DOCS].append(
            DocsStructure(id=doc_id, name=doc_name, reason=reason, document_url="")
        )

    @staticmethod
    def record_skipped_document(
        *,
        metadata: dict[str, Any],
        doc_id: str,
        doc_name: str,
        reason: str,
    ) -> None:
        # Record a skipped document in metadata.
        """Append a skipped-document entry to metadata.

        Args:
            metadata: The metadata dict to update.
            doc_id: Document identifier.
            doc_name: Document name.
            reason: Reason for skipping."""
        metadata[Metrics.External.SKIPPED_DOCS_COUNT] += 1
        metadata[Metrics.External.SKIPPED_DOCS].append(
            DocsStructure(id=doc_id, name=doc_name, reason=reason, document_url="")
        )
