"""Unit tests for event dispatch requests."""

from unittest.mock import MagicMock

import httpx
import pytest

from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.core.event_streaming.dispatch_service import EventDispatchService
from docpipe.core.event_streaming.models import EventMapping, InputEvent


def _event() -> InputEvent:
    return InputEvent.model_validate(
        {
            "event_id": "550e8400-e29b-41d4-a716-446655440000",
            "event_timestamp": "2026-10-12T12:00:00Z",
            "routing_key": "invoices",
            "operation": "create",
            "file_reference": "/documents/invoice.pdf",
        }
    )


def test_dispatch_submits_mapped_flow_run(*, monkeypatch, mocker) -> None:
    """Resolve the routing key and forward the event as a job-run request."""
    monkeypatch.setenv(EnvironmentVariables.DOCPIPE_API_BASE_URL, "https://docpipe.example/")
    mapping_service = MagicMock()
    mapping_service.get_mapping.return_value = EventMapping(key="invoices", flow_id="saved-flow")
    response = MagicMock()
    response.json.return_value = {"job_run_id": "run-123"}
    post = mocker.patch("docpipe.core.event_streaming.dispatch_service.httpx.post", return_value=response)
    event = _event()

    result = EventDispatchService(mapping_service=mapping_service).dispatch(event=event)

    assert result == {"job_run_id": "run-123"}
    mapping_service.get_mapping.assert_called_once_with(key="invoices")
    post.assert_called_once_with(
        "https://docpipe.example/api/v1/job_runs",
        json={
            "entity": {
                "job": {"asset_ref": "saved-flow"},
                "job_run": {
                    "configuration": {
                        "input_event": event.model_dump(mode="json"),
                        "metadata": {
                            "event_id": "550e8400-e29b-41d4-a716-446655440000",
                            "event_timestamp": "2026-10-12T12:00:00+00:00",
                            "routing_key": "invoices",
                            "operation": "create",
                        },
                    }
                },
            }
        },
        headers={"X-Global-Transaction-Id": "550e8400-e29b-41d4-a716-446655440000"},
        timeout=30.0,
    )
    response.raise_for_status.assert_called_once_with()


def test_dispatch_propagates_api_failure(*, mocker) -> None:
    """Propagate an unsuccessful job-run API response to the listener."""
    mapping_service = MagicMock()
    mapping_service.get_mapping.return_value = EventMapping(key="invoices", flow_id="saved-flow")
    response = MagicMock()
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "API unavailable", request=MagicMock(), response=MagicMock()
    )
    mocker.patch("docpipe.core.event_streaming.dispatch_service.httpx.post", return_value=response)

    with pytest.raises(httpx.HTTPStatusError, match="API unavailable"):
        EventDispatchService(mapping_service=mapping_service).dispatch(event=_event())


def test_dispatch_does_not_call_api_when_mapping_is_missing(*, mocker) -> None:
    """Do not submit a job run when the routing key cannot be resolved."""
    mapping_service = MagicMock()
    mapping_service.get_mapping.side_effect = LookupError("unknown routing key")
    post = mocker.patch("docpipe.core.event_streaming.dispatch_service.httpx.post")

    with pytest.raises(LookupError, match="unknown routing key"):
        EventDispatchService(mapping_service=mapping_service).dispatch(event=_event())

    post.assert_not_called()
