"""Factory that builds the lineage observer from environment configuration."""

from __future__ import annotations

from docpipe.core.constants.constants import LineageConstants
from docpipe.core.lineage.domain.ports.execution_lifecycle_observer import ExecutionLifecycleObserverPort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


def create_lineage_observer() -> ExecutionLifecycleObserverPort | None:
    """Build and return a configured lineage observer, or None if lineage is disabled.

    Reads configuration exclusively from environment variables via LineageConstants:
    - DOCPIPE_LINEAGE_ENABLED  — must be "true" to activate (default: "false")
    - DOCPIPE_LINEAGE_MODE     — "flow" or "operator" (default: "flow")
    - DOCPIPE_LINEAGE_NAMESPACE — job namespace (default: "docpipe://local")
    - DOCPIPE_LINEAGE_PRODUCER  — producer URI (default: docling-project/docling-pipelines URL)

    Returns:
        Configured OpenLineageExecutionObserver, or None if lineage is disabled
        or openlineage-python is not installed.
    """
    if LineageConstants.DEFAULT_ENABLED.lower() != "true":
        logger.debug("Lineage emission is disabled (DOCPIPE_LINEAGE_ENABLED != true)")
        return None

    try:
        from docpipe.core.lineage.adapters.openlineage.observer import OpenLineageExecutionObserver
        from docpipe.core.lineage.adapters.openlineage.publisher import OpenLineagePublisherAdapter
        from docpipe.core.lineage.application.lineage_service import LineageService
        from docpipe.core.lineage.domain.ports.lineage_publisher import LineagePublisherPort

        publisher: LineagePublisherPort
        try:
            publisher = OpenLineagePublisherAdapter()
        except ImportError as exc:
            from docpipe.core.lineage.adapters.noop.publisher import NoOpLineagePublisherAdapter

            logger.warning(
                "Lineage enabled but openlineage-python is not installed; falling back to NoOpLineagePublisherAdapter: %s",
                exc,
            )
            publisher = NoOpLineagePublisherAdapter()
        except Exception as exc:
            from docpipe.core.lineage.adapters.noop.publisher import NoOpLineagePublisherAdapter

            logger.warning(
                "Failed to initialize OpenLineagePublisherAdapter; falling back to NoOpLineagePublisherAdapter: %s",
                exc,
            )
            publisher = NoOpLineagePublisherAdapter()

        service = LineageService(
            publisher=publisher,
            namespace=LineageConstants.DEFAULT_NAMESPACE,
            producer=LineageConstants.DEFAULT_PRODUCER,
        )
        mode = LineageConstants.DEFAULT_MODE
        observer = OpenLineageExecutionObserver(lineage_service=service, mode=mode)
        logger.info("Lineage observer created: mode=%s namespace=%s", mode, LineageConstants.DEFAULT_NAMESPACE)
        return observer

    except Exception as exc:
        logger.warning("Failed to create lineage observer - lineage will not be emitted: %s", exc)
        return None
