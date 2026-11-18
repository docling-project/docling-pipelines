# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the Flow model's accessors and post-init normalisation."""

from datetime import UTC, datetime

from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.core.constants.asset_constants import AssetType


class TestFlowAccessors:
    """Tests for Flow identity, type and timestamp accessors."""

    def test_flow_id_setter_updates_asset_id(self):
        """Setting flow_id writes through to asset_id."""
        flow = Flow(name="f", definition={"k": "v"})

        flow.flow_id = "new-id"

        assert flow.asset_id == "new-id"
        assert flow.flow_id == "new-id"

    def test_none_tags_are_normalised_to_empty_list(self):
        """Explicitly passing tags=None results in an empty tag list."""
        flow = Flow(name="f", definition={"k": "v"}, tags=None)  # type: ignore[arg-type]

        assert flow.tags == []

    def test_static_repository_keys(self):
        """The config key and collection name identify flows in repository configuration."""
        assert Flow.get_config_key() == "flow"
        assert Flow.get_collection_name() == "flows"

    def test_asset_type_is_flow(self):
        """get_asset_type reports AssetType.FLOW."""
        assert Flow(name="f").get_asset_type() is AssetType.FLOW

    def test_created_and_updated_accessors_return_timestamps(self):
        """get_created_at / get_updated_at return the stored created_on / modified_on values."""
        created = datetime(2024, 1, 1, tzinfo=UTC)
        modified = datetime(2024, 6, 1, tzinfo=UTC)
        flow = Flow(name="f", created_on=created, modified_on=modified)

        assert flow.get_created_at() == created
        assert flow.get_updated_at() == modified
