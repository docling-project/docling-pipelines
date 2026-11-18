# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for FlowService authoring-format updates, validation wrapping and legacy migration."""

from unittest.mock import Mock

import pytest

from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.core.models.actor_context import ROLE_EDITOR, SYSTEM_ACTOR, ActorContext
from docpipe.exceptions.docpipe_exceptions import DocpipeException, FlowInvalidDataException

FLOW_ID = "12345678-1234-1234-1234-123456789abc"

_INGEST = {"type": "ingest_source", "name": "ingest", "config": {}, "depends_on": []}
_CHUNKER = {"type": "chunker", "name": "chunk", "config": {"size": 10}, "depends_on": ["ingest"]}


@pytest.fixture
def repository():
    """Mock flow repository whose partial_update echoes the updates it received."""
    repo = Mock()
    repo.partial_update.side_effect = lambda flow, updates: flow
    return repo


@pytest.fixture
def service(repository):
    """FlowService backed by the mock repository."""
    return FlowService(repository=repository)


def _authoring_flow():
    """Return a stored flow whose definition is in authoring format."""
    return Flow(
        asset_id=FLOW_ID,
        name="orig",
        description="original description",
        tags=["t1"],
        definition={
            "flow_name": "orig",
            "flow": [dict(_INGEST)],
            "global_config": {"doc_column": "content"},
        },
    )


def _operator_view(operators):
    """Reduce dumped operators to the fields the authoring format defines."""
    return [{key: op[key] for key in ("type", "name", "config", "depends_on")} for op in operators]


class TestPartialUpdateAuthoringFields:
    """Tests for rebuilding the authoring definition during partial_update_flow."""

    def test_flow_name_update_renames_and_rebuilds_definition(self, service, repository):
        """flow_name maps to name and the definition is rebuilt from the stored authoring data."""
        existing = _authoring_flow()
        repository.find_by_id.return_value = existing

        service.partial_update_flow(FLOW_ID, {"flow_name": "renamed"}, actor=SYSTEM_ACTOR)

        repository.partial_update.assert_called_once()
        passed_flow, updates = repository.partial_update.call_args.args
        assert passed_flow is existing
        assert set(updates) == {"name", "definition"}
        assert updates["name"] == "renamed"
        definition = updates["definition"]
        assert definition["flow_name"] == "renamed"
        assert definition["description"] == "original description"
        assert definition["global_config"] == {"doc_column": "content"}
        assert definition["tags"] == ["t1"]
        assert _operator_view(definition["flow"]) == [_INGEST]

    def test_flow_and_global_config_replace_non_authoring_definition(self, service, repository):
        """With a non-dict stored definition, the flow name falls back to the flow's name."""
        existing = Flow(asset_id=FLOW_ID, name="legacy", definition=["not-a-dict"])  # type: ignore[arg-type]
        repository.find_by_id.return_value = existing

        service.partial_update_flow(
            FLOW_ID,
            {"flow": [_INGEST, _CHUNKER], "global_config": {"enable_micro_batching": False}},
            actor=SYSTEM_ACTOR,
        )

        _, updates = repository.partial_update.call_args.args
        assert set(updates) == {"definition"}
        definition = updates["definition"]
        assert definition["flow_name"] == "legacy"
        assert definition["global_config"] == {"enable_micro_batching": False}
        assert _operator_view(definition["flow"]) == [_INGEST, _CHUNKER]

    def test_invalid_authoring_flow_is_rejected_before_persisting(self, service, repository):
        """An authoring update that fails AuthoringFlow validation never reaches the repository."""
        repository.find_by_id.return_value = _authoring_flow()
        broken = {"type": "chunker", "name": "chunk", "config": {}, "depends_on": ["missing"]}

        with pytest.raises(FlowInvalidDataException, match="Dependency 'missing' not found"):
            service.partial_update_flow(FLOW_ID, {"flow": [_INGEST, broken]}, actor=SYSTEM_ACTOR)

        repository.partial_update.assert_not_called()


class TestValueErrorWrapping:
    """Tests that plain ValueErrors from Flow.validate are wrapped as FlowInvalidDataException."""

    def test_create_flow_wraps_value_error(self, service, repository):
        """create_flow converts a ValueError from validate() and does not save."""
        flow = Mock(spec=Flow)
        flow.validate.side_effect = ValueError("boom")

        with pytest.raises(FlowInvalidDataException, match="Invalid flow data: boom"):
            service.create_flow(flow=flow, actor=SYSTEM_ACTOR)

        repository.save.assert_not_called()

    def test_update_flow_wraps_value_error(self, service, repository):
        """update_flow converts a ValueError from validate() and does not touch the repository."""
        flow = Mock(spec=Flow)
        flow.flow_id = FLOW_ID
        flow.validate.side_effect = ValueError("bad")

        with pytest.raises(FlowInvalidDataException, match="Invalid flow data: bad"):
            service.update_flow(flow, actor=SYSTEM_ACTOR)

        repository.find_by_id.assert_not_called()
        repository.update.assert_not_called()


class TestMigrateRootPath:
    """Tests for the legacy root_path -> paths migration on non-standard node configs."""

    def test_nodes_with_non_dict_config_or_connection_params_are_skipped(self, service):
        """Nodes whose config or connection_params are not dicts are left untouched."""
        definition = {
            "flow": [
                {"name": "a", "config": "not-a-dict"},
                {"name": "b", "config": {"provider": "filesystem", "connection_params": "not-a-dict"}},
                {"name": "c", "config": {"provider": "filesystem", "connection_params": {"root_path": ["/x", "/y"]}}},
            ]
        }

        result = service._migrate_root_path(definition)

        assert result["flow"][0]["config"] == "not-a-dict"
        assert result["flow"][1]["config"]["connection_params"] == "not-a-dict"
        assert result["flow"][2]["config"]["connection_params"] == {"paths": ["/x", "/y"]}


class TestCascadeDeleteWithoutJobRuns:
    """Tests for cascade-deleting job runs when the flow had none."""

    def test_zero_deleted_job_runs_is_not_an_error(self, repository):
        """When the job-stats service deletes nothing, delete_flow still succeeds."""
        repository.delete.return_value = True
        job_stats = Mock()
        job_stats.delete_job_runs_by_job_id.return_value = 0
        service = FlowService(repository=repository, job_stats_service=job_stats)

        assert service.delete_flow(FLOW_ID, actor=SYSTEM_ACTOR) is True
        job_stats.delete_job_runs_by_job_id.assert_called_once_with(job_id=FLOW_ID)


class TestDeleteUnknownFlowAsUser:
    """Tests for a non-system actor deleting a flow that does not exist."""

    def test_unknown_flow_skips_ownership_check_and_reports_not_found(self, service, repository):
        """Without a stored flow there is no owner to check; the delete itself reports 404."""
        repository.find_by_id.return_value = None
        repository.delete.return_value = False
        actor = ActorContext(username="alice", roles=frozenset({ROLE_EDITOR}))

        with pytest.raises(DocpipeException) as exc_info:
            service.delete_flow(FLOW_ID, actor=actor)

        assert exc_info.value.status_code == 404
        repository.find_by_id.assert_called_once_with(asset_id=FLOW_ID)
        repository.delete.assert_called_once_with(asset_id=FLOW_ID)
