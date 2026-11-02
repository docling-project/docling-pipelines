"""
Unit tests for MetadataAggregator.aggregate_metadata: default field strategies,
custom strategies and missing/None values.
"""

import pytest

from docpipe.core.job_management.application.aggregation.aggregator import MetadataAggregator
from docpipe.core.job_management.application.aggregation.strategies import AggregationStrategy


def _item(inner: dict) -> dict:
    """A NodeMetadataItem payload as stored per batch."""
    return {"id": "node-1", "operator": "Op", "node_metadata": inner}


class TestRegisterStrategy:
    """register_strategy validation."""

    def test_custom_strategy_without_function_is_rejected(self):
        """CUSTOM needs a function; registering it without one raises."""
        aggregator = MetadataAggregator()

        with pytest.raises(ValueError, match="Custom function required for field: score"):
            aggregator.register_strategy(field_path="score", strategy=AggregationStrategy.CUSTOM)

    def test_registered_custom_function_is_used_by_aggregate_metadata(self):
        """A registered CUSTOM function receives all batch values of the field."""
        aggregator = MetadataAggregator()
        aggregator.register_strategy(
            field_path="longest_title",
            strategy=AggregationStrategy.CUSTOM,
            custom_function=lambda values: max(values, key=len),
        )

        result = aggregator.aggregate_metadata(
            metadata_list=[
                _item({"longest_title": "abc"}),
                _item({"longest_title": "abcdef"}),
                _item({"longest_title": "ab"}),
            ]
        )

        assert result["node_metadata"]["longest_title"] == "abcdef"


class TestMissingValues:
    """None payloads, empty payloads and None field values."""

    def test_only_none_payloads_give_empty_result(self):
        """A list with nothing but None entries aggregates to {}."""
        assert MetadataAggregator().aggregate_metadata(metadata_list=[None, None]) == {}

    def test_empty_payload_contributes_nothing(self):
        """An empty dict among the payloads is ignored."""
        result = MetadataAggregator().aggregate_metadata(
            metadata_list=[{}, {"processed_docs": 2}, {"processed_docs": 3}]
        )

        assert result == {"processed_docs": 5}

    def test_top_level_field_with_only_none_values_is_dropped(self):
        """A top-level field that is None in every batch does not appear in the result."""
        result = MetadataAggregator().aggregate_metadata(
            metadata_list=[{"operator": "Op", "error": None}, {"error": None}]
        )

        assert result == {"operator": "Op"}

    def test_nested_field_with_only_none_values_has_no_value(self):
        """A nested node_metadata field that is None in every batch aggregates to no value."""
        result = MetadataAggregator().aggregate_metadata(
            metadata_list=[_item({"error": None, "processed_docs": 1}), _item({"error": None, "processed_docs": 2})]
        )

        assert result["node_metadata"].get("error") is None
        assert result["node_metadata"]["processed_docs"] == 3


class TestDefaultStrategies:
    """Default strategies for well-known nested node_metadata fields."""

    def test_sql_filter_columns_use_first_and_last_batch(self):
        """columns_before_filter keeps the first batch's value, columns_after_filter the last one."""
        result = MetadataAggregator().aggregate_metadata(
            metadata_list=[
                _item({"columns_before_filter": 12, "columns_after_filter": 9, "docs_before_filter": 10}),
                _item({"columns_before_filter": 11, "columns_after_filter": 8, "docs_before_filter": 5}),
            ]
        )

        inner = result["node_metadata"]
        assert inner["columns_before_filter"] == 12
        assert inner["columns_after_filter"] == 8
        assert inner["docs_before_filter"] == 15

    def test_error_keeps_last_non_empty_message(self):
        """error uses LAST_COMPLETED: a later empty value does not erase an earlier error."""
        result = MetadataAggregator().aggregate_metadata(
            metadata_list=[_item({"error": "first failure"}), _item({"error": "timeout"}), _item({"error": ""})]
        )

        assert result["node_metadata"]["error"] == "timeout"

    def test_failed_docs_union_deduplicates_document_records(self):
        """failed_docs entries (dicts) are deduplicated across batches, order preserved."""
        doc_a = {"id": "a", "name": "a.pdf", "reason": "parse error", "document_url": ""}
        doc_b = {"id": "b", "name": "b.pdf", "reason": "empty", "document_url": ""}

        result = MetadataAggregator().aggregate_metadata(
            metadata_list=[_item({"failed_docs": [doc_a]}), _item({"failed_docs": [doc_a, doc_b]})]
        )

        assert result["node_metadata"]["failed_docs"] == [doc_a, doc_b]

    def test_union_ignores_values_that_are_not_lists(self):
        """UNION is defined for lists; a non-list batch value is not merged in."""
        aggregator = MetadataAggregator()
        aggregator.register_strategy(field_path="languages", strategy=AggregationStrategy.UNION)

        result = aggregator.aggregate_metadata(
            metadata_list=[{"languages": ["en", "de"]}, {"languages": "unknown"}, {"languages": ["de", "fr"]}]
        )

        assert result["languages"] == ["en", "de", "fr"]

    def test_page_type_stats_are_deep_merged_by_summing_counts(self):
        """page_type_stats (DEEP_MERGE) adds up the per-type page counts of all batches."""
        result = MetadataAggregator().aggregate_metadata(
            metadata_list=[
                _item({"page_type_stats": {"digital": 3, "scanned": 2}, "total_pages_converted": 5}),
                _item({"page_type_stats": {"scanned": 1, "mixed": 1}, "total_pages_converted": 2}),
            ]
        )

        inner = result["node_metadata"]
        assert inner["page_type_stats"] == {"digital": 3, "scanned": 3, "mixed": 1}
        assert inner["total_pages_converted"] == 7
