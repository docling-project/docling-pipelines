# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""OpenLineage publisher adapter — concrete LineagePublisherPort using openlineage-python SDK."""

from __future__ import annotations

from typing import TYPE_CHECKING

from docpipe.core.lineage.domain.models.dataset import LineageDataset
from docpipe.core.lineage.domain.models.event_type import LineageEventType
from docpipe.core.lineage.domain.models.job import LineageJob
from docpipe.core.lineage.domain.models.run import LineageRun
from docpipe.core.lineage.domain.ports.lineage_publisher import LineagePublisherPort
from docpipe.integrations.secrets.registry import scrub
from docpipe.utils.infrastructure.exception_sanitizer import sanitize_exception
from docpipe.utils.infrastructure.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger()


def _import_openlineage():
    """Lazy import of openlineage-python SDK.  Raises ImportError with a helpful message if absent."""
    try:
        from openlineage.client import OpenLineageClient as _OLClient
        from openlineage.client.generated.base import Dataset as _Dataset
        from openlineage.client.generated.base import EventType as _EventType
        from openlineage.client.generated.base import Job as _Job
        from openlineage.client.generated.base import Run as _Run
        from openlineage.client.generated.base import RunEvent as _RunEvent

        return _OLClient, _RunEvent, _EventType, _Dataset, _Job, _Run
    except ImportError as exc:
        raise ImportError(
            "openlineage-python is required for lineage emission. "
            "Install it with: pip install 'docling-pipelines[lineage]'"
        ) from exc


_EVENT_TYPE_TO_STATE: dict[str, str] = {
    LineageEventType.START: "START",
    LineageEventType.RUNNING: "RUNNING",
    LineageEventType.COMPLETE: "COMPLETE",
    LineageEventType.FAIL: "FAIL",
    LineageEventType.ABORT: "ABORT",
    LineageEventType.OTHER: "OTHER",
}


class OpenLineagePublisherAdapter(LineagePublisherPort):
    """Publishes lineage events via the openlineage-python SDK.

    The SDK reads transport configuration from the environment (e.g.
    OPENLINEAGE_URL, OPENLINEAGE_API_KEY) or from a config file.
    No transport configuration is hard-coded here.
    """

    def __init__(self) -> None:
        ol_client_cls, _, _, _, _, _ = _import_openlineage()
        self._client = ol_client_cls()

    def publish(
        self,
        *,
        event_type: LineageEventType,
        run: LineageRun,
        job: LineageJob,
        inputs: list[LineageDataset] | None = None,
        outputs: list[LineageDataset] | None = None,
    ) -> None:
        """Translate domain models to openlineage-python SDK objects and emit."""
        _, run_event_cls, event_type_cls, dataset_cls, job_cls, run_cls = _import_openlineage()

        try:
            ol_run = run_cls(runId=run.run_id, facets=run.facets or {})
            ol_job = job_cls(namespace=job.namespace, name=job.name, facets=job.facets or {})

            ol_inputs = [dataset_cls(namespace=d.namespace, name=d.name, facets=d.facets) for d in (inputs or [])]
            ol_outputs = [dataset_cls(namespace=d.namespace, name=d.name, facets=d.facets) for d in (outputs or [])]

            state_name = _EVENT_TYPE_TO_STATE.get(str(event_type), "OTHER")
            state = getattr(event_type_cls, state_name, event_type_cls.OTHER)

            from datetime import UTC, datetime

            from docpipe.core.lineage.utils import LineageUtils

            raw_time = run.start_time or run.end_time
            if isinstance(raw_time, (int, float)):
                event_time = datetime.fromtimestamp(raw_time, tz=UTC).isoformat()
            elif raw_time is not None:
                event_time = str(raw_time)
            else:
                event_time = LineageUtils.now()
            event = run_event_cls(
                eventType=state,
                eventTime=event_time,
                run=ol_run,
                job=ol_job,
                inputs=ol_inputs,
                outputs=ol_outputs,
            )

            self._client.emit(event)
            logger.debug("Lineage event emitted: job=%s run=%s type=%s", job.name, run.run_id, event_type)

        except Exception as exc:
            logger.warning(
                "Failed to emit lineage event for job=%s: %s",
                job.name,
                scrub(sanitize_exception(exc=exc, config_key="lineage")),
            )
