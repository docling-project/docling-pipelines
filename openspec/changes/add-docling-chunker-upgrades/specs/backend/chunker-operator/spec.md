# Spec Delta

## Purpose

Defines the behavioral contract, supported chunking strategies, configuration validation rules, input/output `pyarrow.Table` schema, and execution metadata contract for the `chunker` (`ChunkerOperator`) functional operator.

## ADDED Requirements

### Requirement: Supported Chunking Strategies

The `chunker` operator SHALL support five `chunk_type` strategies: `"simple"`, `"semantic"`, `"hybrid"`, `"hierarchical"`, and `"page"`, defaulting to `"simple"` when `chunk_type` is omitted.

#### Scenario: Default simple chunking strategy
- **WHEN** the `chunker` operator is initialized without a `chunk_type` configuration key
- **THEN** the operator SHALL use the `"simple"` recursive character splitting strategy

#### Scenario: Hierarchical structure-aware chunking strategy
- **WHEN** the `chunker` operator is configured with `chunk_type: "hierarchical"` and transforms a document containing structural elements (headings, paragraphs, lists, or tables)
- **THEN** the operator SHALL emit structure-based chunks according to the configured Docling hierarchical options, including list-item merging and heading emission, without applying token-window splitting

#### Scenario: Page-level chunking strategy
- **WHEN** the `chunker` operator is configured with `chunk_type: "page"` and transforms a multi-page Docling document
- **THEN** the operator SHALL emit one chunk per page with non-empty serialized content, in page-number order, and SHALL omit pages with empty serialized content

#### Scenario: Page chunking without page metadata
- **WHEN** the `chunker` operator uses `chunk_type: "page"` on a document without page metadata, including markdown converted without page metadata
- **THEN** the operator SHALL treat the document as a single page and emit one chunk if its serialized content is non-empty

#### Scenario: Unsupported chunk type rejected
- **WHEN** the `chunker` operator is initialized or validated with an unrecognized `chunk_type` value
- **THEN** validation SHALL record an error and initialization SHALL raise a `ValueError`

### Requirement: Docling Chunk Contextualization

The `chunker` operator SHALL support boolean `contextualize` (default `false`) for `"hybrid"`, `"hierarchical"`, and `"page"`. When enabled, local text MUST use the selected chunker's `contextualize(chunk)` method; remote text MUST use the provider's contextualized representation. Added context SHALL depend on available chunk metadata.

#### Scenario: Contextualization disabled by default
- **WHEN** the `chunker` operator runs with `chunk_type` set to `"hybrid"`, `"hierarchical"`, or `"page"` and `contextualize` omitted or `false`
- **THEN** each chunk dictionary's `"chunk"` field SHALL contain the raw chunk text without additional contextualization; headings already serialized in the raw text SHALL be preserved

#### Scenario: Contextualization enabled prepends headings
- **WHEN** the `chunker` operator runs with `chunk_type` set to `"hybrid"` or `"hierarchical"` and `contextualize: true` on a chunk with heading metadata
- **THEN** the chunk dictionary's `"chunk"` field SHALL contain Docling's contextualized text including the available hierarchical section headings

#### Scenario: Page contextualization without heading metadata
- **WHEN** the `chunker` operator runs with `chunk_type: "page"` and `contextualize: true` and the page chunk has no heading metadata
- **THEN** the operator SHALL use Docling's contextualized text without synthesizing missing parent headings, and the result MAY equal the raw page text

### Requirement: Configurable Hybrid and Hierarchical Chunker Options

The `chunker` operator SHALL expose configuration parameters for Docling chunker behavior: `merge_peers` (boolean, default `true`), `repeat_table_header` (boolean, default `true`), `always_emit_headings` (boolean, default `false`), and `omit_header_on_overflow` (boolean, default `false`) for `"hybrid"`, and `merge_list_items` (boolean, default `true`) and `always_emit_headings` (boolean, default `false`) for `"hierarchical"`.

#### Scenario: Hybrid chunker peer merging disabled
- **WHEN** the `chunker` operator is configured with `chunk_type: "hybrid"` and `merge_peers: false`
- **THEN** adjacent undersized peer chunks sharing the same heading context SHALL NOT be merged into a single chunk

#### Scenario: Hierarchical chunker list item merging disabled
- **WHEN** the `chunker` operator is configured with `chunk_type: "hierarchical"` and `merge_list_items: false`
- **THEN** individual list items SHALL be emitted as separate chunks rather than merged into a single list chunk

#### Scenario: Always emit headings enabled
- **WHEN** the `chunker` operator is configured with `chunk_type: "hybrid"` or `"hierarchical"` and `always_emit_headings: true`
- **THEN** section headings (including empty sections) SHALL be emitted in the chunk stream

### Requirement: Remote Docling Serve Provider Compatibility

When `provider` is configured as `"docling_serve"`, the `chunker` operator SHALL route `"hybrid"` requests to `/v1/chunk/hybrid/source` and `"hierarchical"` requests to `/v1/chunk/hierarchical/source`, and SHALL reject `"page"` chunking during validation because `docling_serve` does not expose a page-chunking endpoint.

#### Scenario: Remote hierarchical chunking endpoint selection
- **WHEN** the `chunker` operator is configured with `provider: "docling_serve"` and `chunk_type: "hierarchical"`
- **THEN** the operator SHALL send chunking requests to `/v1/chunk/hierarchical/source` with `chunking_options.chunker` set to `"hierarchical"`

#### Scenario: Remote page chunking rejected in validation
- **WHEN** `validate()` is called on the `chunker` operator with `provider: "docling_serve"` and `chunk_type: "page"`
- **THEN** `validate()` SHALL append a validation error stating that `chunk_type: "page"` is not supported with `provider: "docling_serve"`

### Requirement: Strategy-Specific Parameter Validation

The `chunker` operator `validate()` method SHALL enforce parameter constraints specific to the configured `chunk_type` rather than applying `"simple"` character-range limits (`500..5000`) to all strategies.

#### Scenario: Simple chunker character range enforced only for simple strategy
- **WHEN** `validate()` is called with `chunk_type: "simple"` and `chunk_size: 200`
- **THEN** `validate()` SHALL append a validation error requiring `chunk_size` between `500` and `5000`

#### Scenario: Hybrid chunker allows token chunk sizes below 500
- **WHEN** `validate()` is called with `chunk_type: "hybrid"` and `chunk_size: 256`
- **THEN** `validate()` SHALL accept `chunk_size` within the Docling token range `[100, 2048]` without raising a `"simple"` chunker range error

#### Scenario: Hierarchical and page strategies ignore chunk_size range limits
- **WHEN** `validate()` is called with `chunk_type: "hierarchical"` or `chunk_type: "page"`
- **THEN** `validate()` SHALL NOT enforce `chunk_size` or `chunk_overlap` numeric range constraints

#### Scenario: Boolean option type validation
- **WHEN** `validate()` is called with a non-boolean value for `contextualize`, `merge_peers`, `repeat_table_header`, `always_emit_headings`, `omit_header_on_overflow`, or `merge_list_items`
- **THEN** `validate()` SHALL append a validation error identifying the invalid boolean parameter

### Requirement: Input and Output PyArrow Table Schema and Metadata Contract

The `chunker` operator SHALL accept a `pa.Table` with the configured document column (`doc_column`, default `"content"`) and `"doc_id"`, returning `tuple[list[pa.Table], dict]`. Inline `chunked_content` SHALL contain dictionaries with `"chunk"`, `"chunk_sequence_number"`, and `"start_index"`, plus optional summaries. Existing memory-mapped storage and metadata contracts SHALL be preserved. This change SHALL NOT add `"num_chunks"` or `"chunking_strategy"` columns.

#### Scenario: Successful document chunking output schema and metadata
- **WHEN** `transform()` processes a `pyarrow.Table` with valid document text in `doc_column` using inline chunk storage
- **THEN** the returned table SHALL include `"chunked_content"` with the existing chunk dictionary fields, and the metadata dictionary SHALL report `total_docs`, `processed_docs`, `total_chunks`, `failed_docs`, and `node_status` using the existing metadata structure

#### Scenario: Original columns preserved according to configuration
- **WHEN** `transform()` returns successfully processed documents
- **THEN** original columns SHALL be preserved except for the configured document column when `retain_original_content` is false

#### Scenario: Empty or missing document content recorded as failure
- **WHEN** `transform()` processes a row whose configured document column is missing or whose content is null, empty, or whitespace-only
- **THEN** the operator SHALL record the document in `failed_docs`, increment the failed-document count, remove the failed row from the output table, and merge `COMPLETED_WITH_ERRORS` into the execution status using the existing status-merging behavior

### Requirement: Docling Chunk Offset Semantics

For Docling-based strategies, `start_index` SHALL remain a best-effort position value in the existing chunk dictionary contract. It SHALL NOT be advertised as an exact source character offset when the source is serialized Docling data or when serialization changes the text. Enabling contextualization SHALL NOT shift the position to account for prepended context.

#### Scenario: Contextualization preserves the body position
- **WHEN** a local Docling chunk is contextualized and the operator locates its body in source text
- **THEN** source lookup SHALL use raw `chunk.text` rather than contextualized text, and `start_index` SHALL refer to that body's position

#### Scenario: Exact source position unavailable
- **WHEN** raw chunk text cannot be reliably located in the source, including serialized Docling input
- **THEN** the operator SHALL retain a deterministic best-effort position without failing the document or claiming that position is an exact source character offset
