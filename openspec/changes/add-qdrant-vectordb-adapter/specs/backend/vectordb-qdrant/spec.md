# Spec Delta

## Purpose

The Qdrant provider of the `vectordb` operator. It defines how `provider: "qdrant"` is configured, authenticated, and connected to, how collections are created and validated, how re-ingest stays idempotent, how writes are checked and attributed, and how failures and flow-enrichment metadata are reported. The provider-agnostic table, metadata, document identity, sparse-mode, and provider-selection contract lives in `backend/vectordb-operator`; this capability does not repeat it.

Configuration problems are detected while the operator is constructed, before any network connection. They surface as initialization failures: the adapter's message is wrapped by the vector store factory ("Failed to create vector store adapter 'qdrant': ...") and by the operator ("Failed to initialize vector database adapter 'qdrant': ..."), and flow validation reports it as "Validation failed for operator 'vectordb': ...". Every requirement below that says "fails to initialize" means the original message text is contained in each of those wrapped messages.

## ADDED Requirements

### Requirement: Qdrant provider registration
The operator SHALL accept `provider: "qdrant"` and route all writes to the Qdrant server described by `provider_config`. Operator metadata SHALL list `qdrant` among the `provider` valid values and SHALL publish a `provider_config` field schema for it. Loading operator metadata MUST NOT import the Qdrant client library. Selecting another provider MUST NOT change its behavior.

#### Scenario: Qdrant listed in operator metadata
- **WHEN** a client requests the `vectordb` operator metadata
- **THEN** the `provider` attribute's valid values include `qdrant` alongside the other registered providers, and `provider_config.providers.qdrant` describes the Qdrant configuration fields with their types, defaults, and descriptions

#### Scenario: API key masked in metadata
- **WHEN** a client requests the `vectordb` operator metadata
- **THEN** the `api_key` field of `provider_config.providers.qdrant` is marked sensitive

#### Scenario: Metadata without the client library
- **WHEN** operator metadata is requested in a process where `qdrant_client` cannot be imported
- **THEN** the metadata is returned, including the `qdrant` configuration schema

### Requirement: Qdrant connection configuration validation
The Qdrant `provider_config` SHALL require `collection_name`. It SHALL accept either a `url` or a `host` with `port` (default 6333), with `grpc_port` (default 6334), `prefer_grpc` (default false), `https` (default false, used with `host` only), `timeout` in seconds (default 30), `batch_size` (default 100), `distance_metric`, and `index_parameters`. The operator SHALL fail to initialize, before connecting, for each missing or invalid field, with a message that names the field. A `url` without a port SHALL connect to `port`. The failure message MUST NOT contain any value taken from `provider_config`.

#### Scenario: Collection name missing
- **WHEN** a `qdrant` node's `provider_config` omits `collection_name`
- **THEN** the operator fails to initialize with a message stating that `collection_name` is not provided, and no connection is attempted

#### Scenario: Collection name rule
- **WHEN** a node's `collection_name` is one of the values below
- **THEN** it is accepted or rejected as listed, and each rejection fails initialization with a message stating the rule: 1 to 255 characters, none of `/`, `\`, `:`, `*`, `?` (the server's rule), not `.` or `..` (rejected by the client), and no control characters (the provider's addition)

| Collection name | Result |
|---|---|
| `DocumentChunks` | accepted |
| `docs_2025` | accepted |
| `doc-chunks` | accepted |
| `doc.chunks` | accepted |
| a name of 255 characters | accepted |
| `doc/chunks` | rejected |
| `docs:2025` | rejected |
| `doc*` | rejected |
| `..` | rejected |
| a name containing a tab | rejected |
| a name of 256 characters | rejected |
| (empty) | rejected |

#### Scenario: URL and host together
- **WHEN** a `qdrant` node sets `url` and also sets `host` to a value other than the default
- **THEN** the operator fails to initialize with a message stating that `url` and `host` are mutually exclusive, and no connection is attempted

#### Scenario: URL without a port
- **WHEN** `url` is `https://xyz.cloud.qdrant.io` with no port, and `port` is not set
- **THEN** the connection goes to port 6333 over HTTPS; with `port: 7000` it goes to port 7000, and with `url` `https://qdrant.example.com:443` it goes to port 443

#### Scenario: Port out of range
- **WHEN** `port` or `grpc_port` is outside 1 to 65535
- **THEN** the operator fails to initialize with a message naming the field

#### Scenario: Unknown distance metric
- **WHEN** `distance_metric` is not one of `cosine`, `dot`, `euclid`, or `manhattan`
- **THEN** the operator fails to initialize with a message naming `distance_metric` and the accepted values

#### Scenario: Unknown index parameter
- **WHEN** `index_parameters` contains a key other than `m`, `ef_construct`, `full_scan_threshold`, `max_indexing_threads`, `payload_m`, or `on_disk`, or one of those keys with a value of the wrong type
- **THEN** the operator fails to initialize, before connecting, with a message naming the key

#### Scenario: Rule not published in metadata
- **WHEN** a client requests the `vectordb` operator metadata
- **THEN** the `collection_name` field schema of `provider_config.providers.qdrant` has no `pattern`, because the rule is enforced by the backend; clients that need it carry their own copy

### Requirement: Qdrant API key handling
The Qdrant provider SHALL support connecting without authentication and with an API key. The API key SHALL be a literal or a `$VAR` / `${VAR}` reference; a `vault://` reference is resolved by the executor before the adapter is built. An API key that is empty, or that resolves to an empty value, SHALL mean no key. The API key MUST NOT appear in log output, in any raised message, or in any failed-item reason.

#### Scenario: Environment variable key
- **WHEN** `api_key` is configured as `$QDRANT_API_KEY` or `${QDRANT_API_KEY}` and that variable is set
- **THEN** the connection authenticates with the variable's value and the value is not logged

#### Scenario: Unset environment variable
- **WHEN** `api_key` is configured as `${QDRANT_API_KEY}` and that variable is not set
- **THEN** the operator fails to initialize, before connecting, with a message that names `QDRANT_API_KEY` and contains no key value

#### Scenario: Reference that resolves to an empty key
- **WHEN** `api_key` is `${QDRANT_API_KEY:}` and `QDRANT_API_KEY` is not set, or `api_key` is `$QDRANT_API_KEY` and the variable is set to an empty string
- **THEN** the connection is made without a key, the HTTPS rule does not apply, and one warning names `api_key` and `QDRANT_API_KEY`; when the server requires a key, the operator fails to initialize as in "Wrong key"

#### Scenario: Vault reference resolved upstream
- **WHEN** `api_key` is configured as a `vault://` reference and the secret provider is registered
- **THEN** the adapter receives the resolved plain value, contains no Vault resolution code, and the value is not logged

#### Scenario: Vault reference during flow validation
- **WHEN** a flow containing a `vectordb` node with a `vault://` API key over HTTPS is validated, so that flow validation has replaced the key with its placeholder
- **THEN** the configuration checks and the HTTPS rule still run, no connection to the server is attempted, and validation does not fail because of the placeholder key

#### Scenario: Placeholder text outside flow validation
- **WHEN** a run, not a flow validation, configures an API key whose text equals the validation placeholder
- **THEN** the connection is attempted with that value like any other key

#### Scenario: Unresolvable Vault reference on a run
- **WHEN** a run's `vault://` API key cannot be resolved because the secret provider is not registered or resolution fails
- **THEN** the run fails before the adapter is built, and the reference text is not sent to the server as a key

#### Scenario: Literal all-caps key
- **WHEN** a literal API key consists only of upper-case letters and underscores and an environment variable of that exact name exists
- **THEN** the environment variable's value is used, because that is the behavior of the shared environment resolver; the documentation recommends an explicit `$VAR` reference for environment values

#### Scenario: Wrong key
- **WHEN** the server rejects the configured API key
- **THEN** the operator fails to initialize with an error naming Qdrant and the target address, the error does not contain the key, and no points are written

#### Scenario: Secret never disclosed on failure
- **WHEN** an error raised by the Qdrant client echoes the configured API key or an `api-key` or `Authorization` header
- **THEN** the message raised by the adapter, the factory, and the operator, every log record, and every failed-item reason show a redaction marker in place of the secret

### Requirement: API key requires an HTTPS connection
The Qdrant provider SHALL NOT send an API key over an unencrypted connection. When a non-empty `api_key` is set, a configured `url` SHALL use the `https` scheme, and a `host` connection SHALL set `https` to true; otherwise initialization SHALL fail before any connection is attempted. The same check SHALL run whenever a connection is built, including flow enrichment.

#### Scenario: Key with an HTTP URL
- **WHEN** a `qdrant` node sets `api_key` and `url` is `http://qdrant.internal:6333`, with or without `https: true`
- **THEN** the operator fails to initialize with a message stating that an API key requires an HTTPS connection, and no connection is attempted

#### Scenario: Key with host and HTTPS off
- **WHEN** a `qdrant` node sets `api_key`, `host`, and `https: false`
- **THEN** the operator fails to initialize with the same message, and no connection is attempted

#### Scenario: Key with an HTTPS URL
- **WHEN** a `qdrant` node sets `api_key` and `url` is `https://xyz.cloud.qdrant.io`
- **THEN** the configuration is accepted and the connection uses HTTPS on port 6333

#### Scenario: Unauthenticated local server
- **WHEN** a `qdrant` node sets no `api_key` and uses `host: "localhost"` with `https: false`
- **THEN** the configuration is accepted and the connection is plain HTTP

#### Scenario: Flow validation disabled
- **WHEN** flow validation is disabled and a `qdrant` node sets an API key with an HTTP connection
- **THEN** the operator still fails to initialize with the same message before any network connection is made, and the key is not sent

#### Scenario: Enrichment with a key over HTTP
- **WHEN** flow enrichment runs for a `qdrant` node that sets an API key with an HTTP connection
- **THEN** enrichment reports `is_docpipe_supported_resource` as `supported: false` with a redacted `error`, without connecting and without sending the key

### Requirement: Qdrant connection and server version check
At initialization the provider SHALL connect with an authenticated request and SHALL read the server version. When the connection fails, initialization SHALL fail with an error that identifies Qdrant, the target URL or host and port, and the redacted cause, and no partial writes SHALL occur. When `add_sparse_vector` is true and the server is older than 1.15.3, initialization SHALL fail with a message naming the server version and the minimum. The provider MUST NOT rely on the client's asynchronous version warning.

#### Scenario: Server unreachable
- **WHEN** the configured URL or host and port have no reachable Qdrant server
- **THEN** operator initialization fails with an error naming Qdrant and the target address, and no points are written

#### Scenario: Health endpoints do not prove the key
- **WHEN** the server answers its unauthenticated root endpoint but rejects the configured key on collection requests
- **THEN** operator initialization fails, rather than the first write

#### Scenario: Sparse mode on an old server
- **WHEN** `add_sparse_vector` is true and the server version is 1.15.1
- **THEN** the operator fails to initialize with a message stating that sparse mode requires Qdrant 1.15.3 or later and naming 1.15.1, and no collection is created

#### Scenario: Server outside the client's version window
- **WHEN** the server's major version differs from the client's, or the minor versions differ by more than one
- **THEN** exactly one warning naming both versions is logged during initialization, and initialization continues

### Requirement: Qdrant collection creation with named vectors
When the collection does not exist, the provider SHALL create it with one named dense vector per detected dense vector column, named by the column's mapped name, with the detected dimension, the configured distance metric (`cosine` default, `dot`, `euclid`, `manhattan`), and `index_parameters` as its HNSW settings. It SHALL then create the identity payload indexes and confirm them by reading the collection back. When creation reports that the collection already exists, the provider SHALL validate the existing collection instead of failing.

#### Scenario: Single embedding column
- **WHEN** a new collection is created for a run whose `embeddings` column is mapped to `vector_embeddings` and has dimension 384
- **THEN** the collection has exactly one named vector `vector_embeddings` of size 384 with the configured distance, and stored points carry 384-dimensional vectors under that name

#### Scenario: Multiple embedding models
- **WHEN** a run has two dense vector columns mapped to `vector_embeddings` and `vector_embeddings_alt`
- **THEN** the collection has two named vectors and each point stores both vectors

#### Scenario: HNSW settings applied
- **WHEN** `index_parameters` is `{"m": 32, "ef_construct": 256}`
- **THEN** the created named vectors use HNSW `m` 32 and `ef_construct` 256

#### Scenario: Concurrent creation
- **WHEN** two workers find the collection absent and both try to create it, and the second creation returns that the collection already exists
- **THEN** the second worker validates the existing collection and continues writing, and neither worker records failed documents because of the race

#### Scenario: Payload index not built as requested
- **WHEN** the server accepts a payload index request but the collection read back does not show a keyword index on `pk`
- **THEN** all documents in scope are recorded as failed with a reason naming the field and the missing index, and `node_status` is `FAILED`

### Requirement: Fixed identity payload fields
Every point SHALL store its chunk primary key verbatim in the payload field `pk` and the file part of that key in the payload field `pk_file`. The provider SHALL write both fields itself. Initialization SHALL fail, before connecting, when a feature mapping sends the primary feature to any name other than `pk`, sends any other feature to `pk`, or sends any feature to `pk_file`.

#### Scenario: Primary feature mapped to pk
- **WHEN** the primary feature is mapped to `pk`
- **THEN** the operator initializes, and each written point's payload has `pk` equal to its chunk key and `pk_file` equal to the part of that key before `_chunk_`

#### Scenario: Primary feature mapped elsewhere
- **WHEN** the primary feature is mapped to a name other than `pk`, such as `chunk_id`
- **THEN** the operator fails to initialize, before connecting, with a message stating that the primary key field must be `pk`

#### Scenario: Another feature mapped to a reserved field
- **WHEN** a feature other than the primary feature is mapped to `pk`, or any feature is mapped to `pk_file`
- **THEN** the operator fails to initialize, before connecting, with a message naming the reserved field

### Requirement: Qdrant payload mapping
Points SHALL carry one payload field per mapped non-vector feature, plus the identity fields and the content field. Feature types SHALL map as follows: `string`, `enum`, `crn`, `date`, `time`, and `timestamp` to strings; `int8`, `int16`, `int32`, and `int64` to integers; `float`, `double`, and `sfloat` to floats; `bool` and `boolean` to booleans; `json` to native JSON values; and `list` to JSON arrays. `vector` and `vector_sparse` features SHALL be written as named vectors, not payload. A feature of any other type SHALL be stored as a string, with one warning naming the feature. Mapped payload names SHALL be non-empty and MUST NOT contain `.`, `[`, or `]`; initialization SHALL fail, before connecting, for a name that breaks this rule, for two vector columns mapped to one name, and for a vector name equal to a payload name.

#### Scenario: Typed metadata fields
- **WHEN** features `page_count` (`int32`), `score` (`double`), and `is_scanned` (`bool`) are mapped
- **THEN** each point's payload stores `page_count` as an integer, `score` as a float, and `is_scanned` as a boolean

#### Scenario: Structured value stored as JSON
- **WHEN** a mapped `json` feature value is a dictionary
- **THEN** the stored payload value is that dictionary as a nested JSON object, not a string

#### Scenario: Name with a path character
- **WHEN** a feature is mapped to the target name `meta.author`
- **THEN** the operator fails to initialize, before connecting, with a message naming `meta.author` and the characters that are not allowed

#### Scenario: Missing value omitted
- **WHEN** a mapped feature's value is null for a chunk
- **THEN** that chunk's point has no payload field for the feature

### Requirement: Identity payload indexes
The provider SHALL keep keyword payload indexes on `pk`, `pk_file`, and the payload fields mapped from `id` and `name`, and SHALL filter only on indexed fields, so that it works with strict mode's unindexed-filter settings. Lookups SHALL use exact matches only, so that they behave the same on every supported server version. Scrolls SHALL use pages of 256 points. Strict mode's other limits, such as a maximum upsert batch size, a query limit, or rate limits, are not adapted to: a request the server rejects under them SHALL fail as described in "Pre-validated batched writes with per-chunk failure attribution".

#### Scenario: Strict mode with unindexed filtering disabled
- **WHEN** the collection has strict mode with unindexed filtering disabled for reads and updates
- **THEN** stale-chunk lookup, query by document name, deletion by key, and the removal of failed documents all succeed

### Requirement: Qdrant sparse (BM25) retrieval mode
When `add_sparse_vector` is true, the provider SHALL create a named sparse vector with the IDF modifier, named by the `sparse_embeddings` mapping (default `sparse_embeddings`), and SHALL have the server compute each point's BM25 term weights from the chunk text with the server's `qdrant/bm25` inference. The flag SHALL be read from the operator's top level: a `qdrant` node that sets `add_sparse_vector` inside `provider_config` but not at the top level SHALL fail to initialize. The content feature MUST be mapped. The provider SHALL NOT pass BM25 options and SHALL NOT read upstream values for the `sparse_embeddings` feature. Runs without dense vector columns SHALL be allowed when the chunks are provided in memory.

#### Scenario: Flag set only inside provider_config
- **WHEN** a `qdrant` node sets `add_sparse_vector` inside `provider_config` and not at the operator's top level
- **THEN** the operator fails to initialize, before the adapter is built and before any connection, with a message stating that `add_sparse_vector` must be set at the operator's top level

#### Scenario: Flag set at both levels
- **WHEN** a `qdrant` node sets `add_sparse_vector` at the operator's top level and also inside `provider_config`
- **THEN** the operator initializes, and the top-level value decides sparse mode for both the operator and the adapter

#### Scenario: Hybrid dense and sparse
- **WHEN** sparse mode is on, `embeddings` is mapped to `vector_embeddings`, and `content` is mapped to `text`
- **THEN** the collection has the dense vector `vector_embeddings` and the sparse vector `sparse_embeddings` with the IDF modifier, and a sparse query for a word in a chunk returns that chunk's point

#### Scenario: Sparse only with in-memory chunks
- **WHEN** sparse mode is on, `available_features` declares no dense vector column, and the input chunks are provided in memory
- **THEN** the collection is created with the sparse vector only, every chunk is written with its text and its sparse vector, the run is not marked `FAILED`, and sparse queries return the chunks

#### Scenario: Sparse only with memory-mapped chunks
- **WHEN** sparse mode is on, `available_features` declares no dense vector column, and the input chunks are memory-mapped file references
- **THEN** this is an existing operator limitation independent of the provider: the affected documents are recorded as failed, and the documentation states that sparse-only runs require in-memory chunks

#### Scenario: Content not mapped
- **WHEN** sparse mode is on and no feature mapping targets the content feature
- **THEN** the operator fails to initialize, before connecting, with a message stating that sparse mode requires the content feature to be mapped to a payload field

#### Scenario: Upstream sparse values not read
- **WHEN** the input table has a column for the `sparse_embeddings` feature and sparse mode is on
- **THEN** each point's sparse vector is computed from the chunk text, and the column's values are not written

### Requirement: Existing Qdrant collection validation
When the collection already exists, the provider SHALL verify its named dense vectors (presence, dimension, and distance), its sparse vector when sparse mode is on (presence and the IDF modifier), and the type of every existing identity payload index. Because an upsert replaces a whole point, the provider SHALL also fail when the collection has a vector that the run would not populate: a named dense vector that no run vector column is mapped to, or a sparse vector while sparse mode is off. A run with no dense vector columns SHALL skip the dimension and distance checks, and the collection SHALL then have no dense vector. It SHALL report every mismatch in one failure. Missing identity payload indexes SHALL be created only when no check failed.

#### Scenario: Dimension mismatch
- **WHEN** the existing collection's named vector `vector_embeddings` has size 768 and the current run produces 384-dimensional embeddings
- **THEN** no points are written, every document in scope is recorded as failed with a reason stating both dimensions, and `node_status` is `FAILED`

#### Scenario: Distance mismatch
- **WHEN** the existing named vector uses `Dot` and the node's `distance_metric` is `cosine`
- **THEN** no points are written and the failure reason names the vector and both distances

#### Scenario: Missing named vector
- **WHEN** the run maps a vector column to `vector_embeddings_alt` and the existing collection has no named vector with that name
- **THEN** no points are written and the failure reason names the missing vector

#### Scenario: Empty existing collection
- **WHEN** the existing collection holds no points and its named vector has a different size than the run's embeddings
- **THEN** the dimension mismatch is still reported, because Qdrant stores the size in the collection configuration

#### Scenario: Sparse vector without IDF
- **WHEN** sparse mode is on and the existing collection's sparse vector has no IDF modifier
- **THEN** no points are written and the failure reason names the sparse vector and the missing modifier

#### Scenario: Identity index of another type
- **WHEN** the existing collection has a text index on `pk`, or an integer index on the field mapped from `id`
- **THEN** no points are written, nothing is deleted, and the failure reason names the field, states that it must have a keyword index, and tells the user to recreate the collection or use a new collection name

#### Scenario: Sparse-only run on an existing collection
- **WHEN** sparse mode is on, the run has no dense vector columns, and the existing collection has an IDF sparse vector, keyword identity indexes, and no dense vector
- **THEN** no dense vector check runs and the write proceeds

#### Scenario: Dense vector the run would not populate
- **WHEN** the existing collection has named vectors `vector_embeddings` and `vector_embeddings_alt`, and the run maps a vector column only to `vector_embeddings`
- **THEN** no points are written, and the failure reason names `vector_embeddings_alt` and states that writing would remove it from every re-ingested point

#### Scenario: Sparse vector with sparse mode off
- **WHEN** sparse mode is off and the existing collection has a matching named dense vector and an IDF sparse vector
- **THEN** no points are written, and the failure reason names the sparse vector and states that writing would remove it from every re-ingested point

#### Scenario: Sparse-only run on a collection with dense vectors
- **WHEN** sparse mode is on, the run has no dense vector columns, and the existing collection has an IDF sparse vector and a named dense vector
- **THEN** no points are written, and the failure reason names the dense vector

#### Scenario: Missing identity index added
- **WHEN** every check passes and the existing collection has no index on `pk_file`
- **THEN** a keyword index on `pk_file` is created before points are written

#### Scenario: Nothing is changed when a check fails
- **WHEN** an identity index is missing and another check on the existing collection fails
- **THEN** the missing index is not created

#### Scenario: Several mismatches at once
- **WHEN** both a dimension mismatch and a missing named vector exist
- **THEN** the single failure reason names both problems

### Requirement: Unsupported Qdrant configurations rejected
The provider SHALL reject existing collections that use a single unnamed vector, and existing sparse-only collections when the run has dense vector columns. Each rejection SHALL return an actionable message.

#### Scenario: Single unnamed vector
- **WHEN** the configured existing collection has one unnamed dense vector and the run has dense vector columns
- **THEN** no points are written and the failure reason states that only collections with named vectors are supported

#### Scenario: Dense run on a sparse-only collection
- **WHEN** the run has a dense vector column and the existing collection has only a sparse vector
- **THEN** no points are written and the failure reason states that the collection has no dense vector

### Requirement: ACL feature stored but not enforced for Qdrant
The Qdrant provider SHALL NOT enforce document access-control lists. A mapped `allowed_users` feature SHALL be stored on every point of its document under its mapped name, as the JSON array of strings the ACL operator produces, with a keyword payload index, so that the application that queries the collection can filter on it. The provider SHALL log one warning stating that docpipe does not enforce ACLs for Qdrant and that the querying application must filter on the field. When `allowed_users` is present upstream but unmapped, the write SHALL proceed without it, with one warning that the ACL is neither stored nor enforced.

#### Scenario: allowed_users mapped
- **WHEN** a `qdrant` node maps `allowed_users` to `allowed_users`, and a document's value is `["alice", "bob"]`
- **THEN** every point of that document has the payload field `allowed_users` with the array `["alice", "bob"]`, the collection has a keyword index on `allowed_users`, a keyword match on `alice` returns that document's points, and one warning states that docpipe does not enforce ACLs for Qdrant

#### Scenario: ACL operator upstream, feature unmapped
- **WHEN** `available_features` contains `allowed_users` and no mapping references it
- **THEN** points are written without any ACL field and one warning states that the ACL is neither stored nor enforced for Qdrant

### Requirement: Schema templates ignored for Qdrant
The Qdrant provider SHALL ignore the operator-level `schema_template_path` option, which applies only to OpenSearch index templates. When it is set, the provider SHALL log one warning naming the option, SHALL NOT read the file, and SHALL build the collection from feature mappings alone.

#### Scenario: Schema template path set
- **WHEN** a `qdrant` node sets `schema_template_path` to a path, including one that does not exist
- **THEN** the operator initializes without error, one warning names the ignored option, and the created collection is identical to one created without the option

### Requirement: Deterministic point identity and in-place re-ingest
Each point SHALL use a UUIDv5 point ID derived from the chunk's positional primary key, which is formed from the hashed file ID and the chunk index, in a fixed namespace. The payload field `pk` SHALL store that key verbatim. Writing a point whose ID already exists SHALL replace it, so re-ingesting a document never duplicates chunks.

#### Scenario: Unchanged re-ingest
- **WHEN** the same document is ingested twice with identical content
- **THEN** the collection's point count is the same after the second run as after the first

#### Scenario: Modified chunk content
- **WHEN** a document is re-ingested after the text of chunk 2 changed
- **THEN** the point for chunk 2 keeps its ID and its stored text and vectors reflect the new content

#### Scenario: Stable point ID
- **WHEN** the point ID is computed for the chunk key `example_chunk_0`, in any process
- **THEN** it is `79a2b24e-4ff8-5ec4-b8f1-77ac5d83102b`, the UUIDv5 of `docpipe:qdrant:example_chunk_0` in the URL namespace

### Requirement: Stale chunk cleanup on re-ingest
Before writing, the provider SHALL find the existing points of each file in the batch by an exact match on `pk_file`, and the operator deletes those whose key is not among the keys of the current run. The lookup SHALL match only that file's points and SHALL return every matching key however many chunks the file has, scrolling in pages of 256 points. A lookup failure SHALL be logged as a warning and SHALL NOT prevent the write.

#### Scenario: Document shrinks
- **WHEN** a document previously stored as 5 chunks is re-ingested as 3 chunks
- **THEN** the points for chunk indexes 3 and 4 are deleted and exactly 3 points remain for that file

#### Scenario: Other files untouched
- **WHEN** files A and B are both stored and only A is re-ingested with fewer chunks
- **THEN** only A's surplus points are deleted and every point for B remains

#### Scenario: File with many chunks
- **WHEN** a file previously stored as 12,000 chunks is re-ingested as 100 chunks
- **THEN** the lookup returns all 12,000 stored keys across several pages, 11,900 points are deleted, and exactly 100 remain for that file

#### Scenario: Lookup fails
- **WHEN** looking up existing chunks fails with a server error
- **THEN** a warning is logged and the new chunks are still written

### Requirement: Pre-validated batched writes with per-chunk failure attribution
The provider SHALL check every point before sending it: each dense vector's dimension against the collection, that every vector value is finite, and that every vector name exists in the collection. A point that fails a check SHALL be reported as failed and SHALL NOT be sent. The provider SHALL write the remaining points in batches no larger than `batch_size` points and a bounded payload size, and SHALL wait for each write to complete. Each upsert request SHALL be retried, up to 3 attempts in total with exponential backoff, when it fails with a connection error, a timeout, HTTP 429, 502, 503, or 504, or gRPC `UNAVAILABLE`, `DEADLINE_EXCEEDED`, or `RESOURCE_EXHAUSTED`; other errors SHALL NOT be retried. When the server rejects a batch as invalid (HTTP 400 or 422, or gRPC `INVALID_ARGUMENT`), the provider SHALL resend its points one at a time and report only the points that fail. When a batch still fails with a connection error or timeout after its last attempt, the remaining batches SHALL NOT be sent, and their points SHALL be reported as failed with the same redacted error. After the last batch, the provider SHALL delete every point of each document that has a failed chunk, matched by `pk_file`, so that no part of a failed document stays searchable, and SHALL then report that document's removed chunks as failed with a reason stating that another chunk of the document failed. When that delete fails, or the server was found unavailable, the provider SHALL skip it and log one warning naming the documents. Each failed point SHALL be reported with its chunk primary key and a redacted reason, and the operator SHALL record the owning document as failed with reason "One or more chunks failed to index", while the points of other documents are still written.

#### Scenario: Wrong dimension caught before sending
- **WHEN** a batch holds 10 documents of 10 chunks each, and one chunk of document D has a 383-dimensional vector for a 384-dimensional named vector
- **THEN** that chunk is reported as failed with a reason naming the vector and both dimensions and is not sent, the 90 points of the other documents are written, D's other 9 points are removed and reported as failed with a reason stating that another chunk of the document failed, D appears in `failed_docs`, and `chunks_failed_to_index` is 10

#### Scenario: Non-finite value caught before sending
- **WHEN** a chunk's vector contains `NaN`, over either REST or gRPC
- **THEN** that chunk is reported as failed with a reason stating that vector values must be finite, and it is not written

#### Scenario: Server rejects a batch
- **WHEN** the server rejects a batch of 100 points because one point is invalid in a way the pre-checks do not detect
- **THEN** the batch's points are resent one at a time, the invalid chunk is reported as failed with the server's redacted message, the points of the other documents are stored, its parent document's other points are removed and reported as failed, and the parent document appears in `failed_docs`

#### Scenario: Transient failure retried
- **WHEN** the first attempt of a batch fails with HTTP 503, or with a timeout, and the second attempt succeeds
- **THEN** every point of the batch is stored once, no chunk is reported as failed, and no document appears in `failed_docs`

#### Scenario: Error that is not retried
- **WHEN** a batch request fails with HTTP 500 or 401
- **THEN** it is sent only once, every point in that batch is reported as failed with the redacted request error, its documents appear in `failed_docs`, and subsequent batches are still attempted

#### Scenario: Server stays unreachable
- **WHEN** a batch fails with a connection error on every attempt
- **THEN** it is attempted 3 times, the remaining batches are not sent, the points of that batch and of every remaining batch are reported as failed with the redacted error, and one warning names the failed documents whose points were not removed

#### Scenario: Failed re-ingest of a stored document
- **WHEN** a document stored by an earlier run as 5 chunks is re-ingested as 5 chunks, and one of its new chunks fails
- **THEN** no point of that document remains in the collection, the document appears in `failed_docs`, and the next successful run writes all 5 of its chunks again

#### Scenario: Removal of a failed document fails
- **WHEN** a document has a failed chunk and the delete that removes its points fails
- **THEN** one warning names the document, the document appears in `failed_docs`, and its other chunks, which stay written, are not reported as failed

#### Scenario: Re-running after a failed batch
- **WHEN** a batch failed after some of its points were written, and the same documents are ingested again
- **THEN** the written points are replaced in place, and the collection holds exactly one point per chunk

### Requirement: Qdrant maintenance operations
The provider SHALL support deleting points by chunk primary key, returning success and failure counts and processing any number of keys in bounded requests. It SHALL also support returning the total point count and querying points by document name through the payload field mapped from `name`.

#### Scenario: Delete more keys than one request allows
- **WHEN** deletion is requested for 25,000 chunk primary keys
- **THEN** all matching points are deleted across requests of at most 500 IDs, and the returned success count is the number of keys in requests that succeeded, because the server does not report how many points it deleted

#### Scenario: Count on missing or unreachable collection
- **WHEN** the point count is requested and the request fails
- **THEN** the count is reported as 0 and the error is logged

#### Scenario: Query by document name
- **WHEN** documents named `report_2025.pdf` and `report-2025.pdf` are both stored, and points are queried by `report_2025.pdf`
- **THEN** only the points of `report_2025.pdf` are returned

### Requirement: Qdrant connection lifecycle
The provider SHALL close its Qdrant client on every path that opened it: after every transform, after flow validation, after enrichment, and when a failure occurs after the connection opened. Closing SHALL be idempotent.

#### Scenario: Transform fails mid-write
- **WHEN** the transform raises an error after the connection is opened
- **THEN** the client is closed before the error is reported

#### Scenario: Flow validation only
- **WHEN** a `vectordb` node with `provider: "qdrant"` is validated in a flow and no transform runs
- **THEN** the client opened during construction is closed when validation finishes, whether or not validation reported errors

#### Scenario: Version check fails after connecting
- **WHEN** the readiness request succeeds but the version check or a later step of construction raises
- **THEN** the client is closed before the error is raised

#### Scenario: Close called twice
- **WHEN** the client has already been closed and `close()` is called again
- **THEN** no error is raised

### Requirement: Qdrant flow-enrichment metadata
For `vectordb` nodes with `provider: "qdrant"`, flow enrichment SHALL return `available_resources`, `selected_resource_schema`, `feature_mappings`, `is_docpipe_supported_resource`, and `stored_resource_metadata` (`vector_similarity`, `dimension_size`), with `vector_similarity` and the distances in `selected_resource_schema` given in the `distance_metric` vocabulary (`cosine`, `dot`, `euclid`, `manhattan`), so the panel can save them back. For every existing collection, `is_docpipe_supported_resource` SHALL report whether the collection would pass the run-time checks with `add_sparse_vector` true, as `sparse_eligible`. It MAY also carry `error`, as the scenarios below describe.

#### Scenario: Existing collection described
- **WHEN** enrichment runs for a node whose `collection_name` names an existing collection with named vector `vector_embeddings` (Qdrant distance `Cosine`, size 384)
- **THEN** `available_resources` includes the collection, `selected_resource_schema.vector_embeddings` reports type `VECTOR`, distance `cosine`, and dimension 384, and `stored_resource_metadata` is `{"vector_similarity": "cosine", "dimension_size": 384}`

#### Scenario: Distance names in the config vocabulary
- **WHEN** an existing collection's named vector uses Qdrant's `Euclid` distance
- **THEN** `stored_resource_metadata.vector_similarity` is `euclid`, a value that `distance_metric` accepts, so saving the node with it passes validation

#### Scenario: New collection name
- **WHEN** `collection_name` is not among the existing collections
- **THEN** `is_docpipe_supported_resource.supported` is true and `feature_mappings` are the defaults computed from `available_features`, with the primary feature mapped to `pk`, unless the node has saved mappings

#### Scenario: Sparse-only collection with sparse mode off
- **WHEN** `collection_name` names an existing collection with only an IDF sparse vector and keyword identity indexes, and `add_sparse_vector` is false
- **THEN** `is_docpipe_supported_resource` reports `supported: false` with a reason and `sparse_eligible: true`

#### Scenario: Dense collection without a sparse vector
- **WHEN** `collection_name` names an existing collection with a matching named dense vector and no sparse vector
- **THEN** `is_docpipe_supported_resource` reports `sparse_eligible: false`, and `supported` is true with `add_sparse_vector` false and false with a reason when it is true

#### Scenario: Hybrid collection with sparse mode off
- **WHEN** `collection_name` names an existing collection with a matching named dense vector and an IDF sparse vector, and `add_sparse_vector` is false
- **THEN** `is_docpipe_supported_resource` reports `supported: false` with a reason naming the sparse vector, and `sparse_eligible: true`

#### Scenario: Ineligible sparse-only collection
- **WHEN** `collection_name` names a collection with only an IDF sparse vector and a text index on `pk`
- **THEN** `is_docpipe_supported_resource` reports `supported: false` and `sparse_eligible: false` regardless of `add_sparse_vector`

#### Scenario: Sparse-only collection with sparse mode on
- **WHEN** `add_sparse_vector` is true and `collection_name` names that same collection
- **THEN** `is_docpipe_supported_resource` reports `supported: true` and `stored_resource_metadata` is `{"vector_similarity": null, "dimension_size": null}`

#### Scenario: Collection failing the runtime checks
- **WHEN** `collection_name` names a collection with a single unnamed vector, or with a non-keyword index on `pk`
- **THEN** `is_docpipe_supported_resource` reports `supported: false` with a reason, because the same collection would be rejected at run time

#### Scenario: Sparse defaults for a new collection
- **WHEN** `add_sparse_vector` is true, `collection_name` is new, and the node has no saved mappings
- **THEN** the returned `feature_mappings` include `content` mapped to `text` and `sparse_embeddings` mapped to `sparse_embeddings`

#### Scenario: No URL or host configured
- **WHEN** the node's `provider_config` contains neither a `url` nor a `host` key
- **THEN** enrichment returns the plain empty five-key result with no `error`, without raising

#### Scenario: Qdrant unreachable or rejecting during enrichment
- **WHEN** the server cannot be reached or rejects the API key
- **THEN** enrichment does not raise, other nodes are still enriched, and the node's `is_docpipe_supported_resource` is `{"supported": false, "error": "<redacted reason>"}` where the reason contains no key

#### Scenario: Reachable server with no collections
- **WHEN** the server is reachable but holds no collections
- **THEN** `available_resources` is empty and `is_docpipe_supported_resource` carries no `error`
