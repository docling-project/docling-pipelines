# Design

## Context

See [proposal.md](proposal.md) for motivation, scope, and rollout. The requirements are in [specs/backend/vectordb-operator/spec.md](specs/backend/vectordb-operator/spec.md) (provider-agnostic contract, describing existing behavior), [specs/backend/vectordb-weaviate/spec.md](specs/backend/vectordb-weaviate/spec.md) (Weaviate provider), and [specs/frontend/properties-panel/spec.md](specs/frontend/properties-panel/spec.md) (modified VectorDB panel requirement).

**Current shape of the VectorDB operator.** It is hexagonal:

- **Application:** `VectorDBOperator` (`core/operators/vectordb/vectordb_operator.py`) drives the transform phases: build doc-ID maps, detect vector dimensions, create or validate the resource, prepare chunk documents, clean up stale primary keys, write, and refresh. It depends only on the port.
- **Port:** `VectorStorePort` (`ports/outbound/vector_store.py`) declares the abstract methods every adapter must implement, including `generate_chunk_pk` and `get_chunk_ids_for_documents`. `close()` is non-abstract and optional.
- **Domain:** `domain/models.py` holds dataclasses only and is unchanged by this design.
- **Adapters:** `adapters/outbound/{opensearch,milvus}/` each follow `adapter.py` (port implementation), `client.py` (connection and auth), `config.py` (Pydantic `provider_config` model plus `ADAPTER_NAME`), `index_manager.py` (resource schema), `batch_processor.py` (writes, deletes, queries), and `resource_metadata.py` (read-only flow enrichment).
- **Registration:** `VectorStoreFactory` registers OpenSearch eagerly and Milvus lazily (`register_lazy`) from `vectordb_operator.py`. `_get_vectordb_provider_schemas()` publishes each adapter's JSON schema in operator metadata. `VectorDBMetadataFetcher` routes enrichment by `if adapter_name == ...`.

**Constraints observed in the current code:**

- **Initialization order and error wrapping.** `flow_validator.py` builds the operator (`operator_class(config=config)`) and only then calls `operator.validate()`. `VectorDBOperator.__init__` builds the adapter through `VectorStoreFactory.create`, which wraps any adapter exception as a 500 `DocpipeException` ("Failed to create vector store adapter ..."), and the operator wraps it again ("Failed to initialize vector database adapter ..."). In flow validation the generic `except Exception` reports it as "Validation failed for operator 'vectordb': ..." (`OPERATOR_VALIDATION_FAILED`). Every adapter configuration error is therefore an **initialization failure whose message text survives the wrapping**; it is never a standalone schema-driven validation message. The existing test for the missing-collection guard documents this ("adapter guard fires before validate()").
- `VectorDBOperator._index_and_record_results` parses failed items as `{"index": {"_id": ..., "error": {"reason": ...}}}` (OpenSearch bulk shape). Milvus returns `{"document": ..., "error": ...}`, so its per-chunk failures cannot be attributed to a document today. Weaviate must emit the parsed shape.
- `_cleanup_stale_pks` calls `get_chunk_ids_for_documents(file_ids)` and expects results keyed by file ID, with chunk primary keys produced by `generate_chunk_pk`.
- Adapters connect in `__init__` (OpenSearch and Milvus both call `get_client()`), and `VectorDBOperator.transform` calls `adapter.close()` in `finally`.
- `VectorDBOperator.validate` runs `adapter.get_config_schema().model_validate(provider_config)` and reports a missing field as `"<field> is not provided"`. It is only reached after construction succeeded.
- `compute_default_feature_mappings` maps the primary feature to `pk` (`DEFAULT_PRIMARY_KEY_FIELD`), `id` to `document_id`, `name` to `document_name`, and the first vector to `vector_embeddings`. With `add_sparse_vector=True` it also maps the sparse feature to `sparse_embeddings` and `content` to `text`. Milvus fixes its primary key field to `pk`.
- **Operator support for sparse runs.** `VectorDBOperator` copies the top-level `add_sparse_vector` into the adapter config, `compute_default_feature_mappings` adds `sparse_embeddings` and `content` defaults when it is set, and `VectorDBOperator._resolve_vector_dimensions` allows sparse-only runs: with no dense columns it returns an empty dimension mapping. The operator treats `sparse_embeddings` as a feature that a provider need not store. This is context only; the Weaviate behavior is defined in D14 on Weaviate's own terms.
- **Operator metadata cannot carry a field `pattern`.** `OperatorUtils._to_docpipe` forwards description, default, min/max, required, enum, and sensitivity, but not `pattern`. The collection-name rule is enforced by a validator on the backend and copied into the frontend provider map.
- **Sensitive-field masking.** `_to_docpipe` marks a field sensitive if its key is in `SENSITIVE_FIELD_NAMES` (`password`, `api_key`, `token`, ...) or its schema carries `sensitive: true` (from `json_schema_extra`). `bearer_token` and `username` are not in the set.
- **Environment references.** `resolve_env_var` resolves `$VAR` and `${VAR}` (raising `ValueError` naming the variable when unset), supports `${VAR:default}`, and also substitutes any string that is all upper case and contains `_` when an environment variable of that name exists.
- **The panel's provider list comes from operator metadata** (`Object.keys(providersMap)`, with an OpenSearch/Milvus fallback only when metadata is absent). All provider-specific rendering in `VectorDB.tsx` and the tearsheet is keyed on `opensearch`/`milvus`, and `getProviderConfig` falls back to the OpenSearch entry for unknown providers.
- `slim/pyproject.toml` also pins `pymilvus` and `opensearch-py`, and has its own `uv.lock`, so the slim variant needs the new dependency too.
- **CI.** `.github/workflows/ci.yml` runs `pytest tests/unit -m "unit and not integration"` and the CLI tests. No vector database container or Milvus Lite integration test runs in CI.

**Upstream facts that shape the approach** (official docs and PyPI):

- `weaviate-client` latest is **4.24.1** (2026-10-26; 4.23.1 on 2026-09-07 and 4.24.0 on 2026-10-21 precede it), BSD-3-Clause, Python ≥3.10. It requires `httpx<0.29`, `pydantic>=2.12`, `authlib>=1.7.1`, `certifi>=2026.10.19`, `protobuf<7`, `validators`, and **`grpcio<1.80.0`**. OSV lists no advisories for the resolved versions (D11).
- Server latest is 1.40.2 (image `cr.weaviate.io/semitechnologies/weaviate:1.40.2`; published 2026-10-22). Every server behavior cited below was reproduced on 1.40.2 with client 4.24.1. The v4 client requires the gRPC port (default 50051) in addition to HTTP (8080).
- Collections must match `^[A-Z][_0-9A-Za-z]*$`. Properties must match `[_A-Za-z][_0-9A-Za-z]*`, with `id`, `_id`, and `_additional` reserved and `vector`/`_vector` discouraged.
- Default text tokenization is `word`, which splits on non-alphanumerics, so `abc_chunk_3` becomes `[abc, chunk, 3]`. `field` tokenization keeps the whole value as one token.
- Self-provided named vectors use `Configure.Vectors.self_provided(name=..., vector_index_config=Configure.VectorIndex.hnsw|flat|dynamic(distance_metric=...))` (client ≥4.16). No dimension is declared; it is fixed by the first insert.
- `data.delete_many` deletes at most `QUERY_MAXIMUM_RESULTS` (default 10,000) objects per call.
- **Offset paging is capped.** `fetch_objects(limit, offset)` fails once `offset + limit` exceeds `QUERY_MAXIMUM_RESULTS` ("the total limit calculated from the provided offset and limit exceeds the configured value"; reproduced on server 1.40.2 at `offset=9500, limit=1000`). Cursor iteration (`after=`) does not accept filters. Keyset paging works: `fetch_objects(filters=<prefix filter> & Filter.by_property("pk").greater_than(last_pk), sort=Sort.by_property("pk"), limit=1000)` at offset 0 returned all 2,500 stored keys in 3 pages (reproduced on 1.40.2 with client 4.24.1).
- **Omitting `vector_config` is not "no vectors".** The v4 client injects a named vector `default` with vectorizer `none` and an HNSW index (read-back confirmed). `vector_config=[]` fails an assertion in the client. A vector declared with `Configure.Vectors.self_provided(name=..., vector_index_config=Configure.VectorIndex.none())` serializes to `{"vectorIndexConfig": {"skip": true}}`; the server accepts it, builds no index, accepts objects with no vector, and serves BM25 and filters (confirmed).
- **Tokenization decides filter, paging, and search semantics** (reproduced on 1.40.2).
  - Keyset paging with `greater_than("pk", last)` on a `word`-tokenized property returned **0 objects** although 700 keys were greater, so paging silently stops after the first page; under `field` tokenization it returned the next 500. This is the strongest reason `pk` must be `field`-tokenized.
  - Equality and prefix filters on a `word`-tokenized property match on shared tokens: `name.equal("report_2025.pdf")` returned `report_2024.pdf` and `report-2025.pdf` as well (3 objects against 2 under `field`). Prefix over-matching depends on key shape: the real key format `{sha3_512_hex}_chunk_{i}` has a single hex token, so only keys that share that token and `chunk` match, but a hand-made key such as `<hash>-chunk-7` still matches under `word`.
  - BM25 over a `field`-tokenized property finds only whole-value matches (`invoice` returned 0 hits, against 2 or more under `word`), so the content property must be `word`-tokenized.
  - Tokenization and the `index_filterable`/`index_searchable` flags are readable from `collection.config.get().properties`.
- **Property names are normalized by the server.** Weaviate lowercases the first character of a property name (`Department` is stored as `department`, `URL` as `uRL`; `fileName` is unchanged). Names that differ only in first-letter case conflict (`add_property("filename")` after `fileName` fails with HTTP 422). Filters and writes using a non-canonical name fail ("no such prop"), and returned properties are keyed by the canonical name. Vector names are not normalized.
- **An all-failed batch raises.** `insert_many` returns `errors={index: ErrorObject}` when only some objects fail, but raises `WeaviateInsertManyAllFailedError` when every object in the batch fails (invalid integer, dimension mismatch, undeclared or wrong-case property). That exception has only a `message` (no per-object errors).
- **`dynamic` index needs async indexing.** Creating a `dynamic` index on a server without `ASYNC_INDEXING=true` fails with HTTP 422 ("the dynamic index can only be created when async indexing is enabled"). On Weaviate Cloud async indexing is enabled in the console. Dynamic is experimental. With async indexing, vector queries can lag behind writes; `client.cluster.nodes(output="verbose")` exposes per-shard `vector_indexing_status` and `vector_queue_length`.
- `data.insert_many` returns `BatchObjectReturn.errors: dict[int, ErrorObject(message, object_)]`.
- Embedded Weaviate is experimental, Linux/macOS only, and downloads a binary at runtime. Auto-schema is on by default (`AUTOSCHEMA_ENABLED`). No quantization is applied by default unless the server sets `DEFAULT_QUANTIZATION`.
- Hybrid search fuses vector search with BM25 keyword search over the inverted index (default fusion `relativeScoreFusion`, alpha 0.75). The docs describe no native sparse-vector type for user-supplied sparse embeddings. BM25 runs over text properties with `index_searchable=True`, and BM25 parameters are set per collection through the inverted-index config. Weaviate's own BM25 defaults are k1 = 1.2 and b = 0.75 (documented).

## Goals / Non-Goals

**Goals:**

- A `weaviate` adapter that is structurally a sibling of the Milvus adapter (same file split, same lazy registration, same enrichment contract).
- Idempotent re-ingest with no duplicate chunks, using a deterministic object identity rather than delete-then-insert.
- Per-chunk failure attribution to documents, using the failed-item shape the operator already parses.
- An explicit, typed schema: the adapter never relies on server auto-schema.
- Credentials never sent in plaintext and never disclosed in errors or logs.
- A usable UI: a user can configure, save, reopen, and enrich a Weaviate VectorDB node without hand-writing JSON for the common path.
- Test coverage at three levels: unit (client mocked), operator (adapter mocked), and real-server (Docker-gated, manual).

**Non-Goals (design level, in addition to the proposal's):**

- No change to `VectorStorePort`, `domain/models.py`, `VectorStoreFactory`, or the failed-item parsing in `VectorDBOperator`. The operator's document identity (D5), its validation-time release (D17), and passing `validating_flow` to the adapter (D18) are the only operator changes.
- No general lazy connection. Weaviate connects in `__init__` like its siblings, and flow validation still needs a reachable server; making all adapters lazy is a separate change. The one exception is a credential that flow validation has replaced with its Vault placeholder, where the connection is skipped because it could not authenticate (D18). Releasing the connection after validation (D17) is in scope.
- No reuse of Milvus code via inheritance. Shared helpers come only from `utils/operators/vectordb_utils.py`.
- No Redux, routing, or BFF changes; no new REST routes.

## Decisions

### D1. Package layout and DDD boundaries

New package `core/operators/vectordb/adapters/outbound/weaviate/`. Its `__init__.py` deliberately exports nothing, as Milvus does.

| File | Layer | Responsibility |
|---|---|---|
| `config.py` | adapter (config contract) | `ADAPTER_NAME = "weaviate"`, `WeaviateConfig(BaseModel, extra="ignore")`, and `format_config_errors` (D3, D15). Field validators carry the spec's messages. A `model_validator(mode="after")` enforces cross-field rules (cloud → `cluster_url`; `auth_type` → its credentials; credentials require TLS; credential references resolvable). |
| `client.py` | adapter (infrastructure) | `WeaviateClient`: build credentials, connect (`connect_to_custom` / `connect_to_weaviate_cloud`), `is_ready()` check, `get_client()`, `close()`, and secret redaction of every error it raises (D4). Errors become `DocpipeException(status_code=503, OPERATOR_EXECUTION_FAILED)` naming the target, never the secrets. |
| `index_manager.py` | adapter | Static name and type rules (`validate_property_names`, `validate_primary_key_mapping`, `map_feature_type`, `tokenization_for`), `collection_exists`, `create_collection`, `validate_existing_collection`, `drop_collection` (used by tests). These are internal; the adapter exposes them through port methods (see below). |
| `batch_processor.py` | adapter | `prepare_document`, `create_batches`, `process_batches`, `delete_documents_by_ids`, `get_document_count`, `get_chunk_ids_for_documents`, `query_by_doc_names`. |
| `adapter.py` | adapter (port implementation) | `@register_vector_store class WeaviateAdapter(VectorStorePort)` wiring the three components. Fail-fast checks run before connecting. Public methods use the `VectorStorePort` names and delegate as the Milvus adapter does (table below). |
| `resource_metadata.py` | adapter (read-only) | `WeaviateResourceMetadata.fetch(...)`, with the same injected-callable signature as `MilvusResourceMetadata`. |

**Port-method delegation** (same shape as `MilvusAdapter`):

| `VectorStorePort` method on `WeaviateAdapter` | Delegates to |
|---|---|
| `get_config_schema()` (static) | returns the `WeaviateConfig` class (D3); no delegate |
| `create_index(*, dimension_mapping)` | `index_manager.create_collection(dimension_mapping=...)` |
| `validate_existing_schema(*, dimension_mapping)` | `index_manager.validate_existing_collection(dimension_mapping=...)` |
| `index_exists()` | `index_manager.collection_exists()` |
| `index_documents(documents)` | `batch_processor.create_batches(...)` then `batch_processor.process_batches(...)` |
| `delete_documents_by_ids`, `get_document_count`, `get_chunk_ids_for_documents`, `query_by_doc_names` | the `batch_processor` method of the same name |
| `detect_vector_dimension(*, table, column_name)` | shared `detect_vector_dimension` in `docpipe/utils/operators/vectordb_utils.py`; `column_name=None` falls back to `self.embeddings_column`, read from the adapter config key `OperatorConstants.Columns.EMBEDDINGS_COLUMN` and defaulting to `EMBEDDINGS_COLUMN_DEFAULT` |
| `detect_all_vector_dimensions(table, *, vector_columns)` | shared `detect_all_vector_dimensions` in `docpipe/utils/operators/vectordb_utils.py` |
| `generate_chunk_pk`, `refresh_index`, `close` | `generate_positional_pk` (D5), a no-op, and `WeaviateClient.close` |

Later sections that name `create_collection` or `validate_existing_collection` refer to the index-manager methods behind `create_index` and `validate_existing_schema`.

The application layer (`VectorDBOperator`) touches only `VectorStorePort` and `VectorStoreFactory`. `metadata_fetcher.py` imports `resource_metadata` lazily inside the `weaviate` branch, so the `weaviate` package is never imported unless that provider is used. Nothing under `domain/` or `ports/` imports from `adapters/`.

### D2. Registration: lazy, like Milvus

`VectorStoreFactory.register_lazy("weaviate", "...weaviate.adapter", "WeaviateAdapter")` goes in `vectordb_operator.py` next to Milvus. `_get_vectordb_provider_schemas()` gains a `WEAVIATE_ADAPTER_NAME: model_schema_to_docpipe(WeaviateConfig.model_json_schema())` entry. Importing `config.py` must not import `weaviate`, which preserves the lazy-import guarantee for metadata.

*Alternative:* eager registration like OpenSearch. Rejected because it would import `weaviate`/`grpc` on every operator-metadata request even though the package is installed.

### D3. `WeaviateConfig` fields

`collection_name` (required; a validator enforces `^[A-Z][_0-9A-Za-z]*$` with the spec message). The pattern is **not** published through operator metadata, because the generic converter does not forward `pattern`; the frontend carries its own copy of the rule (D16).

`connection_type: Literal["custom","cloud"] = "custom"`; `host = "localhost"`; `port = 8080`; `secure = False`; `grpc_host: str | None` (defaults to `host`); `grpc_port = 50051`; `grpc_secure: bool | None` (defaults to `secure`); `cluster_url: str | None`.

`auth_type` selects the method: none (the default), API key, bearer token, or client password. The credential fields are the optional strings `api_key`, `bearer_token`, `username`, and `password`. Credentials are **literal values or `$VAR` / `${VAR}` references**, and **`vault://` references need no resolution code in the adapter**. On a run, `PythonOperatorExecutor._resolve_operator_params` resolves them through the registered secret provider before the operator is constructed, so by the time `WeaviateConfig` sees a credential it is already a plain string; the model validator, the TLS rule, and the redaction helper treat it like any other value. If the provider is not registered or resolution fails, `resolve_value` raises a `ConfigurationError` and the run fails before the adapter is built; the literal reference never reaches it. Flow enrichment differs: it catches that failure and keeps the unresolved configuration, so the literal `vault://` text can reach the metadata client, authentication fails, and the redaction helper keeps the text out of the message. During flow validation `FlowValidator` replaces each `vault://` value with a placeholder, which D18 handles. The UI offers the existing Vault toggle for these fields (D16).

`timeout_init = 30`, `timeout_query = 60`, `timeout_insert = 120` (seconds), `skip_init_checks = False`, `batch_size = 100` (≥1).

`index_type: Literal["hnsw","flat","dynamic"] = "hnsw"`; `distance_metric: Literal["cosine","dot","l2-squared","manhattan","hamming"] = "cosine"`; `index_parameters: dict = {}`; `add_sparse_vector: bool = False` (see D14 for precedence).

- **Defaults** follow Weaviate's own: cosine distance and HNSW. `hfresh` is excluded because it is new and not yet documented as stable for self-provided vectors.
- **`dynamic` prerequisite.** The `index_type` field description states that `dynamic` is experimental and requires async indexing on the server (`ASYNC_INDEXING=true` for a self-hosted deployment; enabled in the console for Weaviate Cloud). The description is published in operator metadata, so API consumers and the UI see it. D8 turns the server's refusal into an actionable error.
- **Validation errors** use plain `ValueError` messages. `format_config_errors` renders a Pydantic `ValidationError` as messages built **only from the error location and message**, mirroring `VectorDBOperator.validate` (`"<field> is not provided"` for a missing field, the message otherwise). It never includes the input value, because Pydantic's default rendering embeds the input and the input is the credential-bearing `provider_config`.
- **Sensitive fields.** `api_key`, `bearer_token`, and `password` carry `json_schema_extra={"sensitive": True}` so operator metadata masks them even though `bearer_token` is not in `SENSITIVE_FIELD_NAMES`. `username` is an identifier, not a secret, and is not flagged. A schema test asserts every credential field is flagged, so a rename cannot silently unmask one.
- **Credential references are checked at configuration time.** A model validator calls `resolve_env_var` on each credential in use and discards the result; an unset variable becomes a configuration error that names the variable (`"Environment variable WEAVIATE_API_KEY is not set"`) and never a value. Resolved values are not stored on the model; `WeaviateClient` resolves again at connect time. Because the check happens during adapter construction, an unset variable is an initialization failure like any other (D15), not a mid-run error.
- **All-caps literals.** `resolve_env_var` substitutes any string that is all upper case and contains `_` when an environment variable of that name exists. A literal credential shaped like `MY_TOKEN` could therefore be replaced silently. The README says to use an explicit `$VAR` reference for environment values and to expect this behavior for all-caps literals; the adapter does not change the shared helper.
- **Operator-injected keys.** `VectorDBOperator.__init__` adds `available_features`, `feature_mappings`, `add_sparse_vector` (when set), `schema_template_path` (when set), and `validating_flow` (D18) to `adapter_config`. None of them are `WeaviateConfig` fields, so `extra="ignore"` keeps validation unaffected. The adapter reads `available_features` and `feature_mappings` and applies `add_sparse_vector` (D14). It handles `schema_template_path` by logging one warning that the option is OpenSearch-only and never reading it.
- **Constants reused** (no new definitions): `OperatorConstants.VectorDB.HOST`, `PORT`, `USERNAME`, `PASSWORD`, `SECURE`, `AUTH_TYPE`, `COLLECTION_NAME`, `INDEX_TYPE`, `INDEX_PARAMETERS`, `DEFAULT_PRIMARY_KEY_FIELD`, plus `OperatorConstants.Config.API_KEY` and `Config.BATCH_SIZE`.
- **Constants added** to `OperatorConstants.VectorDB`: `WEAVIATE`, `CONNECTION_TYPE`, `GRPC_HOST`, `GRPC_PORT`, `GRPC_SECURE`, `CLUSTER_URL`, `BEARER_TOKEN` (carrying the repository's secret-scanner allowlist marker, as `Config.API_KEY` does), `DISTANCE_METRIC`, `TIMEOUT_INIT`, `TIMEOUT_QUERY`, `TIMEOUT_INSERT`, `SKIP_INIT_CHECKS`. `DISTANCE_METRIC` (`"distance_metric"`) is deliberately distinct from Milvus's `METRIC_TYPE` (`"metric_type"`).
- **Credentials require TLS.** The defaults stay plaintext (`secure = False`) because an unauthenticated local test server is the common case. When `connection_type == "custom"` and `auth_type != "none"`, the `model_validator` fails unless `secure` and the resolved `grpc_secure` are both true. The check runs after `grpc_secure` falls back to `secure`, so `secure=true` with an explicit `grpc_secure=false` is also rejected. The message is `"secure and grpc_secure must both be true when auth_type is not 'none'; credentials must not be sent over an unencrypted connection"`. There is no opt-in override. `cloud` is exempt because `connect_to_weaviate_cloud` hardcodes `secure=True` on port 443 for both HTTP and gRPC (verified for 4.23.1; task 1.1 re-checks it for the pinned version).

*Alternatives:*

- Infer cloud vs self-hosted from whether `cluster_url` is set. Rejected because an explicit `connection_type` keeps configuration unambiguous and gives deterministic messages.
- Default `secure` to true. Rejected because it would break the common unauthenticated local server, which has no TLS listener.
- Warn on credentials over plaintext and require an opt-in flag. Rejected because credentials must never be sent unencrypted, and a flag is an escape hatch around that rule.
- Resolve credentials inside the model and store the plaintext value. Rejected because the model is serialized into metadata and error text; only the check runs there.

### D4. Connection, authentication, and error hygiene

- **`custom`** calls `weaviate.connect_to_custom(http_host, http_port, http_secure, grpc_host, grpc_port, grpc_secure, auth_credentials, additional_config=AdditionalConfig(timeout=Timeout(init, query, insert)), skip_init_checks)`.
- **`cloud`** calls `weaviate.connect_to_weaviate_cloud(cluster_url, auth_credentials, additional_config, skip_init_checks)`.
- **Credentials:** the matching `Auth` helper of the SDK (API key, bearer token, or client password), and no `Auth` object for `none`. Values pass through `resolve_env_var` (as in the OpenSearch adapter). An unset variable raises before any network call.
- **Plaintext guard in the client.** `WeaviateClient` repeats the D3 credentials-over-plaintext check before building credentials or calling `connect_to_custom`, and raises a 400 `DocpipeException` with the same message. The adapter path is already covered by the config validator (which always runs during adapter construction, including when `global_config.disable_validation` skips flow validation), but `WeaviateResourceMetadata` builds a `WeaviateClient` straight from a raw config dict during enrichment and never constructs the adapter. The guard is what stops credentials going out over plaintext there.
- **Readiness:** after connecting, `client.is_ready()` must be true, or a 503 `DocpipeException` is raised. The client is closed before that exception (and before any other exception raised after `connect_to_*` returned) leaves `connect`, so a failed readiness check does not leak the HTTP and gRPC connections.
- **Connection ownership.** The `WeaviateClient` that opened a connection owns it, and `close()` is idempotent (a second call is a no-op). `WeaviateAdapter.close()` delegates to it. Three owners cover every path: `VectorDBOperator.transform` closes the adapter in `finally` (existing); `WeaviateResourceMetadata.fetch` closes its own client in `finally` (D10); and `VectorDBOperator.validate` closes the adapter when the operator was built for flow validation (D17). Without the last one, `FlowValidator` constructs the operator (which connects in `__init__`), calls `validate()`, and discards the instance without ever running a transform, so the Weaviate SDK's explicit-close requirement would be violated on every validation.
- **Redaction.** Every exception message and log line the client produces passes through a redaction helper that replaces each resolved credential value (and any `Authorization` header text) with `***`. Messages contain the host or cluster URL, `connection_type`, `auth_type`, the exception class name, and the redacted upstream text. Weaviate client errors can echo URLs and headers, and `VectorStoreFactory.create` and the operator both interpolate the original text into their wrapped messages, so redaction at the source is the only reliable place.
- **Logging:** log lines use `%s` formatting and contain the host or cluster URL, `connection_type`, and `auth_type` only. The batch processor redacts server error text the same way before it enters a failed-item `reason`.

### D5. Object identity: positional primary key → UUIDv5

`generate_chunk_pk` returns `generate_positional_pk(file_id, chunk_index)` (`{sha3_512(file_id)}_chunk_{i}`), the OpenSearch strategy. `file_id` is the row's `id` when it is present and non-empty, and the document ID column value otherwise. **That fallback is an operator change (task 5.5).** Today the operator builds the key from `row_data.get("id", doc_id)`, which yields the string `None` for a null `id` (every such document then shares one key and overwrites the others), and collects the stale-cleanup file IDs only from non-empty `id` values (a document with no `id` is never cleaned up). After the change both sites use the same fallback, so a document's keys and its stale-chunk lookup always agree. Documents that have an `id` are unaffected; for OpenSearch and Milvus only flows whose `id` is null or absent change, and their chunks were already colliding. The object UUID is `weaviate.util.generate_uuid5(chunk_pk)`, and the primary key is also stored verbatim in property `pk`, so stale-chunk lookup and debugging never need to reverse a UUID. Weaviate batch writes replace an existing object with the same UUID, which makes re-ingest an in-place upsert. Integration test I-3 asserts this, since the replace semantics are the one upstream behavior this design depends on.

**The adapter's identity property is always named `pk`** (`DEFAULT_PRIMARY_KEY_FIELD`). It is an ordinary text property that holds the chunk's positional key; it is distinct from the Weaviate object UUID (a UUIDv5 of that key), which is Weaviate's own identifier. The primary feature is the one flagged `is_primary` or tagged `primary` in `available_features`, falling back to the `doc_id_hash` feature. `validate_primary_key_mapping` rejects, before connecting:

- a mapping of the primary feature to any name other than `pk`; and
- a mapping of any other feature to `pk`.

This guarantees a collection never gets two identity properties (a mapped one plus `pk`). `pk` is always declared by the adapter itself; a missing primary mapping is left to the operator's existing mandatory-feature validation.

*Alternative:* Milvus's content-hash key (`{file_hash}_{content_hash}`). Rejected because it turns every content edit into a delete plus insert and churns UUIDs. Positional keys keep UUIDs stable across edits and limit deletes to genuinely removed tail chunks.

### D6. Write path: `data.insert_many` per adapter-built batch

`create_batches` mirrors Milvus: a batch holds up to `batch_size` objects and about 3 MB of estimated payload (`calculate_batch_size_bytes`). Each batch is sent with `collection.data.insert_many([DataObject(properties, uuid, vector={name: list[float]})])`.

- For each `(index, ErrorObject)` in `result.errors`, emit `{"index": {"_id": chunk_pk_of(index), "error": {"reason": <redacted err.message>}}}`.
- A raised exception marks every object in that batch failed with the redacted exception text. Later batches still run.
- Success count = batch size minus errors.

*Alternatives:* `collection.batch.fixed_size()/dynamic()` context managers, which run background threads with their own retry and re-batching. That duplicates our size-aware batching, makes index-to-chunk attribution indirect (`failed_objects` after exit), and is harder to unit test deterministically. `batch.stream()` (server-side batching, ≥1.36) gives better throughput but would raise the minimum server version. It is listed as a follow-up.

### D7. Schema mapping and tokenization

| Feature `type` | Weaviate `DataType` | Value handling |
|---|---|---|
| `text`, `string`, `keyword`, `date` | `TEXT` | Non-`str` values are JSON-serialized |
| `int8`/`int16`/`int32`/`int64`/`integer`/`long`/`short`/`byte` | `INT` | as-is |
| `float`/`double` | `NUMBER` | as-is |
| `bool`/`boolean` | `BOOL` | as-is |
| `json`/`object`/`nested`, unknown | `TEXT` | `json.dumps(value, default=str)`; JSON strings are kept verbatim |

- **Tokenization:** `field` for `pk`, the target names mapped from `id` and `name`, and `keyword`-typed features (the **identity properties**, which are filtered by whole value). `word` for everything else. All text properties keep `index_filterable` and `index_searchable` at their defaults (true). Tokenization of an existing property cannot be changed later, so D8 checks it on existing collections.
- **Always declared:** `pk` and the content property (mapped name of `content`, else `text`). The content property is `word`-tokenized and `index_searchable` in every mode, so keyword (BM25) search over the inverted index is available even with `add_sparse_vector` false. `bytes` values are skipped and `None` values are omitted (Weaviate stores the property as null).
- **Rejected types:** `DATE` is avoided because pipeline dates are not guaranteed RFC 3339. `OBJECT` is avoided because Weaviate requires nested properties to be declared up front.
- **Property-name checks:** `validate_property_names` applies the regex, the reserved names, the `vector`/`_vector` names, and the reserved suffixes (`_searchable`, `_rangeable`, `_temp`, `__meta_count`, `_propertyLength`, `_nullState`). It also enforces the server's name normalization: a mapped property name whose first character is upper case is **rejected** (the server would store it under a lower-cased first character, so writes, filters, and reads by the original name would disagree), with a message that names the property and suggests the lower-cased spelling. It also rejects two mapped names that are equal when case-folded, because the server treats them as the same property. Rejecting rather than silently normalizing keeps the saved mapping, the stored property, and every filter and read on one spelling.
- **Sparse mode (D14):** the `sparse_embeddings` mapping is skipped when building properties and documents, because Weaviate has no field for it.
- **`WeaviateAdapter.__init__` order, all before connecting:**
  1. Validate `provider_config` with `WeaviateConfig` (required `collection_name` and its pattern, cloud `cluster_url`, credentials for `auth_type`, credentials over plaintext, credential references resolvable), reporting failures through `format_config_errors` (D3, D15).
  2. If `add_sparse_vector` is true, require a mapping for the content feature (D14).
  3. Warn once on `schema_template_path` (D3).
  4. Drop and warn on an ACL mapping (D13).
  5. Run `validate_primary_key_mapping` (D5) and `validate_property_names` on the remaining mappings.
  6. Only then `WeaviateClient.connect`.

  The filtered mapping list is the one passed to the index manager and batch processor, so a dropped ACL mapping can reach neither the schema nor the objects.

### D8. Collection creation and existing-collection validation

- **`create_collection`:** raises 409 if the collection exists. It always passes an explicit `vector_config`, because omitting it makes the client inject an indexed named vector called `default` (see Upstream facts). It calls `client.collections.create(name, properties=[...], vector_config=[...])`, with one entry per `dimension_mapping` item: `Configure.Vectors.self_provided(name=mapped(col), vector_index_config=<index>(distance_metric=..., **index_parameters))`. A `TypeError`/`ValueError` from `index_parameters` becomes a 400 `DocpipeException` naming the parameter. Multi-tenancy, replication, and quantization are left at server defaults.
  - In sparse mode it also passes `inverted_index_config=Configure.inverted_index(bm25_k1=1.2, bm25_b=0.75)`, which are Weaviate's own defaults, stated explicitly so the collection config records them.
  - **Keyword-only collections.** When `dimension_mapping` is empty (a sparse-only run), it passes a single non-indexed vector, `Configure.Vectors.self_provided(name="keyword_only", vector_index_config=Configure.VectorIndex.none())`. The server builds no vector index for it, objects are written with no vector, and BM25 and filters work. A **keyword-only collection** is one that has no indexed vector: either it declares named vectors and every one reports `skip`, or it declares no named vectors and its legacy collection-level vector index reports `skip` (the shape `vectorizer_config=none` plus `vector_index_config=none` creates, which is how users often create BM25-only collections by hand). A collection with no named vectors whose legacy vector index is **not** skipped is a legacy indexed collection, not a keyword-only one. Validation (below) and enrichment (D10) share this definition and read both shapes from `collection.config.get()` (`vector_config` and `vector_index_config.skip`). The adapter creates the named non-indexed shape because it uses the non-deprecated `vector_config` argument; the legacy arguments emit deprecation warnings in client 4.24.1.
  - **`dynamic` without async indexing.** The server refuses the request with HTTP 422. `create_collection` catches that refusal, and raises a 400 `DocpipeException` stating that `index_type` `dynamic` requires async indexing (`ASYNC_INDEXING=true` for a self-hosted server, enabled in the console for Weaviate Cloud) and suggesting `hnsw` or `flat`. Other server errors keep their redacted text.
- **`validate_existing_collection(dimension_mapping)`** reads `collection.config.get()` and collects every mismatch into one `DocpipeException` (400), which the operator turns into per-document failures. The scalar checks (steps 4-6) run for **every** run, including sparse-only runs; only the vector checks (steps 1-3) are skipped when `dimension_mapping` is empty.
  1. If `dimension_mapping` is non-empty and the collection has no indexed vector (a keyword-only collection, or a legacy indexed collection with no named vectors), fail with a message naming which of the two it is.
  2. Every mapped vector name must be present and indexed. A vector of that name whose index is skipped counts as missing.
  3. If `aggregate.over_all(total_count=True)` > 0, fetch one object with `include_vector=[names]` and compare each vector's length to the runtime dimension.
  4. For mapped properties that exist, the data type must equal the D7 mapping.
  5. **Identity properties.** `pk`, the targets mapped from `id` and `name`, and `keyword` features must exist with `field` tokenization and `index_filterable=true`. Tokenization cannot change on an existing property, so a mismatch fails naming the property, the tokenization found, and the remediation (recreate the property or collection with `field` tokenization, or use a new collection name). Under `word` tokenization the keyset paging that finds stale chunks silently returns nothing after the first page (so stale chunks survive), and prefix and equality filters can match other files' values that share tokens (so a delete could reach another file's chunks). This check protects both. Property lookups compare canonical names (the server lower-cases the first character), so a collection created with `Pk` is seen as `pk`.
  6. **Content property, in every mode.** The mapped content property must be `index_searchable=true` and `word`-tokenized whether or not `add_sparse_vector` is set, because D7 promises keyword search over content in every mode. Neither attribute can be changed after creation, so a mismatch fails with the same style of message, naming the property and the tokenization found. Reproduced on server 1.40.2: an indexed named vector, a valid `pk`, and a searchable but `field`-tokenized content property accept writes, yet a BM25 query for a single word returns zero objects, so a dense-only run must not accept that collection.
  7. Only when steps 1-6 found no mismatch, missing mapped properties are added with `collection.config.add_property(Property(...))` (identity properties with `field` tokenization, the content property `word`-tokenized and searchable) and logged. Nothing is mutated when the run is going to fail.

*Alternative:* let auto-schema add missing properties. Rejected because it infers types from the first value (for example `"42"` becomes text), which would silently diverge from the declared mapping, and it may be disabled on the server. Integration tests run with `AUTOSCHEMA_ENABLED=false` to prove the adapter never depends on it.

### D9. Stale-chunk lookup, deletes, queries, count

- **`get_chunk_ids_for_documents(file_ids)`:** for each file, keyset-page the file's keys: `query.fetch_objects(filters=Filter.by_property("pk").like(f"{sha3_512(file_id)}_chunk_*") & Filter.by_property("pk").greater_than(last_pk), sort=Sort.by_property("pk", ascending=True), return_properties=["pk"], limit=1000)`, with the `greater_than` clause omitted on the first page. Each page is a query at offset 0, so the `QUERY_MAXIMUM_RESULTS` cap on `offset + limit` never applies and a file of any chunk count is covered. Paging stops at the first short page, and results are keyed by file ID. Matching on the primary-key prefix works regardless of whether the user mapped `id`. Any exception logs and returns `{}`, matching siblings. Verified on server 1.40.2: 2,500 keys came back in 3 pages.

  Both the `greater_than` ordering and the prefix filter depend on `pk` being `field`-tokenized (D7). Under `word` tokenization `greater_than` returned no rows (reproduced), so paging would stop after the first page and later chunks would stay behind as stale data; the prefix filter can also match another file's keys when their tokens overlap. D8 therefore rejects an existing collection whose identity properties are not `field`-tokenized, and integration scenarios I-4 and I-12 exercise the lookup on a real server.
- **`delete_documents_by_ids(chunk_pks)`:** converts primary keys to UUIDv5 in chunks of 500 (`BULK_DELETE_BATCH_SIZE`) and calls `data.delete_many(where=Filter.by_id().contains_any(uuids))`, summing `successful` and `failed`. Chunking keeps each call under the 10,000 cap.
- **`get_document_count()`:** `aggregate.over_all(total_count=True).total_count`, or 0 on error.
- **`query_by_doc_names(names)`:** `fetch_objects(filters=Filter.by_property(<mapped name field>).contains_any(names), return_properties=fields)` returning `properties` dicts. The name property is `field`-tokenized (D7), so matching is exact.
- **`refresh_index()`:** a no-op with a debug log. Writes are visible once `insert_many` returns; async indexing, if enabled server-side, affects only vector-index freshness.

### D10. Flow enrichment (`WeaviateResourceMetadata`)

- **Skip condition:** if neither `host` (custom) nor `cluster_url` (cloud) is present, return `empty_result()`.
- **Fetch:** connect with `WeaviateClient` (which applies the D4 plaintext guard and redaction), then read:
  - `available_resources = sorted(client.collections.list_all(simple=True))`;
  - for an existing selected collection, `selected_resource_schema` with properties as `{type: DATA_TYPE.upper(), is_primary: name == "pk", description, index_searchable}` and each **indexed** named vector as `{type: "VECTOR", dimension: <sampled or None>, index_info: {index_type, metric_type: distance}, index_created: True}`. Skipped (non-indexed) vectors are not listed as vectors;
  - `stored_resource_metadata` from the first indexed named vector, or `{vector_similarity: None, dimension_size: None}` when there is none.
- **Supported versus BM25-eligible.** `is_docpipe_supported_resource` is a dict whose existing keys (`collection_name`, `supported`, `reason`) are kept, with one additive key, `sparse_eligible`:
  - `supported` is true for an empty or new name and for a collection with at least one indexed named vector, provided the D8 scalar checks hold in every mode: its identity properties are `field`-tokenized and its mapped content property is `index_searchable` and `word`-tokenized. A collection that fails them is `supported: false` with a reason, so the panel does not offer a collection that D8 would reject at run time;
  - for a keyword-only collection (D8), `supported` is true only when `add_sparse_vector` is true **and** the collection is BM25-eligible; otherwise it is false with a reason;
  - `sparse_eligible` is true when the selected collection is keyword-only or has vectors, its mapped content property is `index_searchable` and `word`-tokenized, and its identity properties are `field`-tokenized. It is computed **independently of the current flag**, so a keyword-searchable collection that is unsupported while the flag is off reports `supported: false, sparse_eligible: true`. Without that independent signal a user could never reach the control that would make the collection supported (D16);
  - the five top-level enrichment keys are unchanged; the new key lives inside the existing dict.
- **`feature_mappings`:** saved mappings, then live-schema derivation (`pk` → primary feature, first indexed vector → first vector feature, identity names; when `add_sparse_vector` is true and the content property is searchable, also the sparse feature → `sparse_embeddings`), then `default_feature_mappings_from_features` (which already adds the sparse and content defaults in sparse mode).
- **Failure reporting.** Enrichment must tell an unreachable or rejecting deployment apart from a reachable one that has no collections. On any exception (including a refused authenticated-plaintext configuration) the adapter logs a redacted warning and returns the five-key result in which `is_docpipe_supported_resource` is `{"supported": false, "error": "<redacted reason>"}`, where the reason is built from the same redaction helper as D4 and never contains a credential. A skipped fetch for a missing host or cluster URL returns the plain empty result with no `error`. The frontend shows `error` when present (D16); other providers never set it, so their behavior is unchanged. `VectorDBMetadataFetcher` still never raises.
- **Cleanup:** the client is closed in `finally`. (`MilvusResourceMetadata.fetch` does not close its client; that is a known gap in a sibling adapter that this change does not touch.)
- **`vector_similarity` vocabulary.** The value is the key the UI looks up in the provider's own distance options: the tearsheet takes `stored_resource_metadata.vector_similarity` and uses it as the selected value of the provider's similarity field (`distance_metric` for Weaviate), then looks it up in the provider's labels. It therefore has to be in the **Weaviate** vocabulary, and is passed through unchanged rather than normalized to OpenSearch or Milvus names:

  | Emitted by Weaviate (`distance_metric`) |
  |---|
  | `cosine`, `dot`, `l2-squared`, `manhattan`, `hamming` |

  The client returns the metric as an enum; the adapter emits its string `.value`. A value outside the five known names is passed through as-is (the UI shows it unlabeled), and a collection with no indexed named vector yields `None`. The only other `VECTOR_SIMILARITY_KEY` reader in `src` is the OpenSearch metadata module, which reads OpenSearch's own stored value. A unit test pins the five names, an unknown value, and `None`.

`VectorDBMetadataFetcher.fetch_metadata` gains an `OperatorConstants.VectorDB.WEAVIATE` branch.

### D11. Dependency and lockfiles

- **Pin:** `"weaviate-client==4.24.1"` in `[project.dependencies]` of both `pyproject.toml` and `slim/pyproject.toml`, in alphabetical order, with a comment next to the declaration stating that the client caps `grpcio<1.80.0` and why `grpcio` is therefore held below 1.80 (a transitive Dependabot bump fails to resolve against that cap). Task 1.1 re-queries PyPI and replaces the pin if a newer stable client exists; 4.24.1 is the latest as of 2026-10-26.
- **Locks:** run `uv lock` in the repo root and in `slim/`, then `uv pip install -e ".[dev]"`. Commit both `pyproject.toml` files and both `uv.lock` files together, per `AGENTS.md`.
- **Trial resolution** (isolated copies of each project, 4.24.1, 2026-10-26):

  | Project | Packages resolved | Changes versus current lock |
  |---|---|---|
  | root | 500 | add `weaviate-client` 4.24.1, `validators` 0.36.0, `joserfc` 1.7.7; `authlib` 1.6.12 → 1.9.1; `grpcio` 1.84.0 → **1.78.0** |
  | `slim/` | 489 | add `weaviate-client` 4.24.1, `validators` 0.36.0, `joserfc` 1.7.7, `authlib` 1.9.1; `certifi` 2026.7.22 → 2026.10.23; `grpcio` 1.84.0 → **1.78.0** |

  PyPI has no 1.79.x `grpcio` release and 1.78.1 is yanked, so 1.78.0 is the newest installable version under the cap. OSV returned no advisories for `weaviate-client` 4.24.1, `grpcio` 1.78.0, `authlib` 1.7.1 or 1.9.1, `joserfc` 1.7.7, `validators` 0.36.0, or `certifi` 2026.10.23. The slim variant ships Weaviate, as it already ships Milvus and OpenSearch; slim's lock drifts from the root's (for example `opensearch-py` 3.2.0 versus 3.1.0), so it is resolved and verified independently. Resolution re-runs against the real files, and again after any rebase on `main`, because the cap interacts with whatever else moves.
- **Decision gate (task 1.1):**
  - If resolution fails, a resolved package has a published advisory, or the existing Milvus, OpenSearch, or telemetry tests fail on the downgraded `grpcio`, stop and ask the maintainers. Do not add an `override-dependencies` entry on our own.
  - A scoped override such as `grpcio>=1.84` runs the client outside its declared range and would need integration-test evidence and a maintainer decision.
  - The other path is to wait for upstream to lift `<1.80`.

### D12. Testing strategy

Unit tests live under `tests/unit/` and run in CI with the existing selection (`pytest tests/unit -m "unit and not integration"`), so they follow the marker convention of the neighbouring `test_milvus_*` files. The real-server suite is **manual-only**: no vector database container test runs in CI today, and CI excludes anything under `tests/integration/`. The suite is documented as a pre-release check in the VectorDB README and is not given a CI job in this change.

| Level | Location | Scope |
|---|---|---|
| Unit: config | `tests/unit/operators/vectordb/test_weaviate_config.py` | defaults, every validator message, Literal enums equal index-manager constants, JSON schema enums, `extra` ignored; **no `pattern` expected in metadata**; every credential field flagged sensitive in the published schema; credentials over plaintext: each of the three authenticated methods rejected with HTTP TLS off, and with HTTP TLS on plus an explicit gRPC TLS off; accepted with both true; accepted with `secure=true` and `grpc_secure` unset; `auth_type="none"` with plaintext accepted; `cloud` with auth accepted; unset `${VAR}` → configuration error naming the variable, never a value; `$VAR` and `${VAR}` resolvable; `format_config_errors` output never contains an input value |
| Unit: client | `test_weaviate_client.py` | custom/cloud call arguments, each auth helper, `$VAR`/`${VAR}` resolution, unset variable error, not-ready → 503 (client closed first), idempotent `close`; credentials over plaintext → 400 with no `connect_to_*` call, even when built without `WeaviateConfig` validation; connection errors that echo the secret or an `Authorization` header are redacted in the raised message and in `caplog` |
| Unit: index manager | `test_weaviate_index_manager.py` | type table, tokenization rule, property-name rejection cases (**an upper-case first character is rejected, and two names equal when case-folded are rejected**), **primary-key mapping rules** (primary feature to a name other than `pk` rejected; another feature to `pk` rejected; no second identity property), one named vector per dimension entry, invalid `index_parameters` → 400, **`dynamic` refused by the server (422) → 400 naming async indexing**, each existing-collection branch (legacy indexed collection, keyword-only collection in both shapes (all vectors skipped, and no named vectors with a skipped legacy index), missing vector, skipped vector counted as missing, dimension mismatch, empty skip, type mismatch, canonical-name lookup for a property stored with a lower-cased first character, missing property added only when nothing else failed); **identity-property checks** (`pk`, `id`/`name` targets, and `keyword` features each rejected when `word`-tokenized or not filterable, with the remediation text); sparse mode: BM25 `inverted_index_config` passed, **a single non-indexed `keyword_only` vector passed (never an omitted `vector_config`) for an empty `dimension_mapping`**, sparse-only validation skips only the vector checks, **a conflicting existing scalar type or a `word`-tokenized `pk` still fails in a sparse-only run**, non-searchable or non-`word` content property fails **with `add_sparse_vector` both true and false (a dense-only run against an indexed collection whose content property is searchable but `field`-tokenized is rejected)**, `sparse_embeddings` mapping produces no property |
| Unit: batch processor | `test_weaviate_batch_processor.py` | `prepare_document` mapping, JSON, bytes, and None handling; `sparse_embeddings` skipped; sparse-only objects carry no `vector`; count and size batching; `insert_many` error → failed-item shape with redacted reason; whole-batch exception, and `WeaviateInsertManyAllFailedError` (every object in the batch reported failed with the redacted message, later batches still run); UUIDv5 determinism; delete chunking at 500; count; **stale lookup keyset paging** (the second query carries the `greater_than(last_pk)` clause and offset 0; a file with more than 10,000 keys is fully returned; a short page stops paging; no query is issued with an offset); `query_by_doc_names` |
| Unit: adapter | `test_weaviate_adapter.py` | lazy factory registration and `create`, `get_config_schema`, every configuration error raised before `connect` (assert connect not called) and **surviving the wrapping**: the message appears in the `VectorStoreFactory.create` error and in the `FlowValidator` error for a `vectordb` node; sparse mode without a content mapping rejected before `connect`, sparse mode with content mapped accepted; reserved-name rejection; `schema_template_path` (missing file) → no error, one warning, identical `collections.create` arguments; mapped `allowed_users` dropped with one warning; unmapped upstream `allowed_users` → one warning; import isolation (no module under `core/operators/acl` or `docpipe.api` loaded); positional primary key, delegation, `close` (**idempotent; an exception after `connect` closes the client before propagating**); **secret safety across paths**: with credentials supplied through `monkeypatch.setenv` and a mocked client raising errors that echo them, the secret values never appear in any raised message (adapter, batch processor, factory, operator wrapping) or in `caplog` |
| Unit: enrichment | `test_weaviate_resource_metadata.py` + `test_metadata_fetcher.py` | five keys, supported rules (keyword-only collection: unsupported with the flag off and `sparse_eligible: true`, supported with the flag on; ineligible keyword-only collection unsupported in both), `index_searchable` on property entries, skipped vectors not listed, mapping resolution order including sparse defaults, **`vector_similarity` values** (five names, unknown, `None`), **failure reporting** (connection error and rejected credentials → `supported: false` with a redacted `error`; no host or cluster URL → plain empty result without `error`; a reachable deployment with no collections → empty `available_resources` and no `error`), authenticated plaintext → `error` without connecting, client closed in every path; router dispatches `weaviate` |
| Operator | `test_vectordb_operator.py` | `provider` valid values and `providers.weaviate` schema (credential fields sensitive); mocked adapter returning one failed item → parent document in `failed_docs`; adapter closed on exception; **adapter released after flow validation (D17)**; **sparse-mode tests pinning the provider-agnostic spec** (sparse-only run with an empty dimension mapping, sparse plus dense, `sparse_embeddings` ignored by a provider); **tests pinning the provider-agnostic spec** (unknown provider rejected with the available list, missing document ID column, row with an empty document ID skipped, no dense vector column without sparse, N chunks → N objects, returned metadata keys); a scenario with no existing test gets one |
| Real-server (manual) | `tests/integration/weaviate/test_weaviate_with_container.py` | I-1 create + write via `VectorDBOperator`; I-2 two named vectors; I-3 re-ingest leaves count unchanged and UUID stable with new text; I-4 shrink deletes tail; I-5 dimension mismatch → FAILED; I-6 pre-created INT property + string value → exactly one failed chunk attributed; I-7 enrichment against live server, including an unreachable port reported with an `error`; I-8 delete >500 primary keys; I-9 sparse plus dense: `collection.query.bm25` and `collection.query.hybrid` both return the target chunk, and the collection config shows k1 = 1.2 and b = 0.75; I-10 sparse-only (no embeddings column, in-memory chunks): the collection has one non-indexed vector and no indexed vector (the server reports `skip`), chunks are written, BM25 returns them, and a second run passes existing-collection validation; a hand-made legacy-shape keyword-only collection (no named vectors, `vectorizer_config` and `vector_index_config` both none) is recognized as keyword-only and accepted for a sparse-only run; **I-11 `dynamic` index against the async-indexing server (below), polling `vector_queue_length` to 0 before any vector query; and `dynamic` against the default server fails with the actionable 400**; **I-12 a pre-created collection whose `pk` is `word`-tokenized is rejected, nothing is deleted, and a second file's chunks survive a re-ingest of the first; and stale cleanup for a file with more than 10,000 chunks (above `QUERY_MAXIMUM_RESULTS`) deletes every tail chunk**; **I-13 connection release: a flow validation of a `vectordb` node with `provider: "weaviate"` (no transform), and a failed construction against an unready or rejecting server, leave no open HTTP or gRPC connection (the underlying SDK client reports `is_connected()` false afterwards, observed by wrapping the client the adapter opened); I-14 a dense-only run against a pre-created collection with an indexed vector, a valid `pk`, and a searchable but `field`-tokenized content property is rejected naming the content property, with nothing written**; **I-15 document identity through `VectorDBOperator`: two documents with a null `id` both persist with distinct keys, and re-ingesting one with fewer chunks deletes only its own tail chunks, with an `id` column present and with it absent** |

**Secrets in tests.** Fixtures never contain a literal that looks like a credential: values are supplied with `monkeypatch.setenv` and referenced as `$VAR`/`${VAR}`, or built at run time. Where a literal is unavoidable, the line carries the repository's secret-scanner allowlist marker. The detect-secrets hook is run over the new test files (task 9.1).

The integration server comes from `docker/docker-compose.weaviate.yml`. The default service uses image `cr.weaviate.io/semitechnologies/weaviate:1.40.2`, ports `127.0.0.1:8080:8080` and `127.0.0.1:50051:50051`, and environment `AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true`, `PERSISTENCE_DATA_PATH=/var/lib/weaviate`, `DEFAULT_VECTORIZER_MODULE=none`, `AUTOSCHEMA_ENABLED=false`, `CLUSTER_HOSTNAME=node1`, with `ASYNC_INDEXING` unset so vector queries are immediately consistent for scenarios I-1 to I-10 and I-12 to I-14.

A second service, `weaviate-async`, sits behind the compose profile `async` and is started only for I-11. It uses the same image and environment plus `ASYNC_INDEXING=true`, its own volume, and the ports `127.0.0.1:8081:8080` and `127.0.0.1:50052:50051`. The suite reaches it through `DOCPIPE_TEST_WEAVIATE_ASYNC_HOST` (and port variables) and reports I-11 as **blocked**, not passed, when that server is unavailable. Keeping the async server separate means the common scenarios do not inherit index-lag behavior, and the `dynamic` prerequisite is exercised in both directions.

**Test-only hardening.**

- **Loopback binding.** Every published port, on both services, is bound to `127.0.0.1`, never `0.0.0.0`. Anonymous access is acceptable only because of this binding and because the server holds no real data. The compose file's header comment says it is test-only and must not be used for deployment.
- **Image source.** The image comes from the upstream registry `cr.weaviate.io`, not `registry.redhat.io`. That is acceptable only because the compose file is test-only. No deployment artifact references Weaviate: the Dockerfiles, the other compose files, `docker/k8s`, and `docker/all-in-one-deployment` contain no Weaviate reference. The image is not described as approved for production.
- **Revisit trigger.** If a Weaviate server is ever shipped or deployed, it needs an approved image source and authentication enabled, and the plaintext defaults in D3 must be reviewed again.

The suite follows the OpenSearch container test's skip-if-no-Docker helpers and supports both `docker compose` and `docker-compose`. If `DOCPIPE_TEST_WEAVIATE_HOST` is set, it uses that server instead of starting a container (mirroring `DOCPIPE_TEST_POSTGRES_DSN`). Readiness is polled with `client.is_ready()`. Each test uses a unique collection name and drops it in teardown. The suite is auto-marked `integration` by `tests/conftest.py` (anything under an `integration` directory), so no explicit marker is required.

**Auto-schema guard.** A session-scoped fixture creates a scratch collection with one declared property and inserts an object carrying an undeclared property. If the server accepts it, auto-schema is on, and the whole suite **fails** (not skips) with a message that `AUTOSCHEMA_ENABLED=false` is required. This matters most for externally supplied `DOCPIPE_TEST_WEAVIATE_HOST` servers. With auto-schema off the server rejects the object, and the client surfaces that as either an `errors` entry (mixed batch) or `WeaviateInsertManyAllFailedError` (single-object batch, which this probe uses); the guard treats **either** as the expected rejection and any accepted object as a failure. A skipped suite is reported as blocked, never as passed.

### D13. ACL: dropped with a warning, never enforced

**How ACL works today.** `ACLOperator` emits an `allowed_users` column (a JSON-array string flagged `available_for_opensearch`). Nothing in `core/operators/vectordb/` handles it; it reaches OpenSearch only when a user maps it. Enforcement lives entirely in the API layer: `api/services/acl_query_builder.py` adds an `allowed_users` term filter to OpenSearch reads in `api/routes/documents.py`. Weaviate has no read path in docpipe, so there is nothing that could enforce an ACL stored there.

**Decision.**

- In `__init__`, the adapter removes every mapping whose `feature_name` equals `OperatorConstants.ACL.ALLOWED_USERS_COLUMN`, and logs one warning naming the dropped target property.
- If `allowed_users` appears in `available_features` but is unmapped, it logs one warning that ACLs are not enforced for Weaviate.
- The run never fails because of ACL.
- The only ACL-related import is that constant, from `docpipe.core.constants`. The adapter must not import `ACLOperator`, anything under `core/operators/acl/`, or anything under `docpipe.api`. A unit test asserts this by importing the adapter package in a clean interpreter and inspecting `sys.modules`.
- Weaviate RBAC and multi-tenancy stay out of scope (proposal Non-goals).

**Alternatives.**

- Reject a mapped `allowed_users` at startup. Not chosen, by maintainer decision: dropping the ACL column and still ingesting the document is the intended behavior, because Weaviate has no ACL read path in docpipe and the column carries no meaning there. The warning is the signal; the run does not fail.
- Store it as a plain TEXT property. Rejected because the data would look access-controlled when nothing enforces it, and any Weaviate client could read it.

### D14. Sparse (BM25) mode

In Weaviate, "sparse" retrieval means keyword search over the **inverted index** of a text property that is `index_searchable`, scored with BM25 at query time and fused with vector search in hybrid queries. There is no stored sparse vector. The `add_sparse_vector` flag is the operator-level switch that asks for this mode.

| Concern | Weaviate behavior |
|---|---|
| Where scores come from | BM25 over the inverted index of the mapped content property, computed at query time |
| `sparse_embeddings` feature | accepted and ignored: Weaviate has no field for it, so it produces no property and no value |
| BM25 parameters | `Configure.inverted_index(bm25_k1=1.2, bm25_b=0.75)` when the flag is on. These are Weaviate's own defaults; they are set explicitly so the collection config records them |
| Content property | must be mapped when the flag is on (checked in `__init__` before connecting); declared `word`-tokenized and `index_searchable` in every mode, so keyword search also works with the flag off |
| Existing collection | content property must be `index_searchable` and `word`-tokenized **in every mode, including a dense-only run**, and identity properties `field`-tokenized (D8); none of these can be changed after creation |
| Sparse-only runs (no dense columns) | the operator passes an empty `dimension_mapping`; the collection gets one non-indexed named vector (D8) and objects are written with no vector |
| Enrichment | a keyword-only collection is supported when the flag is on and the collection is BM25-eligible (D10) |

For the operator's other providers, the same flag has provider-specific meaning; the comparison with them is architectural context only and no behavior here is derived from it.

- **Precedence:** `VectorDBOperator.__init__` copies the top-level `add_sparse_vector` into `adapter_config`, overriding any `provider_config.add_sparse_vector`. The operator's own dimension resolution reads only the top-level flag. The top-level flag is therefore the supported switch. Setting it only inside `provider_config` enables the adapter's BM25 configuration but not sparse-only runs, and the README says so.
- **Sparse-only requires in-memory chunks.** `VectorDBOperator._extract_chunks_for_row` takes the file-streaming path only when both chunk and vector file references exist. With no vector columns, memory-mapped `chunked_content` falls into the in-memory path and the document fails. The standard extract → chunker → vectordb pipeline produces memory-mapped chunks, so the sparse-only headline case needs in-memory chunks (for example a flow whose upstream operators keep chunks in memory). This is an existing operator limitation that is independent of the provider; fixing it is a separate change. The spec scenario, the README, and I-10 all state the in-memory prerequisite. Hybrid runs (dense plus BM25) are unaffected.
- **Querying** stays a non-goal (proposal). Consumers run `collection.query.bm25(...)` or `collection.query.hybrid(...)` themselves; the README shows both.

**Alternatives.**

- Store externally computed sparse vectors (for example SPLADE) as a property. Rejected: Weaviate offers no native sparse-vector index, so the data would not be searchable.
- Drop sparse mode from this change as surface area for little behavior (the content property is always keyword-searchable). Rejected: the flag is the operator's supported switch for sparse-only runs and for recording the BM25 parameters, and the UI exposes it through one capability-driven checkbox.
- Make keyword indexing of the content property conditional on the flag. Not chosen: it would remove keyword search by default, and `index_searchable` cannot be enabled on an existing property later.

### D15. Error semantics for configuration failures

All Weaviate configuration problems (D3 validators, sparse without content, reserved names, primary-key mapping conflicts, TLS, unresolvable credential references) are raised from `WeaviateAdapter.__init__` before any connection. They are **initialization failures**:

1. `WeaviateAdapter.__init__` raises `ValueError` (or a 400 `DocpipeException`) with the formatted message. A Pydantic `ValidationError` is re-raised with `from None`, so neither the message nor the traceback carries the input.
2. `VectorStoreFactory.create` wraps it as a 500 `DocpipeException` ("Failed to create vector store adapter 'weaviate': ...").
3. `VectorDBOperator.__init__` wraps it again ("Failed to initialize vector database adapter 'weaviate': ...").
4. In flow validation the generic handler reports "Validation failed for operator 'vectordb': ..." (`OPERATOR_VALIDATION_FAILED`).

The specs therefore promise that the original message text is contained in the failure at each of those points. They do not promise a status code other than what the wrapping produces (500 from the factory), and they do not promise the `<field> is not provided` form of `operator.validate()`, which is only reachable when construction succeeds. Making flow validation skip the connection (a shared lazy-validation change) would give these errors a 4xx status and a clean per-field shape; that is out of scope here and listed as a non-goal. `VectorDBOperator.validate` still runs `model_validate` as a safety net, which matters for tests that mock the adapter.

### D16. Frontend: provider configuration, panel, and tearsheet

**Scope.** Only the VectorDB panel and tearsheet (`frontend/src/components/PropertiesPanel/CustomPanels/VectorDB/`). No generic provider-form rewrite, no shared Vault redesign, no panel-wide string migration, no Redux, routing, or BFF change. OpenSearch and Milvus rendering is unchanged.

**Component hierarchy** (Carbon components in brackets; new files marked):

```
VectorDBPanelBody (VectorDB.tsx)
├─ Provider [Dropdown]                      list = Object.keys(operator metadata providers); fallback unchanged
├─ Accordion
│  ├─ "Connection" [AccordionItem]
│  │   ├─ opensearch / milvus: existing inline fields (unchanged)
│  │   └─ weaviate: WeaviateConnectionFields (WeaviateConnectionFields.tsx, new)
│  │        ├─ Connection type [Dropdown]  custom | cloud
│  │        ├─ custom: Host [TextInput], HTTP port [TextInput], HTTP TLS [Toggle],
│  │        │          gRPC host [TextInput, empty = inherit], gRPC port [TextInput],
│  │        │          gRPC TLS [Dropdown: Same as HTTP | On | Off]
│  │        ├─ cloud:  Cluster URL [TextInput]
│  │        └─ TLS rule error [InlineNotification, kind error, role alert]
│  ├─ "Authentication" [AccordionItem]
│  │   ├─ opensearch / milvus: existing fields (unchanged)
│  │   └─ weaviate: Authentication method [Dropdown]  none | API key | Bearer token | Username and password
│  │        ├─ API key / Bearer token [VaultInput]
│  │        └─ Username [TextInput] + Password [VaultInput]
│  └─ "Advanced" [AccordionItem] → provider_config JSON [TextArea]  (unrelated keys preserved)
├─ VectorDBSummaryTable / NoDataEmptyState (existing)
└─ VectorDBFeatureMappingTearsheet (existing)
     ├─ Collection [ComboBox] + new-name [TextInput]   provider name rule + placeholder
     ├─ Distance metric [Dropdown]                      no engine control (hasEngine false)
     ├─ BM25 [Checkbox]                                 shown when the provider's sparse capability is true and the resource is supported or BM25-eligible
     └─ DataTableSkeleton / ErrorEmptyState / VectorDBFeatureMappingTable (existing states)
```

`WeaviateConnectionFields` is a colocated component rather than more inline branches because `VectorDB.tsx` is already large; it receives the parsed config and an update callback and holds no state of its own. Pure logic (validation, default merging, inactive-key cleanup) lives in `vectordb-weaviate.ts` so it can be unit tested without rendering.

**Provider configuration (`constants.ts`).** Add `WEAVIATE: 'weaviate'` to `VECTORDB_PROVIDERS` and an entry in `PROVIDER_CONFIG_MAP`: `resourceNameKey: 'collection_name'`, `resourceLabel: 'collection'`, `similarityKey: 'distance_metric'`, `similarityLabel: 'Distance metric'`, labels and defaults for the five metrics, `hasEngine: false`, a collection-name rule (`/^[A-Z][_0-9A-Za-z]*$/`, its error text, placeholder `e.g. DocumentChunks`), and `supportsSparse: true` with Weaviate's BM25 label. Two additions to `ProviderConfigBase` are data-driven, replacing hardcoded checks, with identical behavior for existing providers: `supportsSparse`/`sparseLabel` (replacing `provider === MILVUS` in the tearsheet; OpenSearch false, Milvus true with its current label) and `advancedOnlyKeys` (replacing the `k !== 'algorithm' && k !== 'index_type'` filter; OpenSearch `['algorithm']`, Milvus `['index_type']`, Weaviate `['index_type', 'index_parameters']`). **Three key sets stay distinct:** `resourceSpecificKeys` (`collection_name`, `distance_metric`, `index_type`, `index_parameters`) are stripped only from the enrichment request, so enrichment does not pin to the saved resource; the managed keys (connection and authentication keys, `collection_name`, `distance_metric`) are hidden from Advanced JSON because a structured control owns them; and `advancedOnlyKeys` are resource-specific keys with **no** structured control, so they must stay visible and editable in Advanced JSON. `index_parameters` has no structured control, so it belongs to the third set; classifying it as managed (the current filter would, because it is in `resourceSpecificKeys`) would hide it with nothing to edit it. A test asserts that a saved `index_parameters` appears in Advanced JSON, survives edits and mode switches, is saved, and is absent from the enrichment payload. The file header, which claims that adding a map entry alone enables a provider, is corrected: provider-specific connection and authentication controls also live in `VectorDB.tsx`. The fallback provider list (`[opensearch, milvus]` when metadata is absent) is deliberately unchanged, so the UI never offers a provider the backend might not have.

**Saved configuration shape** (`provider_config`): `connection_type`; custom: `host`, `port`, `secure`, optional `grpc_host`, `grpc_port`, optional `grpc_secure`; cloud: `cluster_url`; `auth_type` with exactly the credential keys of that method; `collection_name`; `distance_metric`; any other keys from Advanced JSON. Rules:

- **Inherited values stay unset.** `grpc_host` empty and `grpc_secure` "Same as HTTP" delete the key, so the backend's inherit-from-HTTP defaults keep working. The UI never freezes the current HTTP value into them.
- **Inactive keys are removed.** Switching custom ↔ cloud deletes the other mode's keys in one atomic `provider_config` write. Switching authentication method deletes the previous method's credentials and writes `auth_type` in the same write, so the backend never sees a mix.
- **Defaults merged for enrichment.** The payload sent to enrichment is the displayed defaults (`connection_type: custom`, `host`, `port`, `secure`) merged under the saved values, minus any unset inherited gRPC fields. Saving writes only explicit values plus the resource keys; the backend supplies its own defaults for anything absent.
- **Advanced JSON.** Managed keys always win over Advanced JSON, and unrelated keys survive mode and method switches because only the specific inactive keys are deleted.
- **Credentials.** The existing shared `VaultInput` (`@/components/common`), as the OpenSearch and Milvus fields use it. In direct mode it renders a masked `PasswordInput` that accepts a literal or a `$VAR`/`${VAR}` reference; the toggle switches it to a `vault://` reference. The value is stored unchanged either way, and the backend resolves it (D3). `VaultInput` is reused as-is; its internals and messages are not modified. An empty `vault://` is flagged invalid by `VaultInput` itself, and `validateWeaviateConfig` treats any non-empty credential, including a `vault://` reference, as present.

**Validation that blocks.** `vectordb-weaviate.ts` exposes `validateWeaviateConfig(config)` returning per-field errors that mirror the backend messages: custom requires a host and ports in 1-65535; cloud requires a cluster URL; each authentication method requires its credential fields, and a `vault://` credential needs a non-empty `<provider>/<path>`; an authenticated custom connection requires HTTP TLS and effective gRPC TLS (explicit gRPC setting, else HTTP). Errors render as Carbon `invalid`/`invalidText` on the field (for the TLS rule, an error `InlineNotification` with `role="alert"` plus `invalid` on the controls involved) once the user has edited the field or tried to open the tearsheet. While any error exists, the "Add / Edit feature mappings" action does not open the tearsheet or call enrichment; it shows the errors and moves keyboard focus to the first invalid field. In the tearsheet, an invalid new collection name blocks Save through the existing `submitted` gating, with the provider's own message.

**Tearsheet behavior.** The collection-name rule and placeholder come from the provider map instead of the generic `NEW_RESOURCE_NAME_RE`. Distance is selected from the metadata `valid_values` (fallback: the provider defaults) and is read-only for an existing collection that reports a stored metric; there is no engine control. The BM25 checkbox is capability-driven and **eligibility-driven**: it appears when `supportsSparse` is true and either the resource is supported or the backend reports `is_docpipe_supported_resource.sparse_eligible` (D10). The distinction matters because a keyword-searchable collection with no indexed vector is unsupported while the flag is off; hiding the checkbox on `supported === false` would make the only control that can make it supported unreachable. For an eligible-but-unsupported Weaviate collection the checkbox is shown together with the unsupported reason, and checking it re-runs enrichment, which then reports the collection as supported. A collection that is unsupported and not eligible shows only the unsupported state. Its checked state initializes from the saved `add_sparse_vector` on every open (so reopening preserves it), and toggling re-runs enrichment with the new flag (existing behavior). OpenSearch and Milvus never set `sparse_eligible`, so for them the rule reduces to the existing "supported only" behavior.

**Enrichment failure.** The enrichment helper keeps the five keys but the backend now marks an unreachable or rejecting deployment with `is_docpipe_supported_resource.error` (D10). The tearsheet shows that message through the existing error state, distinct from the empty-collections state (a reachable deployment with no collections has no `error`), and does not treat the failed node as an unsupported collection. The `EnrichmentResult` type gains optional `error` and `sparse_eligible` fields on `is_docpipe_supported_resource`. The existing cancellation token, the loading skeleton, the thrown-error message (`loadError`), and the unsupported-resource empty state are preserved.

**Interaction to API/state mapping.** There is no Redux action and no new BFF route; all state is the Elyra property controller and one existing API call.

| Interaction | Effect |
|---|---|
| Select provider | `controller.updatePropertyValue` for `provider`, then `provider_config = {}` and `feature_mappings = []` (existing) |
| Edit a connection/auth field | `updateProviderConfigField` → `controller.updatePropertyValue({ name: 'provider_config' })` |
| Switch connection type or auth method | one atomic `provider_config` write with inactive keys removed |
| Edit Advanced JSON | parsed, managed keys preserved, written only when valid JSON (existing) |
| Open feature mappings | validate (config + Advanced JSON) → open tearsheet → `enrichFlowFeaturesForNode(...)` → `POST /api/v1/validation/enrich_flow_features` through the existing API client |
| Select a different collection / toggle BM25 | re-run `enrichFlowFeaturesForNode` with the resource name stripped or set, superseded responses discarded |
| Save in tearsheet | `provider_config` merged with `collection_name` and `distance_metric`; `feature_mappings`; top-level `add_sparse_vector` |

**Strings and styling.** New strings are defined in a colocated `VectorDB.messages.ts` with `defineMessages` and ids in the existing `src.components.<path>.<key>` form, rendered with `useIntl`. The catalogue is regenerated with `npm run extract:messages` (never hand-edited). Existing hardcoded strings in the panel are not migrated. New styling, if any, goes in `VectorDB.module.scss` using `var(--cds-*)` tokens with no hard-coded colors or pixel literals.

**Accessibility.** Every control has a visible label; credential inputs are masked (`VaultInput` direct mode uses `PasswordInput`, with its visibility toggle reachable by keyboard, and its Vault toggle is a labelled switch); every validation message is attached to its field (`invalid` + `invalidText`, which sets `aria-invalid` and `aria-describedby`) and the TLS rule alert has `role="alert"`; tab order follows visual order; a blocked open moves focus to the first invalid field; dropdowns operate with arrow keys and Enter; the tearsheet keeps Carbon's focus trap and Escape-to-close.

**Frontend tests** (`frontend/tests/unit/components/PropertiesPanel/CustomPanels/VectorDB/`): metadata-driven and fallback provider lists; Weaviate resolves to its own configuration rather than the OpenSearch fallback; custom/cloud switching and credential cleanup; gRPC inheritance and explicit overrides; required-field and TLS gating (tearsheet does not open, enrichment not called, focus on first invalid field); valid and invalid collection names (the same example table as the backend spec scenario); sparse toggle, saved-state reopening, and re-enrichment, **including a collection that is keyword-searchable and unsupported with a saved `false` flag (checkbox shown, checking it re-enriches and the collection becomes supported) and one that is unsupported and not eligible (no checkbox)**; Advanced JSON preservation and the saved `provider_config` shape, **including `index_parameters` staying visible and editable in Advanced JSON, round-tripping through save, and being absent from the enrichment payload**; loading, error, empty-collections, and unsupported states, **with an unreachable Weaviate (`error` present) tested separately from a reachable one with no collections**; keyboard interaction and focus; OpenSearch/Milvus regression. The vacuous "renders provider dropdown" test (it looks up an id that does not exist and falls back to `document.body`) is replaced with assertions on `vectordb-provider-dropdown` and its options; provider-switch tests assert the expected option is present and the interaction took effect.

### D17. Connection release after flow validation

`FlowValidator` builds the operator with `validating_flow=True`, calls `operator.validate()`, and drops the instance. No transform runs, so the `finally` in `VectorDBOperator.transform` never closes the adapter, and a Weaviate client opened in `__init__` would stay open (the SDK requires an explicit `close()`).

- **Operator change (provider-agnostic).** `VectorDBOperator.validate` is wrapped in `try`/`finally`. When `self.validating_flow` is true, the `finally` calls `self.adapter.close()`, logging and swallowing any exception from `close()` exactly as `transform` does. When `validating_flow` is false (a normal run, where `validate()` is called on an operator that goes on to `transform()`), `validate()` does not close the adapter, so the connection stays available for the run. The port's default `close()` is a no-op, so OpenSearch is unaffected and Milvus gains a release it lacked.
- **Why not the executor or the validator.** `FlowValidator` is shared by every operator and has no notion of an adapter. `PythonOperatorExecutor.release()` already calls `op.cleanup()`, but that path covers executed operators, not the validator's throwaway instance. Putting the release in the operator that owns the adapter keeps ownership with the code that opened the connection.
- **Failure after connecting.** `WeaviateClient.connect` closes the client before raising when `is_ready()` is false (D4). `WeaviateAdapter.__init__` also wraps every step after `connect` (building the index manager and batch processor) so that an exception closes the client before it propagates. No construction path leaves an open connection behind.
- **Scope.** This does not make validation lazy: the connection still opens in `__init__` and validation still requires a reachable server (D15, Risks). Only the release is added.
- **Tests.** `test_vectordb_operator.py`: with `validating_flow=True`, `close` is called once after a successful `validate()` and once when `validate()` raises, and a `close()` that raises does not mask the result; with `validating_flow` unset, `validate()` does not call `close` and `transform()` still calls it once. `test_weaviate_client.py`: a not-ready response closes the client before raising; a second `close()` is a no-op. `test_weaviate_adapter.py`: an exception raised after `connect` (patched index-manager construction) closes the client before propagating; building the adapter and calling `close()` twice closes the SDK client once. Real-server scenario I-13 (D12) checks that validation leaves no connection open.

### D18. Flow validation with Vault credentials

`FlowValidator._sanitize_vault_refs_for_validation` replaces every `vault://` value with the string `__vault_placeholder__` before it builds the operator for validation, because validation must not read secrets. The OpenSearch client connects lazily, so the placeholder never reaches a server. Weaviate connects in `__init__`, so without a rule the validator would send the placeholder to the server as a credential, the server would reject it, and an otherwise valid Vault-configured flow would fail validation.

- **Rule.** `WeaviateAdapter.__init__` runs every configuration check (D7 order, including the TLS rule) and then, only if `validating_flow` is true and a credential in use equals the validation placeholder, skips `WeaviateClient.connect` and the index manager and batch processor built on it, logs one message that the connection is deferred because a Vault credential is not available during validation, and leaves them unset. `close()` on an adapter without a client is a no-op.
- **Both conditions are required.** `VectorDBOperator.__init__` adds `validating_flow` to `adapter_config` next to the other operator-injected keys (D3); the adapter reads it, and the other adapters ignore it. A credential that happens to equal the placeholder text in a real run still connects, so a user-typed value cannot silently disable the connection.
- **Why this is safe.** A real run never sees the placeholder: the executor resolves Vault references first, and an unregistered provider or a failed resolution raises before the adapter is built (D3). In validation the operator never calls `transform()`, so an adapter that holds no client is never asked to write.
- **Shared constant.** The placeholder is defined once, as a constant used by both `FlowValidator` and the Weaviate adapter, so the two cannot drift. A test builds the operator through the real `FlowValidator` path and fails if the strings diverge.
- **Cost.** Validation of such a flow no longer checks reachability or credentials; the first run does. Flows without Vault credentials validate exactly as before, including the reachability requirement noted in Risks.
- **Tests.** `test_weaviate_adapter.py`: a placeholder credential with `validating_flow` set constructs the adapter without calling `connect`, the same credential without it connects, configuration errors and the TLS rule still raise, and `close()` is a no-op. A `FlowValidator`-level test: a `vectordb` node with a Vault API key over TLS validates with the client patched and `connect` never called, one over plaintext still fails the TLS rule, and the same node with a literal credential connects as before.

## Risks / Trade-offs

- **[grpcio cap forces a downgrade from 1.84.0 to 1.78.0, and authlib moves with it]** → Gated in task 1.1 (D11) with advisory checks on every changed package and the existing Milvus, OpenSearch, and telemetry suites. The pin and the trial results are re-checked after any rebase. A maintainer decision, not an override, resolves any failure.
- **[API released without the UI]** → The panel would list `weaviate` and render OpenSearch fields. Mitigated by shipping both stacked PRs in one release and merging the UI first if ordering matters (proposal, Rollout).
- **[Stale lookup depends on `pk` being `field`-tokenized]** → Keyset paging (D9) has no 10,000-chunk limit, but it returns nothing after the first page under `word` tokenization. The adapter therefore creates `pk` with `field` tokenization and rejects an existing collection whose `pk` is `word`-tokenized (D8 step 5). A collection created by hand with a different `pk` tokenization must be recreated; the error says so.
- **[Dimension is only checkable by sampling]** → An empty collection skips the check, so the first insert fixes the dimension. A later wrong dimension then fails per object, which is still reported per chunk (D6).
- **[UUIDv5 upsert relies on replace-on-existing-UUID batch semantics]** → Integration test I-3 asserts it against the pinned server version. If the semantics differed, the stale-cleanup path would still prevent duplicates, but in-place updates would surface as per-object errors.
- **[`word` vs `field` tokenization chosen by rule, not configurable]** → The rule covers identity fields. A per-property override can be added later without changing the specs.
- **[Plaintext defaults could expose credentials]** → `secure` defaults to false so unauthenticated local servers work, but any `auth_type` other than `none` is rejected on a plaintext self-hosted connection, in the config validator and again in `WeaviateClient` (which also covers enrichment). `cloud` always uses TLS. The UI blocks the same combination before submission.
- **[Secrets echoed by upstream errors]** → The factory and operator interpolate the original exception text into their wrapped messages and the Weaviate client can echo URLs and headers. Redaction at the source (D4), `from None` on Pydantic errors, and secret-safety tests across the adapter, batch processor, factory, and operator wrapping contain this.
- **[All-caps literal credentials silently substituted]** → A shared-helper behavior (D3). Documented; an explicit `$VAR` reference is the recommended form. The helper is not changed here.
- **[Connecting in `__init__` makes flow validation require a reachable server]** → This matches existing adapters. Configuration errors are raised before connecting, so most mistakes surface without a server, but they surface as initialization failures with the wrapped message (D15), not as per-field validation messages.
- **[Frontend duplicates the collection-name rule]** → The generic metadata converter cannot publish a `pattern`. The backend spec and the frontend test share one example table so a divergence fails a test.
- **[Users expect ACL enforcement with Weaviate]** → The dropped mapping and the unenforced-ACL warning both appear in the run log, the README's Troubleshooting section states that ACL is OpenSearch-only, and the proposal lists ACL as a non-goal.
- **[Sparse-only runs with memory-mapped chunks]** → Existing operator limitation, independent of the provider (D14). Stated in the spec, README, and I-10, which uses in-memory chunks.
- **[BM25 parameters are fixed]** → They are Weaviate's own defaults (k1 = 1.2, b = 0.75). Exposing them would be an additive change later.
- **[`add_sparse_vector` set only in `provider_config`]** → The README states that the top-level flag is authoritative (D14 precedence).
- **[`schema_template_path` silently has no effect]** → One warning names the ignored option, and the README documents it as OpenSearch-only.
- **[Server-default quantization may be lossy (`DEFAULT_QUANTIZATION`)]** → Documented in the README. Configuring quantization is a non-goal.
- **[Two lockfiles (root and slim)]** → Both are regenerated in the same commit, and task 1.2 verifies `uv lock --check` in each.
- **[Real-server suite not in CI]** → Consistent with the other vector databases (none run integration tests in CI). Regressions in real-server behavior are caught by the manual pre-release run documented in the README; the unit suite in CI covers everything that can be mocked.

## Migration Plan

Additive only. Existing flows are unaffected. Deploying requires the regenerated environment (`uv pip install -e ".[dev]"`). Rollback is reverting the change; no stored data or schema migrations are involved, and Weaviate collections created by the adapter remain usable by any Weaviate client. Flows saved from the UI with `provider: "weaviate"` stop being editable in the panel if the UI change is rolled back, but still execute.

## Open Questions

- Minimum Weaviate server version to document. The design uses self-provided named vectors and `insert_many`, both long supported. Task 6.6 records the compatibility floor for the pinned client from its release notes in the README, without changing behavior.
- Whether to move to server-side batching (`batch.stream()`, server ≥1.36) in a follow-up once throughput data from the integration environment is available.
- Whether to add a CI job for the real-server suites of all vector databases (not only Weaviate). Out of scope here; it would be a separate change covering OpenSearch, Milvus, and Weaviate together.
