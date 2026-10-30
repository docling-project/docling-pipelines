"""
MetadataAggregator - Handles custom metadata aggregation strategies.
This class provides flexible aggregation of operator-specific metadata
"""

from typing import Any, Callable

from docpipe.core.constants.operator_constants import OperatorConstants

from .strategies import DEFAULT_STRATEGIES, AggregationStrategy


class MetadataAggregator:
    """
    Handles custom metadata aggregation strategies.

    Supports two metadata formats:
    1. Flat dict: {"processed_docs": 10, "status": "COMPLETED", ...}
    2. Structured NodeMetadataItem: {"id": "...", "operator": "...", "node_metadata": {...}}

    """

    _NUMERIC_STRATEGIES: tuple = (
        AggregationStrategy.SUM,
        AggregationStrategy.AVERAGE,
        AggregationStrategy.WEIGHTED_AVERAGE,
        AggregationStrategy.MIN,
        AggregationStrategy.MAX,
    )
    _COLLECTION_STRATEGIES: tuple = (
        AggregationStrategy.CONCAT,
        AggregationStrategy.MERGE_DICT,
        AggregationStrategy.DEEP_MERGE,
    )

    def __init__(self) -> None:
        """Initialize MetadataAggregator with default strategies."""
        self.strategies: dict[str, AggregationStrategy] = DEFAULT_STRATEGIES.copy()
        self.custom_functions: dict[str, Callable] = {}

    def register_strategy(
        self,
        *,
        field_path: str,
        strategy: AggregationStrategy,
        custom_function: Callable | None = None,
    ) -> None:
        """
        Register aggregation strategy for a metadata field.
        """
        self.strategies[field_path] = strategy
        if strategy == AggregationStrategy.CUSTOM:
            if custom_function is None:
                raise ValueError(f"Custom function required for field: {field_path}")
            self.custom_functions[field_path] = custom_function

    def aggregate_metadata(self, *, metadata_list: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Aggregate metadata across batches using registered strategies.

        Handles both flat metadata dicts and structured NodeMetadataItem payloads.
        For structured payloads with nested 'node_metadata', aggregates the inner
        metadata while preserving the outer structure (id, operator).

        This method is called from batch_aggregator.py and must handle the
        structured format used by enterprise job tracking.

        Enterprise-compatible: Matches docling-pipelines-api aggregator.py behavior.
        """
        if not metadata_list:
            return {}

        metadata_list = [metadata for metadata in metadata_list if metadata is not None]
        if not metadata_list:
            return {}

        # Collect all unique field names
        all_fields: set[str] = set()
        for metadata in metadata_list:
            if metadata:
                all_fields.update(metadata.keys())

        # Aggregate each field
        aggregated = {}
        for field in all_fields:
            if field == OperatorConstants.Metadata.NODE_METADATA:
                # Special handling: recursively aggregate nested node_metadata dictionary
                aggregated[field] = self._aggregate_nested_node_metadata(metadata_list=metadata_list)
            else:
                # Standard aggregation for top-level fields (id, operator, etc.)
                aggregated_value = self._aggregate_field(metadata_list=metadata_list, field_name=field)
                if aggregated_value is not None:
                    aggregated[field] = aggregated_value

        return aggregated

    def _aggregate_nested_node_metadata(self, *, metadata_list: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Aggregates nested node_metadata dictionary.

        Extracts the inner 'node_metadata' field from each item and aggregates them.
        Enterprise-compatible implementation.
        """
        nested_metadata_list = [
            m.get(OperatorConstants.Metadata.NODE_METADATA, {})
            for m in metadata_list
            if OperatorConstants.Metadata.NODE_METADATA in m
            and isinstance(m.get(OperatorConstants.Metadata.NODE_METADATA), dict)
        ]
        return self._aggregate_flat_metadata(metadata_list=nested_metadata_list) if nested_metadata_list else {}

    def _aggregate_field(self, *, metadata_list: list[dict[str, Any]], field_name: str) -> Any:
        """
        Aggregate a specific field across multiple metadata dictionaries.
        """
        values = [m.get(field_name) for m in metadata_list if field_name in m and m.get(field_name) is not None]

        if not values:
            return None

        strategy = self.strategies.get(field_name, AggregationStrategy.LAST)
        return self._apply_strategy(field_name=field_name, values=values, strategy=strategy)

    def _aggregate_flat_metadata(self, *, metadata_list: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Aggregate flat metadata dictionaries using registered strategies.

        This is the core aggregation logic that applies strategies to individual fields.
        """
        all_keys: set[str] = set()
        for metadata in metadata_list:
            all_keys.update(metadata.keys())

        result = {}
        for key in all_keys:
            strategy = self.strategies.get(key, AggregationStrategy.LAST)
            values = [metadata.get(key) for metadata in metadata_list if key in metadata]
            result[key] = self._apply_strategy(field_name=key, values=values, strategy=strategy)

        return result

    @staticmethod
    def _apply_numeric_strategy(*, values: list[Any], strategy: AggregationStrategy) -> Any:
        """Apply SUM / AVERAGE / WEIGHTED_AVERAGE / MIN / MAX strategies."""
        numeric = [v for v in values if isinstance(v, (int, float))]
        if strategy == AggregationStrategy.SUM:
            return sum(numeric)
        if strategy == AggregationStrategy.MIN:
            return min(numeric)
        if strategy == AggregationStrategy.MAX:
            return max(numeric)
        # AVERAGE and WEIGHTED_AVERAGE
        return sum(numeric) / len(numeric) if numeric else 0

    @staticmethod
    def _apply_concat(values: list[Any]) -> list[Any]:
        result: list[Any] = []
        for value in values:
            if isinstance(value, list):
                result.extend(value)
            else:
                result.append(value)
        return result

    @staticmethod
    def _apply_merge_dict(values: list[Any]) -> dict:
        result: dict = {}
        for value in values:
            if isinstance(value, dict):
                result.update(value)
        return result

    def _apply_deep_merge(self, values: list[Any]) -> dict:
        result: dict = {}
        for value in values:
            if isinstance(value, dict):
                result = self._deep_merge(dict1=result, dict2=value)
        return result

    def _apply_collection_strategy(self, *, values: list[Any], strategy: AggregationStrategy) -> Any:
        """Apply CONCAT / MERGE_DICT / DEEP_MERGE strategies."""
        if strategy == AggregationStrategy.CONCAT:
            return self._apply_concat(values)
        if strategy == AggregationStrategy.MERGE_DICT:
            return self._apply_merge_dict(values)
        # DEEP_MERGE
        return self._apply_deep_merge(values)

    @staticmethod
    def _apply_last_completed(values: list[Any]) -> Any:
        for value in reversed(values):
            if value:
                return value
        return values[-1] if values else None

    def _apply_custom_strategy(self, *, field_name: str, values: list[Any]) -> Any:
        custom_func = self.custom_functions.get(field_name)
        return custom_func(values) if custom_func else values[-1]

    def _apply_strategy(self, *, field_name: str, values: list[Any], strategy: AggregationStrategy) -> Any:
        """
        Apply aggregation strategy to a list of values.
        """
        values = [value for value in values if value is not None]
        if not values:
            return None

        if strategy in self._NUMERIC_STRATEGIES:
            return self._apply_numeric_strategy(values=values, strategy=strategy)

        if strategy in self._COLLECTION_STRATEGIES:
            return self._apply_collection_strategy(values=values, strategy=strategy)

        if strategy == AggregationStrategy.UNION:
            return self._apply_union_strategy(values=values)

        if strategy == AggregationStrategy.FIRST:
            return values[0]

        if strategy == AggregationStrategy.LAST:
            return values[-1]

        if strategy == AggregationStrategy.LAST_COMPLETED:
            return self._apply_last_completed(values)

        if strategy == AggregationStrategy.PRIORITY_STATUS:
            status_priority = {
                "RUNNING": 3,
                "FAILING": 2,
                "FAILED": 2,
                "COMPLETED": 1,
                "COMPLETED_WITH_ERRORS": 1,
                "COMPLETED_WITH_WARNINGS": 1,
                "SKIPPED": 0,
            }
            return max(values, key=lambda status: status_priority.get(str(status).upper(), 0))

        if strategy == AggregationStrategy.CUSTOM:
            return self._apply_custom_strategy(field_name=field_name, values=values)

        return values[-1]

    @staticmethod
    def _apply_union_strategy(*, values: list[Any]) -> list[Any]:
        """Apply UNION strategy - union of lists, preserving order."""
        result: list[Any] = []
        seen: set[Any] = set()
        for value in values:
            if isinstance(value, list):
                for item in value:
                    item_key = str(item) if not isinstance(item, (str, int, float, bool, type(None))) else item
                    if item_key not in seen:
                        result.append(item)
                        seen.add(item_key)
        return result

    def _deep_merge(self, *, dict1: dict, dict2: dict) -> dict:
        """
        Deep merge two dictionaries, recursively merging nested dicts.

        Enterprise-compatible implementation with special handling for:
        - Nested dicts: recursively merge
        - Lists: concatenate
        - Numeric values: sum (for counters like processed_docs)
        - Other types: dict2 value wins

        Matches docling-pipelines-api aggregator.py _deep_merge_dicts behavior.
        """
        result = dict1.copy()

        for key, value in dict2.items():
            if key in result:
                if isinstance(result[key], dict) and isinstance(value, dict):
                    # Recursively merge nested dictionaries
                    result[key] = self._deep_merge(dict1=result[key], dict2=value)
                elif isinstance(result[key], list) and isinstance(value, list):
                    # Concatenate lists
                    result[key] = result[key] + value
                elif isinstance(result[key], (int, float)) and isinstance(value, (int, float)):
                    # Sum numeric values (counters like processed_docs, total_docs, etc.)
                    result[key] = result[key] + value
                else:
                    # dict2 wins for other types
                    result[key] = value
            else:
                result[key] = value

        return result
