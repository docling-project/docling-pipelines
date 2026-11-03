# VectorDBOperator

Indexes document embeddings into a vector database for similarity search.

- **Short Name:** `vectordb`
- **Category:** VectorDB

---

## Overview

`VectorDBOperator` takes a PyArrow table containing document embeddings and indexes it into a
vector database. It uses a hexagonal architecture (ports and adapters) so that the core operator
logic is independent of the underlying database; switching providers only requires a config change.

Supported providers: OpenSearch, Milvus, Weaviate.

---

## Key Features

- Multi-provider support via adapter pattern (OpenSearch, Milvus, Weaviate)
- Automatic index/collection creation on first run, with schema validation on later runs
- Provider-specific resource name declared inside `provider_config`
- Configurable KNN engine and algorithm (NMSLIB, Faiss, Lucene for OpenSearch)
- Hybrid search support (dense + sparse embeddings)
- Weaviate: one named vector per embedding column, deterministic object UUIDs so re-ingesting a file updates its chunks in place, and BM25 keyword search over the content property (see [Sparse (BM25) mode](#sparse-bm25-mode-weaviate))
- Batch-based indexing for throughput control
- Auto-detection of vector dimension from input data

---

## Operator Configuration

```json
{
  "type": "vectordb",
  "name": "index_documents",
  "config": {
    "provider": "opensearch",
    "vector_dimension": 384,
    "provider_config": {
      "index_name": "my_documents",
      "host": "localhost",
      "port": 9200,
      "use_ssl": false,
      "verify_certs": false,
      "engine": "nmslib",
      "algorithm": "hnsw",
      "space_type": "l2"
    }
  },
  "depends_on": ["generate_embeddings"]
}
```

---

## Parameters

### Core parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `provider` | string | Yes | — | Vector DB provider: `opensearch`, `milvus`, `weaviate` |
| `add_sparse_vector` | boolean | No | `false` | Enable sparse (keyword) mode. For Weaviate this is BM25 over the content property; see [Sparse (BM25) mode](#sparse-bm25-mode-weaviate). This top-level flag is authoritative |
| `doc_id_column` | string | No | `"doc_id_hash"` | Column used as primary key |
| `embeddings_column` | string | No | `"embeddings"` | Column containing dense embeddings |
| `sparse_embeddings_column` | string | No | — | Column containing sparse embeddings for hybrid search |
| `vector_dimension` | integer | No | auto | Embedding dimension (auto-detected from data if omitted) |
| `provider_config` | object | **Yes** | — | Provider-specific settings including the resource name (see below) |

### OpenSearch `provider_config` fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `index_name` | string | **Yes** | — | Name of the OpenSearch index |
| `host` | string | No | `"localhost"` | OpenSearch host |
| `port` | integer | No | `9200` | OpenSearch port |
| `username` | string | No | — | Authentication username |
| `password` | string | No | — | Authentication password |
| `use_ssl` | boolean | No | `false` | Enable SSL/TLS |
| `verify_certs` | boolean | No | `false` | Verify SSL certificates |
| `engine` | string | No | `"nmslib"` | KNN engine: `nmslib`, `faiss`, `lucene` |
| `algorithm` | string | No | `"hnsw"` | Index algorithm |
| `space_type` | string | No | `"l2"` | Distance metric: `l2`, `cosinesimil`, `innerproduct` |
| `batch_size` | integer | No | `100` | Documents indexed per batch |
| `engine_parameters.ef_construction` | integer | No | `512` | Accuracy/speed tradeoff during indexing |
| `engine_parameters.m` | integer | No | `16` | Number of bi-directional links per node |
| `index_settings.number_of_shards` | integer | No | `1` | OpenSearch shards |
| `index_settings.number_of_replicas` | integer | No | `0` | OpenSearch replicas |
| `aws_auth` | boolean | No | `false` | Use AWS SigV4 auth (for AWS OpenSearch Service) |
| `aws_region` | string | No | — | AWS region (required when `aws_auth: true`) |

### Milvus `provider_config` fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `collection_name` | string | **Yes** | — | Name of the Milvus collection |
| `auth_type` | string | No | `"standalone"` | Auth mode: `lite` (Milvus Lite, embedded local — no Docker needed), `standalone`, `grpc`, `uri`, `token` |
| `uri` | string | Conditional | — | Local `.db` path for `lite`; pre-constructed URI for `uri` auth_type |
| `host` | string | Conditional | `"localhost"` | Milvus host (required for `standalone`, `grpc`, `token`) |
| `port` | integer | No | `19530` | Milvus port |
| `username` | string | No | — | Authentication username |
| `password` | string | No | — | Authentication password |
| `database` | string | No | `"default"` | Database name (not used for `lite`) |
| `secure` | boolean | No | `false` | Enable SSL/TLS (not used for `lite`) |
| `index_type` | string | No | `"HNSW"` | Index type (only `FLAT` is supported for `lite`) |
| `metric_type` | string | No | `"L2"` | Distance metric: `L2`, `IP`, `COSINE` |
| `batch_size` | integer | No | `100` | Documents indexed per batch |
| `add_sparse_vector` | boolean | No | `false` | Enable BM25 sparse vector hybrid search (not supported for `lite`) |

### Weaviate `provider_config` fields

Minimum supported server: Weaviate 1.23.6, the floor stated by the pinned `weaviate-client` 4.24.1.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `collection_name` | string | **Yes** | — | Collection to write to. Must start with an upper-case ASCII letter and contain only ASCII letters, digits, and underscores |
| `connection_type` | string | No | `"custom"` | `custom` (self-hosted) or `cloud` (Weaviate Cloud) |
| `host` | string | No | `"localhost"` | Server host (`custom`) |
| `port` | integer | No | `8080` | HTTP port (`custom`) |
| `secure` | boolean | No | `false` | Use TLS for HTTP (`custom`) |
| `grpc_host` | string | No | `host` | gRPC host |
| `grpc_port` | integer | No | `50051` | gRPC port |
| `grpc_secure` | boolean | No | `secure` | Use TLS for gRPC |
| `cluster_url` | string | Conditional | — | Weaviate Cloud cluster URL; required when `connection_type` is `cloud` |
| `auth_type` | string | No | `"none"` | `none`, `api_key`, `bearer_token`, or `client_password` |
| `api_key` | string | Conditional | — | Required for `api_key` |
| `bearer_token` | string | Conditional | — | Required for `bearer_token` |
| `username`, `password` | string | Conditional | — | Required for `client_password` |
| `timeout_init` | integer | No | `30` | Seconds allowed to connect |
| `timeout_query` | integer | No | `60` | Seconds allowed for a query |
| `timeout_insert` | integer | No | `120` | Seconds allowed for a batch insert |
| `skip_init_checks` | boolean | No | `false` | Skip the connectivity and version checks on connect |
| `batch_size` | integer | No | `100` | Chunks written per request (a batch is also split by payload size) |
| `index_type` | string | No | `"hnsw"` | `hnsw`, `flat`, or `dynamic`. `dynamic` requires a server started with `ASYNC_INDEXING=true` |
| `distance_metric` | string | No | `"cosine"` | `cosine`, `dot`, `l2-squared`, `manhattan`, or `hamming` |
| `index_parameters` | object | No | `{}` | Index-specific settings passed to the collection's vector index configuration |
| `add_sparse_vector` | boolean | No | `false` | Prefer the top-level `add_sparse_vector`; see [Sparse (BM25) mode](#sparse-bm25-mode-weaviate) |

Notes:

- **TLS with credentials.** For `custom` connections, any `auth_type` other than `none` requires both `secure` and `grpc_secure` (which defaults to `secure`) to be `true`, so credentials are never sent unencrypted.
- **Credential references.** Credential fields accept a literal value, a `$VAR` or `${VAR}` environment reference, or a `vault://` reference. The flow executor resolves `vault://` references before the operator runs; flow validation skips the server connection when a credential is still a vault placeholder. A string that is all upper case and contains an underscore (for example `MY_TOKEN`) is replaced by the environment variable of the same name when one exists, so use an explicit `$VAR` reference for environment-sourced secrets.
- **Identity property.** The primary feature must be mapped to `pk`. It is stored as a field-tokenized text property and is distinct from the Weaviate object UUID, which the adapter derives deterministically from the chunk key.
- **Unsupported options.** `schema_template_path` is OpenSearch-only and is ignored with a warning. Access control is not supported: a mapped `allowed_users` is dropped with a warning, and ACL-enforced reads are OpenSearch-only.

#### Sparse (BM25) mode (Weaviate)

Weaviate has no stored sparse vector. "Sparse" retrieval is BM25 keyword search over the inverted index of the mapped content property, scored at query time with Weaviate's defaults (`k1=1.2`, `b=0.75`) and fusable with vector search in hybrid queries. The content property is always created `word`-tokenized and searchable, so keyword search works even with the flag off.

- Set `add_sparse_vector: true` at the top level of the node `config`. Setting it only inside `provider_config` records the BM25 parameters but does not enable sparse-only runs.
- The content feature must be mapped (for example `content` to `text`). A `sparse_embeddings` mapping is accepted and ignored.
- A sparse-only run (no dense embedding column) creates a keyword-only collection: one non-indexed named vector (named `keyword_only`) and objects written without a vector. Sparse-only runs currently require in-memory chunks from upstream operators; the standard extract, chunker, vectordb pipeline produces memory-mapped chunks and does not qualify. Hybrid runs (dense plus BM25) are unaffected.
- An existing collection must have a searchable, `word`-tokenized content property; this cannot be changed after the collection is created.
- Querying is outside this operator. Use the Weaviate client:

```python
collection = client.collections.get("DocpipeChunks")

# Keyword only
collection.query.bm25(query="payment terms", limit=5)

# Dense plus BM25
collection.query.hybrid(query="payment terms", vector=query_vector, target_vector="vector_embeddings", limit=5)
```

---

## Output Columns

The operator does not add or remove columns. The input table is returned unchanged to allow
chaining with downstream operators.

**Required input columns:**

| Column | Type | Required | Tags | Description |
|---|---|---|---|---|
| `doc_id_hash` (or `doc_id_column`) | String | Yes | `mandatory`, `primary` | Unique document ID — used as the primary key |
| `embeddings` (or `embeddings_column`) | Vector (Dense) | Yes | `mandatory` | Dense vector embeddings for similarity search |
| `sparse_embeddings` (or `sparse_embeddings_column`) | Vector (Sparse) | No | — | Sparse vector embeddings for hybrid search |
| `content` | String | No | — | Text content of the document; stored for filtering and retrieval |

---

## Examples

### Example 1 — Basic OpenSearch (local, no auth)

```json
{
  "type": "vectordb",
  "name": "index_documents",
  "config": {
    "provider": "opensearch",
    "vector_dimension": 384,
    "provider_config": {
      "index_name": "documents",
      "host": "localhost",
      "port": 9200,
      "use_ssl": false,
      "verify_certs": false
    }
  },
  "depends_on": ["embeddings"]
}
```

### Example 2 — OpenSearch with Faiss and custom settings

```json
{
  "type": "vectordb",
  "name": "index_documents",
  "config": {
    "provider": "opensearch",
    "vector_dimension": 1536,
    "provider_config": {
      "index_name": "research_papers",
      "host": "opensearch.example.com",
      "port": 9200,
      "username": "admin",
      "password": "${OPENSEARCH_PASSWORD}",
      "batch_size": 500,
      "engine": "faiss",
      "algorithm": "hnsw",
      "space_type": "l2",
      "engine_parameters": {
        "ef_construction": 512,
        "m": 16
      }
    }
  },
  "depends_on": ["embeddings"]
}
```

### Example 3 — AWS OpenSearch Service

```json
{
  "type": "vectordb",
  "name": "index_documents",
  "config": {
    "provider": "opensearch",
    "vector_dimension": 1536,
    "provider_config": {
      "index_name": "documents",
      "host": "search-domain.us-east-1.es.amazonaws.com",
      "port": 443,
      "use_ssl": true,
      "verify_certs": true,
      "aws_auth": true,
      "aws_region": "us-east-1",
      "engine": "faiss",
      "algorithm": "hnsw"
    }
  },
  "depends_on": ["embeddings"]
}
```

### Example 4 — Hybrid search (dense + sparse) with OpenSearch

```json
{
  "type": "vectordb",
  "name": "index_hybrid",
  "config": {
    "provider": "opensearch",
    "embeddings_column": "dense_embeddings",
    "sparse_embeddings_column": "sparse_embeddings",
    "vector_dimension": 768,
    "provider_config": {
      "index_name": "hybrid_search",
      "host": "localhost",
      "port": 9200,
      "engine": "nmslib",
      "algorithm": "hnsw"
    }
  },
  "depends_on": ["embeddings"]
}
```

### Example 5 — Milvus Lite (container-free local)

```json
{
  "type": "vectordb",
  "name": "index_documents",
  "config": {
    "provider": "milvus",
    "provider_config": {
      "collection_name": "local_docs",
      "auth_type": "lite",
      "uri": "./data/milvus/local_docs.db",
      "index_type": "FLAT",
      "metric_type": "COSINE",
      "batch_size": 100
    }
  },
  "depends_on": ["embeddings"]
}
```

> Set `enable_micro_batching: false` in `global_config` — Milvus Lite holds a single-process file lock. See [`sample_flows/quickstart/milvus_lite_integration.json`](../../../sample_flows/quickstart/milvus_lite_integration.json) for a complete working flow.

### Example 6 — Milvus (standalone)

```json
{
  "type": "vectordb",
  "name": "index_documents",
  "config": {
    "provider": "milvus",
    "provider_config": {
      "collection_name": "my_collection",
      "auth_type": "standalone",
      "host": "localhost",
      "port": 19530,
      "username": "<USERNAME>",
      "password": "<PASSWORD>",
      "database": "default",
      "secure": false,
      "index_type": "HNSW",
      "metric_type": "L2"
    }
  },
  "depends_on": ["embeddings"]
}
```

### Example 7 — Weaviate (self-hosted)

```json
{
  "type": "vectordb",
  "name": "index_documents",
  "config": {
    "provider": "weaviate",
    "provider_config": {
      "collection_name": "DocpipeChunks",
      "host": "localhost",
      "port": 8080,
      "grpc_port": 50051,
      "distance_metric": "cosine"
    },
    "feature_mappings": [
      { "feature_name": "doc_id_hash", "mapped_column_name": "pk" },
      { "feature_name": "content", "mapped_column_name": "text" },
      { "feature_name": "name", "mapped_column_name": "doc_name" },
      { "feature_name": "embeddings", "mapped_column_name": "vector_embeddings" }
    ]
  },
  "depends_on": ["embeddings"]
}
```

### Example 8 — Weaviate Cloud with an API key

```json
{
  "type": "vectordb",
  "name": "index_documents",
  "config": {
    "provider": "weaviate",
    "provider_config": {
      "collection_name": "DocpipeChunks",
      "connection_type": "cloud",
      "cluster_url": "https://my-cluster.weaviate.cloud",
      "auth_type": "api_key",
      "api_key": "$WEAVIATE_API_KEY"
    },
    "feature_mappings": [
      { "feature_name": "doc_id_hash", "mapped_column_name": "pk" },
      { "feature_name": "content", "mapped_column_name": "text" },
      { "feature_name": "embeddings", "mapped_column_name": "vector_embeddings" }
    ]
  },
  "depends_on": ["embeddings"]
}
```

### Example 9 — Weaviate with two embedding models

Each dense column becomes its own named vector.

```json
{
  "type": "vectordb",
  "name": "index_documents",
  "config": {
    "provider": "weaviate",
    "provider_config": {
      "collection_name": "DualEmbeddings",
      "host": "localhost"
    },
    "feature_mappings": [
      { "feature_name": "doc_id_hash", "mapped_column_name": "pk" },
      { "feature_name": "content", "mapped_column_name": "text" },
      { "feature_name": "embeddings", "mapped_column_name": "vector_embeddings" },
      { "feature_name": "embeddings_alt", "mapped_column_name": "vector_embeddings_alt" }
    ]
  },
  "depends_on": ["merge_embeddings"]
}
```

### Example 10 — Weaviate hybrid (dense plus BM25)

```json
{
  "type": "vectordb",
  "name": "index_hybrid",
  "config": {
    "provider": "weaviate",
    "add_sparse_vector": true,
    "provider_config": {
      "collection_name": "HybridChunks",
      "host": "localhost"
    },
    "feature_mappings": [
      { "feature_name": "doc_id_hash", "mapped_column_name": "pk" },
      { "feature_name": "content", "mapped_column_name": "text" },
      { "feature_name": "embeddings", "mapped_column_name": "vector_embeddings" }
    ]
  },
  "depends_on": ["embeddings"]
}
```

For a sparse-only run, omit the embeddings feature and see the in-memory chunk requirement under [Sparse (BM25) mode](#sparse-bm25-mode-weaviate).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `DocpipeException: index_name is required` | `index_name` missing from OpenSearch `provider_config` | Add `"index_name": "<your-index>"` inside `provider_config` |
| `DocpipeException: collection_name is required` | `collection_name` missing from Milvus `provider_config` | Add `"collection_name": "<your-collection>"` inside `provider_config` |
| `ConnectionError` to OpenSearch | Service not running or wrong host/port | Start OpenSearch; verify `host` and `port` in `provider_config` |
| `Index already exists` on re-run | Index was already created by a previous run | This is safe — the operator skips creation if the index exists and validates its schema |
| `KeyError: doc_id_hash` | Input table missing the ID column | Ensure `DocIdHashOperator` runs before `VectorDBOperator` |
| `KeyError: embeddings` | Input table missing the embeddings column | Ensure `EmbeddingsOperator` runs before `VectorDBOperator` |
| Vector dimension mismatch | `vector_dimension` does not match embedding model output | Omit it for auto-detection, or set it to match your model (e.g. 384, 768, 1536) |
| Slow indexing | `batch_size` too small | Increase `batch_size` to 500–1000 inside `provider_config` |
| Weaviate: credentials rejected over a plaintext connection | `auth_type` is not `none` but `secure` or `grpc_secure` is `false` | Set `secure: true` (and `grpc_secure: true` if you override it) |
| Weaviate: "Failed to initialize vector database adapter" | A configuration error (bad `collection_name`, missing credential, unset `$VAR`, reserved property name) raised before connecting | Read the listed messages; they name the field without echoing secret values |
| Weaviate: primary feature rejected | The primary feature is mapped to a name other than `pk`, or another feature is mapped to `pk` | Map `doc_id_hash` (or your `doc_id_column`) to `pk` |
| Weaviate: documents with a null `id` | Rows without an `id` | Chunks are keyed by the document hash instead; no action needed |
| Weaviate: cannot connect | gRPC port unreachable (the client needs both HTTP and gRPC) | Publish port 50051 and set `grpc_host` and `grpc_port` |
| Weaviate: collection name rejected | Name does not start with an upper-case ASCII letter | Use a name such as `DocpipeChunks`; Weaviate capitalizes the first letter |
| Weaviate: property name rejected | Name is reserved (for example `id`, `_additional`) or begins with an upper-case letter (the server lower-cases it) | Map the feature to a lower-case, non-reserved name |
| Weaviate: dimension mismatch | The existing collection's named vector has a different dimension than the embeddings | Use the matching model, or write to a new collection |
| Weaviate: existing collection rejected | Its `pk` property is `word`-tokenized, or its content property is not searchable or not `word`-tokenized | These cannot be changed in place; create a new collection |
| Weaviate: `dynamic` index refused | The server was not started with `ASYNC_INDEXING=true` | Enable async indexing on the server or use `hnsw` or `flat` |
| Weaviate: unexpected quantization | The server applies `DEFAULT_QUANTIZATION` to new collections | Check the server's environment; this is not set by the operator |
| Weaviate: sparse mode fails | The content feature is unmapped or the existing content property is not searchable | Map `content` and use a collection whose content property is searchable |
| Weaviate: `allowed_users` ignored | Access control is not supported by Weaviate | Use OpenSearch when ACL-enforced reads are required |
| Weaviate: `schema_template_path` ignored | The option is OpenSearch-only | Remove it for Weaviate |

---

## Architecture

### Hexagonal design

```text
VectorDBOperator (application layer)
    └── VectorStorePort (interface)
            ├── OpenSearchAdapter (outbound adapter)
            │       ├── OpenSearchClient         (connection)
            │       ├── OpenSearchIndexManager   (index ops)
            │       └── OpenSearchBatchProcessor (bulk indexing)
            ├── MilvusAdapter (outbound adapter)
            │       ├── MilvusClient             (connection)
            │       ├── MilvusIndexManager       (collection ops)
            │       └── MilvusBatchProcessor     (bulk insertion)
            └── WeaviateAdapter (outbound adapter)
                    ├── WeaviateClient           (connection)
                    ├── WeaviateIndexManager     (collection ops)
                    └── WeaviateBatchProcessor   (bulk insertion)
```

Adding a new provider requires only a new adapter class decorated with `@register_vector_store("provider_name")`.

### Engine selection guide (OpenSearch)

| Engine | Best for |
|---|---|
| `nmslib` | General use, balanced accuracy/speed |
| `faiss` | Large-scale datasets (millions of docs) |
| `lucene` | Smaller datasets, no native dependency |

### Typical pipeline position

```text
Ingest → Extract → Chunker → Embeddings → VectorDBOperator
```

### Real-server tests (Weaviate)

The Weaviate suite runs against a real server and is manual-only: it is not part of the default test run and is intended as a pre-release check. The server must have `AUTOSCHEMA_ENABLED=false`; the suite fails if the server accepts an undeclared property.

```bash
docker compose -f docker/docker-compose.weaviate.yml up -d
pytest -m integration tests/integration/weaviate
```

The `dynamic` index scenario needs a second server with async indexing, started with `docker compose -f docker/docker-compose.weaviate.yml --profile async up -d weaviate-async`. To use an existing server instead, set `DOCPIPE_TEST_WEAVIATE_HOST` (with optional `DOCPIPE_TEST_WEAVIATE_PORT` and `DOCPIPE_TEST_WEAVIATE_GRPC_PORT`). The compose file is for tests only; do not use it to deploy Weaviate.

### Sample flows

- [`sample_flows/vectordb/opensearch_integration.json`](../../../sample_flows/vectordb/opensearch_integration.json)
- [`sample_flows/vectordb/milvus_integration.json`](../../../sample_flows/vectordb/milvus_integration.json)
- [`sample_flows/vectordb/weaviate_integration.json`](../../../sample_flows/vectordb/weaviate_integration.json)
- [`sample_flows/operators/entity_extraction_litellm.json`](../../../sample_flows/operators/entity_extraction_litellm.json)
