# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Ownership tests for ProjectService create/update/delete and the delete cascade."""

import pytest

from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.projects.application.services.project_service import ProjectService
from docpipe.core.projects.domain.models.project import Project
from docpipe.exceptions.docpipe_exceptions import PermissionDeniedException
from tests.unit.core.ownership.conftest import make_flow


@pytest.fixture
def service(project_repo, flow_repo, flow_service, job_stats_service) -> ProjectService:
    return ProjectService(
        repository=project_repo,  # type: ignore[arg-type]
        flow_repository=flow_repo,  # type: ignore[arg-type]
        flow_service=flow_service,
        job_stats_service=job_stats_service,
    )


def _project(project_id: str = "p1", *, created_by: str | None = None) -> Project:
    return Project(project_id=project_id, name=f"project-{project_id}", created_by=created_by)


class TestCreate:
    def test_actor_sets_created_by(self, service, alice):
        created = service.create_project(project=_project(created_by="mallory"), actor=alice)

        assert created.created_by == "alice"

    def test_no_actor_leaves_created_by_untouched(self, service):
        created = service.create_project(project=_project())

        assert created.created_by is None


class TestUpdate:
    def test_owner_full_update_sets_modified_by(self, service, project_repo, alice):
        project_repo.save(project=_project(created_by="alice"))
        incoming = _project()
        incoming.modified_by = "mallory"

        updated = service.update_project(project=incoming, actor=alice)

        assert updated.modified_by == "alice"

    def test_other_editor_cannot_full_update(self, service, project_repo, bob):
        project_repo.save(project=_project(created_by="alice"))

        with pytest.raises(PermissionDeniedException):
            service.update_project(project=_project(), actor=bob)

    def test_owner_partial_update_ignores_client_modified_by(self, service, project_repo, alice):
        project_repo.save(project=_project(created_by="alice"))

        updated = service.partial_update_project(
            project_id="p1", updates={"description": "d", "modified_by": "mallory"}, actor=alice
        )

        assert updated.description == "d"
        assert updated.modified_by == "alice"

    def test_other_editor_cannot_partial_update(self, service, project_repo, bob):
        project_repo.save(project=_project(created_by="alice"))

        with pytest.raises(PermissionDeniedException):
            service.partial_update_project(project_id="p1", updates={"description": "d"}, actor=bob)

        assert project_repo.projects["p1"].description != "d"

    def test_admin_can_update_any(self, service, project_repo, admin):
        project_repo.save(project=_project(created_by="alice"))

        updated = service.partial_update_project(project_id="p1", updates={"description": "d"}, actor=admin)

        assert updated.modified_by == "root"

    def test_ownerless_project_editable_by_any_editor(self, service, project_repo, bob):
        project_repo.save(project=_project(created_by=None))

        updated = service.partial_update_project(project_id="p1", updates={"description": "d"}, actor=bob)

        assert updated.modified_by == "bob"

    def test_library_path_without_actor(self, service, project_repo):
        project_repo.save(project=_project(created_by="alice"))

        updated = service.partial_update_project(project_id="p1", updates={"description": "d"})

        assert updated.description == "d"
        assert updated.modified_by is None


class TestDelete:
    def test_owner_deletes_project_and_own_flows(self, service, project_repo, flow_repo, alice):
        project_repo.save(project=_project(created_by="alice"))
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice", container_id="p1"))

        service.delete_project(project_id="p1", actor=alice)

        assert "p1" not in project_repo.projects
        assert "f1" not in flow_repo.flows

    def test_other_editor_cannot_delete_project(self, service, project_repo, flow_repo, bob):
        project_repo.save(project=_project(created_by="alice"))
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="bob", container_id="p1"))

        with pytest.raises(PermissionDeniedException):
            service.delete_project(project_id="p1", actor=bob)

        assert "p1" in project_repo.projects
        assert "f1" in flow_repo.flows

    def test_foreign_owned_child_flow_blocks_delete_and_nothing_is_deleted(
        self, service, project_repo, flow_repo, alice
    ):
        project_repo.save(project=_project(created_by="alice"))
        flow_repo.save(asset=make_flow(flow_id="mine", created_by="alice", container_id="p1"))
        flow_repo.save(asset=make_flow(flow_id="theirs", created_by="bob", container_id="p1"))

        with pytest.raises(PermissionDeniedException):
            service.delete_project(project_id="p1", actor=alice)

        assert "p1" in project_repo.projects
        assert set(flow_repo.flows) == {"mine", "theirs"}

    def test_admin_deletes_project_with_foreign_flows(self, service, project_repo, flow_repo, admin):
        project_repo.save(project=_project(created_by="alice"))
        flow_repo.save(asset=make_flow(flow_id="theirs", created_by="bob", container_id="p1"))

        service.delete_project(project_id="p1", actor=admin)

        assert "p1" not in project_repo.projects
        assert "theirs" not in flow_repo.flows

    def test_cascade_calls_bulk_delete_with_actor_none(self, project_repo, flow_repo, job_stats_service, mocker, alice):
        flow_service = mocker.Mock(spec=FlowService)
        flow_service.bulk_delete_flows.return_value = {"total_failed": 0, "total_deleted": 1, "failed": []}
        service = ProjectService(
            repository=project_repo,  # type: ignore[arg-type]
            flow_repository=flow_repo,  # type: ignore[arg-type]
            flow_service=flow_service,
            job_stats_service=job_stats_service,
        )
        project_repo.save(project=_project(created_by="alice"))
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice", container_id="p1"))

        service.delete_project(project_id="p1", actor=alice)

        flow_service.bulk_delete_flows.assert_called_once_with(flow_ids=["f1"], actor=None)

    def test_library_path_without_actor_ignores_ownership(self, service, project_repo, flow_repo):
        project_repo.save(project=_project(created_by="alice"))
        flow_repo.save(asset=make_flow(flow_id="theirs", created_by="bob", container_id="p1"))

        service.delete_project(project_id="p1")

        assert "p1" not in project_repo.projects
        assert "theirs" not in flow_repo.flows
