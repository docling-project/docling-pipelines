"""Design acceptance tests for event mapping APIs and the input event contract.

Coverage: HTTP create, get, update, delete, and list through filesystem storage,
plus agreement between ``InputEvent`` and the Schema Registry JSON Schema.

Do not add, modify, or delete test cases in this file unless the user explicitly
asks you to make those changes here. Add new test cases in a separate file otherwise.
"""

import json
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.auth.models import User
from docpipe.api.dependencies import get_event_mapping_service, get_flow_repository
from docpipe.api.main import app
from docpipe.core.assets.common.adapters.repositories.local_asset_repository import LocalAssetRepository
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.core.event_streaming.models import InputEvent


@pytest.fixture
def event_mapping_client(*, tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    """Use real routes and factory wiring with isolated filesystem storage."""
    flow_repository = LocalAssetRepository(asset_type=Flow, storage_path=str(tmp_path / "flows"))
    config_path = tmp_path / "docling-pipelines-config.yaml"
    config_path.write_text(
        json.dumps(
            {
                "global_storage": {
                    "type": "filesystem",
                    "config": {"base_dir": str(tmp_path / "event-mappings")},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("DOCPIPE_STORAGE_BACKEND", raising=False)
    get_event_mapping_service.cache_clear()
    monkeypatch.setitem(app.dependency_overrides, get_flow_repository, lambda: flow_repository)
    monkeypatch.setitem(
        app.dependency_overrides,
        get_current_user,
        lambda: User(username="testuser", email="test@example.com", full_name="Test User"),
    )

    try:
        yield TestClient(app)
    finally:
        get_event_mapping_service.cache_clear()


def _mapping_file(*, tmp_path, key: str) -> Path:
    """Return the JSON file written by the configured key-value storage."""
    return tmp_path / "event-mappings" / "event_mappings" / f"{key.lower()}.json"


def _create_flow(*, client: TestClient, name: str) -> str:
    """Create a real flow through the API for a valid mapping target."""
    response = client.post(
        "/api/v1/flows?is_elyra=true",
        json={"name": name, "description": "Event mapping test flow"},
    )
    assert response.status_code == 201, response.text
    return response.json()["flow_id"]


def test_create_event_mapping(*, event_mapping_client: TestClient, tmp_path) -> None:
    """Create a mapping through HTTP and verify the JSON record was persisted."""
    flow_id = _create_flow(client=event_mapping_client, name="create-mapping-flow")

    response = event_mapping_client.post(
        "/api/v1/event_mappings",
        json={"key": "invoices-updated", "flow_id": flow_id},
    )

    assert response.status_code == 201, response.text
    assert response.json() == {"key": "invoices-updated", "flow_id": flow_id}
    assert json.loads(_mapping_file(tmp_path=tmp_path, key="invoices-updated").read_text(encoding="utf-8")) == {
        "key": "invoices-updated",
        "flow_id": flow_id,
    }


def test_get_event_mapping(*, event_mapping_client: TestClient, tmp_path) -> None:
    """Read a mapping through HTTP after recreating the factory-backed service."""
    flow_id = _create_flow(client=event_mapping_client, name="get-mapping-flow")
    create_response = event_mapping_client.post(
        "/api/v1/event_mappings",
        json={"key": "invoices-updated", "flow_id": flow_id},
    )
    assert create_response.status_code == 201, create_response.text
    assert _mapping_file(tmp_path=tmp_path, key="invoices-updated").exists()
    get_event_mapping_service.cache_clear()

    response = event_mapping_client.get("/api/v1/event_mappings/invoices-updated")

    assert response.status_code == 200, response.text
    assert response.json() == {"key": "invoices-updated", "flow_id": flow_id}


def test_update_event_mapping(*, event_mapping_client: TestClient, tmp_path) -> None:
    """Update a mapping through HTTP and verify the persisted flow ID changed."""
    original_flow_id = _create_flow(client=event_mapping_client, name="update-mapping-original-flow")
    updated_flow_id = _create_flow(client=event_mapping_client, name="update-mapping-target-flow")
    event_mapping_client.post(
        "/api/v1/event_mappings",
        json={"key": "invoices-updated", "flow_id": original_flow_id},
    )

    response = event_mapping_client.put(
        "/api/v1/event_mappings/invoices-updated",
        json={"flow_id": updated_flow_id},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"key": "invoices-updated", "flow_id": updated_flow_id}
    assert json.loads(_mapping_file(tmp_path=tmp_path, key="invoices-updated").read_text(encoding="utf-8")) == {
        "key": "invoices-updated",
        "flow_id": updated_flow_id,
    }


def test_delete_event_mapping(*, event_mapping_client: TestClient, tmp_path) -> None:
    """Delete a mapping through HTTP and verify its persisted record was removed."""
    flow_id = _create_flow(client=event_mapping_client, name="delete-mapping-flow")
    event_mapping_client.post(
        "/api/v1/event_mappings",
        json={"key": "invoices-updated", "flow_id": flow_id},
    )

    response = event_mapping_client.delete("/api/v1/event_mappings/invoices-updated")

    assert response.status_code == 204, response.text
    assert not _mapping_file(tmp_path=tmp_path, key="invoices-updated").exists()


def test_list_event_mappings(*, event_mapping_client: TestClient, tmp_path) -> None:
    """List mappings through HTTP and verify the backing record exists."""
    flow_id = _create_flow(client=event_mapping_client, name="list-mapping-flow")
    event_mapping_client.post(
        "/api/v1/event_mappings",
        json={"key": "invoices-updated", "flow_id": flow_id},
    )

    response = event_mapping_client.get("/api/v1/event_mappings")

    assert response.status_code == 200, response.text
    assert response.json() == [{"key": "invoices-updated", "flow_id": flow_id}]
    assert _mapping_file(tmp_path=tmp_path, key="invoices-updated").exists()


def test_input_event_model_matches_json_schema() -> None:
    """Keep the Pydantic event contract aligned with the Schema Registry JSON Schema."""
    schema_path = Path(__file__).resolve().parents[3] / "docker/event-streaming/schemas/event_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    model_schema = InputEvent.model_json_schema()

    assert schema["type"] == model_schema["type"]
    assert schema["required"] == model_schema["required"]
    assert set(schema["properties"]) == set(model_schema["properties"])
    assert schema["additionalProperties"] is model_schema["additionalProperties"] is False
    for field_name, schema_property in schema["properties"].items():
        model_property = model_schema["properties"][field_name]
        if "$ref" in model_property:
            model_property = model_schema["$defs"]["InputEventOperation"]
        for keyword in ("type", "format", "pattern", "minLength", "enum"):
            assert schema_property.get(keyword) == model_property.get(keyword)

    event = InputEvent.model_validate(
        {
            "event_id": "550e8400-e29b-41d4-a716-446655440000",
            "event_timestamp": "2026-01-01T00:00:00Z",
            "routing_key": "invoices-updated",
            "operation": "update",
            "file_reference": "/documents/invoice.pdf",
        }
    )
    assert event.operation == "update"
