# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Log-capture tests for the audit trail."""

import logging

import pytest

from docpipe.core.projects.application.services.project_service import ProjectService
from docpipe.core.projects.domain.models.project import Project
from docpipe.exceptions.docpipe_exceptions import FlowNotFoundException, PermissionDeniedException
from docpipe.utils.infrastructure.audit import sanitize_for_log
from tests.unit.core.ownership.conftest import make_actor, make_flow

AUDIT_LOGGER = "docpipe.audit"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.messages: list[str] = []
        self.levels: list[int] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())
        self.levels.append(record.levelno)


@pytest.fixture
def audit_handler():
    # Own handler with propagation off, so the result does not depend on whether other
    # tests left the parent "docpipe" logger propagating (which would double-capture).
    handler = _ListHandler()
    audit_logger = logging.getLogger(AUDIT_LOGGER)
    previous_level, previous_propagate = audit_logger.level, audit_logger.propagate
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False
    audit_logger.addHandler(handler)
    yield handler
    audit_logger.removeHandler(handler)
    audit_logger.setLevel(previous_level)
    audit_logger.propagate = previous_propagate


def _audit_lines(handler: _ListHandler) -> list[str]:
    return handler.messages


def test_successful_create_is_audited(flow_service, alice, audit_handler):
    created = flow_service.create_flow(flow=make_flow(flow_id="f1"), actor=alice)

    assert _audit_lines(audit_handler) == [
        f"AUDIT user=alice action=flow.create target={created.flow_id} outcome=success status=-"
    ]


def test_denial_is_audited_with_user_action_target_and_outcome(flow_service, flow_repo, bob, audit_handler):
    flow_repo.save(asset=make_flow(flow_id="f1", created_by="alice"))

    with pytest.raises(PermissionDeniedException):
        flow_service.delete_flow("f1", actor=bob)

    lines = _audit_lines(audit_handler)
    assert lines == ["AUDIT user=bob action=flow.delete target=f1 outcome=denied status=403"]
    assert "alice" not in lines[0]
    assert audit_handler.levels == [logging.WARNING]


def test_failed_write_is_audited_with_status_code(flow_service, alice, audit_handler):
    with pytest.raises(FlowNotFoundException):
        flow_service.update_flow(make_flow(flow_id="missing"), actor=alice)

    assert _audit_lines(audit_handler) == [
        "AUDIT user=alice action=flow.update target=missing outcome=failed status=404"
    ]


def test_newline_in_username_is_removed(flow_service, audit_handler):
    actor = make_actor("eve\nAUDIT user=root action=flow.delete", "editor")

    flow_service.create_flow(flow=make_flow(flow_id="f1"), actor=actor)

    lines = _audit_lines(audit_handler)
    assert len(lines) == 1
    assert "\n" not in lines[0]
    assert "\r" not in lines[0]


def test_library_path_is_audited_without_user(flow_service, audit_handler):
    flow_service.create_flow(flow=make_flow(flow_id="f1"))

    assert _audit_lines(audit_handler)[0].startswith("AUDIT user=- action=flow.create")


def test_bulk_delete_audits_each_flow(flow_service, flow_repo, alice, audit_handler):
    flow_repo.save(asset=make_flow(flow_id="own", created_by="alice"))
    flow_repo.save(asset=make_flow(flow_id="foreign", created_by="bob"))

    flow_service.bulk_delete_flows(["own", "foreign"], actor=alice)

    assert sorted(_audit_lines(audit_handler)) == [
        "AUDIT user=alice action=flow.bulk_delete target=foreign outcome=denied status=403",
        "AUDIT user=alice action=flow.bulk_delete target=own outcome=success status=-",
    ]


def test_project_create_audit_records_new_project_id(
    project_repo, flow_repo, flow_service, job_stats_service, alice, audit_handler
):
    service = ProjectService(
        repository=project_repo,  # type: ignore[arg-type]
        flow_repository=flow_repo,  # type: ignore[arg-type]
        flow_service=flow_service,
        job_stats_service=job_stats_service,
    )

    created = service.create_project(project=Project(name="p"), actor=alice)

    assert _audit_lines(audit_handler) == [
        f"AUDIT user=alice action=project.create target={created.project_id} outcome=success status=-"
    ]


def test_audit_line_contains_no_secret_fields(flow_service, alice, audit_handler):
    flow_service.create_flow(flow=make_flow(flow_id="f1"), actor=alice)

    line = _audit_lines(audit_handler)[0]
    assert "password" not in line.lower()
    assert "token" not in line.lower()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("plain", "plain"), ("a\nb", "ab"), ("a\r\nb\tc", "abc"), ("x\x00y\x1bz", "xyz"), ("a\u2028b", "ab")],
)
def test_sanitize_for_log(raw, expected):
    assert sanitize_for_log(raw) == expected
