# Node Metadata Aggregation Strategy

## Overview

This document defines how node metadata is aggregated across batch executions in micro-batching scenarios. It serves as the authoritative reference for understanding, maintaining, and extending metadata aggregation behavior.

This is the primary maintainer guide for updating aggregation behavior when operators introduce new metadata fields.


---

## Table of Contents

1. [Core Concepts](#core-concepts)
2. [Aggregation Strategies](#aggregation-strategies)
3. [Default Strategy Mappings](#default-strategy-mappings)
4. [Operator Responsibilities](#operator-responsibilities)
5. [Maintainer Contract](#maintainer-contract)
6. [Adding New Operators](#adding-new-operators)
7. [Modifying Existing Operators](#modifying-existing-operators)
8. [Testing Requirements](#testing-requirements)
9. [Architecture References](#architecture-references)

---

## Core Concepts

### NodeMetadataItem Structure

Each batch execution produces a `NodeMetadataItem` with the following structure:

```python
{
    "id": "node-uuid",                    # Node identifier
    "operator": "Operator Name",          # Operator name
    "node_metadata": {                    # Nested operator-specific data
        # Base metadata fields (present in all operators)
        "total_docs": 100,
        "processed_docs": 100,
        "failed_docs_count": 0,
        "failed_docs": [],
        "skipped_docs_count": 0,
        "skipped_docs": [],
        "node_status": "COMPLETED",

        # Operator-specific fields (varies by operator)
        "progress_percentage": "100.00%",
        "custom_field": "operator-specific value",
        # ... other operator-specific fields
    }
}
```

### Batch-Level vs Aggregated Metadata

- **Batch-Level**: Each batch execution creates one `NodeMetadataItem` record
- **Aggregated**: Multiple batch records are combined using aggregation strategies
- **Storage**: Batch records stored with `batch_id` and `batch_num` fields
- **Retrieval**: API returns aggregated view (single record per node)

---

## Aggregation Strategies

### Strategy Definitions

| Strategy | Description | Example |
|----------|-------------|---------|
| **SUM** | Add numeric values | `10 + 20 = 30` |
| **UNION** | Combine lists, remove duplicates | `[a,b] + [b,c] = [a,b,c]` |
| **INTERSECTION** | Items present in every list, first-list order, no duplicates | `[a,b] ∩ [b,c] = [b]` |
| **CONCAT** | Combine lists, keep duplicates | `[a,b] + [b,c] = [a,b,b,c]` |
| **PRIORITY_STATUS** | Select most severe status | `RUNNING > FAILED > COMPLETED` |
| **MIN** | Select minimum value | `min(10, 5, 15) = 5` |
| **MAX** | Select maximum value | `max(10, 5, 15) = 15` |
| **WEIGHTED_AVERAGE** | Average with batch size consideration | `(50*10 + 75*20) / 30 = 66.67` |
| **LAST_COMPLETED** | Use last non-empty value | Last error message |
| **MERGE_DICT** | Shallow merge dictionaries | `{a:1} + {b:2} = {a:1, b:2}` |
| **DEEP_MERGE** | Deep merge nested dictionaries | Recursive merge |
| **FIRST** | Use first value | First batch value |
| **LAST** | Use last value | Last batch value |
| **CUSTOM** | Custom function | User-defined logic |

### Implementation

Strategies are implemented in:
- **File**: `src/docpipe/core/job_management/application/aggregation/strategies.py`
- **Enum**: `AggregationStrategy`
- **Aggregator**: `MetadataAggregator` class

---

## Default Strategy Mappings

### Standard Metadata Fields

These strategies apply to the nested `node_metadata` field within `NodeStatsDto`:

```python
DEFAULT_STRATEGIES = {
    # Document counters - sum across batches
    "processed_docs": AggregationStrategy.SUM,
    "total_docs": AggregationStrategy.SUM,
    "failed_docs_count": AggregationStrategy.SUM,
    "skipped_docs_count": AggregationStrategy.SUM,

    # Document ID lists - union to avoid duplicates
    "docs_completed": AggregationStrategy.UNION,
    "failed_docs": AggregationStrategy.UNION,
    "skipped_docs": AggregationStrategy.UNION,

    # Status fields - priority-based (RUNNING > FAILED > COMPLETED)
    "status": AggregationStrategy.PRIORITY_STATUS,
    "node_status": AggregationStrategy.PRIORITY_STATUS,

    # Timing fields
    "start_time": AggregationStrategy.MIN,  # Earliest start
    "end_time": AggregationStrategy.MAX,    # Latest end
    "time_taken": AggregationStrategy.SUM,  # Total duration

    # Progress tracking
    "progress_percentage": AggregationStrategy.WEIGHTED_AVERAGE,

    # Error handling - keep last meaningful error
    "error": AggregationStrategy.LAST_COMPLETED,
    "error_message": AggregationStrategy.LAST_COMPLETED,
}
```

### NodeStatsDto Top-Level Fields

These fields are aggregated at the `NodeStatsDto` level (not in nested metadata):

| Field | Strategy | Rationale |
|-------|----------|-----------|
| `node_status` | PRIORITY_STATUS | Most severe status wins |
| `start_time` | MIN | Earliest batch start |
| `end_time` | MAX | Latest batch end |
| `time_taken` | wall clock | Latest end minus earliest start |
| `total_docs` | UNION | All unique document IDs |
| `docs_completed` | UNION | All completed document IDs |
| `failed_docs` | UNION | All failed document IDs |
| `skipped_docs` | UNION | All skipped document IDs |
| `docs_completed_count` | Calculated | `len(docs_completed)` |
| `col_names` | sorted union | Column names from every batch, sorted |
| `error` | join | Non-empty errors joined with `" \| "` |
| `node_metadata` | MetadataAggregator | Nested aggregation |

---

## Operator Responsibilities

### Base Metadata Requirements

All operators **MUST** emit these base metadata fields:

```python
from common.constants.constants import Metrics, ExecutionStatus

metadata = {
    Metrics.External.TOTAL_DOCS: 100,           # Total documents to process
    Metrics.External.PROCESSED_DOCS: 95,        # Documents processed so far
    Metrics.External.FAILED_DOCS_COUNT: 3,      # Count of failed documents
    Metrics.External.FAILED_DOCS: [             # List of failed documents
        {"id": "doc1", "name": "file1.pdf", "reason": "Parse error", "document_url": ""}
    ],
    Metrics.External.SKIPPED_DOCS_COUNT: 2,     # Count of skipped documents
    Metrics.External.SKIPPED_DOCS: [            # List of skipped documents
        {"id": "doc2", "name": "file2.pdf", "reason": "Empty file", "document_url": ""}
    ],
    Metrics.External.NODE_STATUS: ExecutionStatus.COMPLETED.value  # Final status
}
```

### Helper Methods

Use `AbstractOperator` helper methods for consistency:

```python
from core.operators.abstract_operator import AbstractOperator

# Create base metadata
metadata = AbstractOperator.create_base_metadata(
    total_docs_count=table.num_rows,
    node_status=ExecutionStatus.RUNNING.value
)

# Record failed document
AbstractOperator.record_failed_document(
    metadata=metadata,
    doc_id="doc123",
    doc_name="file.pdf",
    reason="Processing error"
)

# Record skipped document
AbstractOperator.record_skipped_document(
    metadata=metadata,
    doc_id="doc456",
    doc_name="empty.pdf",
    reason="Empty file"
)
```

### Operator-Specific Fields

Operators **MAY** add custom fields on top of base metadata:

```python
# Example: Embedding operator
metadata["embedding_model"] = "nomic-embed-text"
metadata["embedding_dimension"] = 768
metadata["batch_size"] = 32

# Example: Extraction operator
metadata["extraction_method"] = "docling"
metadata["tables_extracted"] = 5
metadata["images_extracted"] = 12
```

---

## Maintainer Contract

When an operator adds, removes, renames, or changes the meaning of any emitted metadata field, maintainers must review aggregation behavior in [`strategies.py`](../../src/docpipe/core/job_management/application/aggregation/strategies.py).

### Required Maintainer Checks

1. Identify every new or changed metadata field emitted by the operator.
2. Decide whether the default `LAST` behavior is correct for each field.
3. If a different behavior is required, add or update the field entry in `DEFAULT_STRATEGIES`.
4. Add or update aggregation tests for the changed fields.
5. Update this document when the new field introduces a reusable pattern or non-obvious rule.

### Why This Is Required

Micro-batch execution stores raw node stats per batch and combines them later during read-side aggregation. If a new metadata field is introduced without an explicit aggregation review, the aggregated API view may silently produce incorrect values.

Common examples:
- counters usually need `SUM`
- document collections often need `UNION`
- progress-like values may need `WEIGHTED_AVERAGE`
- status-like fields usually need `PRIORITY_STATUS`
- configuration or descriptive values may legitimately remain `LAST`

### Default Behavior Reminder

If a field is not listed in `DEFAULT_STRATEGIES`, the aggregator falls back to the default `LAST` strategy. That fallback is intentional, but it is not correct for many counters, lists, or status fields.

## Adding New Operators

When creating a new operator that emits metadata:

### Step 1: Define Operator Metadata

```python
class MyNewOperator(AbstractOperator):
    def transform(self, table: pa.Table, file_name: str = None) -> tuple[list[pa.Table], dict[str, Any]]:
        # 1. Create base metadata
        metadata = self.create_base_metadata(
            total_docs_count=table.num_rows,
            node_status=ExecutionStatus.RUNNING.value
        )

        # 2. Add operator-specific fields
        metadata["my_custom_metric"] = 0
        metadata["my_custom_list"] = []

        # 3. Process and update metadata
        # ... processing logic ...

        return [output_table], metadata
```

### Step 2: Review Aggregation Strategy

This step is mandatory whenever the operator emits new metadata.

1. Open [`strategies.py`](../../src/docpipe/core/job_management/application/aggregation/strategies.py).
2. Review whether each new field should keep the default `LAST` behavior.
3. Add strategy mappings to `DEFAULT_STRATEGIES` for every field that requires explicit aggregation.

```python
DEFAULT_STRATEGIES = {
    # ... existing strategies ...
    "my_custom_metric": AggregationStrategy.SUM,
    "my_custom_list": AggregationStrategy.UNION,
}
```

**If using default strategy (`LAST`):**
- no code change is required in `DEFAULT_STRATEGIES`
- the field still requires an explicit maintainer review before leaving it unmapped

### Step 3: Update Documentation

1. Document operator-specific fields in operator's docstring
2. Add example to this document if field has special aggregation needs
3. Update operator README if applicable

### Step 4: Add Tests

Create tests for metadata aggregation:

```python
def test_my_operator_metadata_aggregation():
    """Test metadata aggregation across batches."""
    # Create batch records
    batch1_metadata = {"my_custom_metric": 10, "my_custom_list": ["a", "b"]}
    batch2_metadata = {"my_custom_metric": 20, "my_custom_list": ["b", "c"]}

    # Aggregate
    aggregator = MetadataAggregator()
    result = aggregator.aggregate_metadata(
        metadata_list=[batch1_metadata, batch2_metadata]
    )

    # Verify
    assert result["my_custom_metric"] == 30  # SUM
    assert set(result["my_custom_list"]) == {"a", "b", "c"}  # UNION
```

---

## Modifying Existing Operators

When modifying operator metadata:

### Step 1: Assess Impact

**Questions to answer:**
- Does the change add new metadata fields?
- Does the change modify existing field semantics?
- Does the change affect aggregation behavior?

### Step 2: Update Aggregation Strategy

**If adding new fields:**
- Follow [Step 2](#step-2-review-aggregation-strategy) in the new-operator workflow
- Do not rely on implicit `LAST` behavior without reviewing the field explicitly

**If modifying existing fields:**
1. Review current strategy in `DEFAULT_STRATEGIES`
2. Determine if strategy still appropriate
3. Update if needed and document rationale

### Step 3: Update Tests

**Required test updates:**
- Unit tests for operator metadata emission
- Integration tests for batch aggregation
- End-to-end tests if behavior changes

### Step 4: Update Documentation

**Required documentation updates:**
- Operator docstring
- This document (if strategy changed)
- CHANGELOG.md (if breaking change)

---

## Testing Requirements

### Unit Tests

**Location**: `tests/unit/core/job_management/application/aggregation/`

**Required tests:**
1. Strategy application for each strategy type
2. Edge cases (empty lists, null values, single batch)
3. Custom strategy registration

**Example**:
```python
def test_sum_strategy():
    aggregator = MetadataAggregator()
    result = aggregator.aggregate_metadata(
        metadata_list=[
            {"count": 10},
            {"count": 20},
            {"count": 30}
        ]
    )
    assert result["count"] == 60
```

### Integration Tests

**Location**: `tests/integration/core/job_management/`

**Required tests:**
1. End-to-end batch aggregation
2. Multiple operators with different metadata
3. Real operator metadata structures

**Example**:
```python
def test_batch_aggregation_with_real_operator():
    # Execute operator across 3 batches
    batch_records = execute_operator_in_batches(
        operator=ExtractDocling(),
        batches=3
    )

    # Aggregate
    aggregated = aggregate_batch_node_stats(
        node_id="extract_1",
        batch_records=batch_records,
        aggregator=MetadataAggregator()
    )

    # Verify aggregation
    assert aggregated["node_status"] == "COMPLETED"
    assert len(aggregated["total_docs"]) == total_expected_docs
```

---

## Architecture References

### Key Files

| File | Purpose |
|------|---------|
| `strategies.py` | Strategy enum and default mappings |
| `aggregator.py` | MetadataAggregator implementation |
| `batch_aggregator.py` | Batch-level aggregation logic |
| `node_stats_aggregator.py` | Service layer aggregation |
| `node_stats_dto.py` | NodeStatsDto and NodeMetadataItem models |

### Data Flow

```
Operator Execution (Batch 1)
    ↓
NodeMetadataItem (Batch 1) → Store
    ↓
Operator Execution (Batch 2)
    ↓
NodeMetadataItem (Batch 2) → Store
    ↓
Operator Execution (Batch 3)
    ↓
NodeMetadataItem (Batch 3) → Store
    ↓
API Request (Get Status)
    ↓
NodeStatsAggregator.get_aggregated_node_stats()
    ↓
Fetch all batch records from store
    ↓
Group by node_id
    ↓
aggregate_batch_node_stats() for each node
    ↓
MetadataAggregator.aggregate_metadata()
    ↓
Apply strategy for each field
    ↓
Return aggregated NodeStatsDto
```

### Enterprise Alignment

This implementation aligns with enterprise behavior documented in:
- `JOBSTATS_MANAGEMENT_KNOWLEDGE.md` Section "Aggregation Strategy"
- `JOBSTATS_MANAGEMENT_KNOWLEDGE.md` Section "Node Metadata vs Node Stats"
- `JOBSTATS_MANAGEMENT_KNOWLEDGE.md` Section "Micro-Batching Support"

**Key alignment points:**
1. ✅ Batch-level metadata storage
2. ✅ Strategy-based aggregation (SUM, UNION, PRIORITY_STATUS, etc.)
3. ✅ Nested metadata structure (NodeMetadataItem)
4. ✅ Base metadata fields in all operators
5. ✅ Operator-specific field extensibility

---

## Maintenance Checklist

When working with node metadata:

- [ ] Operator emits all base metadata fields
- [ ] Custom fields have appropriate aggregation strategy
- [ ] Strategy documented in `DEFAULT_STRATEGIES`
- [ ] Unit tests for metadata emission
- [ ] Integration tests for batch aggregation
- [ ] Operator docstring updated
- [ ] This document updated if strategy changed
- [ ] CHANGELOG.md updated if breaking change

---

## Questions and Support

For questions about metadata aggregation:
1. Review this document
2. Check enterprise `JOBSTATS_MANAGEMENT_KNOWLEDGE.md`
3. Examine existing operator implementations
4. Review test cases in `tests/unit/core/job_management/`

---

**Document Version**: 1.0  
**Last Updated**: 2026-04-21  
**Maintained By**: Docling Pipelines Core Team
