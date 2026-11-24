# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the WebPageSourceConfig field validators.

The Field constraints (min_length, ge, le) reject these values before the after-validators
run, so the validators' own guards are exercised by calling them directly.
"""

import pytest

from docpipe.core.operators.ingest.adapters.outbound.sources.web.config import WebPageSourceConfig


class TestValidatorGuards:
    """Guards inside the field validators."""

    def test_validate_urls_rejects_empty_list(self):
        """An empty URL list is rejected."""
        with pytest.raises(ValueError, match="At least one URL must be provided"):
            WebPageSourceConfig.validate_urls([])

    @pytest.mark.parametrize(
        ("value", "message"),
        [(-1, "max_depth must be non-negative"), (11, "max_depth cannot exceed 10")],
    )
    def test_validate_max_depth_bounds(self, value, message):
        """max_depth outside 0..10 is rejected."""
        with pytest.raises(ValueError, match=message):
            WebPageSourceConfig.validate_max_depth(value)

    @pytest.mark.parametrize(
        ("value", "message"),
        [(0, "timeout must be at least 1 second"), (301, "timeout cannot exceed 300 seconds")],
    )
    def test_validate_timeout_bounds(self, value, message):
        """timeout outside 1..300 is rejected."""
        with pytest.raises(ValueError, match=message):
            WebPageSourceConfig.validate_timeout(value)

    def test_values_within_bounds_are_returned(self):
        """Valid values pass through unchanged."""
        assert WebPageSourceConfig.validate_max_depth(10) == 10
        assert WebPageSourceConfig.validate_timeout(300) == 300
