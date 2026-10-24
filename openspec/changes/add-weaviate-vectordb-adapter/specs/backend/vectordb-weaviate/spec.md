# Spec Delta

## Purpose

The Weaviate provider of the `vectordb` operator. It defines how `provider: "weaviate"` is configured, authenticated, and connected to, how collections are created and validated, how re-ingest stays idempotent, and how failures and flow-enrichment metadata are reported. The provider-agnostic table, metadata, and provider-selection contract lives in `backend/vectordb-operator`; this capability does not repeat it.

## ADDED Requirements

### Requirement: Weaviate provider registration
The operator SHALL accept `provider: "weaviate"` and route all writes to the Weaviate deployment described by `provider_config`. Operator metadata SHALL list `weaviate` among the `provider` valid values and SHALL publish a `provider_config` field schema for it. Selecting another provider MUST NOT change its behavior.

#### Scenario: Weaviate listed in operator metadata
- **WHEN** a client requests the `vectordb` operator metadata
- **THEN** the `provider` attribute's valid values include `weaviate` alongside `opensearch` and `milvus`, and `provider_config.providers.weaviate` describes the Weaviate configuration fields with their types, defaults, and descriptions

### Requirement: Weaviate connection configuration validation
The Weaviate `provider_config` SHALL require `collection_name`, matching `^[A-Z][_0-9A-Za-z]*$`. It SHALL support a self-hosted deployment (host, HTTP port default 8080, gRPC host and port default 50051, TLS) and a Weaviate Cloud deployment (cluster URL). Flow validation SHALL report each missing or invalid field as an error.

#### Scenario: Collection name missing
- **WHEN** a `weaviate` node's `provider_config` omits `collection_name`
- **THEN** flow validation reports `collection_name is not provided`

#### Scenario: Collection name violates Weaviate naming conventions
- **WHEN** `collection_name` does not match the Weaviate collection naming pattern `^[A-Z][_0-9A-Za-z]*$`
- **THEN** flow validation reports an error stating that the collection name must start with an uppercase ASCII letter and contain only ASCII letters, digits, and underscores.

#### Scenario: Cloud deployment without cluster URL
- **WHEN** the deployment is Weaviate Cloud and no cluster URL is provided
- **THEN** flow validation reports that the cluster URL is required

### Requirement: Weaviate authentication
The Weaviate provider SHALL support four authentication methods: no authentication, API key, bearer token, and OIDC username/password. Each method SHALL require its credential fields. Credential values written as `$ENV_VAR` references SHALL be resolved from the environment at runtime, and credentials MUST NOT appear in log output.

#### Scenario: API key method without key
- **WHEN** the authentication method is API key and no API key is provided
- **THEN** flow validation reports that the API key is required

#### Scenario: Environment variable credential
- **WHEN** the API key is configured as `$WEAVIATE_API_KEY` and that variable is set
- **THEN** the connection authenticates with the variable's value and the value is not logged

### Requirement: Weaviate connection failure reporting
When the configured Weaviate deployment cannot be reached or rejects the credentials, the operator SHALL fail to initialize with an error that identifies Weaviate, the target host or cluster URL, and the underlying cause. No partial writes SHALL occur.

#### Scenario: Server unreachable
- **WHEN** the configured host and port have no reachable Weaviate server
- **THEN** operator initialization fails with an error naming Weaviate and the target address, and no objects are written

### Requirement: Weaviate collection creation with named vectors
When `create_index` is true and the collection does not exist, the provider SHALL create it with one self-provided named vector per detected dense vector column. Each vector SHALL be named by the column's mapped name and configured with the selected index type (`hnsw` default, `flat`, `dynamic`) and distance metric (`cosine` default, `dot`, `l2-squared`, `manhattan`, `hamming`).

#### Scenario: Single embedding column
- **WHEN** a new collection is created for a run whose `embeddings` column is mapped to `vector_embeddings` and has dimension 384
- **THEN** the collection has exactly one named vector `vector_embeddings` using the configured index type and distance metric, and stored objects carry 384-dimensional vectors under that name

#### Scenario: Multiple embedding models
- **WHEN** a run has two dense vector columns mapped to `vector_embeddings` and `vector_embeddings_alt`
- **THEN** the collection has two named vectors and each object stores both vectors

#### Scenario: Invalid index parameters
- **WHEN** `index_parameters` contains a parameter the selected index type does not accept
- **THEN** collection creation fails, all documents in scope are recorded as failed with a reason naming the invalid parameter, and `node_status` is `FAILED`

### Requirement: Weaviate property schema mapping
New collections SHALL declare one property per mapped non-vector feature, plus the primary-key property and the content property. Feature types SHALL map as follows: text/string/keyword/date to text; integer types to int; float/double to number; bool to boolean; json/object/nested to text holding serialized JSON.

#### Scenario: Typed metadata properties
- **WHEN** features `page_count` (`int32`), `score` (`double`), and `is_scanned` (`bool`) are mapped
- **THEN** the collection declares `page_count` as int, `score` as number, and `is_scanned` as boolean

#### Scenario: Structured value stored as JSON text
- **WHEN** a mapped `json` feature value is a dictionary
- **THEN** the stored property value is that dictionary serialized as a JSON string

### Requirement: Exact-match identity properties
The primary-key property and the properties mapped from the `id` and `name` features, and any `keyword` feature, SHALL be stored so that equality and prefix filters match the whole value. Content and other text properties SHALL remain keyword-searchable (BM25) by word, whether or not `add_sparse_vector` is set.

#### Scenario: Identifier containing underscores
- **WHEN** a chunk primary key such as `<file-hash>_chunk_3` is stored
- **THEN** an equality filter on the primary-key property for that exact value returns exactly that object and does not match `<file-hash>_chunk_30`

#### Scenario: Content remains keyword searchable
- **WHEN** chunk text containing the word "invoice" is stored in the mapped content property
- **THEN** a BM25 query for "invoice" against that property returns the object

### Requirement: Weaviate sparse (BM25) retrieval mode
When `add_sparse_vector` is true, the provider SHALL offer BM25 sparse retrieval over the mapped content property, matching the Milvus provider's server-computed BM25 sparse mode. The content feature MUST be mapped. BM25 SHALL use k1 = 1.2 and b = 0.75. A `sparse_embeddings` mapping SHALL be accepted but not stored, because scores are computed at query time. Runs without dense vector columns SHALL be allowed.

#### Scenario: Hybrid dense and sparse
- **WHEN** sparse mode is on, `embeddings` is mapped to `vector_embeddings`, and `content` is mapped to `text`
- **THEN** the collection has the named vector `vector_embeddings` and BM25 parameters k1 = 1.2 and b = 0.75, a BM25 query for a word in a chunk returns that chunk's object, and a hybrid query combining that word with the chunk's vector also returns it

#### Scenario: Sparse only
- **WHEN** sparse mode is on and `available_features` declares no dense vector column
- **THEN** the collection is created without named vectors, every chunk is written with its text, the run is not marked `FAILED`, and BM25 queries return the chunks

#### Scenario: Content not mapped
- **WHEN** sparse mode is on and no feature mapping targets the content feature
- **THEN** the operator fails to initialize, before connecting, with a message stating that sparse mode requires the content feature to be mapped to a text property

#### Scenario: Sparse mapping not stored
- **WHEN** the mappings include `sparse_embeddings` mapped to `sparse_embeddings`
- **THEN** the collection has no `sparse_embeddings` property and no written object carries one

### Requirement: Existing Weaviate collection validation
When the collection already exists, the provider SHALL verify that every mapped vector column has a named vector of the same name. For non-empty collections it SHALL verify that the stored vector dimension equals the run's detected dimension, and that existing properties have compatible types. Missing scalar properties SHALL be added with the mapped type. In sparse mode the content property SHALL be keyword-searchable, and a run with no dense vector columns SHALL skip all vector checks.

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

#### Scenario: Sparse mode on a non-searchable content property
- **WHEN** sparse mode is on and the existing collection's mapped content property is not keyword-searchable
- **THEN** no objects are written and the failure reason names the content property and states that BM25 requires it to be searchable

#### Scenario: Sparse-only run on an existing collection
- **WHEN** sparse mode is on, the run has no dense vector columns, and the existing collection has a keyword-searchable content property
- **THEN** no vector configuration is checked and the write proceeds

### Requirement: Unsupported Weaviate configurations rejected
The provider SHALL reject existing collections without named vectors when the run has dense vector columns. It SHALL also reject mapped property names Weaviate cannot store: names not matching `^[_A-Za-z][_0-9A-Za-z]*$`, the reserved names `id`, `_id`, and `_additional`, and the names `vector` and `_vector`. Each rejection SHALL return an actionable message.

#### Scenario: Reserved property name
- **WHEN** a feature is mapped to the target name `id`
- **THEN** the operator fails to initialize, before connecting, with a message naming the reserved property

#### Scenario: Legacy single-vector collection
- **WHEN** the configured existing collection has no named vectors and the run has dense vector columns
- **THEN** no objects are written and the failure reason states that only collections with named vectors are supported

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
Before writing, the provider SHALL find existing objects for each file in the batch by primary-key prefix. It SHALL delete those whose primary key is not among the keys produced by the current run. The lookup SHALL match only that file's keys, relying on exact-match storage of the primary-key property. A cleanup failure SHALL be logged as a warning and SHALL NOT prevent the write.

#### Scenario: Document shrinks
- **WHEN** a document previously stored as 5 chunks is re-ingested as 3 chunks
- **THEN** the objects for chunk indexes 3 and 4 are deleted and exactly 3 objects remain for that file

#### Scenario: Other files untouched
- **WHEN** files A and B are both stored and only A is re-ingested with fewer chunks
- **THEN** only A's surplus objects are deleted and every object for B remains

#### Scenario: Cleanup query fails
- **WHEN** looking up existing chunks fails with a server error
- **THEN** a warning is logged and the new chunks are still written

### Requirement: Batched writes with per-chunk failure attribution
The provider SHALL write objects in batches no larger than `batch_size` objects and a bounded payload size. Each object the server rejects SHALL be reported with its chunk primary key and the server's error message. The operator SHALL then record the owning document as failed with reason "One or more chunks failed to index", while other objects in the batch are still written.

#### Scenario: One object rejected
- **WHEN** a batch of 100 objects is written and the server rejects one object for a property type mismatch
- **THEN** 99 objects are stored, `chunks_failed_to_index` is 1, and the rejected chunk's parent document appears in `failed_docs`

#### Scenario: Whole batch request fails
- **WHEN** a batch request fails entirely, for example because of a network error
- **THEN** every object in that batch is reported as failed with the request error, and subsequent batches are still attempted

### Requirement: Weaviate maintenance operations
The provider SHALL support deleting objects by chunk primary key, returning success and failure counts and processing any number of keys in bounded requests. It SHALL also support returning the total object count and querying objects by document name through the mapped name property.

#### Scenario: Delete more keys than one request allows
- **WHEN** deletion is requested for 25,000 chunk primary keys
- **THEN** all matching objects are deleted across multiple requests and the returned success count equals the number deleted

#### Scenario: Count on missing or unreachable collection
- **WHEN** the object count is requested and the request fails
- **THEN** the count is reported as 0 and the error is logged

### Requirement: Weaviate connection lifecycle
The provider SHALL close its Weaviate connection after every transform, whether the transform succeeds or fails.

#### Scenario: Transform fails mid-write
- **WHEN** the transform raises an error after the connection is opened
- **THEN** the connection is closed before the error is reported

### Requirement: Weaviate flow-enrichment metadata
For `vectordb` nodes with `provider: "weaviate"`, flow enrichment SHALL return `available_resources` (collection names), `selected_resource_schema` (properties with types, named vectors with distance metric and dimension when known), `feature_mappings`, `is_docpipe_supported_resource`, and `stored_resource_metadata` (`vector_similarity`, `dimension_size`).

#### Scenario: Existing collection described
- **WHEN** enrichment runs for a node whose `collection_name` names an existing collection with named vector `vector_embeddings` (cosine) holding 384-dimensional vectors
- **THEN** `available_resources` includes the collection, `selected_resource_schema.vector_embeddings` reports type `VECTOR`, distance `cosine`, and dimension 384, and `stored_resource_metadata` is `{"vector_similarity": "cosine", "dimension_size": 384}`

#### Scenario: New collection name
- **WHEN** `collection_name` is not among the existing collections
- **THEN** `is_docpipe_supported_resource.supported` is true and `feature_mappings` are the defaults computed from `available_features` unless the node has saved mappings

#### Scenario: Collection without named vectors
- **WHEN** `collection_name` names an existing collection that has no named vectors and `add_sparse_vector` is false
- **THEN** `is_docpipe_supported_resource` reports `supported: false` with a reason

#### Scenario: Sparse-only collection
- **WHEN** `add_sparse_vector` is true and `collection_name` names an existing collection with no named vectors whose mapped content property is keyword-searchable
- **THEN** `is_docpipe_supported_resource` reports `supported: true` and `stored_resource_metadata` is `{"vector_similarity": null, "dimension_size": null}`

#### Scenario: Sparse defaults for a new collection
- **WHEN** `add_sparse_vector` is true, `collection_name` is new, and the node has no saved mappings
- **THEN** the returned `feature_mappings` include `content` mapped to `text` and `sparse_embeddings` mapped to `sparse_embeddings`

#### Scenario: Weaviate unreachable during enrichment
- **WHEN** the deployment cannot be reached or no host or cluster URL is configured
- **THEN** enrichment returns the empty five-key result for that node without raising, and other nodes are still enriched
