# Design

## Context

The existing notebooks establish clear conventions: a top-level settings cell with capitalised constants for all tuneable parameters, `DocpipeFlowManager` as the programmatic entry point, and a fixed `job_id` / `job_run_id` so output paths are predictable on re-runs. This notebook follows those conventions.

Three decisions from the exploration phase shape the approach here and are not restated in the proposal:

1. **Full pipeline (Option A)**: `ingest → extract → chunk` runs end-to-end. Bypassing extract would deprive the `hybrid` strategy of Docling's parsed document structure — the very thing that makes it distinct from `simple`.
2. **`docs/` as corpus**: Three real markdown files from the project's own documentation serve as the corpus. This is self-referential in a compelling way and avoids synthetic data that would make outputs uninteresting.
3. **Qualitative retrieval signal, not labeled precision/recall**: No ground-truth annotations are required. Cosine similarity ranking with answer-phrase verification is sufficient to expose strategy differences and avoids the annotation maintenance burden that labeled metrics would introduce.

## Goals / Non-Goals

**Goals:**
- Define the notebook's cell group structure and data flow so implementation is mechanical
- Specify the three corpus documents and the rationale for their selection
- Define the five targeted retrieval queries (four with expected answers, one negative control) and the structural property each is designed to expose
- Specify the Ollama availability check pattern and the hard-stop behaviour it enforces
- Specify how intra/inter-chunk coherence scores are computed and how they connect to the retrieval section
- Record the semantic percentile selection decision

**Non-Goals:**
- Does not design new operators or modify `ChunkerOperator`
- Does not design a benchmark harness — outputs are for human reading, not automated regression

## Decisions

### D1: Corpus — three docs files, chosen for structural contrast

| File | Size | Structure | Strategy it highlights |
|---|---|---|---|
| `docs/guides/FLOW_CONFIGURATION_GUIDE.md` | ~21KB | Dense prose + code examples | `simple` — long narrative with predictable sentence boundaries |
| `docs/guides/PYTHON_API_GUIDE.md` | ~20KB | Mixed: procedures + code + prose | Baseline for all three — none has a clear advantage; good for comparison |
| `docs/guides/SECURITY_BEST_PRACTICES.md` | ~14KB | Short-item lists + policy prose | `hybrid` — list items and policy blocks are structural nodes Docling preserves |

**Why not `docs/operators/functional/chunker_readme.md`?** The chunker readme contains a large markdown table block (~4.7 KB as a single "sentence") that overflows Ollama's context window during semantic chunking, causing a 500 error. It was screened out during the exploration phase. The three chosen files all produce valid chunks from all three strategies.

**Why not synthetic documents?** Real project docs make the blog post self-referential and produce outputs a reader can independently verify by looking at the source files.

### D2: Five retrieval queries — four with answer phrases, one negative control

| # | Query | Answer phrase (substring in right chunk) | Source file |
|---|---|---|---|
| 1 | JWT rotation policy | "immediately after any suspected exposure" | `SECURITY_BEST_PRACTICES.md` |
| 2 | How is `job_id` generated? | "UUID v5" | `FLOW_CONFIGURATION_GUIDE.md` |
| 3 | What happens when no `job_id` is passed? | "random UUID will be generated" | `FLOW_CONFIGURATION_GUIDE.md` |
| 4 | How to disable embedded logging? | "configure_logging=False" | `PYTHON_API_GUIDE.md` |
| 5 (control) | In-memory vs filesystem storage | _(no focused paragraph in corpus)_ | — |

Each query has a corresponding `answer_phrase` key in `RETRIEVAL_QUERIES`. The result table shows, for each query and strategy, the rank of the first top-3 chunk containing the answer phrase (or "not in top 3"). No expected winners are written into prose before running — the result table speaks for itself.

The control query (query 5) is expected to return no clean top-3 hit on any strategy. Its presence makes the summary honest: the retrieval comparison is not cherry-picked to show only queries where every strategy succeeds.

### D3: No parquet cache — single fan-out flow with fixed job_id

There is no `notebook_cache/` directory and no `FORCE_REEXTRACT` flag. Instead:

- A single `DocpipeFlowManager` flow runs `ingest → extract → split (branching) → chunk_simple / chunk_hybrid / chunk_semantic` in one call.
- `force_ingest: true` is set on the ingest node so a re-run with the same `job_id` always ingests fresh rather than silently producing zero rows.
- `job_id` and `job_run_id` are fixed constants (`JOB_ID`, `JOB_RUN_ID`) in the settings cell, making output parquet paths predictable: `data/<JOB_ID>/<JOB_RUN_ID>/data/chunk_<x>_0/0/output.parquet`.
- Re-running the flow cell overwrites the existing output folder (same paths, same parquet schema). This is equivalent to the old cache pattern but simpler — no separate cache dir, no cache-guard logic.

**Why a `branching` node?** The fan-out could also be written as three nodes that each list `extract` in `depends_on`. An unconditional `branching` node (`branches: {to_simple: {}, to_hybrid: {}, to_semantic: {}}`) is used instead because it is the documented fan-out pattern, it makes the split visible as a node, and it shows readers the operator. Each branch receives a full copy of the table; chunkers depend on `split.to_<strategy>`. Verified with `.bob/tmp/branch_proto.py`: all three chunkers produced chunk counts identical to the plain `depends_on` version. The `split` node also writes `split_0..2` output folders that the notebook ignores.

**Why `force_ingest: true`?** Verified empirically (`.bob/tmp/noforce.py`): without it, a second run with the same `job_id` produces `ingest_0 = 0 rows` while leaving stale chunk parquet in place from the first run. `force_ingest` prevents silent stale-data use.

### D4: Ollama is REQUIRED — early hard stop, no graceful fallback

Ollama with `nomic-embed-text` is a hard prerequisite. The notebook does not run partially without it. This means:

- One early code cell (after the imports and settings cells) calls `GET /api/tags` against `OLLAMA_HOST` and checks that `EMBEDDING_MODEL` is installed.
- If the check fails (server unreachable or model not installed), the cell raises `RuntimeError` with a message containing the matching command: `ollama serve` when the server is unreachable, `ollama pull nomic-embed-text` when the model is missing. For example:
  ```
  Ollama not available at http://localhost:11434
  To fix, run:
    ollama serve
    ollama pull nomic-embed-text
  ```
- `raise RuntimeError(...)` is Ruff-safe. `raise SystemExit` and `%%script false` are explicitly forbidden.
- There is no `OLLAMA_AVAILABLE` boolean, no `if not OLLAMA_AVAILABLE:` guard in any subsequent cell, and no per-cell skip message. Every cell after the check assumes Ollama is up.

This design was chosen because half-empty tables (structural metrics only, with blank rows for semantic) are misleading and confusing for a reader. A clean hard stop with a clear fix message is better UX.

### D5: Embedding model — `nomic-embed-text` for consistency

The embedding model for semantic chunking, coherence scoring, and retrieval is `nomic-embed-text` (768 dimensions). It is already the standard across `04_embeddings_vectordb.ipynb` and `06_rag_pipeline.ipynb`. A reader who has run any existing notebook already has it pulled.

### D6: Coherence score computation — pure numpy, no new dependencies

Intra-chunk similarity for a single chunk: mean pairwise cosine similarity of sentence-level embeddings within that chunk. Inter-chunk similarity for adjacent pairs: direct cosine similarity between adjacent chunk mean-embeddings.

```
intra_sim(chunk)  = mean(cosine(embed(s_i), embed(s_j)) for all sentence pairs i≠j)
inter_sim(c_i, c_{i+1}) = cosine(mean_embed(c_i), mean_embed(c_{i+1}))
```

Sentence splitting uses `text.split(". ")`, dropping fragments of 20 characters or fewer — deliberately simple. All work uses `numpy` (available in the dev environment via `uv sync --extra notebooks`). No new packages are introduced. Embeddings are computed once and reused across coherence and retrieval.

### D7: Cell group structure

```
§0  Intro + strategy overview table + steps/tech/where-it-runs table
§1  Setup: imports, settings (capitalised constants), Ollama hard-stop check
§2  The corpus documents (small table: file, topic, size)
§3  Build and run ONE fan-out flow:
      ingest → extract → split (branching, 3 unconditional branches) → chunk_simple / chunk_hybrid / chunk_semantic
      (ASCII diagram; fixed job_id/job_run_id; force_ingest:true)
§4  Inspect the chunks — same JWT-rotation passage, all 3 strategies stacked vertically
§5  Structural metrics table (chunk count, mean chars, std dev, max chunk)
§6  Coherence scores (intra + inter per strategy per doc; "closeness score" framing)
§7  Retrieval — 5 queries × 3 strategies; answer-phrase rank table;
      returned chunk text for answer-phrase queries
    Narrative (after the returned-chunk cells): what the numbers mean for each strategy
§8  Choosing a strategy: decision table + config quick-reference
```

### D8: Pre-commit compliance for notebook code cells

Four pre-commit hooks run on `.ipynb` files:

- **`check-json`**: The notebook file must be valid JSON.
- **`nbstripout`**: Strips all cell outputs before staging.
- **`nbqa-ruff-check --nbqa-dont-skip-bad-cells`**: Ruff lints every Python code cell. Key implications:
  - All imports consolidated in the setup cell (§1)
  - No bare `except:` — always catch a specific exception type
  - No unused variables
  - Use `itertools.pairwise` instead of `zip(x, x[1:])` (Ruff B007 / B905 flag)
  - `raise RuntimeError(...)` for the Ollama hard stop — **not** `raise SystemExit`, **not** `%%script false`
  - The old `if not OLLAMA_AVAILABLE: ... else: ...` gating pattern is **removed** — it is no longer present in the notebook
- **`check-added-large-files` (3000KB limit)**: The stripped notebook must stay under 3MB.
- **`detect-secrets`**: No credentials, tokens, or API keys may appear in cell source.

### D9: Semantic chunker — percentile 45 chosen via chunk-size sweep

The semantic chunker's `breakpoint_threshold_amount` controls how aggressively it splits: lower = more splits = smaller chunks.

A sweep over the three corpus documents was run at percentile values 35, 45, 55, 65, 75, 85, 95 (`.bob/tmp/sweep.py`). Mean chunk sizes (chars) per document at key values:

| Percentile | FLOW_CONFIG | PYTHON_API | SECURITY |
|---|---|---|---|
| 95 (default) | 5148 | 6518 | 2256 |
| 55 | 857 | 1303 | 355 |
| 45 | 735 | 1028 | 287 |
| 35 | 623 | 888 | 245 |

**Decision: percentile = 45.** Mean-of-means 683 chars, close to `simple` at 750. This makes the three strategies directly comparable in the structural metrics table without one strategy dominating by chunk count alone.

Note: a single code block in `PYTHON_API_GUIDE.md` (~5 KB, no sentence punctuation) produces one very large chunk (3.9–5.7 KB) at every percentile ≤ 55. The semantic splitter splits on sentence boundaries; a code block has none, so it cannot be split. The notebook calls this out explicitly.

### D10: Notebook numbering — `08_`

Existing notebooks are `01` through `07`. The new file is `08_chunking_strategies.ipynb`. If a future notebook is added at `08` before this is merged, the number should be bumped — noted as a minor merge-time check in tasks.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| `hybrid` chunking on `.md` files produces same output as `simple` if Docling's markdown parser treats all content as flat text | Verified during implementation: the three chosen corpus files show distinct chunk shapes between `simple` and `hybrid`. |
| Intra-chunk similarity is low across all strategies because `docs/` prose is already homogeneous | The comparison is relative, not absolute. Strategy differences are structural and visible even when absolute scores are similar. |
| `nomic-embed-text` embedding calls are slow for large chunk sets | Each embed call is ~50–100ms on a warm Ollama instance. Notebook trims inputs to `max_embed_chars=4000` to avoid Ollama's ~7KB per-request limit. |
| Notebook numbering conflict at merge time | Tasks include a check: confirm no `08_` notebook was added since this change was branched. |

## Open Questions

None — all decisions required before implementation are resolved above.
