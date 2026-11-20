# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for feature flags and summary filtering in docpipe.utils.operators.display."""

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.operators.display import (
    _format_feature_flags,
    display_operator_summary,
    format_operator_details,
)


class TestFormatFeatureFlags:
    """Tests for _format_feature_flags."""

    def test_all_flags_in_fixed_order(self):
        """Every enabled flag is listed, in the documented order."""
        info = {
            OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
            OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
            OperatorConstants.Config.AVAILABLE_FOR_OPENSEARCH: True,
            OperatorConstants.Misc.IS_PRIMARY: True,
        }
        assert _format_feature_flags(info) == ["filterable", "vectorizable", "opensearch", "primary"]

    def test_no_flags(self):
        """Falsy or missing flags yield an empty list."""
        assert _format_feature_flags({OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: False}) == []

    def test_flags_rendered_in_operator_details(self):
        """Flags of an output feature appear in the formatted operator details."""
        metadata = {
            "op": {
                OperatorConstants.Misc.LABEL: "Op",
                OperatorConstants.Config.FEATURES: {
                    "emb": {
                        OperatorConstants.Misc.TYPE: "vector",
                        OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                        OperatorConstants.Config.AVAILABLE_FOR_OPENSEARCH: True,
                    }
                },
            }
        }
        assert "    Flags: vectorizable, opensearch" in format_operator_details(metadata)


class TestDisplayOperatorSummary:
    """Tests for display_operator_summary."""

    def test_operators_without_metadata_are_skipped(self):
        """Operators with empty or None metadata are left out of the summary."""
        metadata = {
            "real_op": {OperatorConstants.Misc.LABEL: "Real", OperatorConstants.Misc.CATEGORY: "Ingest"},
            "ghost_op": None,
            "empty_op": {},
        }
        summary = display_operator_summary(metadata)
        assert "Real (real_op)" in summary
        assert "ghost_op" not in summary
        assert "empty_op" not in summary
