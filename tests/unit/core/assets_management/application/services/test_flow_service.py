"""Unit tests for FlowService."""

import logging
import logging.handlers
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.exceptions.docpipe_exceptions import (
    AssetInvalidDataException,
    DocpipeException,
    FlowAlreadyExistsException,
    FlowInvalidDataException,
)


class TestFlowServiceCreate:
    """Tests for FlowService.create_flow method."""

    def test_create_flow_prevents_duplicate_name(self, mock_flow_repository, sample_flow_with_id):
        """Test that create_flow prevents creating flows with duplicate names."""
        # Arrange
        mock_flow_repository.exists_by_name.return_value = True  # Simulate duplicate name
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(FlowAlreadyExistsException, match="already exists"):
            service.create_flow(flow=sample_flow_with_id, is_elyra=True)

        # Verify save was never called
        mock_flow_repository.save.assert_not_called()

    def test_create_flow_with_valid_data(self, mock_flow_repository, sample_flow_domain):
        """Test creating a flow with valid data."""
        # Arrange
        mock_flow_repository.save.return_value = sample_flow_domain
        mock_flow_repository.exists_by_name.return_value = False  # No duplicate name
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.create_flow(flow=sample_flow_domain, is_elyra=True)

        # Assert
        assert result == sample_flow_domain
        mock_flow_repository.save.assert_called_once_with(asset=sample_flow_domain)

    def test_create_flow_validates_before_saving(self, mock_flow_repository):
        """Test that flow validation occurs before saving."""
        # Arrange
        service = FlowService(repository=mock_flow_repository)
        invalid_flow = Flow(name="", definition={})  # Invalid: empty name and definition

        # Act & Assert
        with pytest.raises(AssetInvalidDataException, match="flow name cannot be empty"):
            service.create_flow(flow=invalid_flow)

        # Verify save was never called
        mock_flow_repository.save.assert_not_called()

    def test_create_flow_with_existing_name_logs_warning(self, mock_flow_repository, sample_flow_with_id):
        """Test creating a flow when name already exists logs warning."""
        # Arrange
        mock_flow_repository.exists_by_name.return_value = True  # Simulate duplicate name
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with patch("docpipe.core.assets.flows.application.services.flow_service.logger") as mock_logger:
            with pytest.raises(FlowAlreadyExistsException, match="already exists"):
                service.create_flow(flow=sample_flow_with_id, is_elyra=True)

            # Verify warning was logged before exception
            mock_logger.warning.assert_called_once()
            assert "existing name" in mock_logger.warning.call_args[0][0].lower()

    def test_create_flow_handles_repository_exception(self, mock_flow_repository, sample_flow_domain):
        """Test that repository exceptions bubble up naturally."""
        # Arrange
        mock_flow_repository.exists_by_name.return_value = False
        mock_flow_repository.save.side_effect = OSError("Disk full")
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(OSError, match="Disk full"):
            service.create_flow(flow=sample_flow_domain, is_elyra=True)

    def test_create_flow_with_is_elyra_false_stores_authoring_format(self, mock_flow_repository):
        """Test that is_elyra=False stores flow in authoring format without transformation."""
        # Arrange
        authoring_flow = Flow(
            asset_id="test-flow-id",
            name="Test Flow",
            definition={
                "flow_name": "Test Flow",
                "flow": [{"type": "ingest_source", "name": "node1", "config": {}, "depends_on": []}],
                "global_config": {},
                "tags": [],
            },
        )
        mock_flow_repository.exists_by_name.return_value = False
        mock_flow_repository.save.return_value = authoring_flow
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.create_flow(flow=authoring_flow, is_elyra=False)

        # Assert - No transformation should occur, flow stored as-is
        assert result == authoring_flow
        mock_flow_repository.save.assert_called_once_with(asset=authoring_flow)

    def test_create_flow_with_is_elyra_true_no_transformation(self, mock_flow_repository):
        """Test that is_elyra=True does not transform (flow already in Elyra format)."""
        # Arrange
        elyra_flow = Flow(
            asset_id="test-flow-id",
            name="Test Flow",
            definition={"doc_type": "pipeline", "pipelines": []},
        )
        mock_flow_repository.exists_by_name.return_value = False
        mock_flow_repository.save.return_value = elyra_flow
        service = FlowService(repository=mock_flow_repository)

        # Act
        with patch("docpipe.utils.orchestration.elyra_converter.ElyraConverter") as mock_converter_class:
            result = service.create_flow(flow=elyra_flow, is_elyra=True)

            # Assert - converter should not be instantiated when is_elyra=True
            mock_converter_class.assert_not_called()
            assert result == elyra_flow


class TestFlowServiceGet:
    """Tests for FlowService.get_flow method."""

    def test_get_flow_validates_empty_flow_id(self, mock_flow_repository):
        """Test that get_flow validates empty flow_id."""
        # Arrange
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert - empty string
        with pytest.raises(DocpipeException, match="asset_id cannot be empty"):
            service.get_flow("")

        # Act & Assert - whitespace only
        with pytest.raises(DocpipeException, match="asset_id cannot be empty"):
            service.get_flow("   ")

        # Verify repository was never called
        mock_flow_repository.find_by_id.assert_not_called()

    def test_get_flow_with_existing_id(self, mock_flow_repository, sample_flow_with_id):
        """Test retrieving an existing flow."""
        # Arrange
        mock_flow_repository.find_by_id.return_value = sample_flow_with_id
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.get_flow("test-flow-id-123")

        # Assert
        assert result == sample_flow_with_id
        mock_flow_repository.find_by_id.assert_called_once_with(asset_id="test-flow-id-123")

    def test_get_flow_with_nonexistent_id_raises_error(self, mock_flow_repository):
        """Test retrieving a non-existent flow raises FlowNotFoundException."""
        # Arrange
        mock_flow_repository.find_by_id.return_value = None
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(DocpipeException, match="Asset with ID 'test-id' not found"):
            service.get_flow("test-id")

    def test_get_flow_handles_repository_exception(self, mock_flow_repository):
        """Test that repository exceptions are propagated."""
        # Arrange
        mock_flow_repository.find_by_id.side_effect = OSError("Read error")
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(OSError, match="Read error"):
            service.get_flow("test-id")


class TestFlowServiceUpdate:
    """Tests for FlowService.update_flow method."""

    def test_update_flow_with_valid_data(self, mock_flow_repository, sample_flow_with_id):
        """Test updating a flow with valid data."""
        # Arrange
        mock_flow_repository.find_by_id.return_value = sample_flow_with_id
        mock_flow_repository.update.return_value = sample_flow_with_id
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.update_flow(sample_flow_with_id)

        # Assert
        assert result == sample_flow_with_id
        mock_flow_repository.find_by_id.assert_called_once_with(asset_id="test-flow-id-123")
        mock_flow_repository.update.assert_called_once()

    def test_update_flow_updates_timestamp(self, mock_flow_repository, sample_flow_with_id):
        """Test that update_flow updates the modified_on timestamp."""
        # Arrange
        mock_flow_repository.find_by_id.return_value = sample_flow_with_id
        mock_flow_repository.save.return_value = sample_flow_with_id
        original_modified = sample_flow_with_id.modified_on
        service = FlowService(repository=mock_flow_repository)

        # Act
        with patch("docpipe.core.assets.flows.domain.models.flow.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)
            service.update_flow(sample_flow_with_id)

        # Assert
        assert sample_flow_with_id.modified_on != original_modified

    def test_update_flow_without_id_raises_error(self, mock_flow_repository, sample_flow_domain):
        """Test updating a flow without flow_id raises FlowInvalidDataException."""
        # Arrange
        sample_flow_domain.flow_id = None
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(FlowInvalidDataException, match="Flow ID is required for update"):
            service.update_flow(sample_flow_domain)

    def test_update_flow_with_nonexistent_id_raises_error(self, mock_flow_repository, sample_flow_with_id):
        """Test updating a non-existent flow raises FlowNotFoundException."""
        # Arrange
        mock_flow_repository.find_by_id.return_value = None
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(DocpipeException, match="not found"):
            service.update_flow(sample_flow_with_id)

    def test_update_flow_validates_before_saving(self, mock_flow_repository, sample_flow_with_id):
        """Test that flow validation occurs before updating."""
        # Arrange
        mock_flow_repository.exists.return_value = True
        service = FlowService(repository=mock_flow_repository)
        sample_flow_with_id.name = ""  # Make it invalid

        # Act & Assert
        with pytest.raises(AssetInvalidDataException, match="flow name cannot be empty"):
            service.update_flow(sample_flow_with_id)

        # Verify save was never called
        mock_flow_repository.save.assert_not_called()

    def test_update_flow_preserves_created_on_from_stored_flow(self, mock_flow_repository, sample_flow_with_id):
        """Test that update_flow preserves created_on from the stored flow, not the incoming object.

        Regression test: a full-replacement PUT was constructing a new Flow domain object
        with created_on=None, which __post_init__ set to datetime.now(). The service
        must restore created_on from the persisted record before saving.
        """
        original_created_on = datetime(2023, 6, 15, 10, 0, 0, tzinfo=UTC)

        # Stored flow has the original created_on
        stored_flow = sample_flow_with_id
        stored_flow.created_on = original_created_on
        stored_flow.created_by = "original_user"

        # Incoming flow (simulating what the route builds from the request)
        # has a fresh created_on from __post_init__
        incoming_flow = Flow(
            asset_id="test-flow-id-123",
            name="Updated Name",
            description="Updated description",
            definition=sample_flow_with_id.definition,
            tags=[],
            container_kind="project",
            container_id="some-container-id",
            created_by="attacker",  # should be overwritten
        )
        # incoming_flow.created_on will be datetime.now() from __post_init__
        assert incoming_flow.created_on != original_created_on

        mock_flow_repository.exists.return_value = True
        mock_flow_repository.find_by_id.return_value = stored_flow
        mock_flow_repository.update.return_value = incoming_flow
        service = FlowService(repository=mock_flow_repository)

        service.update_flow(incoming_flow)

        # created_on and created_by must be restored from the stored flow
        assert incoming_flow.created_on == original_created_on
        assert incoming_flow.created_by == "original_user"


class TestFlowServicePartialUpdate:
    """Tests for FlowService.partial_update_flow method."""

    def test_partial_update_flow_validates_empty_updates(self, mock_flow_repository):
        """Test that partial_update_flow validates empty updates dictionary."""
        # Arrange
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(FlowInvalidDataException, match="updates dictionary cannot be empty"):
            service.partial_update_flow("test-123", {})

        # Verify repository was never called
        mock_flow_repository.find_by_id.assert_not_called()

    def test_partial_update_flow_tracks_updated_fields(self, mock_flow_repository, sample_flow_with_id):
        """Test that partial_update_flow tracks and logs updated fields."""
        # Arrange
        updated_flow = Flow.from_dict(data=sample_flow_with_id.to_dict())
        updated_flow.name = "new_name"
        updated_flow.description = "new_desc"

        mock_flow_repository.find_by_id.return_value = sample_flow_with_id
        mock_flow_repository.partial_update.return_value = updated_flow
        service = FlowService(repository=mock_flow_repository)
        updates = {"name": "new_name", "description": "new_desc"}

        flow_logger = logging.getLogger("docpipe.core.assets.flows.application.services.flow_service")
        handler = logging.handlers.MemoryHandler(capacity=100, flushLevel=logging.CRITICAL)
        handler.setLevel(logging.INFO)
        flow_logger.addHandler(handler)
        try:
            result = service.partial_update_flow("test-flow-id-123", updates)
        finally:
            flow_logger.removeHandler(handler)

        log_messages = " ".join(record.getMessage() for record in handler.buffer)

        # Assert
        assert result.name == "new_name"
        assert result.description == "new_desc"
        assert "Updated fields" in log_messages
        assert "name" in log_messages
        assert "description" in log_messages

    def test_partial_update_flow_with_name_change(self, mock_flow_repository, sample_flow_with_id):
        """Test partial update with name change."""
        # Arrange
        updated_flow = Flow.from_dict(data=sample_flow_with_id.to_dict())
        updated_flow.name = "Updated Flow Name"

        mock_flow_repository.find_by_id.return_value = sample_flow_with_id
        mock_flow_repository.partial_update.return_value = updated_flow
        service = FlowService(repository=mock_flow_repository)
        updates = {"name": "Updated Flow Name"}

        # Act
        result = service.partial_update_flow("test-flow-id-123", updates)

        # Assert
        assert result.name == "Updated Flow Name"
        mock_flow_repository.partial_update.assert_called_once()

    def test_partial_update_flow_without_name_change(self, mock_flow_repository, sample_flow_with_id):
        """Test partial update without name change."""
        # Arrange
        updated_flow = Flow.from_dict(data=sample_flow_with_id.to_dict())
        updated_flow.description = "Updated description"

        mock_flow_repository.find_by_id.return_value = sample_flow_with_id
        mock_flow_repository.partial_update.return_value = updated_flow
        service = FlowService(repository=mock_flow_repository)
        updates = {"description": "Updated description"}

        # Act
        result = service.partial_update_flow("test-flow-id-123", updates)

        # Assert
        assert result.description == "Updated description"
        mock_flow_repository.partial_update.assert_called_once()

    def test_partial_update_flow_ignores_protected_fields(self, mock_flow_repository, sample_flow_with_id):
        """Test that protected fields (flow_id, created_on, created_by) are not updated."""
        # Arrange
        mock_flow_repository.find_by_id.return_value = sample_flow_with_id
        mock_flow_repository.update.return_value = sample_flow_with_id
        service = FlowService(repository=mock_flow_repository)
        original_id = sample_flow_with_id.flow_id
        original_created = sample_flow_with_id.created_on
        updates = {
            "flow_id": "new-id",
            "created_on": datetime(2025, 1, 1, tzinfo=UTC),
            "created_by": "hacker",
        }

        flow_logger = logging.getLogger("docpipe.core.assets.flows.application.services.flow_service")
        handler = logging.handlers.MemoryHandler(capacity=100, flushLevel=logging.CRITICAL)
        handler.setLevel(logging.WARNING)
        flow_logger.addHandler(handler)
        try:
            result = service.partial_update_flow("test-flow-id-123", updates)
        finally:
            flow_logger.removeHandler(handler)

        log_messages = " ".join(record.getMessage() for record in handler.buffer).lower()

        # Assert
        assert result.flow_id == original_id
        assert result.created_on == original_created
        assert "protected field" in log_messages

    def test_partial_update_flow_validates_before_saving(self, mock_flow_repository, sample_flow_with_id):
        """Test that validation occurs before file operations."""
        # Arrange
        mock_flow_repository.find_by_id.return_value = sample_flow_with_id
        # Repository raises AssetInvalidDataException when validation fails
        mock_flow_repository.partial_update.side_effect = AssetInvalidDataException("flow name cannot be empty")

        service = FlowService(repository=mock_flow_repository)
        updates = {"name": ""}  # Invalid empty name

        # Act & Assert
        with pytest.raises(AssetInvalidDataException, match="flow name cannot be empty"):
            service.partial_update_flow("test-flow-id-123", updates)

        # Verify update was never called (partial_update handles validation internally)
        mock_flow_repository.update.assert_not_called()

    def test_partial_update_flow_with_nonexistent_id_raises_error(self, mock_flow_repository):
        """Test partial update with non-existent flow ID raises FlowNotFoundException."""
        # Arrange
        mock_flow_repository.find_by_id.return_value = None
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(DocpipeException):
            service.partial_update_flow("nonexistent-id", {"name": "New Name"})


class TestFlowServiceDelete:
    """Tests for FlowService.delete_flow method."""

    def test_delete_flow_validates_empty_flow_id(self, mock_flow_repository):
        """Test that delete_flow validates empty flow_id."""
        # Arrange
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert - empty string
        with pytest.raises(DocpipeException, match="asset_id cannot be empty"):
            service.delete_flow("")

        # Act & Assert - whitespace only
        with pytest.raises(DocpipeException, match="asset_id cannot be empty"):
            service.delete_flow("   ")

        # Verify repository was never called
        mock_flow_repository.delete.assert_not_called()

    def test_delete_flow_with_existing_id(self, mock_flow_repository):
        """Test deleting an existing flow."""
        # Arrange
        mock_flow_repository.delete.return_value = True
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.delete_flow("test-flow-id")

        # Assert
        assert result is True
        mock_flow_repository.delete.assert_called_once_with(asset_id="test-flow-id")

    def test_delete_flow_with_nonexistent_id(self, mock_flow_repository):
        """Test deleting a non-existent flow raises FlowNotFoundException."""
        # Arrange
        mock_flow_repository.delete.return_value = False
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(DocpipeException, match="Asset with ID 'nonexistent-id' not found"):
            service.delete_flow("nonexistent-id")

    def test_delete_flow_handles_repository_exception(self, mock_flow_repository):
        """Test that repository exceptions are propagated."""
        # Arrange
        mock_flow_repository.delete.side_effect = OSError("Delete error")
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(OSError, match="Delete error"):
            service.delete_flow("test-id")


class TestFlowServiceBulkDelete:
    """Tests for FlowService.bulk_delete_flows method."""

    def test_bulk_delete_flows_success(self, mock_flow_repository):
        """Test bulk delete with all flows deleted successfully."""
        # Arrange
        flow_ids = ["flow-1", "flow-2", "flow-3"]
        mock_flow_repository.bulk_delete.return_value = {
            "deleted": flow_ids,
            "failed": [],
            "total_requested": 3,
            "total_deleted": 3,
            "total_failed": 0,
        }
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.bulk_delete_flows(flow_ids)

        # Assert
        assert result["total_deleted"] == 3
        assert result["total_failed"] == 0
        assert result["deleted"] == flow_ids
        assert result["failed"] == []
        mock_flow_repository.bulk_delete.assert_called_once_with(asset_ids=flow_ids)

    def test_bulk_delete_flows_partial_failure(self, mock_flow_repository):
        """Test bulk delete with some flows succeeding and some failing."""
        # Arrange
        flow_ids = ["flow-1", "flow-2", "flow-3"]
        mock_flow_repository.bulk_delete.return_value = {
            "deleted": ["flow-1", "flow-3"],
            "failed": [{"flow_id": "flow-2", "error": "Flow flow-2 not found"}],
            "total_requested": 3,
            "total_deleted": 2,
            "total_failed": 1,
        }
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.bulk_delete_flows(flow_ids)

        # Assert
        assert result["total_deleted"] == 2
        assert result["total_failed"] == 1
        assert len(result["deleted"]) == 2
        assert len(result["failed"]) == 1
        assert result["failed"][0]["flow_id"] == "flow-2"
        mock_flow_repository.bulk_delete.assert_called_once_with(asset_ids=flow_ids)

    def test_bulk_delete_flows_empty_list(self, mock_flow_repository):
        """Test bulk delete with empty flow_ids list raises FlowInvalidDataException."""
        # Arrange
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(FlowInvalidDataException, match="flow_ids list cannot be empty"):
            service.bulk_delete_flows([])

        # Verify repository was never called
        mock_flow_repository.bulk_delete.assert_not_called()

    def test_bulk_delete_flows_all_fail(self, mock_flow_repository):
        """Test bulk delete where all deletions fail."""
        # Arrange
        flow_ids = ["nonexistent-1", "nonexistent-2"]
        mock_flow_repository.bulk_delete.return_value = {
            "deleted": [],
            "failed": [
                {"flow_id": "nonexistent-1", "error": "Flow nonexistent-1 not found"},
                {"flow_id": "nonexistent-2", "error": "Flow nonexistent-2 not found"},
            ],
            "total_requested": 2,
            "total_deleted": 0,
            "total_failed": 2,
        }
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.bulk_delete_flows(flow_ids)

        # Assert
        assert result["total_deleted"] == 0
        assert result["total_failed"] == 2
        assert result["deleted"] == []
        assert len(result["failed"]) == 2
        mock_flow_repository.bulk_delete.assert_called_once_with(asset_ids=flow_ids)

    def test_bulk_delete_flows_handles_repository_exception(self, mock_flow_repository):
        """Test that repository exceptions are propagated."""
        # Arrange
        flow_ids = ["flow-1", "flow-2"]
        mock_flow_repository.bulk_delete.side_effect = OSError("Disk error")
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(OSError, match="Disk error"):
            service.bulk_delete_flows(flow_ids)

    def test_bulk_delete_flows_parallel_execution(self, mock_flow_repository):
        """Test that bulk delete can handle parallel execution."""
        flow_ids = [f"flow-{i}" for i in range(20)]

        # Mock repository to return success for all
        mock_flow_repository.bulk_delete.return_value = {
            "deleted": flow_ids,
            "failed": [],
            "total_requested": 20,
            "total_deleted": 20,
            "total_failed": 0,
        }

        service = FlowService(repository=mock_flow_repository)
        result = service.bulk_delete_flows(flow_ids)

        assert result["total_deleted"] == 20
        assert len(result["deleted"]) == 20
        assert result["total_failed"] == 0
        # Verify bulk_delete was called once with the flow_ids
        mock_flow_repository.bulk_delete.assert_called_once_with(asset_ids=flow_ids)

    def test_bulk_delete_flows_with_thread_failures(self, mock_flow_repository):
        """Test that bulk delete handles thread failures gracefully."""
        flow_ids = [f"flow-{i}" for i in range(10)]

        # Mock repository to simulate some deletions failing
        mock_flow_repository.bulk_delete.return_value = {
            "deleted": ["flow-0", "flow-2", "flow-4", "flow-6", "flow-8"],
            "failed": [
                {"flow_id": "flow-1", "error": "Permission denied"},
                {"flow_id": "flow-3", "error": "File not found"},
                {"flow_id": "flow-5", "error": "Lock timeout"},
                {"flow_id": "flow-7", "error": "I/O error"},
                {"flow_id": "flow-9", "error": "Disk full"},
            ],
            "total_requested": 10,
            "total_deleted": 5,
            "total_failed": 5,
        }

        service = FlowService(repository=mock_flow_repository)
        result = service.bulk_delete_flows(flow_ids)

        # Verify partial success
        assert result["total_requested"] == 10
        assert result["total_deleted"] == 5
        assert result["total_failed"] == 5
        assert len(result["deleted"]) == 5
        assert len(result["failed"]) == 5

        # Verify failed flows have error messages
        for failed_item in result["failed"]:
            assert "flow_id" in failed_item
            assert "error" in failed_item
            assert failed_item["error"]  # Error message is not empty

        # Verify repository was called correctly
        mock_flow_repository.bulk_delete.assert_called_once_with(asset_ids=flow_ids)


class TestFlowServiceList:
    """Tests for FlowService.list_flows method."""

    def test_list_flows_validates_pagination_skip_negative(self, mock_flow_repository):
        """Test that list_flows validates skip parameter."""
        # Arrange
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(FlowInvalidDataException, match="skip must be >= 0"):
            service.list_flows(skip=-1)

    def test_list_flows_validates_pagination_limit_zero(self, mock_flow_repository):
        """Test that list_flows validates limit parameter (zero)."""
        # Arrange
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(FlowInvalidDataException, match="limit must be > 0"):
            service.list_flows(limit=0)

    def test_list_flows_validates_pagination_limit_negative(self, mock_flow_repository):
        """Test that list_flows validates limit parameter (negative)."""
        # Arrange
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert
        with pytest.raises(FlowInvalidDataException, match="limit must be > 0"):
            service.list_flows(limit=-5)

    def test_list_flows_without_filters(self, mock_flow_repository, multiple_sample_flows):
        """Test listing all flows without filters."""
        # Arrange
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.list_flows()

        # Assert
        assert len(result) == 5
        # Flows are sorted newest-first (descending modified_on: 4 -> 0)
        expected = sorted(multiple_sample_flows, key=lambda f: f.modified_on, reverse=True)
        assert result == expected

    def test_list_flows_with_pagination(self, mock_flow_repository, multiple_sample_flows):
        """Test listing flows with pagination."""
        # Arrange
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        # Act - sorted newest-first: Flow 4, Flow 3, Flow 2, Flow 1, Flow 0
        result = service.list_flows(skip=2, limit=2)

        # Assert
        assert len(result) == 2
        assert result[0].name == "Test Flow 2"
        assert result[1].name == "Test Flow 1"

    def test_list_flows_sorted_by_recent_modification(self, mock_flow_repository, multiple_sample_flows):
        """Test that list_flows returns flows sorted newest-first (most recently modified at top)."""
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        result = service.list_flows()

        assert result[0].name == "Test Flow 4"
        assert result[4].name == "Test Flow 0"

    def test_list_flows_with_name_filter(self, mock_flow_repository, multiple_sample_flows):
        """Test listing flows with name filter."""
        # Arrange
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.list_flows(name_filter="Flow 2")

        # Assert
        assert len(result) == 1
        assert result[0].name == "Test Flow 2"

    def test_list_flows_with_tags_filter(self, mock_flow_repository, multiple_sample_flows):
        """Test listing flows with tags filter."""
        # Arrange
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.list_flows(tags_filter=["tag-1"])

        # Assert
        assert len(result) == 1
        assert "tag-1" in result[0].tags

    def test_list_flows_with_is_hidden_filter(self, mock_flow_repository, multiple_sample_flows):
        """Test listing flows with is_hidden filter."""
        # Arrange
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.list_flows(is_hidden=True)

        # Assert
        assert len(result) == 3  # Flows 0, 2, 4 are hidden
        assert all(flow.is_hidden for flow in result)

    def test_list_flows_with_combined_filters(self, mock_flow_repository, multiple_sample_flows):
        """Test listing flows with multiple filters combined."""
        # Arrange
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.list_flows(name_filter="Flow", is_hidden=False, skip=0, limit=10)

        # Assert
        assert len(result) == 2  # Flows 1 and 3 are not hidden
        assert all(not flow.is_hidden for flow in result)


class TestFlowServiceCount:
    """Tests for FlowService.count_flows method."""

    def test_count_flows_without_filters(self, mock_flow_repository, multiple_sample_flows):
        """Test counting all flows without filters."""
        # Arrange
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.count_flows()

        # Assert
        assert result == 5

    def test_count_flows_with_name_filter(self, mock_flow_repository, multiple_sample_flows):
        """Test counting flows with name filter."""
        # Arrange
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.count_flows(name_filter="Flow 2")

        # Assert
        assert result == 1

    def test_count_flows_with_is_hidden_filter(self, mock_flow_repository, multiple_sample_flows):
        """Test counting flows with is_hidden filter."""
        # Arrange
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.count_flows(is_hidden=True)

        # Assert
        assert result == 3


class TestFlowServiceListIsElyra:
    """Tests for is_elyra format filter in list_flows."""

    @pytest.fixture
    def mixed_format_flows(self) -> list:
        """Five flows: 3 authoring (have flow_name in definition), 2 Elyra (do not)."""
        from datetime import UTC, datetime

        from docpipe.core.assets.flows.domain.models.flow import Flow

        flows = []
        for i in range(3):
            flows.append(
                Flow(
                    asset_id=f"authoring-id-{i}",
                    name=f"Authoring Flow {i}",
                    definition={"flow_name": f"Authoring Flow {i}", "flow": []},
                    created_on=datetime(2024, 1, i + 1, tzinfo=UTC),
                    modified_on=datetime(2024, 1, i + 1, tzinfo=UTC),
                )
            )
        for i in range(2):
            flows.append(
                Flow(
                    asset_id=f"elyra-id-{i}",
                    name=f"Elyra Flow {i}",
                    definition={"doc_type": "pipeline", "pipelines": []},
                    created_on=datetime(2024, 2, i + 1, tzinfo=UTC),
                    modified_on=datetime(2024, 2, i + 1, tzinfo=UTC),
                )
            )
        return flows

    def test_list_flows_is_elyra_none_returns_all(self, mock_flow_repository, mixed_format_flows):
        """is_elyra=None returns all flows regardless of format."""
        mock_flow_repository.find_all.return_value = mixed_format_flows
        service = FlowService(repository=mock_flow_repository)

        result = service.list_flows(is_elyra=None)

        assert len(result) == 5

    def test_list_flows_is_elyra_false_returns_authoring_only(self, mock_flow_repository, mixed_format_flows):
        """is_elyra=False returns only authoring-format flows."""
        mock_flow_repository.find_all.return_value = mixed_format_flows
        service = FlowService(repository=mock_flow_repository)

        result = service.list_flows(is_elyra=False)

        assert len(result) == 3
        assert all("flow_name" in f.definition for f in result)

    def test_list_flows_is_elyra_true_returns_elyra_only(self, mock_flow_repository, mixed_format_flows):
        """is_elyra=True returns only Elyra-format flows."""
        mock_flow_repository.find_all.return_value = mixed_format_flows
        service = FlowService(repository=mock_flow_repository)

        result = service.list_flows(is_elyra=True)

        assert len(result) == 2
        assert all("flow_name" not in f.definition for f in result)

    def test_list_flows_is_elyra_filter_applied_before_pagination(self, mock_flow_repository, mixed_format_flows):
        """Format filter is applied before pagination so limit/skip operate on the filtered set."""
        mock_flow_repository.find_all.return_value = mixed_format_flows
        service = FlowService(repository=mock_flow_repository)

        # 3 authoring flows; skip=1, limit=1 should return 1 (not 0)
        result = service.list_flows(is_elyra=False, skip=1, limit=1)

        assert len(result) == 1
        assert "flow_name" in result[0].definition


class TestFlowServiceCountIsElyra:
    """Tests for is_elyra format filter in count_flows."""

    @pytest.fixture
    def mixed_format_flows(self) -> list:
        """Three authoring + two Elyra flows."""
        from datetime import UTC, datetime

        from docpipe.core.assets.flows.domain.models.flow import Flow

        flows = []
        for i in range(3):
            flows.append(
                Flow(
                    asset_id=f"authoring-id-{i}",
                    name=f"Authoring Flow {i}",
                    definition={"flow_name": f"Authoring Flow {i}", "flow": []},
                    created_on=datetime(2024, 1, i + 1, tzinfo=UTC),
                    modified_on=datetime(2024, 1, i + 1, tzinfo=UTC),
                )
            )
        for i in range(2):
            flows.append(
                Flow(
                    asset_id=f"elyra-id-{i}",
                    name=f"Elyra Flow {i}",
                    definition={"doc_type": "pipeline", "pipelines": []},
                    created_on=datetime(2024, 2, i + 1, tzinfo=UTC),
                    modified_on=datetime(2024, 2, i + 1, tzinfo=UTC),
                )
            )
        return flows

    def test_count_flows_is_elyra_none_counts_all(self, mock_flow_repository, mixed_format_flows):
        """is_elyra=None counts all flows."""
        mock_flow_repository.find_all.return_value = mixed_format_flows
        service = FlowService(repository=mock_flow_repository)

        assert service.count_flows(is_elyra=None) == 5

    def test_count_flows_is_elyra_false_counts_authoring(self, mock_flow_repository, mixed_format_flows):
        """is_elyra=False counts only authoring flows."""
        mock_flow_repository.find_all.return_value = mixed_format_flows
        service = FlowService(repository=mock_flow_repository)

        assert service.count_flows(is_elyra=False) == 3

    def test_count_flows_is_elyra_true_counts_elyra(self, mock_flow_repository, mixed_format_flows):
        """is_elyra=True counts only Elyra flows."""
        mock_flow_repository.find_all.return_value = mixed_format_flows
        service = FlowService(repository=mock_flow_repository)

        assert service.count_flows(is_elyra=True) == 2

    def test_count_flows_is_elyra_consistent_with_list_flows(self, mock_flow_repository, mixed_format_flows):
        """count_flows and list_flows return consistent totals for same filters."""
        mock_flow_repository.find_all.return_value = mixed_format_flows
        service = FlowService(repository=mock_flow_repository)

        count = service.count_flows(is_elyra=False)
        listed = service.list_flows(is_elyra=False)

        assert count == len(listed)


class TestFlowServiceExists:
    """Tests for FlowService.flow_exists method."""

    def test_flow_exists_validates_empty_flow_id(self, mock_flow_repository):
        """Test that flow_exists validates empty flow_id."""
        # Arrange
        service = FlowService(repository=mock_flow_repository)

        # Act & Assert - empty string
        with pytest.raises(DocpipeException, match="asset_id cannot be empty"):
            service.flow_exists("")

        # Act & Assert - whitespace only
        with pytest.raises(DocpipeException, match="asset_id cannot be empty"):
            service.flow_exists("   ")

        # Verify repository was never called
        mock_flow_repository.find_by_id.assert_not_called()

    def test_flow_exists_returns_true_for_existing_flow(self, mock_flow_repository):
        """Test flow_exists returns True for existing flow."""
        # Arrange
        mock_flow_repository.exists.return_value = True
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.flow_exists("test-id")

        # Assert
        assert result is True
        mock_flow_repository.exists.assert_called_once_with(asset_id="test-id")

    def test_flow_exists_returns_false_for_nonexistent_flow(self, mock_flow_repository):
        """Test flow_exists returns False for non-existent flow."""
        # Arrange
        mock_flow_repository.exists.return_value = False
        service = FlowService(repository=mock_flow_repository)

        # Act
        result = service.flow_exists("nonexistent-id")

        # Assert
        assert result is False


class TestFlowServiceValidateFlowId:
    """Tests for FlowService._validate_flow_id."""

    def test_validate_flow_id_raises_on_empty_string(self, mock_flow_repository):
        service = FlowService(repository=mock_flow_repository)
        with pytest.raises(FlowInvalidDataException, match="flow_id cannot be empty"):
            service._validate_flow_id("")

    def test_validate_flow_id_raises_on_whitespace(self, mock_flow_repository):
        service = FlowService(repository=mock_flow_repository)
        with pytest.raises(FlowInvalidDataException, match="flow_id cannot be empty"):
            service._validate_flow_id("   ")

    def test_validate_flow_id_returns_id_when_valid(self, mock_flow_repository):
        service = FlowService(repository=mock_flow_repository)
        assert service._validate_flow_id("abc-123") == "abc-123"


class TestFlowServiceMigrateRootPath:
    """Tests for FlowService._migrate_root_path."""

    def test_migrate_root_path_converts_root_path_to_paths_list(self, mock_flow_repository):
        service = FlowService(repository=mock_flow_repository)
        definition = {
            "flow": [
                {
                    "name": "ingest",
                    "config": {
                        "provider": "filesystem",
                        "connection_params": {"root_path": "/data/docs"},
                    },
                }
            ]
        }
        result = service._migrate_root_path(definition)
        conn = result["flow"][0]["config"]["connection_params"]
        assert conn["paths"] == ["/data/docs"]
        assert "root_path" not in conn

    def test_migrate_root_path_skips_nodes_already_using_paths(self, mock_flow_repository):
        service = FlowService(repository=mock_flow_repository)
        definition = {
            "flow": [
                {
                    "name": "ingest",
                    "config": {
                        "provider": "filesystem",
                        "connection_params": {"paths": ["/already/migrated"]},
                    },
                }
            ]
        }
        result = service._migrate_root_path(definition)
        conn = result["flow"][0]["config"]["connection_params"]
        assert conn["paths"] == ["/already/migrated"]
        assert "root_path" not in conn

    def test_migrate_root_path_skips_non_filesystem_nodes(self, mock_flow_repository):
        service = FlowService(repository=mock_flow_repository)
        definition = {
            "flow": [
                {
                    "name": "ingest",
                    "config": {
                        "provider": "s3",
                        "connection_params": {"root_path": "/bucket"},
                    },
                }
            ]
        }
        result = service._migrate_root_path(definition)
        conn = result["flow"][0]["config"]["connection_params"]
        # Non-filesystem node must not be touched
        assert "root_path" in conn
        assert "paths" not in conn

    def test_migrate_root_path_returns_non_dict_definition_unchanged(self, mock_flow_repository):
        service = FlowService(repository=mock_flow_repository)
        assert service._migrate_root_path(None) is None
        assert service._migrate_root_path("raw-string") == "raw-string"

    def test_migrate_root_path_uses_dag_key_when_flow_key_absent(self, mock_flow_repository):
        service = FlowService(repository=mock_flow_repository)
        definition = {
            "dag": [
                {
                    "name": "ingest",
                    "config": {
                        "provider": "filesystem",
                        "connection_params": {"root_path": "/legacy"},
                    },
                }
            ]
        }
        result = service._migrate_root_path(definition)
        conn = result["dag"][0]["config"]["connection_params"]
        assert conn["paths"] == ["/legacy"]
        assert "root_path" not in conn


class TestFlowServicePartialUpdateEdgeCases:
    """Additional edge-case tests for partial_update_flow."""

    def test_partial_update_flow_raises_on_empty_flow_id(self, mock_flow_repository):
        service = FlowService(repository=mock_flow_repository)
        with pytest.raises(FlowInvalidDataException, match="flow_id cannot be empty"):
            service.partial_update_flow("", {"description": "x"})

    def test_partial_update_flow_raises_on_whitespace_flow_id(self, mock_flow_repository):
        service = FlowService(repository=mock_flow_repository)
        with pytest.raises(FlowInvalidDataException, match="flow_id cannot be empty"):
            service.partial_update_flow("   ", {"description": "x"})

    def test_partial_update_flow_returns_existing_when_only_unknown_fields(
        self, mock_flow_repository, sample_flow_with_id
    ):
        """When updates contain only unknown fields, the existing flow is returned unchanged."""
        mock_flow_repository.find_by_id.return_value = sample_flow_with_id
        service = FlowService(repository=mock_flow_repository)

        result = service.partial_update_flow("test-flow-id-123", {"unknown_field_xyz": "value"})

        assert result == sample_flow_with_id
        mock_flow_repository.partial_update.assert_not_called()

    def test_partial_update_flow_returns_existing_when_only_protected_fields(
        self, mock_flow_repository, sample_flow_with_id
    ):
        """When updates contain only protected fields, the existing flow is returned unchanged."""
        mock_flow_repository.find_by_id.return_value = sample_flow_with_id
        service = FlowService(repository=mock_flow_repository)

        result = service.partial_update_flow("test-flow-id-123", {"flow_id": "new-id", "created_by": "hacker"})

        assert result == sample_flow_with_id
        mock_flow_repository.partial_update.assert_not_called()


class TestFlowServiceUpdateFlowIdWhitespace:
    """Whitespace flow_id edge case for update_flow."""

    def test_update_flow_with_whitespace_id_raises_error(self, mock_flow_repository, sample_flow_domain):
        service = FlowService(repository=mock_flow_repository)
        sample_flow_domain.flow_id = "   "
        with pytest.raises(FlowInvalidDataException, match="Flow ID is required for update"):
            service.update_flow(sample_flow_domain)


class TestFlowServiceContainerIdFilter:
    """Tests for container_id filtering in list_flows / count_flows."""

    def test_list_flows_with_container_id_filter(self, mock_flow_repository, multiple_sample_flows):
        """list_flows filters by container_id when provided."""
        # Give one flow a specific container_id
        multiple_sample_flows[0].container_id = "project-abc"
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        result = service.list_flows(container_id="project-abc")

        assert len(result) == 1
        assert result[0].container_id == "project-abc"

    def test_list_flows_container_id_no_match_returns_empty(self, mock_flow_repository, multiple_sample_flows):
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        result = service.list_flows(container_id="nonexistent-container")

        assert result == []

    def test_count_flows_with_container_id_filter(self, mock_flow_repository, multiple_sample_flows):
        multiple_sample_flows[1].container_id = "project-xyz"
        multiple_sample_flows[2].container_id = "project-xyz"
        mock_flow_repository.find_all.return_value = multiple_sample_flows
        service = FlowService(repository=mock_flow_repository)

        assert service.count_flows(container_id="project-xyz") == 2
