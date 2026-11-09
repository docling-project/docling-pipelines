# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Ownership tests for FlowService create/update/delete/bulk-delete."""

import pytest

from docpipe.core.models.ownership import PERMISSION_DENIED_MESSAGE
from docpipe.exceptions.docpipe_exceptions import PermissionDeniedException
from tests.unit.core.ownership.conftest import make_flow


class TestCreate:
    def test_actor_sets_created_by(self, flow_service, alice):
        flow = make_flow(flow_id="f1")

        created = flow_service.create_flow(flow=flow, actor=alice)

        assert created.created_by == "alice"

    def test_actor_overrides_client_supplied_created_by(self, flow_service, alice):
        flow = make_flow(flow_id="f1", created_by="mallory")

        created = flow_service.create_flow(flow=flow, actor=alice)

        assert created.created_by == "alice"

    def test_no_actor_leaves_created_by_empty(self, flow_service):
        created = flow_service.create_flow(flow=make_flow(flow_id="f1"))

        assert created.created_by is None


class TestUpdate:
    def test_owner_update_sets_modified_by(self, flow_service, flow_repo, alice):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

        updated = flow_service.update_flow(make_flow(flow_id="f1"), actor=alice)

        assert updated.modified_by == "alice"
        assert updated.created_by == "alice"

    def test_modified_by_in_body_is_ignored(self, flow_service, flow_repo, alice):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))
        incoming = make_flow(flow_id="f1")
        incoming.modified_by = "mallory"

        updated = flow_service.update_flow(incoming, actor=alice)

        assert updated.modified_by == "alice"

    def test_other_editor_refused_and_flow_unchanged(self, flow_service, flow_repo, bob):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))
        incoming = make_flow(flow_id="f1")
        incoming.description = "changed"

        with pytest.raises(PermissionDeniedException):
            flow_service.update_flow(incoming, actor=bob)

        assert flow_repo.flows["f1"].description != "changed"

    def test_ownerless_flow_is_editable_by_any_editor(self, flow_service, flow_repo, bob):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by=None))

        updated = flow_service.update_flow(make_flow(flow_id="f1"), actor=bob)

        assert updated.modified_by == "bob"

    def test_admin_overrides_ownership(self, flow_service, flow_repo, admin):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

        updated = flow_service.update_flow(make_flow(flow_id="f1"), actor=admin)

        assert updated.modified_by == "root"
        assert updated.created_by == "alice"

    def test_viewer_refused(self, flow_service, flow_repo, viewer):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="vera"))

        with pytest.raises(PermissionDeniedException):
            flow_service.update_flow(make_flow(flow_id="f1"), actor=viewer)

    def test_no_actor_updates_regardless_of_owner(self, flow_service, flow_repo):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

        updated = flow_service.update_flow(make_flow(flow_id="f1"))

        assert updated.created_by == "alice"
        assert updated.modified_by is None


class TestPartialUpdate:
    def test_owner_partial_update_sets_modified_by_over_client_value(self, flow_service, flow_repo, alice):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

        updated = flow_service.partial_update_flow("f1", {"description": "x", "modified_by": "mallory"}, actor=alice)

        assert updated.description == "x"
        assert updated.modified_by == "alice"

    def test_other_editor_refused(self, flow_service, flow_repo, bob):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

        with pytest.raises(PermissionDeniedException):
            flow_service.partial_update_flow("f1", {"description": "x"}, actor=bob)

        assert flow_repo.flows["f1"].description != "x"

    def test_no_actor_keeps_library_behaviour(self, flow_service, flow_repo):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

        updated = flow_service.partial_update_flow("f1", {"description": "x"})

        assert updated.description == "x"


class TestDelete:
    def test_owner_deletes(self, flow_service, flow_repo, alice):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

        assert flow_service.delete_flow("f1", actor=alice) is True
        assert "f1" not in flow_repo.flows

    def test_other_editor_refused_and_flow_remains(self, flow_service, flow_repo, bob):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

        with pytest.raises(PermissionDeniedException) as exc_info:
            flow_service.delete_flow("f1", actor=bob)

        assert "f1" in flow_repo.flows
        assert "alice" not in str(exc_info.value)

    def test_admin_deletes_any(self, flow_service, flow_repo, admin):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

        assert flow_service.delete_flow("f1", actor=admin) is True

    def test_library_path_without_actor_deletes_owned_flow(self, flow_service, flow_repo):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

        assert flow_service.delete_flow("f1") is True
        assert "f1" not in flow_repo.flows


class TestBulkDelete:
    def test_mixed_bulk_delete_reports_refused_flow_without_naming_owner(self, flow_service, flow_repo, alice):
        flow_repo.save(asset=make_flow(flow_id="own1", created_by="alice"))
        flow_repo.save(asset=make_flow(flow_id="own2", created_by="alice"))
        flow_repo.save(asset=make_flow(flow_id="foreign", created_by="bob-the-owner"))

        result = flow_service.bulk_delete_flows(["own1", "foreign", "own2"], actor=alice)

        assert sorted(result["deleted"]) == ["own1", "own2"]
        assert result["failed"] == [{"flow_id": "foreign", "error": PERMISSION_DENIED_MESSAGE}]
        assert result["total_requested"] == 3
        assert result["total_deleted"] == 2
        assert result["total_failed"] == 1
        assert "bob-the-owner" not in str(result)
        assert "foreign" in flow_repo.flows

    def test_all_refused_does_not_touch_repository(self, flow_service, flow_repo, bob):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

        result = flow_service.bulk_delete_flows(["f1"], actor=bob)

        assert result["total_deleted"] == 0
        assert result["total_failed"] == 1
        assert "f1" in flow_repo.flows

    def test_no_actor_deletes_everything(self, flow_service, flow_repo):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))
        flow_repo.save(asset=make_flow(flow_id="f2", created_by="bob"))

        result = flow_service.bulk_delete_flows(["f1", "f2"])

        assert result["total_deleted"] == 2
        assert result["total_failed"] == 0

    def test_admin_deletes_foreign_flows(self, flow_service, flow_repo, admin):
        flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

        result = flow_service.bulk_delete_flows(["f1"], actor=admin)

        assert result["deleted"] == ["f1"]
