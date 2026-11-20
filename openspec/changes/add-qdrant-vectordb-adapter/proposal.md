# Proposal

## Why

The `vectordb` operator can write to OpenSearch and Milvus, and the `add-weaviate-vectordb-adapter` change plans Weaviate. Qdrant is another widely used open-source (Apache-2.0) vector database, with named dense vectors, native sparse vectors, payload filtering, and a managed cloud offering. Teams that run Qdrant cannot use docpipe as their ingestion pipeline without writing a custom operator.

The operator was built for this kind of extension. It has a hexagonal design (`VectorStorePort`, `VectorStoreFactory` lazy registration, and a Pydantic config per adapter) and a provider-agnostic contract, the `backend/vectordb-operator` capability, to which the Weaviate change adds requirements. Qdrant can therefore be added as a first-class provider without changing the operator's contract.

As with Weaviate, a backend adapter alone is not a usable feature. The VectorDB properties panel builds its provider list from operator metadata, but its provider-specific branches are keyed on `opensearch` or `milvus`, and an unknown provider falls back to the OpenSearch configuration. Once the backend lists `qdrant`, the panel would offer it and then render OpenSearch fields. The UI work is therefore part of this change.

**Layer:** full-stack. The backend gets a new storage adapter, metadata enrichment, a dependency, docs, a sample flow, and a test server. The frontend gets narrowly scoped VectorDB panel support for the new provider. There are no routing, BFF proxy, or Redux slice changes.

**Delivery:** one change and one set of specs, implemented as stacked pull requests (see Rollout).

## What Changes

### Backend

- **New `qdrant` VectorDB adapter** at `src/docpipe/core/operators/vectordb/adapters/outbound/qdrant/`. It follows the Milvus/OpenSearch/Weaviate structure (`adapter.py`, `client.py`, `config.py`, `index_manager.py`, `batch_processor.py`, `resource_metadata.py`) and implements every `VectorStorePort` method:
  - creates a collection with one **named dense vector** per detected vector column, so multi-model embeddings are supported, and keyword payload indexes for the fields the provider filters on;
  - validates an existing collection: named-vector presence, dimension, and distance, the sparse vector configuration, and the identity payload indexes, and adds missing payload indexes only when every check passed. Because an upsert replaces a whole point, it also refuses a collection with a dense or sparse vector that the run would not populate, instead of silently removing that vector from every re-ingested point;
  - writes points in batches with deterministic UUIDv5 point IDs derived from positional chunk primary keys, so re-ingest replaces chunks in place;
  - cleans up stale chunks, deletes by key, queries by document name, and counts points.
- **Fixed identity payload fields.** Every point stores its chunk primary key in the payload field `pk` and the file part of that key in `pk_file`. A feature mapping that sends the primary feature anywhere other than `pk`, or sends another feature to `pk` or `pk_file`, is rejected at initialization.
- **Stale-chunk lookup without prefix filters.** Qdrant has a prefix match only from server 1.19, and older servers silently build a keyword index without prefix support. The provider therefore stores the file part of the key in `pk_file` and finds a file's chunks with an exact match on it. This works on every supported server version, and with strict mode's unindexed-filter settings, which reject filters on fields without a payload index. The chain from chunk key to point ID to `pk_file` is stated as one decision in design D6.
- **Pre-validated, attributable writes.** A Qdrant upsert batch is not atomic: a batch with one invalid point can leave an unpredictable subset written. The provider therefore:
  - checks each point's vector names, dimensions, and finite values before sending;
  - retries transient failures (connection errors, timeouts, 429, 502, 503, 504) a bounded number of times, which is safe because point IDs are deterministic;
  - resends a batch point by point when the server still rejects it as invalid, so only the invalid points are reported as failed;
  - removes every point of a document that has a failed chunk, so no partial document stays searchable;
  - reports failed points in the failed-item shape `VectorDBOperator` already parses.
- **Sparse (BM25) mode.** `add_sparse_vector: true` creates a named sparse vector with the IDF modifier and has the server compute its BM25 term weights from each chunk's text (`qdrant/bm25` inference). It needs Qdrant server 1.15.3 or later; on an older server initialization fails with a message naming the version. Sparse-only runs (no dense vectors) create a collection with the sparse vector only. The flag is read from the operator's top level; for `qdrant`, a flag set only inside `provider_config` is rejected at initialization instead of turning sparse mode on in the adapter alone.
- **Lazy registration** of `qdrant` in `vectordb_operator.py` (`VectorStoreFactory.register_lazy`). The operator's `provider_config` JSON-schema map, `provider` valid values, and descriptions now include Qdrant.
- **Flow enrichment.** `VectorDBMetadataFetcher` routes `qdrant` to a new `QdrantResourceMetadata`. It returns the same five keys as the other providers, plus the additive `sparse_eligible` and `error` keys inside `is_docpipe_supported_resource` that the Weaviate change defines.
- **Credential handling.** An API key requires an HTTPS connection; the provider checks the URL scheme itself, because the client keeps `http` for an `http://` URL even when `https` is set. Whether to add an explicit opt-in for keys over plain HTTP on internal networks is an open question (design, Open Questions). The API key field is flagged sensitive in operator metadata, accepts literal values or `$VAR`/`${VAR}` references, and never appears in raised messages or logs. A key that is empty or resolves to an empty value means no key, with a warning when a reference resolved to empty.
- **Dependency.** Add `qdrant-client` as a pinned core dependency in both `pyproject.toml` and `slim/pyproject.toml`, and regenerate both lockfiles. Trial resolution against `qdrant-client==1.20.0` adds only `qdrant-client` and `portalocker` 4.4.2 to each lockfile and changes no existing package (design D11). The version is re-checked at implementation time, behind a maintainer-decision gate.
- **Constants.** Add `OperatorConstants.VectorDB.QDRANT` and the Qdrant-specific config keys.
- **Testing.** Unit tests for every new module (client mocked) run in CI. A real-server suite runs against pinned `qdrant/qdrant` containers (`docker/docker-compose.qdrant.yml`) that it starts itself. It is manual-only, like the other vector database container tests, unless the maintainers decide to run vector database suites in CI (design D12).
- **Docs and samples.** Add `docs/operators/vectordb/qdrant.md` next to `milvus.md` and `opensearch.md`, update `docs/operators/vectordb/vectordb_readme.md`, `docs/reference/OPERATORS.md`, and the files that list vector databases, and add `sample_flows/vectordb/qdrant_integration.json`.
- **Lineage.** Add a Qdrant rule to `core/lineage/dataset_naming.py`, so each collection is its own OpenLineage dataset.

### Frontend

- **Provider configuration map.** Add a Qdrant entry: no engine selector, the collection naming rule and placeholder, the distance metric labels and options, and the sparse (BM25) capability.
- **Connection and authentication controls** in the VectorDB panel: a URL or a host and port with HTTPS, the gRPC port and preference, the request timeout, and an API key input that reuses `VaultInput` (masked literal or `$VAR`/`${VAR}` reference, with the existing Vault toggle).
- **Validation that blocks.** An API key over a non-HTTPS connection, and a missing or invalid connection setting, show accessible inline errors and block opening the feature-mapping tearsheet and enrichment while invalid.
- **Feature-mapping tearsheet.** The provider-specific collection-name rule, distance metric selection without an engine control, a capability- and eligibility-driven BM25 checkbox, and display of the enrichment `error`. `index_parameters` stays editable in Advanced JSON.
- **Strings.** New strings are colocated message definitions, extracted into the catalogue with `npm run extract:messages`.
- **Compatibility.** OpenSearch, Milvus, and Weaviate behavior is unchanged.

No **BREAKING** changes. Existing providers' behavior, configuration, and defaults are unchanged.

## Capabilities

### New Capabilities

- `backend/vectordb-qdrant`: the Qdrant provider contract: registration, configuration and credential validation, the HTTPS rule, the server version check, collection creation and validation, the fixed identity payload fields and their indexes, sparse (BM25) mode, the deterministic-ID upsert and stale-chunk lifecycle, pre-validated writes with per-chunk failure reporting, secret hygiene, and flow-enrichment metadata.

The provider-agnostic table, metadata, document identity, sparse-mode, and validation-release contract lives in `backend/vectordb-operator`, including the requirements that `add-weaviate-vectordb-adapter` adds there. This change does not restate or modify them.

### Modified Capabilities

- `frontend/properties-panel`: a new requirement, "VectorDB Qdrant provider configuration", covers the Qdrant panel and tearsheet. It is added as its own requirement rather than as another modification of "VectorDB feature mapping and backend configuration", so this change and the Weaviate change, which modifies that requirement, can be archived in either order without overwriting each other.

## Frontend Carbon components

Existing Carbon React components and tokens only: `Dropdown`, `TextInput` (including numeric entry, as the current panel does), `PasswordInput`, `Toggle`, `Checkbox`, `Accordion`/`AccordionItem`, `InlineNotification`, and the existing `Tearsheet` and `DataTableSkeleton`. New styling reuses the existing `VectorDB.module.scss` and Carbon `var(--cds-*)` tokens.

## Relationship to the Weaviate change

`add-weaviate-vectordb-adapter` plans several provider-agnostic changes that this provider also relies on: document identity when `id` is missing (its design D5), releasing the adapter after flow validation (D17), the shared Vault placeholder constant (D18), capability-based provider wording in the operator, and the data-driven panel fields `supportsSparse`, `sparseLabel`, and `advancedOnlyKeys` (D16). This change relies on that work but does not specify it again: it stays in the Weaviate change's spec deltas, so each requirement has one owner.

- If the Weaviate API and UI PRs are merged first, this change reuses their work.
- If this change is implemented first, the shared work is delivered first as its own PR, implementing the Weaviate change's deltas for it and citing them, and this change builds on it. Neither provider's PR implements behavior outside its declared specs.

Tasks 1.3, 5.1, 5.2, and 7.1 say how to check what already exists.

## Rollout

The change is delivered as a stack:

1. **API PR**: groups 1-6 in `tasks.md` (all backend).
2. **UI PR**, stacked on the API PR and merged after it: groups 7-8. It can be developed against the `provider_config` schema and enrichment shape fixed by the specs, with enrichment mocked.
3. **Integrated verification and docs**: group 9, after both are in.

Both PRs MUST ship in the same release. If only the API PR is released, the panel lists `qdrant` and renders the OpenSearch fallback. If the merge order ever slipped, a UI PR merged first would be harmless, because the provider list comes from operator metadata and does not include `qdrant` until the API PR is in.

## Non-goals

- Frontend changes beyond the VectorDB panel and tearsheet: no routing, BFF proxy, or Redux slice changes, and no generic provider-form rewrite.
- Qdrant's local mode (`QdrantClient(":memory:")` or `path=`). It is an in-process client implementation, not a server: payload indexes do nothing, strict mode is ignored, batches are atomic, and BM25 inference needs `fastembed`. It is neither offered to users nor used as a substitute for the real-server tests, and the docs state that a running Qdrant server is required. A dense-only local mode, comparable to Milvus Lite, is a possible follow-up change, with sparse mode staying server-only (design, Open Questions).
- Reimplementing any part of the Qdrant server. The adapter is a client of an existing Qdrant deployment through the official `qdrant-client`.
- Search or query features beyond what `VectorStorePort` requires: no hybrid, BM25, or nearest-neighbor query API, and no reranking.
- Client-side embedding (`fastembed`) or Qdrant Cloud inference. docpipe supplies dense vectors from the `embeddings` operator, and BM25 term weights come from the server's built-in `qdrant/bm25` inference.
- Custom sparse embeddings such as SPLADE. No upstream operator produces sparse vectors; the `sparse_embeddings` mapping names the BM25 sparse vector, and any upstream values for it are not read.
- BM25 tuning (`k`, `b`, `avg_len`, language). The server's defaults are used; the server accepts unknown options silently, so the provider passes none.
- Multi-tenancy, sharding and replication settings, quantization, aliases, snapshots, JWT or RBAC management, and read-only keys.
- ACL enforcement. A mapped `allowed_users` feature is stored as a payload array with a keyword index, so the application that queries Qdrant can filter on it, but docpipe does not enforce it for Qdrant; a warning and the docs say so.
- OpenSearch schema templates. The operator-level `schema_template_path` option is ignored with a warning.
- Changing the OpenSearch, Milvus, or Weaviate adapters, `VectorStoreFactory`, or the factory's 500 wrapping of adapter errors. The existing adapters return failed items in shapes the operator does not parse; fixing that is a separate change.
- OpenLineage naming beyond a `qdrant://<host>:<port>` namespace and the collection name (task 5.5).
- Adapter-specific Vault handling. `vault://` references are resolved upstream by the flow executor and by flow enrichment, exactly as for the other adapters.

## Impact

- **Operators:** `vectordb` (`VectorDBOperator`) gains a provider. No new operator; `DOCPIPE_OPERATORS` is unchanged. The shared operator changes listed under "Relationship to the Weaviate change" are made once, by whichever change is implemented first.
- **Storage adapters:** new `qdrant` outbound adapter package; `VectorStoreFactory` registration in `vectordb_operator.py`; `VectorDBMetadataFetcher` routing.
- **REST routes:** none added or changed. `GET /api/v1/operators/metadata` now lists `qdrant` in `provider` valid values and `provider_config.providers`. `POST /api/v1/validation/enrich_flow_features` returns Qdrant metadata for `vectordb` nodes with `provider: "qdrant"`.
- **Frontend:** `frontend/src/components/PropertiesPanel/CustomPanels/VectorDB/` (`constants.ts`, `VectorDB.tsx`, `VectorDBFeatureMappingTearsheet.tsx`, `VectorDB.module.scss`, a colocated messages file) and `frontend/src/i18n/messages_en.json`; extended tests under `frontend/tests/unit/components/PropertiesPanel/CustomPanels/VectorDB/`.
- **Dependencies:** `qdrant-client` (pinned) in `[project.dependencies]` of `pyproject.toml` and `slim/pyproject.toml`; both `uv.lock` files regenerated. The only new transitive package is `portalocker`.
- **Infrastructure and tests:** new `docker/docker-compose.qdrant.yml` (test-only); new `tests/unit/operators/vectordb/test_qdrant_*.py` and `tests/integration/qdrant/`; possibly a CI job (design D12).
- **Docs:** VectorDB operator README, `docs/reference/OPERATORS.md`, provider enumerations, and a sample flow. `CHANGELOG.md` is not touched.
