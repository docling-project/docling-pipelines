"""Tests for job run API routes."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.auth.models import User
from docpipe.api.dependencies import get_job_management_service, get_job_stats_service
from docpipe.api.main import app
from docpipe.core.constants.constants import ExecutionStatus
from docpipe.exceptions.docpipe_exceptions import JobRunNotFoundException, JobRunOperationFailedException


@pytest.fixture
def client():
    """Create test client with auth bypassed."""
    app.dependency_overrides[get_current_user] = lambda: User(
        username="testuser", email="test@example.com", full_name="Test User"
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def mock_job_management_service():
    """Mock job management service."""
    service = Mock()
    app.dependency_overrides[get_job_management_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_job_management_service, None)


@pytest.fixture
def mock_job_stats_service():
    """Mock job stats service."""
    service = Mock()
    app.dependency_overrides[get_job_stats_service] = lambda: service
    return service


class TestCreateJobRun:
    """Tests for create_job_run endpoint."""

    def test_create_job_run_enterprise_format(self, client, mock_job_management_service):
        """Test creating job run with enterprise format."""
        mock_job_management_service.create_job_run_from_request.return_value = {
            "job_id": "66666666-6666-6666-6666-666666666666",
            "job_run_id": "33333333-3333-3333-3333-333333333333",
        }

        response = client.post(
            "/api/v1/job_runs",
            json={
                "entity": {
                    "job": {
                        "asset_ref": "66666666-6666-6666-6666-666666666666",
                        "name": "Test Flow",
                        "configuration": {"batch_size": "100"},
                    },
                    "job_run": {"configuration": {"user_id": "user123"}},
                }
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["job_run_id"] == "33333333-3333-3333-3333-333333333333"
        assert data["status"] in [
            ExecutionStatus.RUNNING.value,
            ExecutionStatus.STARTING.value,
        ]
        assert "successfully" in data["message"].lower()

    def test_create_job_run_legacy_format(self, client, mock_job_management_service):
        """Test creating job run with legacy format (backward compatibility)."""
        mock_job_management_service.create_job_run_from_request.return_value = {
            "job_id": "77777777-7777-7777-7777-777777777777",
            "job_run_id": "44444444-4444-4444-4444-444444444444",
        }

        response = client.post(
            "/api/v1/job_runs",
            json={
                "job_id": "77777777-7777-7777-7777-777777777777",
                "flow_name": "Legacy Flow",
                "flow_config": {"batch_size": "50"},
                "metadata": {"source": "legacy"},
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["job_run_id"] == "44444444-4444-4444-4444-444444444444"
        assert data["status"] in [
            ExecutionStatus.RUNNING.value,
            ExecutionStatus.STARTING.value,
        ]

    def test_create_job_run_missing_asset_ref(self, client):
        """Test creating job run without required asset_ref."""
        response = client.post(
            "/api/v1/job_runs",
            json={"entity": {"job": {"name": "Test"}, "job_run": {}}},
        )

        assert response.status_code == 404
        assert "asset_ref" in response.text.lower()

    def test_create_job_run_service_error(self, client, mock_job_management_service):
        """Test handling service errors during job run creation."""
        from docpipe.exceptions.docpipe_exceptions import JobRunOperationFailedException

        mock_job_management_service.create_job_run_from_request.side_effect = JobRunOperationFailedException(
            "Database error"
        )

        response = client.post(
            "/api/v1/job_runs",
            json={
                "entity": {
                    "job": {
                        "asset_ref": "66666666-6666-6666-6666-666666666666",
                        "configuration": {},
                    },
                    "job_run": {},
                }
            },
        )

        assert response.status_code == 500
        assert "failed" in response.text.lower()


class TestListJobRuns:
    """Tests for list_job_runs endpoint."""

    def test_list_job_runs_success(self, client, mock_job_management_service):
        """Test listing job runs successfully."""
        mock_job_management_service.list_job_runs.return_value = {
            "list": [
                {
                    "job_run_id": "11111111-1111-1111-1111-111111111111",
                    "job_id": "88888888-8888-8888-8888-888888888888",
                    "status": ExecutionStatus.COMPLETED,
                },
                {
                    "job_run_id": "22222222-2222-2222-2222-222222222222",
                    "job_id": "99999999-9999-9999-9999-999999999999",
                    "status": ExecutionStatus.RUNNING,
                },
            ],
            "count": 2,
            "total": 2,
        }

        response = client.get("/api/v1/job_runs")

        assert response.status_code == 200
        data = response.json()
        assert "list" in data
        assert "count" in data
        assert "total" in data
        assert data["count"] == 2
        assert len(data["list"]) == 2

    def test_list_job_runs_with_filters(self, client, mock_job_management_service):
        """Test listing job runs with query filters."""
        mock_job_management_service.list_job_runs.return_value = {
            "list": [],
            "count": 0,
            "total": 0,
        }

        response = client.get("/api/v1/job_runs?job_id=66666666-6666-6666-6666-666666666666&status=Completed&limit=50")

        assert response.status_code == 200
        mock_job_management_service.list_job_runs.assert_called_once_with(
            job_id="66666666-6666-6666-6666-666666666666",
            status=None,
            limit=50,
        )

    def test_list_job_runs_service_error(self, client, mock_job_management_service):
        """Test handling service errors during listing."""
        mock_job_management_service.list_job_runs.side_effect = JobRunOperationFailedException("Database error")

        response = client.get("/api/v1/job_runs")

        assert response.status_code == 500
        assert "failed" in response.text.lower()


class TestGetJobRunStatus:
    """Tests for get_job_run_status endpoint."""

    def test_get_job_run_status_success(self, client, mock_job_stats_service):
        """Test getting job run status successfully without logs by default."""
        mock_job_stats_service.get_formatted_job_stats.return_value = {
            "job_run_id": "12345678-1234-1234-1234-123456789abc",
            "status": ExecutionStatus.RUNNING,
            "node_sequence": [],
            "job_stats": {
                "job_run_id": "12345678-1234-1234-1234-123456789abc",
                "job_id": "88888888-8888-8888-8888-888888888888",
                "status": ExecutionStatus.RUNNING,
                "start_time": 0,
                "orchestrator": "Python",
            },
            "node_metadata": [],
            "logs": [],
        }

        response = client.get("/api/v1/job_runs/12345678-1234-1234-1234-123456789abc")

        assert response.status_code == 200
        data = response.json()
        assert data["job_run_id"] == "12345678-1234-1234-1234-123456789abc"
        assert data["status"] in [
            ExecutionStatus.RUNNING.value,
            ExecutionStatus.STARTING.value,
        ]
        assert data["logs"] == []

    def test_get_job_run_status_with_logs(self, client, mock_job_stats_service):
        """Test getting job run status with synthesized logs when requested."""
        mock_job_stats_service.get_formatted_job_stats.return_value = {
            "job_run_id": "12345678-1234-1234-1234-123456789abc",
            "status": "Running",
            "node_sequence": [],
            "job_stats": {
                "job_run_id": "12345678-1234-1234-1234-123456789abc",
                "job_id": "88888888-8888-8888-8888-888888888888",
                "status": ExecutionStatus.RUNNING,
                "start_time": 0,
                "orchestrator": "Python",
            },
            "node_metadata": [],
            "logs": [
                "Starting execution: Step Name: extract",
                "Completed execution: extract, Time = 5.00 seconds",
            ],
        }

        response = client.get("/api/v1/job_runs/12345678-1234-1234-1234-123456789abc?include_logs=true")

        assert response.status_code == 200
        data = response.json()
        assert data["job_run_id"] == "12345678-1234-1234-1234-123456789abc"
        assert data["status"] in ["Running", "Starting"]
        assert data["logs"] == [
            "Starting execution: Step Name: extract",
            "Completed execution: extract, Time = 5.00 seconds",
        ]

    def test_get_job_run_status_not_found(self, client, mock_job_stats_service):
        """Test getting status for non-existent job run."""
        from docpipe.exceptions.docpipe_exceptions import JobRunNotFoundException

        mock_job_stats_service.get_formatted_job_stats.side_effect = JobRunNotFoundException(
            "Job run not found: 00000000-0000-0000-0000-000000000000",
            job_run_id="00000000-0000-0000-0000-000000000000",
        )

        response = client.get("/api/v1/job_runs/00000000-0000-0000-0000-000000000000")

        assert response.status_code == 404
        assert "not found" in response.text.lower()

    def test_get_job_run_status_service_error(self, client, mock_job_stats_service):
        """Test handling service errors during status retrieval."""
        mock_job_stats_service.get_formatted_job_stats.side_effect = JobRunOperationFailedException("Database error")

        response = client.get("/api/v1/job_runs/12345678-1234-1234-1234-123456789abc")

        assert response.status_code == 500
        assert "failed" in response.text.lower()


class TestCancelJobRun:
    """Tests for cancel_job_run endpoint."""

    def test_cancel_job_run_success(self, client, mock_job_management_service):
        """Test canceling a job run successfully."""
        response = client.post("/api/v1/job_runs/12345678-1234-1234-1234-123456789abc/cancel")

        assert response.status_code == 202
        data = response.json()
        assert data["job_run_id"] == "12345678-1234-1234-1234-123456789abc"
        assert data["status"] == ExecutionStatus.CANCELING.value
        assert "cancellation requested" in data["message"].lower()

    def test_cancel_job_run_not_found(self, client, mock_job_management_service):
        """Test cancelling non-existent job run."""
        from docpipe.exceptions.docpipe_exceptions import JobRunNotFoundException

        mock_job_management_service.cancel_job_run.side_effect = JobRunNotFoundException(
            "Job run not found: 00000000-0000-0000-0000-000000000000",
            job_run_id="00000000-0000-0000-0000-000000000000",
        )

        response = client.post("/api/v1/job_runs/00000000-0000-0000-0000-000000000000/cancel")

        assert response.status_code == 404
        assert "not found" in response.text.lower()

    def test_cancel_job_run_service_error(self, client, mock_job_management_service):
        """Test handling service errors during cancellation."""
        mock_job_management_service.cancel_job_run.side_effect = JobRunOperationFailedException("Cancellation failed")

        response = client.post("/api/v1/job_runs/12345678-1234-1234-1234-123456789abc/cancel")

        assert response.status_code == 500
        assert "failed" in response.text.lower()


class TestDeleteJobRun:
    """Tests for delete_job_run endpoint."""

    def test_delete_job_run_success(self, client, mock_job_management_service):
        """Test deleting job run successfully."""
        mock_job_management_service.delete_job_run.return_value = None

        response = client.delete("/api/v1/job_runs/12345678-1234-1234-1234-123456789abc")

        assert response.status_code == 204
        assert response.content == b""

    def test_delete_job_run_not_found(self, client, mock_job_management_service):
        """Test deleting non-existent job run."""
        from docpipe.exceptions.docpipe_exceptions import JobRunNotFoundException

        mock_job_management_service.delete_job_run.side_effect = JobRunNotFoundException(
            "Job run not found: 00000000-0000-0000-0000-000000000000",
            job_run_id="00000000-0000-0000-0000-000000000000",
        )

        response = client.delete("/api/v1/job_runs/00000000-0000-0000-0000-000000000000")

        assert response.status_code == 404
        assert "not found" in response.text.lower()

    def test_delete_job_run_service_error(self, client, mock_job_management_service):
        """Test handling service errors during deletion."""
        mock_job_management_service.delete_job_run.side_effect = JobRunOperationFailedException("Deletion failed")

        response = client.delete("/api/v1/job_runs/12345678-1234-1234-1234-123456789abc")

        assert response.status_code == 500
        assert "failed" in response.text.lower()


class TestErrorHandling:
    """Tests for error handling consistency across routes."""

    def test_all_routes_return_error_response_format(self, client, mock_job_management_service, mock_job_stats_service):
        """Test that all routes return consistent error format."""
        # Mock for routes using JobManagementService
        mock_job_management_service.create_job_run_from_request.side_effect = JobRunOperationFailedException("Error")
        mock_job_management_service.list_job_runs.side_effect = JobRunOperationFailedException("Error")
        mock_job_management_service.cancel_job_run.side_effect = JobRunOperationFailedException("Error")
        mock_job_management_service.delete_job_run.side_effect = JobRunOperationFailedException("Error")

        # Mock for routes using JobStatsService
        mock_job_stats_service.get_formatted_job_stats.side_effect = JobRunOperationFailedException("Error")

        endpoints = [
            (
                "POST",
                "/api/v1/job_runs",
                {"entity": {"job": {"asset_ref": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}}},
            ),
            ("GET", "/api/v1/job_runs/55555555-5555-5555-5555-555555555555", None),
            (
                "POST",
                "/api/v1/job_runs/55555555-5555-5555-5555-555555555555/cancel",
                None,
            ),
            ("DELETE", "/api/v1/job_runs/55555555-5555-5555-5555-555555555555", None),
        ]

        for method, url, json_data in endpoints:
            response = None
            if method == "POST":
                response = client.post(url, json=json_data)
            elif method == "GET":
                response = client.get(url)
            elif method == "DELETE":
                response = client.delete(url)

            assert response is not None
            assert response.status_code in [404, 500]
            error_data = response.json()
            assert "errors" in error_data
            assert isinstance(error_data["errors"], list)
            assert error_data["errors"]
            assert "code" in error_data["errors"][0]
            assert "message" in error_data["errors"][0]


class TestReportAndFlowDefinition:
    """GET /job_runs/{id}/report and /job_runs/{id}/flow_definition."""

    _JOB_RUN_ID = "33333333-3333-4333-8333-333333333333"

    def test_report_for_unknown_job_run_returns_404(self, client, mock_job_stats_service):
        mock_job_stats_service.get_job.return_value = None

        response = client.get(f"/api/v1/job_runs/{self._JOB_RUN_ID}/report")

        assert response.status_code == 404
        mock_job_stats_service.get_job.assert_called_once_with(job_run_id=self._JOB_RUN_ID, include_node_stats=False)

    def test_report_for_running_job_returns_425(self, client, mock_job_stats_service):
        mock_job_stats_service.get_job.return_value = Mock(status=ExecutionStatus.RUNNING.value, job_id="job-1")

        response = client.get(f"/api/v1/job_runs/{self._JOB_RUN_ID}/report")

        assert response.status_code == 425

    def test_flow_definition_is_returned_as_json(self, client, mock_job_stats_service):
        definition = {"flow_name": "snapshot", "flow": [{"type": "ingest_source", "name": "ingest"}]}
        mock_job_stats_service.get_flow_definition.return_value = definition

        response = client.get(f"/api/v1/job_runs/{self._JOB_RUN_ID}/flow_definition")

        assert response.status_code == 200
        assert response.json() == definition
        mock_job_stats_service.get_flow_definition.assert_called_once_with(job_run_id=self._JOB_RUN_ID)

    def test_flow_definition_for_unknown_job_run_returns_404(self, client, mock_job_stats_service):
        mock_job_stats_service.get_flow_definition.side_effect = JobRunNotFoundException(
            message="Job run not found", job_run_id=self._JOB_RUN_ID
        )

        response = client.get(f"/api/v1/job_runs/{self._JOB_RUN_ID}/flow_definition")

        assert response.status_code == 404
