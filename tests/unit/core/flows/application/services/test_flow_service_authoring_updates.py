# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for FlowService partial updates in authoring format.

Covers _transform_authoring_updates() via partial_update_flow(): a partial
authoring PATCH must preserve stored definition keys the authoring DTO does
not manage, and updates that cannot be applied must raise
FlowInvalidDataException instead of a raw pydantic ValidationError.
"""

from unittest.mock import Mock

import pytest

from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.exceptions.docpipe_exceptions import FlowInvalidDataException

FLOW_ID = "12345678-1234-1234-1234-123456789abc"

AUTHORING_OPERATOR = {"type": "ingest_source", "name": "source", "depends_on": [], "config": {}}


@pytest.fixture
def mock_repository():
    return Mock()


@pytest.fixture
def service(mock_repository):
    return FlowService(repository=mock_repository)


class TestAuthoringPartialUpdate:
    """partial_update_flow() for flows stored in authoring format."""

    def test_partial_update_preserves_unmanaged_definition_keys(self, service, mock_repository):
        """A flow_name-only PATCH keeps stored keys like flow_source and flow_id."""
        existing = Flow(
            asset_id=FLOW_ID,
            name="original-name",
            definition={
                "flow_name": "original-name",
                "flow": [AUTHORING_OPERATOR],
                "global_config": {"doc_column": "content"},
                "flow_source": "ui",
                "flow_id": FLOW_ID,
            },
        )
        mock_repository.find_by_id.return_value = existing
        mock_repository.partial_update.return_value = existing

        service.partial_update_flow(FLOW_ID, {"flow_name": "renamed-flow"})

        mock_repository.partial_update.assert_called_once()
        validated_updates = mock_repository.partial_update.call_args[0][1]
        definition = validated_updates["definition"]
        assert definition["flow_name"] == "renamed-flow"
        assert definition["flow"] == [AUTHORING_OPERATOR]
        assert definition["global_config"] == {"doc_column": "content"}
        assert definition["flow_source"] == "ui"
        assert definition["flow_id"] == FLOW_ID

    def test_partial_update_on_elyra_flow_raises_invalid_data(self, service, mock_repository):
        """A PATCH that cannot rebuild an authoring definition raises FlowInvalidDataException."""
        existing = Flow(
            asset_id=FLOW_ID,
            name="elyra-flow",
            definition={
                "doc_type": "pipeline",
                "version": "3.0",
                "pipelines": [{"id": "pipeline-1", "nodes": []}],
            },
        )
        mock_repository.find_by_id.return_value = existing

        with pytest.raises(FlowInvalidDataException) as exc_info:
            service.partial_update_flow(FLOW_ID, {"flow_name": "renamed-flow"})

        mock_repository.partial_update.assert_not_called()
        assert "input_value" not in str(exc_info.value)

    def test_partial_update_on_elyra_flow_replaces_definition(self, service, mock_repository):
        """An authoring PATCH on an Elyra-format flow replaces the definition cleanly.

        The stored record must not end up holding Elyra keys (doc_type,
        version, pipelines) next to authoring keys (flow_name, flow).
        """
        existing = Flow(
            asset_id=FLOW_ID,
            name="elyra-flow",
            definition={
                "doc_type": "pipeline",
                "version": "3.0",
                "pipelines": [{"id": "pipeline-1", "nodes": []}],
            },
        )
        mock_repository.find_by_id.return_value = existing
        mock_repository.partial_update.return_value = existing

        service.partial_update_flow(FLOW_ID, {"flow": [AUTHORING_OPERATOR]})

        mock_repository.partial_update.assert_called_once()
        definition = mock_repository.partial_update.call_args[0][1]["definition"]
        assert definition["flow_name"] == "elyra-flow"
        assert definition["flow"] == [AUTHORING_OPERATOR]
        assert "doc_type" not in definition
        assert "version" not in definition
        assert "pipelines" not in definition
