# Proposal

## Why

The `ChunkerOperator` supports three distinct strategies — `simple`, `semantic`, and `hybrid` — but no focused learning resource demonstrates how they differ in practice or helps users choose the right one for their use case. Practitioners evaluating docling-pipelines for RAG workloads must currently piece together this understanding from scattered operator docs and the generic `02_operator_showcase` notebook. A dedicated, runnable notebook that shows all three strategies on real documents, compares their outputs, and surfaces a lightweight retrieval signal will accelerate adoption and provide concrete material for a Medium blog post targeting the RAG practitioner audience.

## What Changes

- Add a new Jupyter notebook `examples/notebooks/08_chunking_strategies.ipynb` that:
  - Runs the full `ingest → extract → chunk` pipeline (Option A) using three selected markdown files from `docs/guides/` as the corpus: `FLOW_CONFIGURATION_GUIDE.md`, `PYTHON_API_GUIDE.md`, and `SECURITY_BEST_PRACTICES.md`
  - Executes all three chunking strategies (`simple`, `semantic`, `hybrid`) in a single fan-out flow (`ingest → extract → split (branching) → chunk_simple / chunk_hybrid / chunk_semantic`) with a fixed `job_id` and `force_ingest: true`
  - Requires Ollama with `nomic-embed-text` — **the notebook stops with a `RuntimeError` and instructions if Ollama is unreachable** (no partial run, no graceful fallback)
  - Evaluates each strategy across three progressive metric classes:
    - **Structural metrics** (chunk count, avg size, std deviation, max chunk size) — answers "what did the chunker do?"
    - **Semantic coherence metrics** (intra-chunk cosine similarity and inter-chunk cosine similarity using `nomic-embed-text`) — answers "were the splits semantically meaningful?"
    - **Qualitative retrieval signal**: for 5 queries (four with known answer phrases, one negative control), rank all chunks by cosine similarity and show the first top-3 rank containing the answer phrase per strategy — answers "does this strategy surface the right content?"
  - Ties retrieval results back to coherence scores so readers can see *why* one strategy retrieves better, not just that it does
  - Semantic coherence and retrieval cells share the same Ollama embedding pass — no double cost
  - Includes a strategy decision guide table and config quick-reference section
- Update `examples/notebooks/README.md` to register the new notebook in the available-notebooks table

## Capabilities

### New Capabilities

None. This change introduces no new system capabilities — it documents and demonstrates existing `ChunkerOperator` behavior through an example notebook.

### Modified Capabilities

None. No existing spec-level requirements change.

> **Note:** This change sets `skip_specs: true` — it is a pure documentation/examples artifact. The `ChunkerOperator` behavior it demonstrates is already implemented; no behavioral contracts are being added or modified.

## Impact

- **Layer affected:** backend-only (Python examples, no frontend changes)
- **Files added:** `examples/notebooks/08_chunking_strategies.ipynb`
- **Files modified:** `examples/notebooks/README.md`
- **Dependencies:** Requires Ollama with `nomic-embed-text` (hard prerequisite — the notebook halts with a clear error and fix instructions if Ollama is unreachable)
- **No operator code changes**, no API route changes, no storage adapter changes

## Non-goals

- No new operator implementations or modifications to `ChunkerOperator`
- No OpenSearch integration — retrieval comparison stays in-memory
- No changes to existing notebooks
- No new Python package dependencies (uses `numpy` for cosine similarity, already available in the dev environment)
- Not a comprehensive benchmark — the notebook is a learning and evaluation aid, not a performance comparison tool
- Not a tutorial for custom chunking strategies or subclassing `AbstractOperator`
