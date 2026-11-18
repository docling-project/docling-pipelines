"""
Unit tests for MetadataAggregator - nested metadata handling.

Tests the enterprise-compatible nested node_metadata aggregation.
"""

from docpipe.core.job_management.application.aggregation.aggregator import MetadataAggregator
from docpipe.core.job_management.application.aggregation.strategies import AggregationStrategy


class TestNestedMetadataAggregation:
    """Test aggregation of structured NodeMetadataItem payloads."""

    def test_structured_metadata_with_nested_node_metadata(self):
        """Test aggregation of structured metadata with nested node_metadata field."""
        aggregator = MetadataAggregator()

        metadata_list = [
            {
                "id": "node-123",
                "operator": "ExtractOperator",
                "node_metadata": {
                    "processed_docs": 10,
                    "total_docs": 20,
                    "node_status": "RUNNING",
                },
            },
            {
                "id": "node-123",
                "operator": "ExtractOperator",
                "node_metadata": {
                    "processed_docs": 15,
                    "total_docs": 20,
                    "node_status": "COMPLETED",
                },
            },
        ]

        result = aggregator.aggregate_metadata(metadata_list=metadata_list)

        # Outer fields preserved from first item
        assert result["id"] == "node-123"
        assert result["operator"] == "ExtractOperator"

        # Inner node_metadata aggregated
        assert "node_metadata" in result
        inner = result["node_metadata"]
        assert inner["processed_docs"] == 25  # SUM strategy
        assert inner["total_docs"] == 40  # SUM strategy
        assert inner["node_status"] == "RUNNING"  # PRIORITY_STATUS strategy

    def test_flat_metadata_backward_compatibility(self):
        """Test that flat metadata (without nested node_metadata) still works."""
        aggregator = MetadataAggregator()

        metadata_list = [
            {"processed_docs": 10, "total_docs": 20, "node_status": "RUNNING"},
            {"processed_docs": 15, "total_docs": 20, "node_status": "COMPLETED"},
        ]

        result = aggregator.aggregate_metadata(metadata_list=metadata_list)

        # Flat aggregation
        assert result["processed_docs"] == 25  # SUM strategy
        assert result["total_docs"] == 40  # SUM strategy
        assert result["node_status"] == "RUNNING"  # PRIORITY_STATUS strategy

    def test_empty_metadata_list(self):
        """Test aggregation with empty metadata list."""
        aggregator = MetadataAggregator()
        result = aggregator.aggregate_metadata(metadata_list=[])
        assert result == {}

    def test_none_metadata_filtered(self):
        """Test that None values are filtered out."""
        aggregator = MetadataAggregator()

        metadata_list = [
            None,
            {
                "id": "node-123",
                "operator": "ExtractOperator",
                "node_metadata": {"processed_docs": 10},
            },
            None,
        ]

        result = aggregator.aggregate_metadata(metadata_list=metadata_list)

        assert result["id"] == "node-123"
        assert result["node_metadata"]["processed_docs"] == 10


class TestDeepMergeEnhanced:
    """Test enhanced _deep_merge with list concatenation and numeric summing."""

    def test_deep_merge_nested_dicts(self):
        """Test deep merge recursively merges nested dictionaries."""
        aggregator = MetadataAggregator()

        dict1 = {"a": {"b": 1, "c": 2}}
        dict2 = {"a": {"b": 3, "d": 4}}

        result = aggregator._deep_merge(dict1=dict1, dict2=dict2)

        assert result["a"]["b"] == 4  # Summed (numeric)
        assert result["a"]["c"] == 2  # From dict1
        assert result["a"]["d"] == 4  # From dict2

    def test_deep_merge_concatenates_lists(self):
        """Test deep merge concatenates lists."""
        aggregator = MetadataAggregator()

        dict1 = {"docs": ["doc1", "doc2"]}
        dict2 = {"docs": ["doc3", "doc4"]}

        result = aggregator._deep_merge(dict1=dict1, dict2=dict2)

        assert result["docs"] == ["doc1", "doc2", "doc3", "doc4"]

    def test_deep_merge_sums_numeric_values(self):
        """Test deep merge sums numeric values (counters)."""
        aggregator = MetadataAggregator()

        dict1 = {"processed_docs": 10, "total_docs": 20}
        dict2 = {"processed_docs": 15, "total_docs": 30}

        result = aggregator._deep_merge(dict1=dict1, dict2=dict2)

        assert result["processed_docs"] == 25
        assert result["total_docs"] == 50

    def test_deep_merge_dict2_wins_for_other_types(self):
        """Test deep merge uses dict2 value for non-dict/list/numeric types."""
        aggregator = MetadataAggregator()

        dict1 = {"status": "RUNNING", "message": "Processing"}
        dict2 = {"status": "COMPLETED", "message": "Done"}

        result = aggregator._deep_merge(dict1=dict1, dict2=dict2)

        assert result["status"] == "COMPLETED"
        assert result["message"] == "Done"


class TestAggregationStrategies:
    """Test various aggregation strategies work correctly."""

    def test_sum_strategy(self):
        """Test SUM strategy aggregates numeric values."""
        aggregator = MetadataAggregator()
        aggregator.register_strategy(field_path="count", strategy=AggregationStrategy.SUM)

        metadata_list = [{"count": 10}, {"count": 20}, {"count": 30}]
        result = aggregator.aggregate_metadata(metadata_list=metadata_list)

        assert result["count"] == 60

    def test_union_strategy(self):
        """Test UNION strategy deduplicates lists."""
        aggregator = MetadataAggregator()
        aggregator.register_strategy(field_path="docs", strategy=AggregationStrategy.UNION)

        metadata_list = [
            {"docs": ["doc1", "doc2"]},
            {"docs": ["doc2", "doc3"]},
            {"docs": ["doc3", "doc4"]},
        ]
        result = aggregator.aggregate_metadata(metadata_list=metadata_list)

        assert set(result["docs"]) == {"doc1", "doc2", "doc3", "doc4"}

    def test_last_strategy_default(self):
        """Test LAST strategy is used as default for unknown fields."""
        aggregator = MetadataAggregator()

        metadata_list = [
            {"custom_field": "value1"},
            {"custom_field": "value2"},
            {"custom_field": "value3"},
        ]
        result = aggregator.aggregate_metadata(metadata_list=metadata_list)

        assert result["custom_field"] == "value3"


class TestNewHelperMethods:
    def setup_method(self):
        self.agg = MetadataAggregator()

    # --- _apply_numeric_strategy ---

    def test_numeric_sum(self):
        assert self.agg._apply_numeric_strategy(values=[1, 2, 3], strategy=AggregationStrategy.SUM) == 6

    def test_numeric_min(self):
        assert self.agg._apply_numeric_strategy(values=[3, 1, 2], strategy=AggregationStrategy.MIN) == 1

    def test_numeric_max(self):
        assert self.agg._apply_numeric_strategy(values=[3, 1, 2], strategy=AggregationStrategy.MAX) == 3

    def test_numeric_average(self):
        assert self.agg._apply_numeric_strategy(values=[10, 20], strategy=AggregationStrategy.AVERAGE) == 15.0

    def test_numeric_weighted_average(self):
        assert self.agg._apply_numeric_strategy(values=[10, 20], strategy=AggregationStrategy.WEIGHTED_AVERAGE) == 15.0

    def test_numeric_average_empty_returns_zero(self):
        assert self.agg._apply_numeric_strategy(values=["a", "b"], strategy=AggregationStrategy.AVERAGE) == 0

    # --- _apply_concat ---

    def test_concat_flattens_lists(self):
        result = self.agg._apply_concat([["a", "b"], ["c"]])
        assert result == ["a", "b", "c"]

    def test_concat_appends_scalar(self):
        result = self.agg._apply_concat(["x", "y"])
        assert result == ["x", "y"]

    # --- _apply_merge_dict ---

    def test_merge_dict_merges(self):
        result = self.agg._apply_merge_dict([{"a": 1}, {"b": 2}])
        assert result == {"a": 1, "b": 2}

    def test_merge_dict_skips_non_dicts(self):
        result = self.agg._apply_merge_dict([{"a": 1}, "not-a-dict"])
        assert result == {"a": 1}

    # --- _apply_deep_merge (instance method) ---

    def test_apply_deep_merge_sums_nested(self):
        result = self.agg._apply_deep_merge([{"x": 1}, {"x": 2}])
        assert result == {"x": 3}

    def test_apply_deep_merge_skips_non_dicts(self):
        result = self.agg._apply_deep_merge([{"x": 1}, "bad"])
        assert result == {"x": 1}

    # --- _apply_collection_strategy ---

    def test_collection_strategy_concat(self):
        result = self.agg._apply_collection_strategy(values=[["a"], ["b"]], strategy=AggregationStrategy.CONCAT)
        assert result == ["a", "b"]

    def test_collection_strategy_merge_dict(self):
        result = self.agg._apply_collection_strategy(
            values=[{"k": 1}, {"v": 2}], strategy=AggregationStrategy.MERGE_DICT
        )
        assert result == {"k": 1, "v": 2}

    def test_collection_strategy_deep_merge(self):
        result = self.agg._apply_collection_strategy(
            values=[{"n": 1}, {"n": 2}], strategy=AggregationStrategy.DEEP_MERGE
        )
        assert result == {"n": 3}

    # --- _apply_last_completed ---

    def test_last_completed_returns_last_truthy(self):
        assert self.agg._apply_last_completed(["", None, "done", "last"]) == "last"

    def test_last_completed_falls_back_to_last_when_all_falsy(self):
        assert self.agg._apply_last_completed(["", None, 0]) == 0

    def test_last_completed_empty_list_returns_none(self):
        assert self.agg._apply_last_completed([]) is None

    # --- _apply_custom_strategy ---

    def test_custom_strategy_calls_registered_function(self):
        self.agg.register_strategy(
            field_path="my_field",
            strategy=AggregationStrategy.CUSTOM,
            custom_function=lambda vals: sum(vals),
        )
        result = self.agg._apply_custom_strategy(field_name="my_field", values=[1, 2, 3])
        assert result == 6

    def test_custom_strategy_falls_back_to_last_when_not_registered(self):
        result = self.agg._apply_custom_strategy(field_name="unregistered", values=["a", "b", "c"])
        assert result == "c"


class TestMetadataAggregatorStaticMethods:
    """Verify aggregation strategy helpers are static and callable without an instance."""

    STATIC_METHODS = (
        "_apply_numeric_strategy",
        "_apply_union_strategy",
    )

    def test_strategy_helpers_are_static(self):
        """Every converted strategy helper must be a true staticmethod."""
        import inspect

        for method_name in self.STATIC_METHODS:
            assert isinstance(inspect.getattr_static(MetadataAggregator, method_name), staticmethod), (
                f"{method_name} is not a staticmethod"
            )

    def test_apply_numeric_strategy_class_call(self):
        """Numeric strategies work when called directly on the class."""
        assert MetadataAggregator._apply_numeric_strategy(values=[1, 2, 3], strategy=AggregationStrategy.SUM) == 6
        assert MetadataAggregator._apply_numeric_strategy(values=[1, 2, 3], strategy=AggregationStrategy.MIN) == 1
        assert MetadataAggregator._apply_numeric_strategy(values=[1, 2, 3], strategy=AggregationStrategy.MAX) == 3

    def test_apply_union_strategy_class_call(self):
        """UNION strategy works when called directly on the class."""
        result = MetadataAggregator._apply_union_strategy(values=[[1, 2], [2, 3], [4]])

        assert result == [1, 2, 3, 4]
