"""Unit tests for event mapping API routes."""

from typing import Generator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from docpipe.api.dependencies import get_event_mapping_service, get_flow_service
from docpipe.api.middleware.error_handler import (
    docpipe_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from docpipe.api.routes.event_mappings import event_mappings_router
from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.event_streaming.mapping_service import EventMappingService
from docpipe.core.event_streaming.models import EventMapping
from docpipe.exceptions.docpipe_exceptions import DocpipeException, FlowNotFoundException
from docpipe.exceptions.error_codes import ErrorCode

pytestmark = pytest.mark.unit

FLOW_ID = "00000000-0000-0000-0000-000000000001"
UPDATED_FLOW_ID = "00000000-0000-0000-0000-000000000002"


@pytest.fixture
def mapping_service() -> MagicMock:
    return MagicMock(spec=EventMappingService)


@pytest.fixture
def flow_service() -> MagicMock:
    return MagicMock(spec=FlowService)


@pytest.fixture
def client(mapping_service: MagicMock, flow_service: MagicMock) -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(event_mappings_router)
    app.dependency_overrides[get_event_mapping_service] = lambda: mapping_service
    app.dependency_overrides[get_flow_service] = lambda: flow_service
    app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_create_event_mapping_validates_flow_and_returns_created_mapping(
    *, client: TestClient, mapping_service: MagicMock, flow_service: MagicMock
) -> None:
    mapping_service.create_mapping.return_value = EventMapping(key="Invoice-Ready", flow_id=FLOW_ID)

    response = client.post("/event_mappings", json={"key": "Invoice-Ready", "flow_id": FLOW_ID})

    assert response.status_code == 201
    assert response.json() == {"key": "Invoice-Ready", "flow_id": FLOW_ID}
    flow_service.get_flow.assert_called_once_with(FLOW_ID)
    mapping_service.create_mapping.assert_called_once_with(key="Invoice-Ready", flow_id=FLOW_ID)


def test_create_event_mapping_rejects_invalid_request(*, client: TestClient, mapping_service: MagicMock) -> None:
    response = client.post("/event_mappings", json={"key": "bad key", "flow_id": FLOW_ID})

    assert response.status_code == 400
    mapping_service.create_mapping.assert_not_called()


def test_create_event_mapping_returns_flow_lookup_failure(
    *,
    client: TestClient,
    mapping_service: MagicMock,
    flow_service: MagicMock,
) -> None:
    flow_service.get_flow.side_effect = FlowNotFoundException("Flow not found", flow_id=FLOW_ID)

    response = client.post("/event_mappings", json={"key": "Invoice-Ready", "flow_id": FLOW_ID})

    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "flow_not_found"
    mapping_service.create_mapping.assert_not_called()


def test_create_event_mapping_returns_duplicate_failure(*, client: TestClient, mapping_service: MagicMock) -> None:
    mapping_service.create_mapping.side_effect = DocpipeException(
        "Mapping already exists", status_code=409, error_code=ErrorCode.EVENT_MAPPING_ALREADY_EXISTS
    )

    response = client.post("/event_mappings", json={"key": "Invoice-Ready", "flow_id": FLOW_ID})

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "event_mapping_already_exists"


def test_get_event_mapping_returns_mapping(*, client: TestClient, mapping_service: MagicMock) -> None:
    mapping_service.get_mapping.return_value = EventMapping(key="Invoice-Ready", flow_id=FLOW_ID)

    response = client.get("/event_mappings/INVOICE-READY")

    assert response.status_code == 200
    assert response.json() == {"key": "Invoice-Ready", "flow_id": FLOW_ID}
    mapping_service.get_mapping.assert_called_once_with(key="INVOICE-READY")


def test_get_event_mapping_returns_not_found(*, client: TestClient, mapping_service: MagicMock) -> None:
    mapping_service.get_mapping.side_effect = DocpipeException(
        "Mapping not found", status_code=404, error_code=ErrorCode.EVENT_MAPPING_NOT_FOUND
    )

    response = client.get("/event_mappings/missing")

    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "event_mapping_not_found"


def test_get_event_mapping_rejects_invalid_path_key(*, client: TestClient, mapping_service: MagicMock) -> None:
    response = client.get("/event_mappings/bad%20key")

    assert response.status_code == 400
    mapping_service.get_mapping.assert_not_called()


def test_update_event_mapping_changes_flow(
    *, client: TestClient, mapping_service: MagicMock, flow_service: MagicMock
) -> None:
    mapping_service.get_mapping.return_value = EventMapping(key="Invoice-Ready", flow_id=FLOW_ID)
    mapping_service.update_mapping.return_value = EventMapping(key="Invoice-Ready", flow_id=UPDATED_FLOW_ID)

    response = client.put("/event_mappings/INVOICE-READY", json={"flow_id": UPDATED_FLOW_ID})

    assert response.status_code == 200
    assert response.json() == {"key": "Invoice-Ready", "flow_id": UPDATED_FLOW_ID}
    mapping_service.get_mapping.assert_called_once_with(key="INVOICE-READY")
    flow_service.get_flow.assert_called_once_with(UPDATED_FLOW_ID)
    mapping_service.update_mapping.assert_called_once_with(key="INVOICE-READY", flow_id=UPDATED_FLOW_ID)


def test_update_event_mapping_returns_not_found_for_missing_mapping(
    *, client: TestClient, mapping_service: MagicMock, flow_service: MagicMock
) -> None:
    mapping_service.get_mapping.side_effect = DocpipeException(
        "Mapping not found", status_code=404, error_code=ErrorCode.EVENT_MAPPING_NOT_FOUND
    )

    response = client.put("/event_mappings/missing", json={"flow_id": UPDATED_FLOW_ID})

    assert response.status_code == 404
    flow_service.get_flow.assert_not_called()
    mapping_service.update_mapping.assert_not_called()


def test_update_event_mapping_returns_flow_lookup_failure(
    *, client: TestClient, mapping_service: MagicMock, flow_service: MagicMock
) -> None:
    mapping_service.get_mapping.return_value = EventMapping(key="Invoice-Ready", flow_id=FLOW_ID)
    flow_service.get_flow.side_effect = DocpipeException("Flow not found", status_code=404)

    response = client.put("/event_mappings/Invoice-Ready", json={"flow_id": UPDATED_FLOW_ID})

    assert response.status_code == 404
    mapping_service.update_mapping.assert_not_called()


def test_update_event_mapping_rejects_invalid_flow_uuid(*, client: TestClient, mapping_service: MagicMock) -> None:
    response = client.put("/event_mappings/Invoice-Ready", json={"flow_id": "not-a-uuid"})

    assert response.status_code == 400
    mapping_service.get_mapping.assert_not_called()


def test_delete_event_mapping_returns_no_content(*, client: TestClient, mapping_service: MagicMock) -> None:
    response = client.delete("/event_mappings/Invoice-Ready")

    assert response.status_code == 204
    assert response.content == b""
    mapping_service.delete_mapping.assert_called_once_with(key="Invoice-Ready")


def test_delete_event_mapping_returns_not_found(*, client: TestClient, mapping_service: MagicMock) -> None:
    mapping_service.delete_mapping.side_effect = DocpipeException(
        "Mapping not found", status_code=404, error_code=ErrorCode.EVENT_MAPPING_NOT_FOUND
    )

    response = client.delete("/event_mappings/missing")

    assert response.status_code == 404


def test_list_event_mappings_returns_all_mappings(*, client: TestClient, mapping_service: MagicMock) -> None:
    mapping_service.list_mappings.return_value = [
        EventMapping(key="Invoice-Ready", flow_id=FLOW_ID),
        EventMapping(key="Report-Ready", flow_id=UPDATED_FLOW_ID),
    ]

    response = client.get("/event_mappings")

    assert response.status_code == 200
    assert response.json() == [
        {"key": "Invoice-Ready", "flow_id": FLOW_ID},
        {"key": "Report-Ready", "flow_id": UPDATED_FLOW_ID},
    ]


def test_list_event_mappings_returns_empty_list(*, client: TestClient, mapping_service: MagicMock) -> None:
    mapping_service.list_mappings.return_value = []

    response = client.get("/event_mappings")

    assert response.status_code == 200
    assert response.json() == []
