"""Resolve events and submit mapped flow runs through the job-run API."""

import json
import os
from typing import Any

import httpx

from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.core.event_streaming.mapping_service import EventMappingService
from docpipe.core.event_streaming.models import InputEvent
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class EventDispatchService:
    """Dispatch validated events to their mapped flows through REST."""

    def __init__(self, *, mapping_service: EventMappingService) -> None:
        self._mapping_service = mapping_service
        self._api_base_url = os.environ.get(EnvironmentVariables.DOCPIPE_API_BASE_URL, "http://127.0.0.1:8080").rstrip(
            "/"
        )

    def dispatch(self, *, event: InputEvent) -> dict[str, Any]:
        """Resolve the event routing key and submit an asynchronous job run."""
        mapping = self._mapping_service.get_mapping(key=event.routing_key)
        event_payload = event.model_dump(mode="json")
        event_metadata = {
            "event_id": str(event.event_id),
            "event_timestamp": event.event_timestamp.isoformat(),
            "routing_key": event.routing_key,
            "operation": event.operation.value,
        }
        request_payload = {
            "entity": {
                "job": {"asset_ref": mapping.flow_id},
                "job_run": {
                    "configuration": {
                        "input_event": event_payload,
                        "metadata": event_metadata,
                    }
                },
            }
        }
        response = httpx.post(
            f"{self._api_base_url}/api/v1/job_runs",
            json=request_payload,
            headers={"X-Global-Transaction-Id": event_metadata["event_id"]},
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()
        logger.info(
            "Event job run submitted: %s",
            json.dumps({**event_metadata, "job_run_id": result.get("job_run_id")}),
        )
        return result
