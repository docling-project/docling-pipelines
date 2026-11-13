# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for synchronous in-process event dispatch."""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from docpipe.core.assets.flows.domain.models.flow import Flow
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


@pytest.fixture
def dispatch_services():
    """Provide a saved authoring flow and isolated dispatch dependencies."""
    mapping_service = MagicMock()
    mapping_service.get_mapping.return_value = EventMapping(key="invoices", flow_id="saved-flow")
    flow_service = MagicMock()
    flow_service.get_flow.return_value = Flow(
        asset_id="saved-flow",
        name="invoices",
        definition={
            "flow_name": "invoices",
            "flow": [
                {
                    "type": "ingest_source",
                    "name": "source",
                    "config": {"provider": "filesystem", "provider_config": {"paths": ["/documents"]}},
                }
            ],
        },
    )
    orchestrator = MagicMock()
    service = EventDispatchService(
        mapping_service=mapping_service, flow_service=flow_service, orchestrator=orchestrator
    )
    return service, mapping_service, flow_service, orchestrator


def test_dispatch_executes_mapped_flow_in_process(*, dispatch_services) -> None:
    """Compile the saved flow and execute it directly with the input event."""
    service, mapping_service, flow_service, orchestrator = dispatch_services
    event = _event()
    original_definition = deepcopy(flow_service.get_flow.return_value.definition)

    result = service.dispatch(event=event)

    assert result is None
    mapping_service.get_mapping.assert_called_once_with(key="invoices")
    flow_service.get_flow.assert_called_once_with(flow_id="saved-flow")
    orchestrator.execute.assert_called_once()
    execution = orchestrator.execute.call_args.kwargs
    assert execution["params"] == {"input_event": event.model_dump(mode="json")}
    assert execution["flow"]["name"] == "invoices"
    assert execution["flow"]["dag"][0]["operator"] == "ingest_source"
    assert execution["flow"]["dag"][0]["config"] == original_definition["flow"][0]["config"]
    assert flow_service.get_flow.return_value.definition == original_definition


def test_dispatch_propagates_execution_failure(*, dispatch_services) -> None:
    """Propagate a streaming execution failure to the listener."""
    service, _, _, orchestrator = dispatch_services
    orchestrator.execute.side_effect = RuntimeError("sink unavailable")

    with pytest.raises(RuntimeError, match="sink unavailable"):
        service.dispatch(event=_event())


def test_dispatch_does_not_execute_when_mapping_is_missing(*, dispatch_services) -> None:
    """Do not load or execute a flow when its routing key cannot be resolved."""
    service, mapping_service, flow_service, orchestrator = dispatch_services
    mapping_service.get_mapping.side_effect = LookupError("unknown routing key")

    with pytest.raises(LookupError, match="unknown routing key") as error:
        service.dispatch(event=_event())

    assert "unknown routing key" in str(error.value)
    assert error.value is mapping_service.get_mapping.side_effect

    flow_service.get_flow.assert_not_called()
    orchestrator.execute.assert_not_called()


def test_dispatch_propagates_failed_flow_load(*, dispatch_services) -> None:
    """The original loading error reaches the listener unchanged."""
    service, _, flow_service, _ = dispatch_services
    flow_service.get_flow.side_effect = LookupError("flow deleted")
    with pytest.raises(LookupError, match="flow deleted") as error:
        service.dispatch(event=_event())
    assert error.value is flow_service.get_flow.side_effect
