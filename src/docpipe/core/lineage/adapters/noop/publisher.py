"""NoOp publisher adapter — concrete LineagePublisherPort that discards events."""

from __future__ import annotations

from docpipe.core.lineage.domain.models.dataset import LineageDataset
from docpipe.core.lineage.domain.models.event_type import LineageEventType
from docpipe.core.lineage.domain.models.job import LineageJob
from docpipe.core.lineage.domain.models.run import LineageRun
from docpipe.core.lineage.domain.ports.lineage_publisher import LineagePublisherPort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class NoOpLineagePublisherAdapter(LineagePublisherPort):
    """No-op publisher that silently discards all lineage events."""

    def publish(
        self,
        *,
        event_type: LineageEventType,
        run: LineageRun,
        job: LineageJob,
        inputs: list[LineageDataset] | None = None,
        outputs: list[LineageDataset] | None = None,
    ) -> None:
        """Discard lineage event without performing any action."""
        logger.debug(
            "NoOpLineagePublisherAdapter.publish called: event_type=%s job=%s run=%s",
            event_type,
            getattr(job, "name", None),
            getattr(run, "run_id", None),
        )
