# Tasks

Groups 1-6 are the API PR, groups 7-8 the UI PR stacked on it, and group 9 the integrated verification after both. Every task is sized at two hours or less. "Design Dn" refers to `design.md`; requirement names refer to `specs/backend/vectordb-qdrant/spec.md` and `specs/frontend/properties-panel/spec.md`.

Shared work that `add-weaviate-vectordb-adapter` specifies (tasks 1.3, 5.1, 5.2, and 7.1) is never implemented inside this change's PRs. If it is missing, it is delivered first as its own PR that implements the Weaviate change's deltas for it and cites them.

## 1. Validation, dependency gate, constants, and shared operator work

- [ ] 1.1 [backend] Run `openspec validate add-qdrant-vectordb-adapter --strict` and fix any finding before starting. Then the **gate:** in scratch copies of the repo root and of `slim/`, add the then-latest `qdrant-client` release as an exact pin and run `uv lock` in each (design D11). Record the packages added and changed per project, check every added or changed package on OSV, and run `pytest tests/unit/operators/vectordb/` against the scratch environment.
  - If resolution changes an existing package, a package has a published advisory, or an existing Milvus, OpenSearch, or telemetry test fails, stop and ask the maintainers. Do not add an `override-dependencies` entry on your own and do not continue to task 1.2.
  - Update the D11 table in `design.md` and the dependency line in `proposal.md` if the evidence differs.
  - Verify by attaching the recorded table to the API PR description.
- [ ] 1.2 [backend] Add the exact `qdrant-client` pin to `[project.dependencies]` of `pyproject.toml` and `slim/pyproject.toml`, in alphabetical order. Run `uv lock` in both directories and `uv pip install -e ".[dev]"`. Add `OperatorConstants.VectorDB.QDRANT = "qdrant"` and the Qdrant config keys, reusing existing constants for shared keys. Verify with `uv lock --check` in both directories and by committing both `pyproject.toml` and both `uv.lock` files together.
- [ ] 1.3 [backend] Check whether the operator already implements the requirement "Document identity" of `backend/vectordb-operator` (a null or missing `id` falls back to the document ID for chunk keys and stale-chunk lookup), added by `add-weaviate-vectordb-adapter` (its design D5, task 5.5). If it does, reuse it. If it does not, stop and deliver it first as a shared PR (see the note at the top). Verify with the operator tests named in that requirement's scenarios.

## 2. Configuration model and client

- [ ] 2.1 [backend] Write `adapters/outbound/qdrant/config.py` with `QdrantConfig(BaseModel, extra="ignore")` and every check that runs before connecting (design D3, D6, D7, D13):
  - the field table in D3, the collection-name rule, `url` and `host` exclusivity, port ranges, `distance_metric`, and the `index_parameters` keys and types;
  - the `api_key` reference check with `resolve_env_var`, discarding the result;
  - the HTTPS rule for an API key (D4);
  - the identity mapping rules for `pk` and `pk_file`, payload and vector name rules, and the content-mapping rule in sparse mode;
  - error messages built from each Pydantic error's location and message only, re-raised `from None`.

  Verify with `tests/unit/operators/vectordb/test_qdrant_config.py`, covering every scenario of "Qdrant connection configuration validation", "API key requires an HTTPS connection", "Fixed identity payload fields", and the name rules of "Qdrant payload mapping", including the collection-name table.
- [ ] 2.2 [backend] Write `client.py` (design D4, D5): build `QdrantClient` with `check_compatibility=False`, resolve the API key at connect time, re-check the HTTPS rule, run `get_collections()` as the readiness check, read the version with `info()`, enforce the 1.15.3 minimum in sparse mode, log one synchronous version-window warning, redact the API key and `api-key`/`Authorization` text in every message, recognize both `UnexpectedResponse` and `grpc.RpcError`, close the client before raising after a failed step, and make `close()` idempotent. Verify with `test_qdrant_client.py` (client mocked), covering "Qdrant API key handling", "Qdrant connection and server version check", and "Qdrant connection lifecycle".
- [ ] 2.3 [backend] Add two schema tests: the rendered `provider_config.providers.qdrant` schema marks `api_key` sensitive and has no `pattern` on `collection_name`, and importing `config.py` succeeds with `qdrant_client` blocked in `sys.modules`. Verify both pass.

## 3. Collection management

- [ ] 3.1 [backend] Write collection creation in `index_manager.py` (design D8): named dense vectors with size, distance, and HNSW settings; the IDF sparse vector in sparse mode; a sparse-only collection when there are no dense columns; keyword payload indexes on the identity fields, read back from `payload_schema`; and validation of the existing collection when creation returns 409. Verify with `test_qdrant_index_manager.py`, covering "Qdrant collection creation with named vectors".
- [ ] 3.2 [backend] Write existing-collection validation (design D9): named-vector presence, dimension, and distance, skipped for runs without dense columns; the sparse vector and its IDF modifier in sparse mode; identity index types; one combined error; and adding missing identity indexes only when every check passed. Reject single-unnamed-vector collections and dense runs on sparse-only collections. Verify with `test_qdrant_index_manager.py`, covering "Existing Qdrant collection validation" and "Unsupported Qdrant configurations rejected".

## 4. Writes, deletes, and queries

- [ ] 4.1 [backend] Write the write path in `batch_processor.py` (design D7, D10, D13):
  - point preparation with UUIDv5 IDs (D6, including the pinned example), identity fields, typed payload per the D7 table, and named vectors;
  - `models.Document(text=..., model="qdrant/bm25")` for the sparse vector in sparse mode;
  - pre-validation of dimension, finite values, and vector names;
  - batches bounded by `batch_size` and by `calculate_batch_size_bytes` on the plain dicts, sent with `wait=True`;
  - a one-point-at-a-time resend only for a batch rejected with HTTP 400 or 422 or gRPC `INVALID_ARGUMENT`, and whole-batch failure for every other error;
  - failed items in the `{"index": {"_id", "error": {"reason"}}}` shape.

  Verify with `test_qdrant_batch_processor.py`, covering "Pre-validated batched writes with per-chunk failure attribution", "Deterministic point identity and in-place re-ingest", "Qdrant payload mapping", and the write scenarios of "Qdrant sparse (BM25) retrieval mode".
- [ ] 4.2 [backend] Write stale-key lookup by `MatchAny` on `pk_file` with full scroll paging, deletes in requests of 500 IDs with the success count defined in design D14, `count(exact=True)` with 0 on error, and query by the mapped name field (design D14). Verify with `test_qdrant_batch_processor.py`, covering "Stale chunk cleanup on re-ingest", "Identity payload indexes", and "Qdrant maintenance operations".

## 5. Adapter, registration, enrichment, and lineage

- [ ] 5.1 [backend] Write `adapter.py` wiring the parts, with `generate_chunk_pk` using `generate_positional_pk`, `refresh_index` as a no-op, and the initialization order: configuration checks, then connection, then version check (design D1, D16). Check whether the operator already releases the adapter after flow validation (Weaviate design D17), passes `validating_flow` to the adapter config, and has the shared Vault placeholder constant (Weaviate design D18); if any is missing, deliver it first as a shared PR. Skip the connection under flow validation when `api_key` equals the placeholder. Verify with `test_qdrant_adapter.py` and the flow-validation scenarios of "Qdrant API key handling" and "Qdrant connection lifecycle".
- [ ] 5.2 [backend] Register `qdrant` with `VectorStoreFactory.register_lazy` next to Milvus and add the `qdrant` entry to `_get_vectordb_provider_schemas()`. The `provider` and operator descriptions must list providers by capability or from the registry rather than by name; if the Weaviate change has not done that yet, it is shared work (see the note at the top). Verify with `test_vectordb_operator.py`, covering "Qdrant provider registration".
- [ ] 5.3 [backend] Write `resource_metadata.py` (design D15), including the distance names in the `distance_metric` vocabulary and `sparse_eligible` for every existing collection, and route `qdrant` to it in `VectorDBMetadataFetcher`, importing it lazily. Verify with `test_qdrant_resource_metadata.py` and `test_metadata_fetcher.py`, covering "Qdrant flow-enrichment metadata" and the enrichment scenario of "API key requires an HTTPS connection".
- [ ] 5.4 [backend] Drop an `allowed_users` mapping with one warning, warn once when `allowed_users` is upstream but unmapped, and ignore `schema_template_path` with one warning, without reading the file. Do not import `core/operators/acl` or `docpipe.api` from the adapter; a test checks `sys.modules`. Verify with `test_qdrant_adapter.py`, covering "ACL enforcement not supported for Qdrant" and "Schema templates ignored for Qdrant".
- [ ] 5.5 [backend] Add a Qdrant rule to `src/docpipe/core/lineage/dataset_naming.py`, modeled on the Milvus rule: namespace `qdrant://<host>:<port>` from `url` (host and port only, never credentials) or from `host` and `port`, and the collection name as the dataset name. Verify with a unit test for a URL config and a host config, and that two collections on one server are two datasets.

## 6. Spec-pinning tests, test server, samples, and backend docs

- [ ] 6.1 [backend] Map every scenario of `specs/backend/vectordb-qdrant/spec.md` to at least one test, unit or real-server, and list the mapping in the API PR description. If a test contradicts the spec, fix the spec text, not the production code, and say so in the PR. Verify `pytest tests/unit -m "unit and not integration"` passes and the PR coverage check passes for every new module.
- [ ] 6.2 [backend] Add `docker/docker-compose.qdrant.yml` pinning `qdrant/qdrant:v1.20.0`, ports bound to `127.0.0.1`, with a test-only header: a plain service, and a second service with an API key and TLS whose certificate directory comes from an environment variable. Add the suite's session fixtures in `tests/integration/qdrant/conftest.py`: generate a self-signed certificate into a temporary directory, start and stop both services (with `docker compose` or `docker-compose`), make the client trust the certificate through `SSL_CERT_FILE` (confirm the client honors it, otherwise record the alternative in design D12), and allow `DOCPIPE_TEST_QDRANT_URL` to target another server. Verify that both services start, and that a client with the key connects over HTTPS and gets 401 without it.
- [ ] 6.3 [backend] Add `tests/integration/qdrant/test_qdrant_with_container.py`, with a unique collection per test deleted in teardown, covering partial batch writes and the resend, the payload-index read-back, strict mode, the 409 race, server-side BM25, paging over 10,000 points, and authentication. Verify with `pytest -m integration tests/integration/qdrant`; a skipped suite counts as blocked, never as passed.
- [ ] 6.4 [backend] Only if the maintainers decide to run vector database suites in CI (design D12, Open Questions): add a `qdrant-integration-test` job to `.github/workflows/ci.yml` that runs `pytest -m integration -rs tests/integration/qdrant` on a runner with Docker. Verify the job passes on the API PR.
- [ ] 6.5 [backend] Add `sample_flows/vectordb/qdrant_integration.json` (ingest → extract → chunk → embeddings → vectordb with `provider: "qdrant"`, `host: "localhost"`, `port: 6333`, `distance_metric: "cosine"`, and feature mappings including `pk` for the primary feature and `content → text`, modeled on `milvus_integration.json`). Verify it parses as JSON and that `docling-pipelines validate-flow sample_flows/vectordb/qdrant_integration.json` passes with the compose server running.
- [ ] 6.6 [backend] Add `docs/operators/vectordb/qdrant.md` next to `milvus.md` and `opensearch.md`: configuration fields, the HTTPS rule, the identity fields `pk` and `pk_file`, sparse mode and its minimum server version, the sparse-only in-memory limitation, ACL and schema-template behavior, and the `$VAR` recommendation for keys. Add Qdrant to `docs/operators/vectordb/vectordb_readme.md` and to the `docs/reference/OPERATORS.md` VectorDB section without duplicating the README. Update the files that list vector databases: `README.md`, `ARCHITECTURE.md`, `USER_GUIDE_PIPELINE_SETUP.md`, `docs/README.md`, and `sample_flows/README.md`; check `AGENTS.md`, `docs/guides/SLIM_VARIANT.md`, and `frontend/src` (`grep -rniE 'milvus' frontend/src --include=*.ts --include=*.tsx --include=*.json -l`) and edit only text that lists providers. Do not touch `CHANGELOG.md`. Verify that every relative link resolves.

## 7. Frontend: provider configuration and connection controls

Paths are under `frontend/src/components/PropertiesPanel/CustomPanels/VectorDB/`. Enrichment can be mocked against the shape fixed by "Qdrant flow-enrichment metadata".

- [ ] 7.1 [frontend] Check whether `PROVIDER_CONFIG_MAP` entries already have the data-driven `supportsSparse`, `sparseLabel`, and `advancedOnlyKeys` fields, and whether the enrichment result type already has `error` and `sparse_eligible` (Weaviate design D16). If they do, reuse them. If they do not, deliver them first as a shared PR (see the note at the top). Verify the existing VectorDB panel tests pass unchanged.
- [ ] 7.2 [frontend] Add the `qdrant` entry to `PROVIDER_CONFIG_MAP` (design D17): `collection_name`, "Collection", `distance_metric` with Cosine, Dot, Euclid, and Manhattan as labels for `cosine`, `dot`, `euclid`, and `manhattan`, no engine, sparse capability with the label "BM25", `advancedOnlyKeys` with `index_parameters`, resource-specific keys, and the default config. Verify with a unit test that selecting `qdrant` no longer falls back to the OpenSearch entry.
- [ ] 7.3 [frontend] Add `QdrantConnectionFields.tsx` (no state) and `vectordb-qdrant.ts` (pure rules: collection name, HTTPS with an API key, port ranges). Implement the URL versus host-and-port choice, removing only the inactive mode's keys in one write, and the API key through the existing `VaultInput`. Verify with unit tests for the rules and the scenarios "URL versus host and port", "API key accepts literals, environment references, and Vault references", and "Advanced JSON preserved".
- [ ] 7.4 [frontend] Block opening the tearsheet and enrichment while a connection setting is invalid (an API key over HTTP, an empty URL, an invalid port, or an empty Vault reference), show accessible inline errors, and move focus to the first invalid field. The collection name is validated inside the tearsheet and does not block opening it. Verify with tests for "Empty Vault reference blocked", "API key over HTTP blocked", "Invalid connection settings blocked", "Blocked open moves focus", and "Keyboard operation and focus".

## 8. Frontend: tearsheet, strings, and tests

- [ ] 8.1 [frontend] In `VectorDBFeatureMappingTearsheet.tsx`, add the Qdrant collection-name rule and placeholder, the distance metric without an engine control, the BM25 option (shown for a new collection, and for an existing one only when `sparse_eligible` is true, preserved on reopen), and the enrichment `error` notification. Verify with tests for the tearsheet scenarios of "VectorDB Qdrant provider configuration".
- [ ] 8.2 [frontend] Add a test that OpenSearch, Milvus, and (if present) Weaviate render exactly as before. Verify it passes.
- [ ] 8.3 [frontend] Put every new string in `VectorDB.messages.ts`, run `npm run extract:messages`, and commit the regenerated `frontend/src/i18n/messages_en.json` without hand edits. Run `npm run lint`, `npx tsc --noEmit`, `npm run test`, and `npm run build` in `frontend/`. Verify all pass; report pre-existing failures separately from new ones.

## 9. Integrated verification

- [ ] 9.1 [both] With the compose server running, run the sample flow end to end three times: dense only, with `add_sparse_vector: true`, and again after removing chunks from one document. Verify the point counts, that the shrunk document has no stale points, and that a sparse query returns a chunk by one of its words.
- [ ] 9.2 [both] Start the backend and frontend, configure a `qdrant` node in the panel against the compose server (with and without the API key service), and run enrichment. Verify the collection list, the schema, that selecting an existing collection saves a valid `distance_metric`, the BM25 option, and that an API key over HTTP is blocked in the panel and rejected by the backend.
- [ ] 9.3 [both] Run `openspec validate add-qdrant-vectordb-adapter --strict`. Inspect the full diff for unrelated changes and confirm `CHANGELOG.md` is untouched. Commit with `git commit -s`, run `pre-commit run --from-ref origin/main --to-ref HEAD`, fix findings in changed paths only, and rerun. Verify a clean run.

## Workflow follow-up

- Each PR description follows the repository PR template and includes the pre-commit output.
- Merge order: any shared PR first, then the API PR, then the UI PR, in the same release.
- After both are merged and verified, run `openspec archive add-qdrant-vectordb-adapter`.
