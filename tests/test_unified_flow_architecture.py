# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Test unified asset architecture with Flow.

This test verifies that the unified architecture works end-to-end:
- Asset base class
- AssetRepository[T] interface
- LocalAssetRepository[Flow] implementation
- AssetService[T] base class
- FlowService(AssetService[Flow]) implementation
"""

import shutil
import tempfile

import pytest

from docpipe.core.assets.common.adapters.repositories.local_asset_repository import LocalAssetRepository
from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.assets.flows.domain.models.flow import Flow


@pytest.fixture
def temp_storage():
    """Create temporary storage directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def flow_repository(temp_storage):
    """Create LocalAssetRepository[Flow]."""
    return LocalAssetRepository[Flow](asset_type=Flow, storage_path=temp_storage)


@pytest.fixture
def flow_service(flow_repository):
    """Create FlowService with LocalAssetRepository[Flow]."""
    return FlowService(repository=flow_repository)


def test_create_flow_via_service(flow_service):
    """Test creating a flow through FlowService."""
    flow = Flow(
        name="Test Pipeline",
        description="Test description",
        definition={"nodes": [], "edges": []},
        tags=["test"],
    )

    created_flow = flow_service.create_flow(flow=flow)

    assert created_flow.asset_id is not None
    assert created_flow.flow_id == created_flow.asset_id
    assert created_flow.name == "Test Pipeline"
    assert created_flow.description == "Test description"
    assert created_flow.created_on is not None
    assert created_flow.modified_on is not None


def test_get_flow_via_service(flow_service):
    """Test retrieving a flow through FlowService."""
    flow = Flow(name="Get Test", definition={"nodes": []})
    created = flow_service.create_flow(flow=flow)

    retrieved = flow_service.get_flow(created.flow_id)

    assert retrieved.flow_id == created.flow_id
    assert retrieved.name == "Get Test"


def test_update_flow_via_service(flow_service):
    """Test updating a flow through FlowService."""
    flow = Flow(name="Update Test", definition={"nodes": []})
    created = flow_service.create_flow(flow=flow)

    created.name = "Updated Name"
    created.description = "Updated description"

    updated = flow_service.update_flow(created)

    assert updated.name == "Updated Name"
    assert updated.description == "Updated description"
    assert updated.modified_on > created.created_on


def test_delete_flow_via_service(flow_service):
    """Test deleting a flow through FlowService."""
    flow = Flow(name="Delete Test", definition={"nodes": []})
    created = flow_service.create_flow(flow=flow)

    result = flow_service.delete_flow(created.flow_id)

    assert result is True
    assert not flow_service.flow_exists(created.flow_id)


def test_list_flows_via_service(flow_service):
    """Test listing flows through FlowService."""
    flow1 = Flow(name="Flow 1", definition={"nodes": []})
    flow2 = Flow(name="Flow 2", definition={"nodes": []})

    flow_service.create_flow(flow=flow1)
    flow_service.create_flow(flow=flow2)

    flows = flow_service.list_flows()

    assert len(flows) == 2
    assert any(f.name == "Flow 1" for f in flows)
    assert any(f.name == "Flow 2" for f in flows)


def test_flow_exists_via_service(flow_service):
    """Test checking flow existence through FlowService."""
    flow = Flow(name="Exists Test", definition={"nodes": []})
    created = flow_service.create_flow(flow=flow)

    assert flow_service.flow_exists(created.flow_id) is True
    assert flow_service.flow_exists("nonexistent-id") is False


def test_inherited_methods_work(flow_service):
    """Test that inherited methods from AssetService work correctly."""
    flow = Flow(name="Inherited Test", definition={"nodes": []})
    created = flow_service.create_flow(flow=flow)

    # Test inherited get_by_id
    retrieved = flow_service.get_by_id(asset_id=created.flow_id)
    assert retrieved.name == "Inherited Test"

    # Test inherited exists
    assert flow_service.exists(asset_id=created.flow_id) is True

    # Test inherited delete
    result = flow_service.delete(asset_id=created.flow_id)
    assert result is True


def test_repository_health_check(flow_repository):
    """Test repository health check."""
    health = flow_repository.health_check()

    assert health["status"] == "healthy"
    assert "storage_path" in health
    assert health["storage_exists"] is True
    assert "asset_count" in health
