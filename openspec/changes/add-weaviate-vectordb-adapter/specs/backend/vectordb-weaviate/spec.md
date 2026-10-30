# Spec Delta

## Purpose

The Weaviate provider of the `vectordb` operator. It defines how `provider: "weaviate"` is configured, authenticated, and connected to, how collections are created and validated, how re-ingest stays idempotent, and how failures and flow-enrichment metadata are reported. The provider-agnostic table, metadata, and provider-selection contract lives in `backend/vectordb-operator`; this capability does not repeat it.

Configuration problems are detected while the operator is constructed, before any network connection. They surface as initialization failures: the adapter's message is wrapped by the vector store factory ("Failed to create vector store adapter 'weaviate': ...") and by the operator ("Failed to initialize vector database adapter 'weaviate': ..."), and flow validation reports it as "Validation failed for operator 'vectordb': ...". Every requirement below that says "fails to initialize" means the original message text is contained in each of those wrapped messages.

## ADDED Requirements

### Requirement: Weaviate provider registration
The operator SHALL accept `provider: "weaviate"` and route all writes to the Weaviate deployment described by `provider_config`. Operator metadata SHALL list `weaviate` among the `provider` valid values and SHALL publish a `provider_config` field schema for it. Selecting another provider MUST NOT change its behavior.

#### Scenario: Weaviate listed in operator metadata
- **WHEN** a client requests the `vectordb` operator metadata
- **THEN** the `provider` attribute's valid values include `weaviate` alongside `opensearch` and `milvus`, and `provider_config.providers.weaviate` describes the Weaviate configuration fields with their types, defaults, and descriptions

#### Scenario: Credential fields masked in metadata
- **WHEN** a client requests the `vectordb` operator metadata
- **THEN** the `api_key`, `bearer_token`, and `password` fields of `provider_config.providers.weaviate` are marked sensitive

### Requirement: Weaviate connection configuration validation
The Weaviate `provider_config` SHALL require `collection_name`, matching `^[A-Z][_0-9A-Za-z]*$`. It SHALL support a self-hosted deployment (host, HTTP port default 8080, gRPC host and port default 50051, TLS) and a Weaviate Cloud deployment (cluster URL). The operator SHALL fail to initialize, before connecting, for each missing or invalid field, with a message that names the field. The failure message MUST NOT contain any value taken from `provider_config`.

#### Scenario: Collection name missing
- **WHEN** a `weaviate` node's `provider_config` omits `collection_name`
- **THEN** the operator fails to initialize with a message stating that `collection_name` is not provided, and no connection is attempted

#### Scenario: Collection name naming rule
- **WHEN** `collection_name` is evaluated against the Weaviate collection naming pattern `^[A-Z][_0-9A-Za-z]*$`
- **THEN** the values below are accepted or rejected as listed, and each rejection fails initialization with a message stating that the name must start with an uppercase ASCII letter and contain only ASCII letters, digits, and underscores

| Collection name | Result |
|---|---|
| `DocumentChunks` | accepted |
| `Docs_2025` | accepted |
| `A` | accepted |
| `documentChunks` | rejected |
| `2Docs` | rejected |
| `Doc-Chunks` | rejected |
| `Doc Chunks` | rejected |
| (empty) | rejected |

#### Scenario: Cloud deployment without cluster URL
- **WHEN** the deployment is Weaviate Cloud and no cluster URL is provided
- **THEN** the operator fails to initialize with a message stating that the cluster URL is required

#### Scenario: Pattern not published in metadata
- **WHEN** a client requests the `vectordb` operator metadata
- **THEN** the collection-name rule is enforced by the backend only; clients that need it carry their own copy

### Requirement: Weaviate authentication
The Weaviate provider SHALL support four authentication methods: none, API key, bearer token, and OIDC username/password. Each method SHALL require its credential fields. Credentials SHALL be literals or `$VAR` / `${VAR}` references; a `vault://` reference is resolved by the executor before the adapter is built. Credentials MUST NOT appear in log output or in any raised message.

#### Scenario: API key method without key
- **WHEN** the authentication method is API key and no API key is provided
- **THEN** the operator fails to initialize with a message stating that the API key is required

#### Scenario: Environment variable credential
- **WHEN** the API key is configured as `$WEAVIATE_API_KEY` or `${WEAVIATE_API_KEY}` and that variable is set
- **THEN** the connection authenticates with the variable's value and the value is not logged

#### Scenario: Vault reference resolved upstream
- **WHEN** a credential is configured as a `vault://` reference and the secret provider is registered
- **THEN** the adapter receives the resolved plain value, contains no Vault resolution code, and the value is not logged

#### Scenario: Vault reference during flow validation
- **WHEN** a flow containing a `vectordb` node with a `vault://` credential over TLS is validated, so that flow validation has replaced the credential with its placeholder
- **THEN** configuration and TLS checks still run, no connection to the server is attempted, and validation does not fail because of the placeholder credential

#### Scenario: Placeholder text outside flow validation
- **WHEN** a run, not a flow validation, configures a credential whose text equals the validation placeholder
- **THEN** the connection is attempted with that value like any other credential

#### Scenario: Unresolvable Vault reference on a run
- **WHEN** a run's `vault://` credential cannot be resolved because the secret provider is not registered or resolution fails
- **THEN** the run fails before the adapter is built, and the reference text is not sent to the server as a credential

#### Scenario: Unset environment variable
- **WHEN** the API key is configured as `${WEAVIATE_API_KEY}` and that variable is not set
- **THEN** the operator fails to initialize, before connecting, with a message that names `WEAVIATE_API_KEY` and contains no credential value

#### Scenario: Literal all-caps credential
- **WHEN** a literal credential consists only of upper-case letters and underscores and an environment variable of that exact name exists
- **THEN** the environment variable's value is substituted, because that is the behavior of the shared environment resolver; an explicit `$VAR` reference is the recommended form for environment values

#### Scenario: Secret never disclosed on failure
- **WHEN** a connection or write error raised by the Weaviate client echoes a configured credential value or an `Authorization` header
- **THEN** the message raised by the adapter, the factory, and the operator, every log record, and every failed-item reason show a redaction marker in place of the secret

### Requirement: Credentials require an encrypted connection
The Weaviate provider SHALL NOT send credentials over an unencrypted connection. For a self-hosted deployment with any authentication method other than none, both the HTTP and gRPC connections SHALL use TLS; otherwise initialization SHALL fail before any connection is attempted. The same check SHALL run whenever a connection is built, including flow enrichment. A gRPC setting left unset inherits the HTTP TLS setting.

#### Scenario: Credentials over plaintext HTTP
- **WHEN** a self-hosted `weaviate` node uses API key, bearer token, or username/password authentication and the HTTP connection is not secure
- **THEN** the operator fails to initialize with a message stating that `secure` and `grpc_secure` must both be true when authentication is configured, and no connection is attempted

#### Scenario: Credentials with plaintext gRPC only
- **WHEN** a self-hosted `weaviate` node uses authentication, the HTTP connection is secure, and the gRPC connection is explicitly not secure
- **THEN** the operator fails to initialize with the same message, and no connection is attempted

#### Scenario: Unauthenticated local server
- **WHEN** a self-hosted `weaviate` node uses no authentication and leaves the TLS settings at their defaults
- **THEN** the configuration is accepted and the connection is plaintext, because plaintext is the default for a self-hosted deployment without authentication

#### Scenario: Authenticated TLS connection
- **WHEN** a self-hosted `weaviate` node uses API key authentication, the HTTP connection is secure, and the gRPC TLS setting is left unset
- **THEN** the configuration is accepted and both connections use TLS

#### Scenario: Flow validation disabled
- **WHEN** flow validation is disabled and a self-hosted `weaviate` node uses authentication over a non-secure connection
- **THEN** the operator still fails to initialize with the same message before any network connection is made, and no credential is sent

#### Scenario: Enrichment with authentication over plaintext
- **WHEN** flow enrichment runs for a self-hosted `weaviate` node that uses authentication over a non-secure connection
- **THEN** enrichment reports `is_docpipe_supported_resource` as `supported: false` with a redacted `error`, without connecting and without sending a credential

#### Scenario: Weaviate Cloud
- **WHEN** a `weaviate` node uses the Weaviate Cloud deployment with an API key
- **THEN** the connection uses TLS for both HTTP and gRPC with no additional setting

### Requirement: Weaviate connection failure reporting
When the configured Weaviate deployment cannot be reached or rejects the credentials, the operator SHALL fail to initialize with an error that identifies Weaviate, the target host or cluster URL, and the redacted underlying cause. No partial writes SHALL occur.

#### Scenario: Server unreachable
- **WHEN** the configured host and port have no reachable Weaviate server
- **THEN** operator initialization fails with an error naming Weaviate and the target address, and no objects are written

### Requirement: Weaviate collection creation with named vectors
When `create_index` is true and the collection does not exist, the provider SHALL create it with one self-provided named vector per detected dense vector column, named by the column's mapped name and configured with the selected index type (`hnsw` default, `flat`, `dynamic`) and distance metric (`cosine` default, `dot`, `l2-squared`, `manhattan`, `hamming`). A server that refuses the `dynamic` index SHALL produce a failure naming async indexing.

#### Scenario: Single embedding column
- **WHEN** a new collection is created for a run whose `embeddings` column is mapped to `vector_embeddings` and has dimension 384
- **THEN** the collection has exactly one named vector `vector_embeddings` using the configured index type and distance metric, and stored objects carry 384-dimensional vectors under that name

#### Scenario: Multiple embedding models
- **WHEN** a run has two dense vector columns mapped to `vector_embeddings` and `vector_embeddings_alt`
- **THEN** the collection has two named vectors and each object stores both vectors

#### Scenario: Invalid index parameters
- **WHEN** `index_parameters` contains a parameter the selected index type does not accept
- **THEN** collection creation fails, all documents in scope are recorded as failed with a reason naming the invalid parameter, and `node_status` is `FAILED`

#### Scenario: Dynamic index on a server without async indexing
- **WHEN** `index_type` is `dynamic` and the server does not have async indexing enabled
- **THEN** no collection is created, all documents in scope are recorded as failed with a reason stating that `dynamic` requires async indexing and suggesting `hnsw` or `flat`, and `node_status` is `FAILED`

#### Scenario: Dynamic index with async indexing
- **WHEN** `index_type` is `dynamic` and the server has async indexing enabled
- **THEN** the collection is created with a dynamic index, and vector queries return the written objects once the server's indexing queue is empty

### Requirement: Fixed identity property
The provider's identity property in every Weaviate collection SHALL be named `pk`. It is an ordinary text property, distinct from the Weaviate object UUID. The provider SHALL declare it itself and SHALL store the chunk's primary key verbatim in it. Initialization SHALL fail, before connecting, when a feature mapping sends the primary feature to any name other than `pk`, or sends any other feature to `pk`, so that a collection never has two identity properties.

#### Scenario: Primary feature mapped to pk
- **WHEN** the primary feature is mapped to `pk`
- **THEN** the operator initializes and the collection declares exactly one primary-key property, `pk`

#### Scenario: Primary feature mapped elsewhere
- **WHEN** the primary feature is mapped to a name other than `pk`, such as `chunk_id`
- **THEN** the operator fails to initialize, before connecting, with a message stating that the primary key property must be `pk`, and no property `chunk_id` is created

#### Scenario: Another feature mapped to pk
- **WHEN** a feature other than the primary feature is mapped to `pk`
- **THEN** the operator fails to initialize, before connecting, with a message stating that `pk` is reserved for the primary key

### Requirement: Weaviate property schema mapping
New collections SHALL declare one property per mapped non-vector feature, plus the primary-key property and the content property. Feature types SHALL map as follows: text/string/keyword/date to text; integer types to int; float/double to number; bool to boolean; json/object/nested to text holding serialized JSON.

#### Scenario: Typed metadata properties
- **WHEN** features `page_count` (`int32`), `score` (`double`), and `is_scanned` (`bool`) are mapped
- **THEN** the collection declares `page_count` as int, `score` as number, and `is_scanned` as boolean

#### Scenario: Structured value stored as JSON text
- **WHEN** a mapped `json` feature value is a dictionary
- **THEN** the stored property value is that dictionary serialized as a JSON string

### Requirement: Exact-match identity properties
The `pk` property, the properties mapped from the `id` and `name` features, and any `keyword` feature SHALL be stored with whole-value (`field`) tokenization and be filterable, so that equality and prefix filters match the whole value and nothing else, and so that ordered paging over the primary key returns every key. Content and other text properties SHALL remain keyword-searchable by word, whether or not `add_sparse_vector` is set.

#### Scenario: Identifier containing underscores
- **WHEN** a chunk primary key such as `<file-hash>_chunk_3` is stored
- **THEN** an equality filter on the primary-key property for that exact value returns exactly that object and does not match `<file-hash>_chunk_30`

#### Scenario: Names sharing tokens
- **WHEN** documents named `report_2025.pdf` and `report-2025.pdf` are both stored
- **THEN** an equality filter on the mapped name property for `report_2025.pdf` returns only that document's objects

#### Scenario: Content remains keyword searchable
- **WHEN** chunk text containing the word "invoice" is stored in the mapped content property
- **THEN** a BM25 query for "invoice" against that property returns the object

### Requirement: Weaviate sparse (BM25) retrieval mode
When `add_sparse_vector` is true, the provider SHALL configure keyword (BM25) retrieval over the inverted index of the mapped content property, a text property that is searchable and tokenized by word. The content feature MUST be mapped. The collection SHALL record BM25 parameters k1 = 1.2 and b = 0.75, which are Weaviate's own defaults. A `sparse_embeddings` mapping SHALL be accepted but not stored. Runs without dense vector columns SHALL be allowed when the chunks are provided in memory.

#### Scenario: Top-level flag is authoritative
- **WHEN** `add_sparse_vector` is set only inside `provider_config` and not at the operator's top level
- **THEN** the collection is configured for BM25, but runs without dense vector columns are not enabled

#### Scenario: Hybrid dense and sparse
- **WHEN** sparse mode is on, `embeddings` is mapped to `vector_embeddings`, and `content` is mapped to `text`
- **THEN** the collection has the named vector `vector_embeddings` and BM25 parameters k1 = 1.2 and b = 0.75, a BM25 query for a word in a chunk returns that chunk's object, and a hybrid query combining that word with the chunk's vector also returns it

#### Scenario: Sparse only with in-memory chunks
- **WHEN** sparse mode is on, `available_features` declares no dense vector column, and the input chunks are provided in memory
- **THEN** the collection is created as a keyword-only collection whose single declared vector is not indexed, no automatically added default vector index exists, every chunk is written with its text and no vector, the run is not marked `FAILED`, and BM25 queries return the chunks

#### Scenario: Sparse only with memory-mapped chunks
- **WHEN** sparse mode is on, `available_features` declares no dense vector column, and the input chunks are memory-mapped file references
- **THEN** this is an existing operator limitation independent of the provider: the affected documents are recorded as failed, and the documentation states that sparse-only runs require in-memory chunks

#### Scenario: Content not mapped
- **WHEN** sparse mode is on and no feature mapping targets the content feature
- **THEN** the operator fails to initialize, before connecting, with a message stating that sparse mode requires the content feature to be mapped to a text property

#### Scenario: Sparse mapping not stored
- **WHEN** the mappings include `sparse_embeddings` mapped to `sparse_embeddings`
- **THEN** the collection has no `sparse_embeddings` property and no written object carries one

### Requirement: Existing Weaviate collection validation
When the collection already exists, the provider SHALL verify vector columns, property types, identity-property tokenization, and that the content property is searchable and word-tokenized, whether or not `add_sparse_vector` is set. A run with no dense vector columns SHALL skip only the vector checks. Missing properties SHALL be added only when no check failed.

#### Scenario: Dimension mismatch
- **WHEN** the existing collection stores 768-dimensional vectors under `vector_embeddings` and the current run produces 384-dimensional embeddings
- **THEN** no objects are written, every document in scope is recorded as failed with a reason stating both dimensions, and `node_status` is `FAILED`

#### Scenario: Missing named vector
- **WHEN** the run maps a vector column to `vector_embeddings_alt` and the existing collection has no named vector with that name
- **THEN** no objects are written and the failure reason names the missing vector

#### Scenario: New metadata property on existing collection
- **WHEN** the run maps a feature `department` that the existing collection lacks
- **THEN** the property `department` is added with the mapped type before objects are written, and the written objects carry it

#### Scenario: Empty existing collection
- **WHEN** the collection exists with matching named vectors but contains no objects
- **THEN** the dimension check is skipped and the write proceeds

#### Scenario: Non-searchable content property
- **WHEN** the existing collection's mapped content property is not searchable or is not word-tokenized, with `add_sparse_vector` either true or false
- **THEN** no objects are written and the failure reason names the content property and states that keyword retrieval requires it to be searchable and word-tokenized

#### Scenario: Field-tokenized content in a dense-only run
- **WHEN** `add_sparse_vector` is false, the existing collection has an indexed named vector and a valid `pk`, and its content property is searchable but field-tokenized
- **THEN** no objects are written and the failure reason names the content property and its tokenization, because a BM25 query for a single word would return nothing

#### Scenario: Sparse-only run on an existing collection
- **WHEN** sparse mode is on, the run has no dense vector columns, and the existing collection is keyword-only (all vectors skipped, or no named vectors with a skipped legacy vector index) or has indexed vectors, with a searchable, word-tokenized content property and whole-value identity properties
- **THEN** no vector configuration is checked and the write proceeds

#### Scenario: Sparse-only run still checks scalar types
- **WHEN** sparse mode is on, the run has no dense vector columns, and the existing collection stores a mapped property with a type that differs from the mapped type
- **THEN** no objects are written and the failure reason names the property and both types

#### Scenario: Identity property with word tokenization
- **WHEN** the existing collection's `pk` property, or a property mapped from `id`, `name`, or a `keyword` feature, uses word tokenization or is not filterable
- **THEN** no objects are written, nothing is deleted, and the failure reason names the property, states that it must use whole-value tokenization and be filterable, and tells the user to recreate the property or use a new collection name

#### Scenario: Keyword-only collection with a dense run
- **WHEN** the run has a dense vector column and the existing collection is keyword-only, in either shape (every named vector skipped, or no named vectors with a skipped legacy vector index)
- **THEN** no objects are written and the failure reason states that the collection has no indexed named vector

#### Scenario: Nothing is changed when a check fails
- **WHEN** the run maps a new property `department` and another check on the existing collection fails
- **THEN** the property `department` is not added

### Requirement: Unsupported Weaviate configurations rejected
The provider SHALL reject existing collections without an indexed named vector when the run has dense vector columns, and SHALL reject mapped property names it cannot store: names outside the property-name pattern (a letter or underscore followed by letters, digits, or underscores), and the reserved names `id`, `_id`, `_additional`, `vector`, and `_vector`. Each rejection SHALL return an actionable message.

#### Scenario: Reserved property name
- **WHEN** a feature is mapped to the target name `id`
- **THEN** the operator fails to initialize, before connecting, with a message naming the reserved property

#### Scenario: Legacy single-vector collection
- **WHEN** the configured existing collection has no named vectors and the run has dense vector columns
- **THEN** no objects are written and the failure reason states that only collections with indexed named vectors are supported

### Requirement: Property names are stored as given
Weaviate lower-cases the first character of a property name. The provider SHALL therefore reject, before connecting, mapped property names whose first character is upper case and two mapped names that differ only by case, so that writes, filters, and reads all use the stored spelling.

#### Scenario: Upper-case first character
- **WHEN** a feature is mapped to the target name `Department`
- **THEN** the operator fails to initialize, before connecting, with a message naming `Department` and suggesting `department`

#### Scenario: Names differing only by case
- **WHEN** two features are mapped to `fileName` and `filename`
- **THEN** the operator fails to initialize, before connecting, with a message naming both properties

#### Scenario: Existing property stored with a lower-cased first character
- **WHEN** the existing collection was created with a property `Department` and the run maps a feature to `department`
- **THEN** the existing property is recognized as `department` and no second property is added

### Requirement: ACL enforcement not supported for Weaviate
The Weaviate provider SHALL NOT store or enforce document access-control lists. A `feature_mappings` entry for the ACL operator's `allowed_users` feature SHALL be dropped from the collection schema and from every written object, with one warning naming the dropped mapping. When `allowed_users` is present upstream but unmapped, the write SHALL proceed with one warning that ACLs are not enforced.

#### Scenario: allowed_users mapped
- **WHEN** a `weaviate` node maps `allowed_users` to a target property
- **THEN** the operator initializes and writes normally, the collection has no property for that mapping, no written object carries it, and one warning states that ACLs are not supported for Weaviate and the mapping was ignored

#### Scenario: ACL operator upstream, feature unmapped
- **WHEN** `available_features` contains `allowed_users` and no mapping references it
- **THEN** objects are written without any ACL property and one warning states that ACLs are not enforced for Weaviate

#### Scenario: No access-control configuration on the collection
- **WHEN** the provider creates or validates a collection
- **THEN** it configures no multi-tenancy, no RBAC roles or permissions, and no ACL-related properties

### Requirement: Schema templates ignored for Weaviate
The Weaviate provider SHALL ignore the operator-level `schema_template_path` option, which applies only to OpenSearch index templates. When it is set, the provider SHALL log one warning naming the option, SHALL NOT read the file, and SHALL build the collection schema from feature mappings alone.

#### Scenario: Schema template path set
- **WHEN** a `weaviate` node sets `schema_template_path` to a path, including one that does not exist
- **THEN** the operator initializes without error, one warning names the ignored option, and the created collection is identical to one created without the option

### Requirement: Deterministic object identity and in-place re-ingest
Each Weaviate object SHALL use a UUIDv5 derived from the chunk's positional primary key, which is formed from the hashed file ID and the chunk index. The primary-key property SHALL store that key verbatim. Writing an object whose UUID already exists SHALL replace it, so re-ingesting a document never duplicates chunks.

#### Scenario: Unchanged re-ingest
- **WHEN** the same document is ingested twice with identical content
- **THEN** the collection's object count is the same after the second run as after the first

#### Scenario: Modified chunk content
- **WHEN** a document is re-ingested after the text of chunk 2 changed
- **THEN** the object for chunk 2 keeps its UUID and its stored text and vector reflect the new content

### Requirement: Stale chunk cleanup on re-ingest
Before writing, the provider SHALL find existing objects for each file in the batch by primary-key prefix and delete those whose primary key is not among the keys of the current run. The lookup SHALL match only that file's keys and SHALL return every matching key however many chunks the file has, without being limited by the server's maximum query result size. A cleanup failure SHALL be logged as a warning and SHALL NOT prevent the write.

#### Scenario: Document shrinks
- **WHEN** a document previously stored as 5 chunks is re-ingested as 3 chunks
- **THEN** the objects for chunk indexes 3 and 4 are deleted and exactly 3 objects remain for that file

#### Scenario: Other files untouched
- **WHEN** files A and B are both stored and only A is re-ingested with fewer chunks
- **THEN** only A's surplus objects are deleted and every object for B remains

#### Scenario: File with more chunks than one query can return
- **WHEN** a file previously stored as 12,000 chunks is re-ingested as 100 chunks, and the server's maximum query result size is 10,000
- **THEN** the lookup returns all 12,000 stored keys across several pages, 11,900 objects are deleted, and exactly 100 remain for that file

#### Scenario: Cleanup query fails
- **WHEN** looking up existing chunks fails with a server error
- **THEN** a warning is logged and the new chunks are still written

### Requirement: Batched writes with per-chunk failure attribution
The provider SHALL write objects in batches no larger than `batch_size` objects and a bounded payload size. Each object the server rejects SHALL be reported with its chunk primary key and the server's redacted error message. The operator SHALL then record the owning document as failed with reason "One or more chunks failed to index", while other objects in the batch are still written.

#### Scenario: One object rejected
- **WHEN** a batch of 100 objects is written and the server rejects one object for a property type mismatch
- **THEN** 99 objects are stored, `chunks_failed_to_index` is 1, and the rejected chunk's parent document appears in `failed_docs`

#### Scenario: Whole batch request fails
- **WHEN** a batch request fails entirely, for example because of a network error
- **THEN** every object in that batch is reported as failed with the redacted request error, and subsequent batches are still attempted

#### Scenario: Every object in a batch rejected
- **WHEN** the server rejects every object in a batch, for example a single-object batch whose integer property receives text, and the client reports this as one error without per-object detail
- **THEN** every object in that batch is reported as failed with the redacted error message, the owning documents appear in `failed_docs`, and subsequent batches are still attempted



### Requirement: Weaviate maintenance operations
The provider SHALL support deleting objects by chunk primary key, returning success and failure counts and processing any number of keys in bounded requests. It SHALL also support returning the total object count and querying objects by document name through the mapped name property.

#### Scenario: Delete more keys than one request allows
- **WHEN** deletion is requested for 25,000 chunk primary keys
- **THEN** all matching objects are deleted across multiple requests and the returned success count equals the number deleted

#### Scenario: Count on missing or unreachable collection
- **WHEN** the object count is requested and the request fails
- **THEN** the count is reported as 0 and the error is logged

### Requirement: Weaviate connection lifecycle
The provider SHALL close its Weaviate connection (HTTP and gRPC) on every path that opened it: after every transform, after flow validation, after enrichment, and when a failure occurs after the connection opened. Closing SHALL be idempotent.

#### Scenario: Transform fails mid-write
- **WHEN** the transform raises an error after the connection is opened
- **THEN** the connection is closed before the error is reported

#### Scenario: Flow validation only
- **WHEN** a `vectordb` node with `provider: "weaviate"` is validated in a flow and no transform runs
- **THEN** the connection opened during construction is closed when validation finishes, whether or not validation reported errors

#### Scenario: Readiness check fails after connecting
- **WHEN** the client connects but the readiness check fails, or a later step of construction raises
- **THEN** the opened connection is closed before the error is raised

#### Scenario: Close called twice
- **WHEN** the connection has already been closed and `close()` is called again
- **THEN** no error is raised

### Requirement: Weaviate flow-enrichment metadata
For `vectordb` nodes with `provider: "weaviate"`, flow enrichment SHALL return `available_resources`, `selected_resource_schema`, `feature_mappings`, `is_docpipe_supported_resource`, and `stored_resource_metadata` (`vector_similarity`, `dimension_size`), with `vector_similarity` being the Weaviate distance metric name unchanged. Vectors whose index is skipped SHALL NOT be listed. `is_docpipe_supported_resource` MAY carry `sparse_eligible` and `error`, as the scenarios below describe.

#### Scenario: Existing collection described
- **WHEN** enrichment runs for a node whose `collection_name` names an existing collection with named vector `vector_embeddings` (cosine) holding 384-dimensional vectors
- **THEN** `available_resources` includes the collection, `selected_resource_schema.vector_embeddings` reports type `VECTOR`, distance `cosine`, and dimension 384, and `stored_resource_metadata` is `{"vector_similarity": "cosine", "dimension_size": 384}`

#### Scenario: Distance metric names passed through
- **WHEN** an existing collection's named vector uses `l2-squared`
- **THEN** `stored_resource_metadata.vector_similarity` is `l2-squared`

#### Scenario: New collection name
- **WHEN** `collection_name` is not among the existing collections
- **THEN** `is_docpipe_supported_resource.supported` is true and `feature_mappings` are the defaults computed from `available_features` unless the node has saved mappings

#### Scenario: Keyword-only collection with sparse mode off
- **WHEN** `collection_name` names an existing keyword-only collection (every named vector skipped, or no named vectors with a skipped legacy vector index), `add_sparse_vector` is false, and its mapped content property is searchable and word-tokenized and its identity properties are field-tokenized
- **THEN** `is_docpipe_supported_resource` reports `supported: false` with a reason and `sparse_eligible: true`

#### Scenario: Keyword-only collection with sparse mode on
- **WHEN** `add_sparse_vector` is true and `collection_name` names that same eligible keyword-only collection
- **THEN** `is_docpipe_supported_resource` reports `supported: true` and `stored_resource_metadata` is `{"vector_similarity": null, "dimension_size": null}`

#### Scenario: Ineligible keyword-only collection
- **WHEN** `collection_name` names a keyword-only collection whose content property is not searchable, or whose `pk` is word-tokenized
- **THEN** `is_docpipe_supported_resource` reports `supported: false` and `sparse_eligible: false` regardless of `add_sparse_vector`

#### Scenario: Indexed collection failing the scalar checks
- **WHEN** `collection_name` names a collection with an indexed named vector whose content property is searchable but `field`-tokenized, or whose `pk` is word-tokenized
- **THEN** `is_docpipe_supported_resource` reports `supported: false` with a reason, because the same collection would be rejected at run time in every mode

#### Scenario: Skipped vectors not listed
- **WHEN** an existing collection has one indexed named vector and one vector whose index is skipped
- **THEN** `selected_resource_schema` lists only the indexed vector

#### Scenario: Sparse defaults for a new collection
- **WHEN** `add_sparse_vector` is true, `collection_name` is new, and the node has no saved mappings
- **THEN** the returned `feature_mappings` include `content` mapped to `text` and `sparse_embeddings` mapped to `sparse_embeddings`

#### Scenario: No host or cluster URL configured
- **WHEN** no host or cluster URL is configured for the node
- **THEN** enrichment returns the plain empty five-key result with no `error`, without raising

#### Scenario: Weaviate unreachable or rejecting during enrichment
- **WHEN** the deployment cannot be reached or rejects the credentials
- **THEN** enrichment does not raise, other nodes are still enriched, and the node's `is_docpipe_supported_resource` is `{"supported": false, "error": "<redacted reason>"}` where the reason contains no credential

#### Scenario: Reachable deployment with no collections
- **WHEN** the deployment is reachable but holds no collections
- **THEN** `available_resources` is empty and `is_docpipe_supported_resource` carries no `error`
