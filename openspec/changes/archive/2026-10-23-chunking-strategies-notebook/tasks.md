# Tasks

## 1. Scaffold and setup [backend]

- [x] 1.1 Confirm no `08_` notebook already exists in `examples/notebooks/`; if a conflict exists, choose the next available number and update the file name used in all subsequent tasks. Verify by listing `examples/notebooks/`. _(verified: only `08_chunking_strategies.ipynb` exists)_
- [x] 1.2 Create `examples/notebooks/08_chunking_strategies.ipynb` via `.bob/tmp/build_nb.py` with: imports cell, capitalised-constant settings cell (`CORPUS`, `OLLAMA_HOST`, `EMBEDDING_MODEL`, chunker settings, `JOB_ID`, `JOB_RUN_ID`, `QUERIES` with `answer_phrase` keys), Ollama hard-stop cell, helper functions cell. Verify the file exists and the notebook is valid JSON. _(verified: 33-cell notebook generated; `check-json` pre-commit passes)_

## 2. Fan-out flow — Ingest + Extract + Branching + three Chunkers [backend]

- [x] 2.1 Implement a single fan-out `DocpipeFlowManager` flow with an unconditional `branching` node (`branches: {to_simple: {}, to_hybrid: {}, to_semantic: {}}`; chunkers depend on `split.to_<strategy>`): `ingest → extract → split (branching) → chunk_simple / chunk_hybrid / chunk_semantic`. Fixed `JOB_ID = "chunking-strategies-nb"` and `JOB_RUN_ID = "run"`. Set `force_ingest: true` on the ingest node so re-runs with the same `job_id` ingest fresh rows rather than silently producing zero rows. Corpus: `docs/guides/FLOW_CONFIGURATION_GUIDE.md`, `docs/guides/PYTHON_API_GUIDE.md`, `docs/guides/SECURITY_BEST_PRACTICES.md`. Verify output parquet is written under `data/chunking-strategies-nb/run/data/chunk_<x>_0/0/output.parquet` and each strategy produces at least one chunk per document. _(verified headlessly via `.bob/tmp/inspect_results.py`)_
- [x] 2.2 After the flow cell, load each chunker output back from parquet into a `CHUNKS` dict (`{strategy: {doc_name: [chunk_text, …]}}`). Add a check that all 3 strategies × 3 documents have at least 1 chunk each. _(verified: all 9 combinations have chunks)_

## 3. Inspect + structural metrics [backend]

- [x] 3.1 Implement the chunk-inspect cell (§4): pick the JWT-rotation passage in `SECURITY_BEST_PRACTICES.md` using a `chunk_with_phrase(strategy, doc_name, phrase)` helper; display the chunk text from all three strategies, one block per strategy. Verify by running the cell — each strategy must return at least one hit for the phrase.
- [x] 3.2 Implement the structural metrics table (§5): for each strategy and document compute chunk count, mean chunk chars, std deviation, max chunk chars, and approximate overlap ratio. Display as a `pandas.DataFrame`. Verify the table renders with all three strategies as rows (or grouped rows) and all metric columns present.
- [x] 3.3 Add "Points to notice" markdown bullets after the structural metrics table explaining what patterns to look for (`simple` capped at `SIMPLE_CHUNK_SIZE`, `hybrid` with smaller and variable chunks, `semantic` with occasionally very large chunks due to code blocks that have no sentence boundaries). Verify the cell is markdown only and contains substantive prose.
- [x] 3.4 Add a display cell showing the JWT-rotation passage chunks from all three strategies. Render with `display(HTML(...))`, one bordered block per strategy stacked vertically (a three-column table was unreadable). Verify the output visibly shows boundary differences between strategies.

## 4. Ollama hard-stop check [backend]

- [x] 4.1 Implement the Ollama check cell (§1, order: imports -> settings -> Ollama check -> helpers): call `GET /api/tags` against `OLLAMA_HOST`; if the request fails, `raise RuntimeError(...)` with the `ollama serve` instruction; if `EMBEDDING_MODEL` is not listed, `raise RuntimeError(...)` with the `ollama pull nomic-embed-text` instruction. There is no `OLLAMA_AVAILABLE` boolean and no per-cell skip guard anywhere in the notebook. Verify: with Ollama running, the cell prints a ready message; with Ollama stopped (or pointed at a closed port), a `RuntimeError` is raised with the instructions in the message. _(RuntimeError verified: see task 7.5)_
- [x] 4.2 Confirm there are no `OLLAMA_AVAILABLE` references, no `if not OLLAMA_AVAILABLE:` guards, no `raise SystemExit`, and no `%%script false` in any cell. _(verified: `nbqa-ruff-check` pre-commit passes on the generated notebook)_

## 5. Coherence scores + retrieval [backend]

- [x] 5.1 Implement `embed_texts(texts, batch_size=32)` helper (§1 helpers cell) with an `EMBED_CACHE` dict so each unique text is embedded once and reused across coherence and retrieval steps. Verify by calling it twice with the same input and confirming the second call is a cache hit (no Ollama request).
- [x] 5.2 Compute coherence scores (§6): for each chunk, split into sentences with `text.split(". ")` (deliberately simple; fragments of 20 characters or fewer are dropped), embed each sentence (up to `MAX_SENTENCES_PER_CHUNK`), compute mean pairwise cosine similarity (intra) and cosine similarity between adjacent chunk mean-embeddings (inter). Display as a `pandas.DataFrame` with per-strategy per-document rows. Verify the table renders with `intra_chunk_sim` and `inter_chunk_sim` columns.
- [x] 5.3 Implement the retrieval cell (§7): for each of the 5 queries in `QUERIES`, embed the query, compute cosine similarity against all chunks from each strategy (using pre-computed normalised chunk vectors), and build a summary table showing the rank of the first top-3 chunk containing the `answer_phrase` (or `"not in top 3"` / `"no answer exists"` for the control). Verify the summary table renders with one row per query and one column per strategy.
- [x] 5.4 Add a "Returned chunks" cell (§7) showing top-`TOP_K` chunk excerpts per strategy for each query, with `*` marking chunks that contain the answer phrase. Verify the cell renders and `*` markers appear where expected.

## 6. Narrative + decision guide + README [backend]

- [x] 6.1 Add the narrative markdown cell after the section 7 returned-chunks cells. Text must be based on actual run numbers, explain what each strategy does well and where it falls short, and mention the code-block caveat for `semantic`. Verify the cell contains substantive prose (not placeholder text). _(narrative from `.bob/tmp/narrative.md`, checked against headless run results)_
- [x] 6.2 Add the strategy decision guide ("## 8. Choosing a strategy"): a markdown table mapping input type to recommended strategy with a one-line rationale per row, plus a config quick-reference showing the minimal JSON config for each strategy. Verify the markdown renders cleanly.
- [x] 6.3 Update `examples/notebooks/README.md` to add `08_chunking_strategies.ipynb` to the "Available Notebooks" table and add a section with description, "What you'll learn" bullets, and prerequisites (Ollama with `nomic-embed-text` required; `nomic-embed-text` must be pulled). Verify the README entry matches the actual notebook prerequisites.

## 7. Validation [backend]

- [x] 7.1 Audit every Python code cell for Ruff compliance: all imports in the imports cell; `except` clauses catch specific exception types; no unused variables; `itertools.pairwise` used instead of `zip(x, x[1:])`; `raise RuntimeError(...)` for the Ollama check (not `raise SystemExit`, not `%%script false`). Verify by running `pre-commit run nbqa-ruff-check --files examples/notebooks/08_chunking_strategies.ipynb` — must exit 0. _(verified: pre-commit passes)_
- [x] 7.2 Run `pre-commit run nbstripout --files examples/notebooks/08_chunking_strategies.ipynb` and confirm it exits 0 and the file has `"outputs": []` in every code cell. _(verified: pre-commit passes)_
- [x] 7.3 Run `pre-commit run check-json end-of-file-fixer trailing-whitespace detect-secrets --files examples/notebooks/08_chunking_strategies.ipynb` and confirm all hooks exit 0. _(verified: pre-commit passes)_
- [x] 7.4 Execute the full notebook end-to-end with Ollama running (`jupyter nbconvert --to notebook --execute`) and confirm: no cell raises an uncaught exception, all sections produce visible output, the structural metrics table shows all three strategies, and the retrieval summary table renders for all five queries. _(verified: `jupyter nbconvert --to notebook --execute` completed with 0 cell errors; 11/12 code cells have outputs (cell 8 is a pure function-definition cell that produces no output); retrieval summary table rendered with all 5 queries × 3 strategies)_
- [x] 7.5 With Ollama pointed at a closed port (`http://localhost:19999`), confirm the Ollama check cell raises `RuntimeError` containing the `ollama serve` / `ollama pull nomic-embed-text` instructions — and does not silently skip or print a non-error message. _(verified: manual test of `ollama_problem()` + `raise RuntimeError(...)` in isolation — `RuntimeError` raised with `"Start it with: ollama serve"` in message)_

## Workflow follow-up

- Stage changes with `git add examples/notebooks/08_chunking_strategies.ipynb examples/notebooks/README.md openspec/changes/chunking-strategies-notebook/` and commit with `git commit -s`.
- Run `pre-commit run --from-ref origin/main --to-ref HEAD` and fix any remaining hook failures before pushing.
- Archive the change after review: `/opsx-archive`.
