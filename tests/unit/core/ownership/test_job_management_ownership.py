# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Ownership tests for JobManagementService create/cancel/delete/list."""

from unittest.mock import Mock

import pytest

from docpipe.core.job_management.application.services.job_management_service import JobManagementService
from docpipe.core.job_management.domain.models import JobStats
from docpipe.exceptions.docpipe_exceptions import JobRunNotFoundException, PermissionDeniedException

_AUTHORING_FLOW = {
    "flow_name": "f",
    "flow": [{"type": "ingest_source", "name": "ingest", "config": {}, "depends_on": []}],
    "global_config": {},
}


class _Config:
    def __init__(self, user_id: str | None) -> None:
        self.user_id = user_id
        self.metadata: dict[str, str] = {}

    def model_dump(self, *, exclude_none: bool = True) -> dict:
        return {"user_id": self.user_id} if self.user_id is not None else {}


def _request(*, client_user_id: str | None = None) -> Mock:
    body = Mock()
    body.entity.job = Mock(asset_ref="flow-1", configuration={})
    body.entity.job_run = Mock(configuration=_Config(client_user_id))
    return body


def _stats(*, user_id: str | None) -> JobStats:
    return JobStats(job_id="j1", job_run_id="r1", flow_id="flow-1", user_id=user_id)


@pytest.fixture
def stats_service() -> Mock:
    return Mock()


@pytest.fixture
def manager() -> Mock:
    return Mock()


@pytest.fixture
def service(stats_service, manager) -> JobManagementService:
    return JobManagementService(
        job_stats_service=stats_service,
        job_run_manager=manager,
        flow_service=Mock(),
        executor=Mock(),
    )


class TestCancelAndDelete:
    @pytest.mark.parametrize("method", ["cancel_job_run", "delete_job_run"])
    def test_owner_allowed(self, service, stats_service, method, alice):
        stats_service.get_job_run_stats.return_value = _stats(user_id="alice")

        getattr(service, method)(job_run_id="r1", actor=alice)

    @pytest.mark.parametrize(
        ("method", "stats_call", "manager_call"),
        [
            ("cancel_job_run", "request_cancel_job", "cancel_job_run"),
            ("delete_job_run", "request_delete_job_run", "delete_job_run"),
        ],
    )
    def test_other_editor_refused_and_run_untouched(
        self, service, stats_service, manager, method, stats_call, manager_call, bob
    ):
        stats_service.get_job_run_stats.return_value = _stats(user_id="alice")

        with pytest.raises(PermissionDeniedException):
            getattr(service, method)(job_run_id="r1", actor=bob)

        getattr(stats_service, stats_call).assert_not_called()
        getattr(manager, manager_call).assert_not_called()

    @pytest.mark.parametrize("method", ["cancel_job_run", "delete_job_run"])
    def test_admin_overrides(self, service, stats_service, method, admin):
        stats_service.get_job_run_stats.return_value = _stats(user_id="alice")

        getattr(service, method)(job_run_id="r1", actor=admin)

    @pytest.mark.parametrize("method", ["cancel_job_run", "delete_job_run"])
    def test_ownerless_run_allowed_for_any_editor(self, service, stats_service, method, bob):
        stats_service.get_job_run_stats.return_value = _stats(user_id=None)

        getattr(service, method)(job_run_id="r1", actor=bob)

    @pytest.mark.parametrize("method", ["cancel_job_run", "delete_job_run"])
    def test_unknown_run_raises_not_found_for_actor(self, service, stats_service, method, alice):
        stats_service.get_job_run_stats.return_value = None

        with pytest.raises(JobRunNotFoundException):
            getattr(service, method)(job_run_id="r1", actor=alice)

    @pytest.mark.parametrize("method", ["cancel_job_run", "delete_job_run"])
    def test_library_path_skips_ownership_lookup(self, service, stats_service, method):
        getattr(service, method)(job_run_id="r1")

        stats_service.get_job_run_stats.assert_not_called()


class TestCreate:
    def _create(self, service, stats_service, manager, *, request, actor):
        service.flow_service.get_flow.return_value = Mock(job_id=None, name="f", definition=_AUTHORING_FLOW)
        manager.create_job_run.return_value = {"job_id": "j1", "job_run_id": "r1"}
        service.create_job_run_from_request(request_body=request, actor=actor)
        return stats_service.start_tracking_job.call_args.kwargs["user_id"]

    def test_actor_overrides_client_user_id(self, service, stats_service, manager, alice):
        user_id = self._create(service, stats_service, manager, request=_request(client_user_id="mallory"), actor=alice)

        assert user_id == "alice"

    def test_no_actor_falls_back_to_client_user_id(self, service, stats_service, manager):
        user_id = self._create(service, stats_service, manager, request=_request(client_user_id="carol"), actor=None)

        assert user_id == "carol"

    def test_no_actor_and_no_client_user_id_is_none(self, service, stats_service, manager):
        user_id = self._create(service, stats_service, manager, request=_request(), actor=None)

        assert user_id is None


class TestList:
    def test_list_includes_user_id(self, service, stats_service):
        stats_service.list_job_runs.return_value = [_stats(user_id="alice")]

        result = service.list_job_runs()

        assert result["list"][0]["user_id"] == "alice"
