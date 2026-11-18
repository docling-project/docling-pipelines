# Proposal

## Why

`ChunkerOperator` (`chunker`) currently exposes only a single Docling chunking strategy (`hybrid` via `HybridChunker`) with hardcoded behavior (`merge_peers=True`, raw `chunk.text` output without heading contextualization) and applies `simple` character-based `chunk_size` validation (`500..5000`) to all chunking strategies. Expanding `ChunkerOperator` to support `docling_core`'s structure-aware `hierarchical` (`HierarchicalChunker`) and page-level `page` (`PageChunker`) strategies, heading contextualization (`chunker.contextualize(chunk)`), configurable Docling chunker flags, and strategy-aware validation unlocks richer document-structure preservation and higher-quality RAG retrieval without adding new dependencies.

## What Changes

- **New Docling chunking strategies in `ChunkerOperator`**:
  - Add `"hierarchical"` (`ChunkType.HIERARCHICAL`) backed by `docling_core.transforms.chunker.hierarchical_chunker.HierarchicalChunker` (creates structure-based chunks according to list-merging and heading options, without token-window splitting).
  - Add `"page"` (`ChunkType.PAGE`) backed by `docling_core.transforms.chunker.page_chunker.PageChunker` (creates one chunk per page with non-empty serialized content; documents without page metadata are treated as a single page).
- **Heading contextualization (`contextualize`)**:
  - Add boolean configuration parameter `contextualize` (default `False`) for Docling chunkers (`hybrid`, `hierarchical`, `page`). When `True`, serialize each chunk via `chunker.contextualize(chunk)` instead of `chunk.text` using the context available in each chunk; page chunks without heading metadata do not gain synthesized parent headings.
- **Configurable Docling chunker parameters**:
  - Expose `merge_peers: bool = True`, `repeat_table_header: bool = True`, `always_emit_headings: bool = False`, and `omit_header_on_overflow: bool = False` for `HybridChunker` (`chunk_type="hybrid"`).
  - Expose `merge_list_items: bool = True` and `always_emit_headings: bool = False` for `HierarchicalChunker` (`chunk_type="hierarchical"`).
  - Support remote `docling_serve` chunking for both `"hybrid"` (`/v1/chunk/hybrid/source`) and `"hierarchical"` (`/v1/chunk/hierarchical/source`), and emit a validation error when `provider="docling_serve"` is paired with `"page"` (which has no remote endpoint).
- **Strategy-aware parameter validation in `ChunkerValidator` and `ChunkerOperator.validate`**:
  - Restrict `ChunkerValidator.validate_simple_chunker` (`chunk_size` in `[500, 5000]`) to `chunk_type == "simple"`, while validating `hybrid` token-based `chunk_size` against `[100, 2048]` (`DOCLING_CHUNK_SIZE_MIN` to `DOCLING_CHUNK_SIZE_MAX`) and skipping character/token `chunk_size` range checks for strategies that do not use `chunk_size` (`hierarchical`, `page`, `semantic`).
  - Validate boolean types for new Docling chunker options (`contextualize`, `merge_peers`, `repeat_table_header`, `always_emit_headings`, `omit_header_on_overflow`, `merge_list_items`).

## Non-goals

- Changing the output `pyarrow.Table` schema or structure of the `chunked_content` list-of-dicts column (downstream `EmbeddingsOperator` and `VectorDBOperator` compatibility is preserved without schema changes).
- Introducing custom frontend properties panel components (new parameters are exposed through `ChunkerOperator.get_metadata()` JSON schema and rendered automatically by the dynamic schema form).
- Modifying `simple` (`RecursiveCharacterTextSplitter`) or `semantic` (`SemanticChunker`) splitting algorithms.
- Adding new third-party dependencies (`docling_core` is already installed via `docling`).

## Capabilities

### New Capabilities
- `backend/chunker-operator`: Multi-strategy document chunking operator (`simple`, `semantic`, `hybrid`, `hierarchical`, `page`), Docling chunk contextualization, strategy-specific parameter validation, and `pyarrow.Table` input/output and metadata contracts.

### Modified Capabilities
<!-- None -->

## Impact

- **Affected Layers**: `backend-only` (no REST API route signatures, BFF proxy routes, `/ui` routes, Redux slices, or storage adapters are modified).
- **Affected Operators & Validators**:
  - `src/docpipe/core/operators/functional/chunker.py` (`ChunkerOperator`, `ChunkType`)
  - `src/docpipe/core/operators/functional/chunker_validator.py` (`ChunkerValidator`)
- **Affected REST / Metadata Surfaces**:
  - `GET /api/v1/operators/metadata` and `POST /api/v1/validation/validate_flow` automatically reflect the updated `ChunkerOperator.get_metadata()` schema and `ChunkerOperator.validate()` rules.
- **Documentation & Tests**:
  - `docs/operators/functional/chunker_readme.md` and `docs/reference/OPERATORS.md`
  - `tests/unit/operators/chunker/test_chunker.py`
