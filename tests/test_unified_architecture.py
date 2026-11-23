# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Simple test to verify the unified asset architecture works end-to-end.

This test demonstrates:
1. Creating a Flow instance
2. Saving it via LocalAssetRepository
3. Retrieving it via AssetService
4. Verifying all components work together
"""

import pytest

from docpipe.core.assets.common.adapters.repositories.local_asset_repository import LocalAssetRepository
from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.core.models.actor_context import SYSTEM_ACTOR


@pytest.fixture
def temp_flows_dir(tmp_path):
    """Create a temporary directory for flow storage."""
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    return flows_dir


def test_unified_architecture_end_to_end(temp_flows_dir):
    """Test the unified architecture with Flow."""

    # 1. Create repository with temp storage
    repository = LocalAssetRepository(asset_type=Flow, storage_path=str(temp_flows_dir))

    # 2. Create service
    service = FlowService(repository=repository)

    # 3. Create a flow
    flow = Flow(
        name="Test Pipeline",
        description="A test pipeline for unified architecture",
        definition={
            "doc_type": "pipeline",
            "version": "3.0",
            "pipelines": [{"id": "pipeline-1", "nodes": [], "app_data": {}}],
        },
        tags=["test", "unified-architecture"],
        container_kind="project",
        container_id="test-project-123",
    )

    # 4. Save via service
    created_flow = service.create_flow(flow=flow, actor=SYSTEM_ACTOR)

    # 5. Verify creation
    assert created_flow.asset_id is not None
    assert created_flow.name == "Test Pipeline"
    assert created_flow.get_asset_type() == "flow"
    assert "test" in created_flow.tags
    assert created_flow.created_on is not None

    print(f"Created flow: {created_flow.asset_id}")

    # 6. Retrieve via service
    retrieved_flow = service.get_by_id(asset_id=created_flow.asset_id)

    # 7. Verify retrieval
    assert retrieved_flow.asset_id == created_flow.asset_id
    assert retrieved_flow.name == created_flow.name
    assert retrieved_flow.description == created_flow.description
    assert retrieved_flow.definition == created_flow.definition

    print(f"Retrieved flow: {retrieved_flow.name}")

    # 8. Update flow
    retrieved_flow.description = "Updated description"
    updated_flow = service.update_flow(flow=retrieved_flow, actor=SYSTEM_ACTOR)

    assert updated_flow.description == "Updated description"
    assert updated_flow.modified_on is not None
    assert updated_flow.created_on is not None
    assert updated_flow.modified_on > updated_flow.created_on

    print("Updated flow description")

    # 9. List all flows
    all_flows = service.list_all()
    assert len(all_flows) == 1
    assert all_flows[0].asset_id == created_flow.asset_id

    print(f"Listed {len(all_flows)} flow(s)")

    # 10. Check existence
    assert service.exists(asset_id=created_flow.asset_id)
    assert service.exists_by_name(name="Test Pipeline")

    print("Verified existence checks")

    # 11. Delete flow
    deleted = service.delete(asset_id=created_flow.asset_id)
    assert deleted is True

    # 12. Verify deletion
    assert not service.exists(asset_id=created_flow.asset_id)
    assert len(service.list_all()) == 0

    print("Deleted flow")

    print("\nAll tests passed! Unified architecture works end-to-end.")
