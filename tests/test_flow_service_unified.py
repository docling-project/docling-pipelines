# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Test FlowService with unified architecture.

Tests the FlowService that extends AssetService[Flow] to ensure
Flow-specific business logic works correctly.
"""

import shutil
import tempfile

import pytest

from docpipe.core.assets.common.adapters.repositories.local_asset_repository import LocalAssetRepository
from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.exceptions.docpipe_exceptions import AssetInvalidDataException


@pytest.fixture
def temp_storage():
    """Create temporary storage directory for tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def flow_service(temp_storage):
    """Create FlowService with LocalAssetRepository using temp storage."""
    repository = LocalAssetRepository(asset_type=Flow, storage_path=temp_storage)
    return FlowService(repository=repository)


@pytest.fixture
def sample_flow():
    """Create a sample flow for testing."""
    return Flow(
        name="Test Pipeline",
        description="A test pipeline",
        definition={
            "doc_type": "pipeline",
            "version": "3.0",
            "pipelines": [{"id": "pipeline-1", "nodes": [], "app_data": {}}],
        },
        tags=["test", "pipeline"],
        is_hidden=False,
    )


def test_create_flow(flow_service, sample_flow):
    """Test creating a flow using FlowService."""
    # Create flow
    created_flow = flow_service.create_flow(flow=sample_flow)

    # Verify flow was created
    assert created_flow.asset_id is not None
    assert created_flow.flow_id == created_flow.asset_id  # Backward compatibility
    assert created_flow.name == "Test Pipeline"
    assert created_flow.description == "A test pipeline"
    assert created_flow.tags == ["test", "pipeline"]
    assert created_flow.is_hidden is False
    assert created_flow.created_on is not None
    assert created_flow.modified_on is not None


def test_create_flow_duplicate_name(flow_service, sample_flow):
    """Test that creating a flow with duplicate name raises exception."""
    # Create first flow
    flow_service.create_flow(flow=sample_flow)

    # Try to create another flow with same name
    duplicate_flow = Flow(
        name="Test Pipeline",  # Same name
        description="Another pipeline",
        definition={"doc_type": "pipeline", "pipelines": []},
    )

    from docpipe.exceptions.docpipe_exceptions import FlowAlreadyExistsException

    with pytest.raises(FlowAlreadyExistsException, match="already exists"):
        flow_service.create_flow(flow=duplicate_flow)


def test_get_flow_by_id(flow_service, sample_flow):
    """Test retrieving a flow by ID."""
    # Create flow
    created_flow = flow_service.create_flow(flow=sample_flow)

    # Retrieve by ID
    retrieved_flow = flow_service.get_by_id(asset_id=created_flow.asset_id)

    assert retrieved_flow.asset_id == created_flow.asset_id
    assert retrieved_flow.name == created_flow.name
    assert retrieved_flow.definition == created_flow.definition


def test_get_flow_by_name(flow_service, sample_flow):
    """Test retrieving a flow by name."""
    # Create flow
    created_flow = flow_service.create_flow(flow=sample_flow)

    # Retrieve by name
    retrieved_flow = flow_service.get_by_name(name="Test Pipeline")

    assert retrieved_flow.asset_id == created_flow.asset_id
    assert retrieved_flow.name == "Test Pipeline"


def test_list_flows(flow_service):
    """Test listing flows with pagination and filtering."""
    # Create multiple flows
    for i in range(5):
        flow = Flow(
            name=f"Pipeline {i}",
            description=f"Pipeline number {i}",
            definition={"doc_type": "pipeline", "pipelines": []},
            tags=["test"] if i % 2 == 0 else ["production"],
            is_hidden=i == 4,
        )
        flow_service.create_flow(flow=flow)

    # List all flows
    all_flows = flow_service.list_flows(skip=0, limit=10)
    assert len(all_flows) == 5

    # List with pagination
    page1 = flow_service.list_flows(skip=0, limit=2)
    assert len(page1) == 2

    page2 = flow_service.list_flows(skip=2, limit=2)
    assert len(page2) == 2

    # Filter by name
    filtered = flow_service.list_flows(name_filter="Pipeline 1")
    assert len(filtered) == 1
    assert filtered[0].name == "Pipeline 1"

    # Filter by tags
    test_flows = flow_service.list_flows(tags_filter=["test"])
    assert len(test_flows) == 3  # Flows 0, 2, 4

    # Filter by is_hidden
    visible_flows = flow_service.list_flows(is_hidden=False)
    assert len(visible_flows) == 4

    hidden_flows = flow_service.list_flows(is_hidden=True)
    assert len(hidden_flows) == 1


def test_count_flows(flow_service):
    """Test counting flows with filters."""
    # Create multiple flows
    for i in range(5):
        flow = Flow(
            name=f"Pipeline {i}",
            description=f"Pipeline number {i}",
            definition={"doc_type": "pipeline", "pipelines": []},
            tags=["test"] if i % 2 == 0 else ["production"],
        )
        flow_service.create_flow(flow=flow)

    # Count all
    total = flow_service.count_flows()
    assert total == 5

    # Count with filters
    test_count = flow_service.count_flows(tags_filter=["test"])
    assert test_count == 3


def test_update_flow(flow_service, sample_flow):
    """Test updating a flow."""
    # Create flow
    created_flow = flow_service.create_flow(flow=sample_flow)

    # Update flow
    created_flow.description = "Updated description"
    created_flow.tags = ["updated", "test"]

    updated_flow = flow_service.update_flow(flow=created_flow)

    assert updated_flow.description == "Updated description"
    assert updated_flow.tags == ["updated", "test"]
    assert updated_flow.modified_on is not None


def test_partial_update_flow(flow_service, sample_flow):
    """Test partially updating a flow."""
    # Create flow
    created_flow = flow_service.create_flow(flow=sample_flow)

    # Partial update
    updated_flow = flow_service.partial_update_flow(
        flow_id=created_flow.asset_id, updates={"description": "Partially updated", "modified_by": "updater"}
    )

    assert updated_flow.description == "Partially updated"
    assert updated_flow.name == "Test Pipeline"  # Unchanged
    assert updated_flow.modified_by == "updater"


def test_partial_update_protected_fields(flow_service, sample_flow):
    """Test that protected fields cannot be updated."""
    # Create flow
    created_flow = flow_service.create_flow(flow=sample_flow)
    original_id = created_flow.asset_id
    original_created_on = created_flow.created_on

    # Try to update protected fields
    updated_flow = flow_service.partial_update_flow(
        flow_id=created_flow.asset_id,
        updates={
            "flow_id": "new-id",  # Protected
            "asset_id": "another-id",  # Protected
            "created_on": "2020-01-01",  # Protected
            "description": "Valid update",  # Valid
            "modified_by": "updater",
        },
    )

    # Protected fields should remain unchanged
    assert updated_flow.asset_id == original_id
    assert updated_flow.created_on == original_created_on
    # Valid field should be updated
    assert updated_flow.description == "Valid update"


def test_delete_flow(flow_service, sample_flow):
    """Test deleting a flow."""
    # Create flow
    created_flow = flow_service.create_flow(flow=sample_flow)
    flow_id = created_flow.asset_id

    # Delete flow
    result = flow_service.delete(asset_id=flow_id)
    assert result is True

    # Verify flow is deleted
    assert not flow_service.exists(asset_id=flow_id)


def test_bulk_delete_flows(flow_service):
    """Test bulk deleting flows."""
    # Create multiple flows
    flow_ids = []
    for i in range(3):
        flow = Flow(
            name=f"Pipeline {i}",
            description=f"Pipeline number {i}",
            definition={"doc_type": "pipeline", "pipelines": []},
        )
        created = flow_service.create_flow(flow=flow)
        flow_ids.append(created.asset_id)

    # Bulk delete
    result = flow_service.bulk_delete_flows(flow_ids=flow_ids)

    assert result["total_requested"] == 3
    assert result["total_deleted"] == 3
    assert result["total_failed"] == 0
    assert len(result["deleted"]) == 3

    # Verify all flows are deleted
    for flow_id in flow_ids:
        assert not flow_service.exists(asset_id=flow_id)


def test_bulk_delete_partial_failure(flow_service):
    """Test bulk delete with some failures."""
    # Create one flow
    flow = Flow(name="Pipeline 1", description="Pipeline", definition={"doc_type": "pipeline", "pipelines": []})
    created = flow_service.create_flow(flow=flow)

    # Try to delete existing and non-existing flows
    flow_ids = [created.asset_id, "nonexistent-id"]
    result = flow_service.bulk_delete_flows(flow_ids=flow_ids)

    assert result["total_requested"] == 2
    assert result["total_deleted"] == 1
    assert result["total_failed"] == 1
    assert len(result["deleted"]) == 1
    assert len(result["failed"]) == 1


def test_add_tags(flow_service, sample_flow):
    """Test adding tags to a flow."""
    # Create flow
    created_flow = flow_service.create_flow(flow=sample_flow)

    # Add tags using partial_update_flow
    new_tags = [*created_flow.tags, "new-tag", "another-tag"]
    updated_flow = flow_service.partial_update_flow(
        flow_id=created_flow.asset_id, updates={"tags": new_tags, "modified_by": "updater"}
    )

    assert "new-tag" in updated_flow.tags
    assert "another-tag" in updated_flow.tags
    assert "test" in updated_flow.tags  # Original tags preserved


def test_remove_tags(flow_service, sample_flow):
    """Test removing tags from a flow."""
    # Create flow
    created_flow = flow_service.create_flow(flow=sample_flow)

    # Remove tags using partial_update_flow
    new_tags = [tag for tag in created_flow.tags if tag != "test"]
    updated_flow = flow_service.partial_update_flow(
        flow_id=created_flow.asset_id, updates={"tags": new_tags, "modified_by": "updater"}
    )

    assert "test" not in updated_flow.tags
    assert "pipeline" in updated_flow.tags  # Other tags preserved


def test_validation_errors(flow_service):
    """Test validation errors."""
    from docpipe.exceptions.docpipe_exceptions import FlowInvalidDataException

    # Empty name - raises AssetInvalidDataException from Flow.validate()
    flow1 = Flow(name="", description="Test", definition={"doc_type": "pipeline", "pipelines": []})
    with pytest.raises(AssetInvalidDataException):
        flow_service.create_flow(flow=flow1)

    # Empty definition - raises AssetInvalidDataException from Flow.validate()
    flow2 = Flow(name="Test", description="Test", definition={})
    with pytest.raises(AssetInvalidDataException):
        flow_service.create_flow(flow=flow2)

    # Invalid skip/limit - raises FlowInvalidDataException from service layer
    with pytest.raises(FlowInvalidDataException):
        flow_service.list_flows(skip=-1, limit=10)

    with pytest.raises(FlowInvalidDataException):
        flow_service.list_flows(skip=0, limit=0)
