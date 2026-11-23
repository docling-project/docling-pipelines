# Tasks

## 1. Docling Chunker Strategies & Contextualization

- [ ] 1.1 [backend] Extend `ChunkType` with `HIERARCHICAL = "hierarchical"` and `PAGE = "page"` and add configuration attributes (`contextualize`, `merge_peers`, `repeat_table_header`, `always_emit_headings`, `omit_header_on_overflow`, `merge_list_items`) to `ChunkerOperator.__init__` in `src/docpipe/core/operators/functional/chunker.py`; verify initialization defaults via `pytest tests/unit/operators/chunker/test_chunker.py`.
- [ ] 1.2 [backend] Update `ChunkerOperator._get_docling_chunker()`, `_docling_split_text()`, and `_docling_serve_split_text()` in `src/docpipe/core/operators/functional/chunker.py` to instantiate `HybridChunker`, `HierarchicalChunker`, and `PageChunker`, apply `chunker.contextualize(chunk)` when `contextualize=True`, and route remote `hierarchical` chunking to `/v1/chunk/hierarchical/source`; verify with unit tests in `tests/unit/operators/chunker/test_chunker.py` covering `hierarchical`, `page`, `contextualize`, and `HybridChunker`/`HierarchicalChunker` flags.

## 2. Strategy-Scoped Validation & Operator Metadata

- [ ] 2.1 [backend] Refactor `ChunkerValidator` (`src/docpipe/core/operators/functional/chunker_validator.py`) and `ChunkerOperator.validate()` (`src/docpipe/core/operators/functional/chunker.py`) so `validate_simple_chunker` runs only for `chunk_type == "simple"`, `hybrid` validates token `chunk_size` in `[100, 2048]`, `docling_serve` rejects `chunk_type == "page"`, and boolean types are validated for all new Docling options; verify with validation unit tests in `tests/unit/operators/chunker/test_chunker.py`.
- [ ] 2.2 [backend] Update `ChunkerOperator.get_metadata()` in `src/docpipe/core/operators/functional/chunker.py` and operator documentation in `docs/operators/functional/chunker_readme.md` and `docs/reference/OPERATORS.md` to document `"hierarchical"`, `"page"`, `contextualize`, and the new `HybridChunker`/`HierarchicalChunker` parameters; verify metadata schema and docs completeness via `docling-pipelines --list-operators --verbose`.

## 3. Integration & Quality Verification

- [ ] 3.1 [backend] Run the full chunker test suite, linter, and static type checks (`pytest tests/unit/operators/chunker/ -v`, `ruff check src/docpipe/core/operators/functional/chunker.py src/docpipe/core/operators/functional/chunker_validator.py tests/unit/operators/chunker/test_chunker.py`, and `mypy src/docpipe/core/operators/functional/chunker.py src/docpipe/core/operators/functional/chunker_validator.py`) and verify zero errors.

## Workflow follow-up

- Archive the change with `openspec archive add-docling-chunker-upgrades` after implementation, tests, and code review are complete.
