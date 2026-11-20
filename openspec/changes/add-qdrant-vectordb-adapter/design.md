# Design

## Context

**Current shape of the VectorDB operator.** `VectorDBOperator` builds one adapter through `VectorStoreFactory.create(provider, **provider_config)` and drives it through `VectorStorePort`:

1. `index_exists()`, then `create_index(dimension_mapping=...)` or `validate_existing_schema(dimension_mapping=...)`.
2. `get_chunk_ids_for_documents(file_ids)` and `delete_documents_by_ids(stale)` for stale-chunk cleanup.
3. `index_documents([(pk, document), ...])` and `refresh_index()`.
4. `close()`, in the `finally` block of `transform`.

Feature mappings (`[{"feature_name", "mapped_column_name"}]`) are applied by the adapter. Each chunk document is a shallow copy of the row with every vector column replaced by that chunk's `list[float]`, and the chunk text under the key `content`. The operator generates each chunk key with `adapter.generate_chunk_pk(file_id=..., chunk_index=..., chunk_content=...)`, where `file_id` is the row's `id` value, and maps keys back to documents to attribute failures.

**Constraints observed in the current code:**

- **Failure shape.** The operator parses only `{"index": {"_id": <chunk pk>, "error": {"reason": str}}}` (`vectordb_operator.py`). The Milvus and OpenSearch adapters return other shapes, so their chunk failures are recorded as one document named `unknown`. The Weaviate design (D6) emits the parsed shape; Qdrant does the same.
- **Stale-chunk lookup.** Milvus finds a file's chunks with a primary-key prefix filter (`pk like "<sha3_512(id)>_%"`). The operator passes `id` values to `get_chunk_ids_for_documents` and expects `dict[str, set[str]]` keyed by those values.
- **Sparse mode.** `add_sparse_vector` is read from the operator's top level. It allows zero dense columns, changes the default mappings (`sparse_embeddings`, and `content` to `text`), and is forwarded to the adapter. The operator forwards it only when the top level sets it, so a value set only inside `provider_config` reaches the adapter while the operator itself keeps sparse mode off. No upstream operator produces sparse vectors; `sparse_embeddings` is declared by the vectordb operator itself and nothing fills it.
- **Injected keys.** The operator adds `available_features`, `feature_mappings`, `add_sparse_vector` (when set), and `schema_template_path` (when set) to the adapter config. `MilvusAdapter` reads them from the raw config dict rather than from `MilvusConfig`.
- **Provider lists.** `provider` valid values come from the factory registry, but the operator descriptions hard-code "opensearch, milvus", `_get_vectordb_provider_schemas()` is a hand-written map, `VectorDBMetadataFetcher` routes with a hard-coded `if`, and the panel falls back to OpenSearch for an unknown provider.
- **Secrets.** `OperatorUtils._to_docpipe` marks a field sensitive when its key is in `SENSITIVE_FIELD_NAMES` (which includes `api_key`) or its schema carries `sensitive: True`. `resolve_env_var` resolves `$VAR`, `${VAR}`, and `${VAR:default}`, so a reference with an empty default resolves to an empty string when the variable is unset. `vault://` references are resolved by `PythonOperatorExecutor._resolve_operator_params` before the operator is built; during flow validation `FlowValidator` replaces them with `__vault_placeholder__`.

**Upstream facts that shape the approach.** All observed against real `qdrant/qdrant` containers with `qdrant-client` 1.20.0 (released 2026-10-22, Apache-2.0). Server 1.20.0 is the reference; older servers were checked where the behavior differs.

- **Point IDs** must be unsigned integers or UUIDs. A string such as `abc_chunk_1` is rejected (`value abc_chunk_1 is not a valid point ID, valid values are either an unsigned integer or a UUID`). UUID spellings are normalized. Upserting an existing ID replaces the whole point, including payload fields and vectors that the new point omits.
- **Collection names** are case-sensitive, 1 to 255 characters, and must not contain `/`, `\`, `:`, `*`, or `?`. The client also rejects `.` and `..`. Spaces, dots, hyphens, and non-ASCII letters are accepted. Creating an existing collection returns 409.
- **Named vectors** are read back from `config.params.vectors` as `dict[str, VectorParams]`; a single unnamed vector reads back as one `VectorParams`, and a sparse-only collection as `{}`. A point may carry a subset of the named vectors. Cosine vectors are stored normalized.
- **Batches are not atomic.** On 1.20.0 a wrong dimension rejects the whole batch, but an unknown vector name, an unknown sparse name, or a sparse value sent to a dense field returns 400 after writing an unpredictable subset (1,000 good points and 1 bad one left 749 points over REST and 444 over gRPC). On 1.16.0 and older, a wrong dimension also leaves partial writes. gRPC stores `NaN` vectors that REST rejects.
- **Prefix matching** (`MatchPrefix`, keyword index with `prefix: true`) exists from server 1.19.0 and client 1.19. On 1.16.0 and 1.18.3 the server accepts `prefix: true` but builds the index without it. `MatchText` is not a whole-value or prefix match, and its meaning changed between 1.16 and 1.19. An exact `MatchValue` or `MatchAny` on a keyword field works on every version from 1.12.6.
- **Scroll paging** with `next_page_offset` returns every matching point with no result window (12,000 of 30,000 points at page sizes 1,000 to 50,000).
- **Strict mode** (`unindexed_filtering_retrieve`, `unindexed_filtering_update`) exists from 1.12.6 and is off by default on self-hosted servers. When on, filters need a matching payload index; deletes by ID are always allowed. Strict mode also has other limits, among them `upsert_max_batchsize`, `max_query_limit`, `filter_max_conditions`, `condition_max_size`, `read_rate_limit`, and `write_rate_limit`.
- **Payloads are schemaless.** One field can hold an integer in one point and a string in another; an integer payload index skips the values that are not integers.
- **Server-side BM25.** A `models.Document(text=..., model="qdrant/bm25")` sent for a sparse vector is turned into BM25 term weights by the server, in upsert and query, over REST and gRPC, with no FastEmbed and no Cloud. It works on 1.15.3, 1.16.0, and 1.20.0. On 1.15.1 and 1.13.6 it fails with 500 `InferenceService is not initialized`. The IDF modifier must be set on the sparse vector explicitly; without it the server accepts the documents silently. Unknown BM25 options are accepted silently.
- **Authentication.** Without a key, protected endpoints return 401 `Must provide an API key or an Authorization bearer token`. `/`, `/healthz`, `/readyz`, and `/livez` need no key, so a health probe does not prove the key works; `get_collections` does. The client warns `Api key is used with an insecure connection.` when a key is used over HTTP. An `http://` URL stays HTTP even with `https=True`. A `url` without a port connects to the client's `port` argument (default 6333); `port=None` uses the scheme's default port. The key never appeared in any exception text, REST or gRPC.
- **Version check.** By default the client checks the server version in a background thread and only warns, asynchronously, when the major versions differ or the minor versions differ by more than one.
- **Errors.** REST raises `qdrant_client.http.exceptions.UnexpectedResponse` (with `status_code` and the server message); gRPC raises `grpc.RpcError`. A local-mode client raises `ValueError` instead.
- **Dependency.** `qdrant-client` 1.20.0 requires `grpcio>=1.41.0`, `httpx[http2]>=0.20.0`, `protobuf>=3.20.0`, `pydantic>=1.10.8` (excluding early 2.x), `urllib3<3,>=1.26.14`, `portalocker<5.0,>=2.7.0`, and `numpy>=1.26` on Python 3.12. Everything except `portalocker` is already in the lockfiles at compatible versions.

## Goals / Non-Goals

**Goals:**

- `provider: "qdrant"` works end to end: configuration, connection, collection lifecycle, idempotent writes, stale-chunk cleanup, flow enrichment, and the panel.
- Behavior that depends on a server version is either portable across supported versions or checked at initialization.
- A failed write never hides which chunks failed, never leaves a collection the operator cannot write to again, and, as far as the server can still be reached, never leaves part of a document searchable (D10).
- A run never silently removes data that the collection holds and the run does not write (D9).
- Reuse the Weaviate change's provider-agnostic decisions instead of inventing parallel ones.

**Non-Goals (design level, in addition to the proposal's):**

- Supporting servers older than 1.15.3 in sparse mode, or prefix-based lookups on servers older than 1.19.
- Making the existing adapters' failure shapes match the operator.
- A shared client or redaction module across providers. Shared helpers come only from `utils/operators/vectordb_utils.py`.

## Decisions

### D1. Package layout and DDD boundaries

A new package `adapters/outbound/qdrant/` whose `__init__.py` exports nothing, as for Weaviate:

| File | Responsibility |
|---|---|
| `config.py` | `QdrantConfig` Pydantic model and every check that runs before connecting. Does not import `qdrant_client`. |
| `client.py` | Builds `QdrantClient`, resolves credentials, checks the HTTPS rule again, runs the readiness and version check, redacts errors, and closes. |
| `index_manager.py` | Collection creation and validation, payload indexes. |
| `batch_processor.py` | Point preparation and pre-validation, batched upserts with retries and the per-point resend, removal of failed documents, stale-key lookup, deletes, count, and queries. |
| `adapter.py` | `QdrantAdapter(VectorStorePort)`: wires the parts and enforces the initialization order. |
| `resource_metadata.py` | `QdrantResourceMetadata` for flow enrichment. |

Port delegation follows the same shape as `MilvusAdapter`: `index_exists`, `create_index`, and `validate_existing_schema` go to the index manager; `index_documents`, `get_chunk_ids_for_documents`, `delete_documents_by_ids`, `get_document_count`, and `query_by_doc_names` go to the batch processor; `detect_vector_dimension` and `detect_all_vector_dimensions` use the shared helpers in `vectordb_utils.py`; `generate_chunk_pk` uses `generate_positional_pk`; `refresh_index` is a no-op, because a write with `wait=True` is visible when it returns; `close` goes to the client. `metadata_fetcher.py` imports `resource_metadata` lazily. Nothing in `domain/` or `ports/` imports from the adapter.

### D2. Lazy registration

`VectorStoreFactory.register_lazy("qdrant", "<package>.adapter", "QdrantAdapter")` sits next to the Milvus entry, so a metadata request does not import `qdrant_client`, `grpc`, or `httpx`. `_get_vectordb_provider_schemas()` gets a `qdrant` entry built from `QdrantConfig`. `config.py` must not import `qdrant_client`; a test imports `config.py` with `qdrant_client` blocked in `sys.modules`. The test takes the module and the blocked package as parameters, so it can later cover the other providers' config modules; extending it to them is outside this change.

### D3. Configuration fields

`QdrantConfig(BaseModel, extra="ignore")` declares only the user-facing fields below, so the schema published in operator metadata lists only those.

- **Injected keys and the mapping checks.** The keys the operator injects (`available_features`, `feature_mappings`, `add_sparse_vector`, `schema_template_path`) are not model fields; `extra="ignore"` drops them from the model, and the adapter reads them from the raw config dict, as `MilvusAdapter` does. The adapter passes them to `validate_mappings(feature_mappings, available_features, add_sparse_vector)`, a plain function in `config.py` that runs the mapping rules of D6, D7, and D13 right after the model is built and before connecting. Keeping them off the model keeps them out of the published schema.
- **Flow validation flag.** The operator does not pass `validating_flow` to adapters today; Weaviate design D18 adds that, and task 5.1 checks for it.

| Field | Type | Default | Notes |
|---|---|---|---|
| `collection_name` | str | required | Server naming rule, checked before connecting (below). |
| `url` | str \| None | None | Full URL, for example a Qdrant Cloud cluster. Its scheme decides HTTP or HTTPS. Without a port, `port` is used. |
| `host` | str | `"localhost"` | Used when `url` is not set. |
| `port` | int | 6333 | REST port; 1-65535. Also used for a `url` without a port. |
| `grpc_port` | int | 6334 | 1-65535. |
| `prefer_grpc` | bool | False | REST by default; gRPC is opt-in. |
| `https` | bool | False | Used with `host`. Ignored with `url`, whose scheme decides. |
| `api_key` | str \| None | None | Sensitive. Literal, `$VAR`, or `${VAR}`. Empty means no key. |
| `timeout` | int | 30 | Seconds, at least 1. The client's REST default (5 seconds) is too short for large upserts. |
| `batch_size` | int | 100 | Points per upsert request, 1-1000. |
| `distance_metric` | Literal[`cosine`, `dot`, `euclid`, `manhattan`] | `cosine` | Mapped to Qdrant's `Cosine`, `Dot`, `Euclid`, `Manhattan`. |
| `index_parameters` | dict | `{}` | HNSW settings for new dense vectors (D8). |

- **`url` and a non-default `host` are mutually exclusive.** The client raises `Only one of <location>, <url>, <host> or <path> should be specified.` when both reach it; the config reports the conflict by field name before that.
- **`url` without a port.** A URL such as `https://xyz.cloud.qdrant.io` connects to `port` (default 6333), which is where Qdrant Cloud serves REST. This is the client's own behavior; the provider passes `port` explicitly, so it does not depend on a client default. A server behind a proxy on the scheme's default port needs that port in the URL, for example `https://qdrant.example.com:443`.
- **Collection name rule.** 1 to 255 characters; none of `/`, `\`, `:`, `*`, `?`; no control characters; not `.` or `..`. This is the server's own rule plus one addition: the server also accepts control characters such as a tab, but such a name cannot be typed or shown reliably, so the provider rejects it. Any other existing collection can be used. The rule is enforced by the backend; it is not published in metadata.
- **Credentials.** `api_key` is checked with `resolve_env_var` in a model validator and the result is discarded; the client resolves it again at connect time, so resolved values are never stored on the model. An unset `$VAR` fails with a message that names the variable and no value. As in the Weaviate design, a literal made only of upper-case letters and underscores is substituted when an environment variable of that name exists, because that is the shared resolver's behavior; the docs recommend the explicit `$VAR` form.
- **Empty key.** An `api_key` that is empty, or a reference that resolves to an empty value (`${QDRANT_API_KEY:}` with the variable unset, or a variable set to an empty string), means no key: none is sent, and the HTTPS rule does not apply. A reference that resolves to an empty value logs one warning naming `api_key` and the variable, because an empty default can hide a missing secret. A server that requires a key then rejects the readiness call (D4), so the run fails at initialization.
- **The API key requires HTTPS** (D4). This proposal has no opt-in override; whether to add one for internal networks is an open question.
- **Error messages** are built from each Pydantic error's location and message only, never its input value, and re-raised `from None`. If the Weaviate change's configuration-error formatter exists by then, it is reused.
- **Constants.** Add `OperatorConstants.VectorDB.QDRANT = "qdrant"` and the new config keys; reuse existing constants for shared keys.

*Alternative:* a `connection_type` field with `custom` and `cloud`, as for Weaviate. Rejected because Qdrant Cloud needs no separate SDK entry point: a cluster is an `https://` URL plus an API key, so a URL field covers it.

### D4. Connection, authentication, and error hygiene

- **HTTPS rule.** When a non-empty `api_key` is set (D3), the connection must be HTTPS: with `url`, its scheme must be `https`; with `host`, `https` must be true. Otherwise initialization fails before connecting, with a message stating that an API key requires an HTTPS connection. The client repeats the check, because flow enrichment builds a client without the adapter.
- **Client construction.** `QdrantClient(url=... | host=..., port, grpc_port, prefer_grpc, https, api_key, timeout, check_compatibility=False)`, with `port` always passed (D3) and `api_key` omitted when it is empty. The background version check is disabled because its warning is asynchronous and arrives after construction, attributed to whichever client happens to be logging; D5 replaces it with an explicit check.
- **Readiness.** The first network call is `get_collections()`, an authenticated call, so a wrong key fails at initialization rather than on the first write. A code comment at the call records why it is not a health endpoint: `/`, `/healthz`, `/readyz`, and `/livez` need no key, so they would not prove the key works. A failure raises an error naming Qdrant, the target address (URL or host and port), and the redacted cause. The client is closed before raising.
- **Redaction.** A redaction helper in `client.py` replaces the resolved API key, and any `api-key` or `Authorization` header text, with `***` in every raised message, log record, failed-item reason, and enrichment `error`. The client never echoed the key in the tests, so this is defense in depth. It is done in the client because the factory and the operator copy the original error text into their own messages.
- **Error types.** Errors are recognized as `UnexpectedResponse` (REST) or `grpc.RpcError` (gRPC); both are handled wherever the provider inspects a status.
- **Logs** use `%s` formatting and carry the target address and whether a key is set, never the key.
- **Close.** `close()` is idempotent. As in the Weaviate design, the connection is closed in three places: the `finally` block of `transform`, the `finally` block of the enrichment fetch, and `validate` under flow validation (D16).

### D5. Server version check

Right after readiness, the client reads the server version from `info()` (`GET /`).

- **Sparse mode** requires server 1.15.3 or later, the first version observed to run `qdrant/bm25` inference; 1.15.1 fails every BM25 write with 500, and 1.15.2 was not tested. On an older server, initialization fails with a message naming the server version and the minimum.
- **Dense mode** has no minimum beyond what the pinned client supports. The provider's own checks (D10, D14) are written to be correct on servers that write partial batches and have no prefix filter.
- **Client window.** When the server's major version differs from the client's, or the minor versions differ by more than one, the provider logs one warning naming both versions, synchronously, instead of the client's asynchronous one.

### D6. Point identity and the lookup chain

Milvus uses one string as both the point ID and the lookup key: the chunk key is the primary key, and a file's chunks are found with a prefix filter on it. Qdrant allows neither: point IDs must be integers or UUIDs, and prefix filters are not portable. The provider therefore splits identity into four linked parts. Together they are the decision the rest of the provider depends on, and none of them changes once released:

1. **Chunk key.** `generate_chunk_pk` returns `generate_positional_pk(file_id=..., chunk_index=...)`: `{sha3_512(file_id)}_chunk_{index}`, the OpenSearch format that the Weaviate design also adopts. The Milvus content-hash key is not used, because it changes a chunk's ID whenever its text changes.
2. **Point ID.** `uuid.uuid5(uuid.NAMESPACE_URL, "docpipe:qdrant:" + chunk_key)`. A unit test pins one example: the key `example_chunk_0` gives `79a2b24e-4ff8-5ec4-b8f1-77ac5d83102b`. The same key always maps to the same point, so re-ingest replaces chunks in place, and retries and resends are idempotent. Deletes by key convert each key to its point ID.
3. **`pk` payload field.** The chunk key verbatim, so failed items, the stale-key lookup result, and the operator's stale-key diff all use the operator's own key. The provider never filters on `pk`.
4. **`pk_file` payload field with a keyword index.** The file part of the key (the text before `_chunk_`, which is `sha3_512(id)`), indexed when the collection is created (D8). The stale-chunk lookup (D14) and the removal of failed documents (D10) are exact matches on it.

**Under strict mode**, filters need a matching payload index, and deletes by ID are always allowed. The chain needs nothing more: the provider's only filters are exact matches on `pk_file` and on the field mapped from `name`, both indexed, and deletes by key go by point ID. Strict mode's other limits are covered in D14.

- **Mapping rules, before connecting.** The primary feature must be mapped to `pk`. Initialization fails when it is mapped elsewhere, when another feature is mapped to `pk`, or when any feature is mapped to `pk_file`.
- **Document identity** when `id` is missing follows the operator requirement "Document identity" (Weaviate design D5); see task 1.3.

### D7. Payload mapping and names

- **Values.** Only mapped features are written, as the other adapters do. The feature types of `OPERATOR_TYPE_PATTERN` map as follows:

  | Feature type | Payload value |
  |---|---|
  | `string`, `enum`, `crn`, `date`, `time`, `timestamp` | string |
  | `int8`, `int16`, `int32`, `int64` | integer |
  | `float`, `double`, `sfloat` | float |
  | `bool`, `boolean` | boolean |
  | `json` | native JSON value; unlike Weaviate, not serialized to text, because Qdrant payloads support nested objects |
  | `list` | JSON array |
  | `vector`, `vector_sparse` | not payload: named vectors (D8, D13) |

  Arrays are converted with `tolist()`; `None` values are omitted. A type outside the table is stored as a string, with one warning naming the feature.
- **ACL feature.** A mapped `allowed_users` feature is stored as a JSON array of strings, the value the ACL operator produces (its declared feature type is `string`, but the column holds a list of user identities), with a keyword payload index (D8), so an application that queries the collection can filter on it. docpipe enforces ACLs only through its OpenSearch documents API, so it does not enforce this field for Qdrant; the provider logs one warning saying so, and the docs say that the querying application must apply the filter. An unmapped `allowed_users` feature is not written, like any other unmapped feature, with one warning that the ACL is neither stored nor enforced.
- **Content.** The chunk text is stored under the mapped content name (default `text`).
- **Names.** A mapped payload name must be non-empty and must not contain `.`, `[`, or `]`, because Qdrant filter keys use them for nested paths and array elements; such a name could be written but not filtered reliably. The names `pk` and `pk_file` are reserved (D6). These checks run before connecting.
- **Vector names.** A dense vector is named by its column's mapped name. Two vector columns mapped to the same name, or a vector name equal to a payload name, fail before connecting.

### D8. Collection creation

- **Creation.** `create_collection` with an explicit `vectors_config` dict: one `VectorParams(size=<detected dimension>, distance=<distance_metric>, hnsw_config=<index_parameters>)` per detected dense column. In sparse mode it adds `sparse_vectors_config={<sparse name>: SparseVectorParams(modifier=Modifier.IDF)}` (D13). A sparse-only run creates the sparse vector only.
- **`index_parameters`.** Accepted keys are the HNSW settings `m`, `ef_construct`, `full_scan_threshold`, `max_indexing_threads`, `payload_m` (non-negative integers), and `on_disk` (boolean). Any other key, or a value of the wrong type, fails before connecting with a message naming the key. The keys are listed in `config.py`, which must not import `qdrant_client` (D2).
- **Payload indexes.** Right after creation, the provider creates keyword payload indexes on `pk`, `pk_file`, the payload names mapped from `id` and `name`, and the name mapped from `allowed_users` when it is mapped (D7). The provider filters on `pk_file` and the name field (D10, D14); the other indexed fields are the ones applications are most likely to filter on. Every field the provider filters on is indexed, so it works with strict mode's unindexed-filter settings (D6). It reads `payload_schema` back and fails if an index is missing, because the server can accept an index request and build something else (observed for `prefix: true` on old servers).
- **Concurrent creation.** Micro-batching can run several workers at once, and `index_exists()` followed by `create_index()` is not atomic. When creation returns 409, the provider validates the existing collection (D9) instead of failing.

*Alternative:* let the first upsert create nothing and rely on schemaless payloads. Rejected because vectors need an explicit configuration and the identity fields need indexes before the first filter.

### D9. Existing collection validation

Every mismatch is collected into one error (400), so the user sees all problems at once. Nothing is changed when a check fails.

- **Dense vectors.** The collection must use named vectors; a collection with a single unnamed vector is rejected with a message stating that only named vectors are supported. Each run vector must exist by name with the run's dimension and the configured distance; a missing vector, a different dimension, or a different distance is reported with both values. Qdrant stores the dimension in the collection configuration, so the check does not depend on the collection holding points.
- **Dense run on a sparse-only collection** fails with a message stating that the collection has no dense vector.
- **Sparse mode.** The mapped sparse vector must exist with the IDF modifier; a missing vector or a missing modifier is reported.
- **Vectors the run would not populate.** An upsert replaces the whole point, so a point written without one of the collection's vectors loses that vector, and hybrid search silently becomes dense-only for every re-ingested document. Validation therefore fails when the collection has a named dense vector that no run vector column is mapped to, or a sparse vector while sparse mode is off. A sparse-only run on a collection with dense vectors fails for the same reason. The message names each such vector and states that writing would remove it from every re-ingested point.
- **Payload fields are not checked.** Payloads are schemaless, so a mapping change that stops writing a field cannot be detected from the collection; re-ingested points lose that field. The docs state this (Risks).
- **Identity indexes.** An existing index on `pk`, `pk_file`, the `id` or `name` field, or the mapped `allowed_users` field must be of type keyword. An index of another type is reported, and the message tells the user to recreate the collection or use a new name, because changing an index type in place silently replaces it.
- **Additions.** Only when every check passed, missing payload indexes from D8 are created, then read back as in D8.

### D10. Write path

- **Preparation.** Each document becomes a `PointStruct(id=<uuid5>, vector={...}, payload={...})` with the identity fields, mapped payload, and named vectors.
- **Pre-validation, before sending.** Every dense vector must have the collection's dimension for its name and contain only finite numbers, and every vector name must exist in the collection. A point that fails is reported as failed with a reason naming the vector and the problem, and is not sent. This matters because a rejected batch can be partly written, and gRPC stores `NaN`.
- **Batches.** Points are sent with `upsert(..., wait=True)` in batches of at most `batch_size` points and about 3 MB, measured with `calculate_batch_size_bytes` on the plain payload and vector dicts (it serializes with `json.dumps`, so it is not given `PointStruct` or `Document` objects), well under the server's 32 MiB REST body limit.
- **Retries.** Every upsert request, a batch or one point of a resend, is retried when it fails transiently: a connection error, a timeout, HTTP 429, 502, 503, or 504, or gRPC `UNAVAILABLE`, `DEADLINE_EXCEEDED`, or `RESOURCE_EXHAUSTED`. There are at most 3 attempts in total, with exponential backoff and jitter (about 1 and then 2 seconds between attempts). Retrying is safe because point IDs are deterministic (D6): a request that timed out after the server applied it writes the same points again. Other errors are not retried, because they repeat: a 500 such as `InferenceService is not initialized`, or a 401, 403, or 404.
- **Rejected batch.** When the server rejects a batch as invalid (HTTP 400 or 422, or gRPC `INVALID_ARGUMENT`), the provider resends that batch one point at a time and reports only the points that fail. The extra requests happen only on failure and are bounded by `batch_size`; deterministic IDs make the resend idempotent.
- **Request failure.** When a batch fails for any other reason (401, 403, 404, 500, or a transient error after its last attempt), every point in it is reported as failed with the redacted error, and later batches are still attempted.
- **Server unavailable.** When a batch still fails with a connection error or timeout after its last attempt, the remaining batches of that call are not sent, and their points are reported as failed with the same redacted error. Without this, a server that went down would cost every remaining batch 3 attempts of up to `timeout` seconds each.
- **Failed documents are removed.** After the last batch, the provider deletes every point of each document that has a failed chunk, with one filtered delete (`MatchAny` on `pk_file`, `wait=True`, the retry policy above). Without this, a batch rejected as a whole could leave some of the document's points written, and a point held back by pre-validation would leave its siblings written: the collection would hold part of the document, searchable, with nothing marking it incomplete. For a re-ingested document, this also removes the previously stored version, which the failed write may already have partly replaced; the document is recorded as failed, and the next successful run writes it again. Once removed, the document's other chunks are reported as failed too, with a reason stating that another chunk of the document failed, and the success count excludes them, so the operator's counts match the collection. The removal is best effort: when the delete fails, or the server was found unavailable, it is skipped with one warning naming the documents; their other chunks, still written, are then not reported as failed, and the documents' next successful run replaces their points.
- **Failed items** use `{"index": {"_id": <chunk pk>, "error": {"reason": <redacted message>}}}`, the shape the operator parses.

*Alternatives:*
- `upload_points` with its built-in batching and retries. Rejected because it defaults to `wait=False`, retries whole batches, and raises without per-point attribution.
- Keeping a failed document's written points until the next successful run. Rejected because a retrieval index that answers from part of a document gives incomplete context with nothing flagging it, which is worse than the document being absent and recorded as failed.
- Removing only the point IDs the failed run sent. Rejected because the upsert may already have replaced some of the stored version's points, so the result would mix the old and new versions.

### D11. Dependency and lockfiles

- **Pin.** Exact `"qdrant-client==1.20.0"` in `[project.dependencies]` of both `pyproject.toml` and `slim/pyproject.toml`, in alphabetical order, matching the existing exact-pin style.
- **Evidence.** Trial resolution with `uv lock` in the root and in `slim/` (on main at 63e71e39) gave the same result in both projects:

  | Project | Packages resolved | Added | Changed |
  |---|---|---|---|
  | root | 500 | `qdrant-client` 1.20.0, `portalocker` 4.4.2 | none |
  | `slim/` | 483 | `qdrant-client` 1.20.0, `portalocker` 4.4.2 | none |

  `grpcio` 1.84.0, `protobuf` 6.33.6, `httpx` 0.28.1 with `h2` 4.4.1, `numpy`, `pydantic`, and `urllib3` already satisfy the client's constraints.
- **Gate (task 1.1).** Before touching a real file, re-run the trial in scratch copies against the then-current main and the then-latest client release, and check OSV for every added or changed package. If resolution changes an existing package, a package has a published advisory, or the existing Milvus, OpenSearch, or telemetry tests fail, stop and ask the maintainers. Do not add an `override-dependencies` entry on your own.
- **Lockfiles.** Run `uv lock` in both directories, commit both `pyproject.toml` files and both `uv.lock` files together, and verify with `uv lock --check` in each.

### D12. Testing strategy

| Level | Location | Scope |
|---|---|---|
| Unit (client mocked) | `tests/unit/operators/vectordb/test_qdrant_{config,client,index_manager,batch_processor,adapter,resource_metadata}.py` | Every requirement scenario that does not need a server. Runs in CI through `pytest tests/unit -m "unit and not integration"`. |
| Operator (adapter mocked) | `tests/unit/operators/vectordb/test_vectordb_operator.py`, `test_metadata_fetcher.py` | Registration, metadata, routing. |
| Real server | `tests/integration/qdrant/test_qdrant_with_container.py` | Against `docker/docker-compose.qdrant.yml`. |

- **Real-server suite.** `docker/docker-compose.qdrant.yml` pins `qdrant/qdrant:v1.20.0`, binds ports to `127.0.0.1` only, and carries a test-only header. A second service with an API key and TLS covers authentication. The suite starts and stops the compose services itself, like the OpenSearch container test: a session fixture first generates a self-signed certificate into a temporary directory (never committed), passes that directory to compose through an environment variable used in the volume mount, and makes the test client trust it through `SSL_CERT_FILE`, which the client's HTTP library honors (to be confirmed in task 6.2). `DOCPIPE_TEST_QDRANT_URL` overrides the target, mirroring the other `DOCPIPE_TEST_*` variables. Each test uses a unique collection and deletes it in teardown. The suite is marked `integration` by `tests/conftest.py`'s path rule, so the unit job excludes it.
- **Scenarios that need a real server**, because local mode and mocks behave differently: partial batch writes, the per-point resend, and the removal of failed documents, the payload-index read-back, strict mode, the 409 race, server-side BM25, paging over 10,000 points, and authentication.
- **CI.** Proposed: a `qdrant-integration-test` job that runs the suite on a GitHub runner, which has Docker, so the suite starts both compose services itself as it does locally. The image is small and starts in seconds. The Weaviate change keeps its suite manual-only and lists one CI job for all vector databases as an open question; the decision should be the same for both providers (Open Questions). Until then the suite stays manual-only. Either way, a skipped suite is reported as blocked, never as passed.
- **Local mode is not used** as a stand-in for the server: its errors are `ValueError`, it accepts IDs the server rejects, its batches never write partially, its payload indexes do nothing, and its BM25 needs `fastembed`.
- **Secrets in tests** come from `monkeypatch.setenv` and `$VAR` references; where a literal is unavoidable it carries the detect-secrets allowlist marker.

### D13. Sparse (BM25) mode

- **Meaning.** With `add_sparse_vector: true` at the operator's top level, the collection gets a named sparse vector with the IDF modifier, and each point sends `models.Document(text=<chunk text>, model="qdrant/bm25")` for it. The server tokenizes the text and stores BM25 term weights; IDF is computed by the server at query time.
- **Flag location.** The operator forwards its top-level flag only when the top level sets it (Context), so a value set only inside `provider_config` would turn sparse mode on in the adapter while the operator keeps the dense-only default mappings and refuses sparse-only runs. For `provider: "qdrant"`, the operator therefore fails initialization, before building the adapter, when `provider_config` contains `add_sparse_vector` and the top level does not, with a message to set it at the operator's top level. The check is in the operator because the adapter cannot tell where a forwarded value came from. When both levels set it, the top-level value is forwarded as today. Other providers are unchanged.
- **Names.** The sparse vector is named by the `sparse_embeddings` mapping (default `sparse_embeddings`). Any upstream values for that feature are not read: no upstream operator produces them, and the BM25 vector is computed from the chunk text.
- **Content.** The content feature must be mapped; otherwise initialization fails before connecting with a message stating that sparse mode needs the content feature mapped to a payload field.
- **Options.** No BM25 options are sent. The server accepts unknown options silently, so passing user options would hide typos.
- **Server version.** 1.15.3 or later (D5).
- **Sparse-only runs** are allowed when the chunks are provided in memory; memory-mapped chunks without dense vectors are an existing operator limitation.

*Alternatives:*
- Client-side BM25 with `fastembed`. Rejected because it adds a heavy dependency (an ONNX runtime and tokenizers) for a result the server computes itself.
- Rejecting `add_sparse_vector` for Qdrant. Rejected because sparse retrieval is a main reason to choose Qdrant, and the server feature has been stable since 1.15.3.

### D14. Stale-chunk lookup, deletes, count, and query

- **Lookup.** `get_chunk_ids_for_documents(ids)` maps each `id` to `sha3_512(id)` and scrolls with `MatchAny` on `pk_file` (at most 100 values per filter), `with_payload=["pk", "pk_file"]`, `with_vectors=False`, in pages of 256 points (a module constant), following `next_page_offset` until it is empty. There is no result window, so every key is returned. Results are keyed by the input `id`; ids with no chunks are omitted. On error it logs a warning and returns `{}`, so the write still runs.
  - *Alternative:* `MatchPrefix` on `pk`. Rejected because it needs server 1.19 and client 1.19, and older servers accept a prefix index silently without building it.
- **Delete.** `delete_documents_by_ids(keys)` converts keys to point IDs (D6) and deletes in requests of 500 IDs with `wait=True` and the retry policy of D10; deletes are idempotent too. The server ignores missing IDs and does not report how many points it deleted, so the success count is the number of keys in requests that succeeded, and the failure count the number in requests that failed.
- **Count.** `count(exact=True)`; 0 on error, logged.
- **Query by name.** `query_by_doc_names(names, fields)` scrolls with `MatchAny` on the payload field mapped from `name`, in the same pages, returning payloads limited to `fields`.
- **Strict mode's other limits.** The provider works with strict mode's unindexed-filter settings (D6). It does not read or adapt to the other strict-mode limits, such as `upsert_max_batchsize`, `max_query_limit`, `filter_max_conditions`, `condition_max_size`, or the read and write rate limits. A request over such a limit is rejected by the server and handled like any other failed request (D10), where an HTTP 429 is retried. The docs list the provider's request sizes (`batch_size`, scroll pages of 256 points, 100 values per `MatchAny`, and 500 IDs per delete) so users can keep them within their collection's limits.

### D15. Flow enrichment

- **Shape.** The five keys of the other providers: `available_resources` (collection names), `selected_resource_schema`, `feature_mappings`, `is_docpipe_supported_resource`, and `stored_resource_metadata` (`vector_similarity`, `dimension_size`). As defined by the Weaviate change, `is_docpipe_supported_resource` may also carry `sparse_eligible` and `error`.
- **Schema.** `selected_resource_schema` lists dense vectors as `{"type": "VECTOR", "distance": <Qdrant name>, "dimension": <size>}`, sparse vectors as `{"type": "SPARSE_VECTOR", "modifier": <name or null>}`, and payload indexes as `{"type": <index type in upper case>}`.
- **Similarity.** `vector_similarity` uses the config vocabulary of `distance_metric` (`cosine`, `dot`, `euclid`, `manhattan`), mapped from Qdrant's names (`Cosine`, `Dot`, `Euclid`, `Manhattan`), and is taken from the first dense vector. The panel copies this value into `distance_metric` when an existing collection is selected, so it must be a value the config accepts. `selected_resource_schema` uses the same names.
- **Support rules** mirror D9 for the node's current mode: an unnamed-vector collection, wrong-typed identity indexes, no dense vector in a dense run, a vector the run would not populate, or (with `add_sparse_vector` true) no IDF sparse vector make it unsupported.
- **`sparse_eligible`** is set for every existing collection: true when the collection would pass every D9 check with `add_sparse_vector` true. A collection with only an IDF sparse vector is therefore unsupported with sparse mode off, but sparse-eligible. So is a collection with matching dense vectors and an IDF sparse vector, because a dense-only run would remove its sparse vectors. A dense collection without an IDF sparse vector is never sparse-eligible, so the panel does not offer BM25 for it.
- **Mappings.** Saved mappings, then mappings derived from the live collection, then the defaults from `compute_default_feature_mappings`, with `pk` for the primary feature.
- **Failures.** No URL and no host give the plain empty result with no `error`. An unreachable server or a rejected key gives `{"supported": false, "error": "<redacted reason>"}` without raising, and other nodes are still enriched. The client is closed in `finally`. The HTTPS rule (D4) is checked before connecting.

### D16. Shared operator changes and flow validation

- **Release after flow validation** (Weaviate D17) and the **Vault placeholder** (Weaviate D18) are provider-agnostic. They are implemented once, by whichever change is implemented first.
- **Placeholder.** The Qdrant client makes no network call in its constructor once the version check is disabled (D4), so the first call is the readiness check. Under flow validation, when `api_key` equals the shared placeholder constant, the provider runs every configuration check, including the HTTPS rule, and skips connecting. Outside flow validation, a key equal to the placeholder text is used like any other.
- **Construction failure.** When a step after connecting fails during construction, the provider closes the client before raising.

### D17. Frontend

- **Scope.** The VectorDB panel and tearsheet only. A colocated `QdrantConnectionFields.tsx` holds no state; pure rules (collection name, HTTPS with an API key, port ranges) live in `vectordb-qdrant.ts`; strings live in `VectorDB.messages.ts`, as in the Weaviate design.
- **Map entry.** `PROVIDER_CONFIG_MAP.qdrant`: resource key `collection_name`, label "Collection", similarity key `distance_metric` with labels Cosine, Dot, Euclid, and Manhattan, no engine selector, sparse capability on with the label "BM25", resource-specific keys stripped before enrichment, and a default config. Its `advancedOnlyKeys` contain `index_parameters`, so that key stays editable in Advanced JSON, survives save and reopen, and is not sent to enrichment. It uses the data-driven `supportsSparse`, `sparseLabel`, and `advancedOnlyKeys` fields and the `error` and `sparse_eligible` enrichment types (Weaviate D16); if those do not exist yet, they are added first (task 7.1).
- **Connection fields.** A choice between "URL" and "Host and port"; switching removes the inactive keys in one write. HTTPS toggle (host mode), gRPC port and preference, and timeout. The API key reuses `VaultInput` unchanged.
- **Validation.** An API key over HTTP (an `http://` URL, or host mode with HTTPS off), an empty URL, or an invalid port shows an inline error, blocks opening the tearsheet and enrichment, and moves focus to the first invalid field. The collection name is entered inside the tearsheet, so an invalid name is shown there and does not block opening it.
- **Tearsheet.** The collection-name rule and placeholder, the distance metric without an engine control, and the BM25 checkbox: shown for a new collection, shown for an existing one only when `sparse_eligible` is true, and preserved on reopen. The enrichment `error` is shown. `index_parameters` stays in Advanced JSON.

## Risks / Trade-offs

- **[New dependency]** → `qdrant-client` and `portalocker` join both lockfiles. Mitigation: the trial changed no other package; the task 1.1 gate re-checks before any real change.
- **[Partial batch writes]** → a rejected batch may leave some points written. Mitigation: pre-validation removes the known causes, the per-point resend attributes the rest, the points of every failed document are removed after the batches, deterministic IDs make reruns replace whatever was written, and the owning documents are always recorded as failed.
- **[Failed re-ingest removes the stored version]** → removing a failed document also removes the version stored by an earlier run. Mitigation: the failed write may already have replaced part of that version, so it is no longer whole; the document is recorded as failed, and the next successful run restores it. The alternatives are listed under D10.
- **[Removal skipped]** → when the server cannot be reached, the removal of failed documents is skipped, and part of a document may stay searchable until its next successful run. Mitigation: one warning names those documents, and they are recorded as failed, so an incremental run retries them.
- **[Retries lengthen failing runs]** → a transient error costs up to 3 attempts. Mitigation: only transient errors are retried, and after a batch exhausts its attempts on a connection error or timeout, the remaining batches are not sent (D10).
- **[Payload fields dropped by a mapping change]** → re-ingesting with a mapping that no longer writes a field removes that field from the re-ingested points, which validation cannot detect because payloads are schemaless (D9). Mitigation: the docs state it; vectors, which the collection does describe, are checked.
- **[ACL stored but not enforced]** → a mapped `allowed_users` field is in the collection, but nothing in docpipe filters on it for Qdrant. Mitigation: one warning per run, the docs, and a keyword index so the querying application can filter on it, including under strict mode.
- **[Extra payload field]** → `pk_file` is stored on every point. Mitigation: it is the only portable way to look up a file's chunks, it is reserved and documented, and its index keeps lookups fast.
- **[Server version drift]** → BM25 and filter semantics changed across releases. Mitigation: sparse mode is version-checked at initialization; the provider uses only `MatchValue` and `MatchAny`, which behave the same on every tested version; the real-server suite pins its image.
- **[Two providers in flight]** → the Weaviate and Qdrant changes touch the same operator and panel code. Mitigation: shared work is done once (proposal, "Relationship to the Weaviate change"), and the frontend requirement is added separately so the archives do not overwrite each other.

## Migration Plan

No migration: the provider is new and opt-in, and existing flows are unaffected. A flow switches to Qdrant by setting `provider: "qdrant"` and a `provider_config`. Rollback is removing the registration and the dependency; existing Qdrant collections stay untouched.

## Open Questions

- **CI job for the real-server suite** (D12): add the proposed `qdrant-integration-test` job, or keep the suite manual-only like the OpenSearch, Milvus, and Weaviate container tests? This is the same question as the Weaviate change's open question on one CI job for all vector databases.
- **Private certificate authorities:** self-hosted servers with a private CA are trusted through the system trust store or `SSL_CERT_FILE`. Should `provider_config` also accept a CA bundle path?
- **Minimum server version for dense mode:** is "no minimum, version-independent behavior" acceptable, or should the provider require a tested release window (for example 1.16 and later)?
- **API key over plain HTTP on an internal network:** the HTTPS rule (D4) blocks a common self-hosted setup, a server on a cluster-internal address such as `http://qdrant:6333` with an API key and no TLS, and those users are likely to drop the key rather than set up TLS. Keep the rule strict, or add an explicit opt-in such as `allow_api_key_over_http` (default false, one WARNING per connection when true, and the panel's HTTPS check relaxed only when it is set)? The upstream client allows this with a warning. Until the maintainers decide, the rule stays strict.
- **Local mode follow-up:** Milvus has a local mode (Milvus Lite) that runs without a server; Qdrant's local mode is a non-goal here. Should a dense-only local mode (`path=`) be planned as a follow-up change? Sparse mode would stay server-only, because local BM25 needs `fastembed`, and local mode would need its own rules for payload indexes, which do nothing there, and for its `ValueError` errors. Until then, the docs state that a running Qdrant server is required.
