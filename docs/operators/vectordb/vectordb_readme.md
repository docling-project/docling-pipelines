# VectorDBOperator

Indexes document embeddings into a vector database for similarity search.

- **Short Name:** `vectordb`
- **Category:** VectorDB

---

## Overview

`VectorDBOperator` takes a PyArrow table containing document embeddings and indexes it into a
vector database. It uses a hexagonal architecture (ports and adapters) so that the core operator
logic is independent of the underlying database; switching providers only requires a config change.

Supported providers: OpenSearch, Milvus.

---

## Key Features

- Multi-provider support via adapter pattern (OpenSearch, Milvus)
- Automatic index/collection creation on first run, with schema validation on later runs
- Provider-specific resource name declared inside `provider_config`
- Configurable KNN engine and algorithm (NMSLIB, Faiss, Lucene for OpenSearch)
- Hybrid search support (dense + sparse embeddings)
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
| `provider` | string | Yes | — | Vector DB provider: `opensearch`, `milvus` |
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

---

## Architecture

### Hexagonal design

```
VectorDBOperator (application layer)
    └── VectorStorePort (interface)
            ├── OpenSearchAdapter (outbound adapter)
            │       ├── OpenSearchClient         (connection)
            │       ├── OpenSearchIndexManager   (index ops)
            │       └── OpenSearchBatchProcessor (bulk indexing)
            └── MilvusAdapter (outbound adapter)
                    ├── MilvusClient             (connection)
                    ├── MilvusIndexManager       (collection ops)
                    └── MilvusBatchProcessor     (bulk insertion)
```

Adding a new provider requires only a new adapter class decorated with `@register_vector_store("provider_name")`.

### Engine selection guide (OpenSearch)

| Engine | Best for |
|---|---|
| `nmslib` | General use, balanced accuracy/speed |
| `faiss` | Large-scale datasets (millions of docs) |
| `lucene` | Smaller datasets, no native dependency |

### Typical pipeline position

```
Ingest → Extract → Chunker → Embeddings → VectorDBOperator
```

### Sample flows

- [`sample_flows/vectordb/opensearch_integration.json`](../../../sample_flows/vectordb/opensearch_integration.json)
- [`sample_flows/vectordb/milvus_integration.json`](../../../sample_flows/vectordb/milvus_integration.json)
- [`sample_flows/operators/entity_extraction_litellm.json`](../../../sample_flows/operators/entity_extraction_litellm.json)
