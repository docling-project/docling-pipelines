# Design

## Context

See `proposal.md` for motivation. Within the `docpipe` architecture, `ChunkerOperator` (`src/docpipe/core/operators/functional/chunker.py`) is a built-in `Functional` operator extending `AbstractOperator` (`src/docpipe/core/operators/abstract_operator.py`), accompanied by `ChunkerValidator` (`src/docpipe/core/operators/functional/chunker_validator.py`). It operates purely in the core operator execution layer—receiving and returning `pyarrow.Table` instances—without touching DDD domain/application/adapter layers in `core/assets/` or `core/job_management/`.

On `HEAD`, `ChunkerOperator` has three technical limitations:
1. `_get_docling_chunker()` only instantiates `HybridChunker(tokenizer=hf_tokenizer, merge_peers=True)`, ignoring `HierarchicalChunker` and `PageChunker` from `docling_core.transforms.chunker` as well as `HybridChunker`'s configurable parameters.
2. `_docling_split_text()` always reads `chunk.text`, discarding hierarchical section headings stored in `chunk.meta.headings` unless `chunker.contextualize(chunk)` is invoked.
3. `ChunkerOperator.validate()` unconditionally executes `ChunkerValidator.validate_simple_chunker()`, enforcing `chunk_size` in `[500, 5000]` even when `chunk_type` is `"hybrid"` (which uses token counts in `[100, 2048]`) or a strategy that does not use `chunk_size`.

## Goals / Non-Goals

**Goals:**
- Unify local Docling chunking (`hybrid`, `hierarchical`, `page`) behind `docling_core.transforms.chunker.base.BaseChunker` inside `ChunkerOperator._get_docling_chunker()`.
- Support optional heading contextualization (`contextualize: bool = False`) across all Docling chunkers (`hybrid`, `hierarchical`, `page`) while preserving the existing `chunked_content` schema (`chunk`, `chunk_sequence_number`, `start_index`).
- Expose `HybridChunker` and `HierarchicalChunker` structural parameters in both `__init__`, `validate()`, and `get_metadata()`.
- Decouple strategy validation in `ChunkerValidator` so each `chunk_type` validates only its applicable parameters.

**Non-Goals:**
- Altering downstream `EmbeddingsOperator` or `VectorDBOperator` table contracts.
- Adding custom React components in `frontend/src/` (the operator JSON schema in `get_metadata()` drives UI rendering automatically).

## Decisions

### 1. Polymorphic `BaseChunker` Initialization in `_get_docling_chunker()`
- **Decision**: Extend `ChunkType` with `HIERARCHICAL = "hierarchical"` and `PAGE = "page"`, define a helper `_is_docling_chunker()` (or `DOCLING_CHUNK_TYPES = {ChunkType.HYBRID, ChunkType.HIERARCHICAL, ChunkType.PAGE}`), and branch inside `_get_docling_chunker()` to return a `BaseChunker` instance:
  - `ChunkType.HYBRID`: Load `AutoTokenizer.from_pretrained(self.docling_tokenizer)`, wrap in `HuggingFaceTokenizer(tokenizer=..., max_tokens=self.chunk_size)`, and instantiate `HybridChunker(tokenizer=hf_tokenizer, merge_peers=self.merge_peers, repeat_table_header=self.repeat_table_header, always_emit_headings=self.always_emit_headings, omit_header_on_overflow=self.omit_header_on_overflow)`.
  - `ChunkType.HIERARCHICAL`: Instantiate `HierarchicalChunker(merge_list_items=self.merge_list_items, always_emit_headings=self.always_emit_headings)` directly without loading a HuggingFace tokenizer.
  - `ChunkType.PAGE`: Instantiate `PageChunker()` directly without loading a HuggingFace tokenizer.
- **Alternatives Considered**:
  - *Creating separate operator classes (`HierarchicalChunkerOperator`, `PageChunkerOperator`)*: Rejected because `ChunkerOperator` already encapsulates multi-strategy chunking via `chunk_type` and shares document deserialization (`DocLangDocDeserializer` / `MarkdownDocumentBackend`), remote `docling_serve` fallback, and output column formatting.

### 2. Heading Contextualization via `chunker.contextualize(chunk)` in `chunk` Text
- **Decision**: Add `contextualize: bool = False` to `ChunkerOperator`. In `_docling_split_text()`, compute `chunk_text = chunker.contextualize(chunk) if self.contextualize else chunk.text` and store `chunk_text` in the `"chunk"` field of each dictionary in `chunked_content`. For `provider == "docling_serve"`, pass `"include_raw_text": not self.contextualize` in `chunking_options` and select contextualized text when `self.contextualize` is `True`.
- **Alternatives Considered**:
  - *Adding a separate `headings` field inside `chunked_content` dicts and leaving `chunk` uncontextualized*: Rejected as primary mechanism because `EmbeddingsOperator` embeds `item["chunk"]` directly; prepending headings via Docling's native `chunker.contextualize(chunk)` immediately improves embedding and retrieval quality with zero changes to downstream operators.

### 3. Strategy-Scoped Validation in `ChunkerValidator`
- **Decision**: Refactor `ChunkerOperator.validate()` and `ChunkerValidator` so that:
  - Common string parameters (`doc_column`, `output_column`, `chunk_type`) are validated for all strategies via `validate_common_chunk_parameters()`.
  - `validate_simple_chunker()` (`chunk_size` in `[500, 5000]`, `chunk_overlap` in `[0, 500]`, `chunk_overlap < chunk_size`, `split_by` type check) runs **only** when `chunk_type == ChunkType.SIMPLE.value`.
  - `validate_docling_chunker()` runs for `"hybrid"`, `"hierarchical"`, and `"page"`, validating `provider` (`"docling_library"` or `"docling_serve"`), boolean flags (`contextualize`, `merge_peers`, `repeat_table_header`, `always_emit_headings`, `omit_header_on_overflow`, `merge_list_items`), and enforcing `chunk_size` in `[100, 2048]` (`DOCLING_CHUNK_SIZE_MIN..DOCLING_CHUNK_SIZE_MAX`) and `docling_tokenizer` only when `chunk_type == ChunkType.HYBRID.value`.
  - When `provider == "docling_serve"` and `chunk_type == ChunkType.PAGE.value`, `validate_docling_chunker()` appends a validation error because `docling_serve` only exposes `/v1/chunk/hybrid/source` and `/v1/chunk/hierarchical/source`.

### 4. `start_index` Calculation with `contextualize=True`
- **Decision**: When `contextualize=True`, `chunker.contextualize(chunk)` prepends headings that may not appear verbatim right before the body text in the raw source string. `_docling_split_text()` will first attempt `text.find(chunk.text, current_pos)` using the raw `chunk.text` to locate the raw body in source text, falling back to a deterministic best-effort position if not found. Serialized Docling input and text changed by serialization do not guarantee exact source character offsets. Contextualization must not shift the position to account for prepended context.

## Risks / Trade-offs

- **[Risk] Markdown input lacks explicit page break markers for `PageChunker`** → **Mitigation**: `PageChunker` iterates `DoclingDocument.pages` in page-number order and omits pages with empty serialized content. Without page metadata, it emits a single chunk for non-empty serialized document content. Page chunks have no heading metadata, so contextualization need not add headings; document in `chunker_readme.md` and `OPERATORS.md` that `chunk_type="page"` is intended for `doclang` output from `ExtractOperator`.
- **[Risk] Existing flows relying on `HybridChunker` defaults** → **Mitigation**: All new boolean options default to `docling_core`'s current behavior (`contextualize=False`, `merge_peers=True`, `repeat_table_header=True`, `always_emit_headings=False`, `omit_header_on_overflow=False`, `merge_list_items=True`), preserving the intended local defaults. Remote raw/contextualized text selection must be verified against the server response contract during implementation.

### Output and failure compatibility

The existing `chunked_content` dictionary fields, optional summaries, memory-mapped storage, original-content retention, and execution metadata remain unchanged. Do not add `num_chunks` or `chunking_strategy` columns. Missing, null, empty, or whitespace-only content remains a document failure: record it, remove the failed row, and merge `COMPLETED_WITH_ERRORS` into the status.
