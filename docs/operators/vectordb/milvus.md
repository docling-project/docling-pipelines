# VectorDB Operator - Milvus Configuration

## Overview

The VectorDB operator stores documents and embeddings in vector databases for similarity search. This document covers Milvus-specific configuration.

When configured with `provider: "milvus"`, the operator supports multiple index types, hybrid search (dense + sparse vectors), multi-model embeddings, and incremental updates.

## Features

### Core Capabilities
- **Multiple Index Types**: HNSW, IVF_FLAT, IVF_SQ8, FLAT, AUTOINDEX, BIN_FLAT, BIN_IVF_FLAT
- **GPU Indexes**: GPU_CAGRA, GPU_IVF_FLAT, GPU_IVF_PQ, GPU_BRUTE_FORCE (`vector_mode: "gpu"`)
- **Vector Similarity Metrics**: L2, IP (Inner Product), COSINE, HAMMING, JACCARD
- **Binary Vector Support**: 1-bit quantized compact vector embeddings (`BIN_FLAT`, `BIN_IVF_FLAT`) for 32x memory and storage savings
- **Hybrid Search**: Dense + sparse vector support with BM25
- **Multi-Model Embeddings**: Multiple embedding models with different dimensions in same collection (including mixing dense float and binary vectors)
- **Batch Processing**: Configurable batch sizes for optimal performance
- **Incremental Updates**: Query and delete capabilities
- **Error Handling**: Detailed failure tracking and retry logic
- **Nullable Fields**: Support for optional fields to handle varying data schemas

### Supported Index Types

| Index Type | Vector Type | Speed | Accuracy | Memory | Use Case |
|-----------|-------------|-------|----------|--------|----------|
| HNSW | Dense Float | Fast | High | Medium | General purpose, recommended |
| IVF_FLAT | Dense Float | Very Fast | Medium | Low | Large datasets, speed priority |
| IVF_SQ8 | Dense Float | Very Fast | Medium | Very Low | Memory-constrained environments |
| FLAT | Dense Float | Slow | Perfect | High | Small datasets, exact search |
| AUTOINDEX | Dense Float | Varies | High | Varies | Automatic optimization |
| BIN_FLAT | Binary | Brute force | Perfect | Very Low | Exact search for 1-bit quantized binary vectors |
| BIN_IVF_FLAT | Binary | Very Fast | High | Very Low | Inverted index for large-scale binary vector retrieval |

> [!NOTE]
> Milvus Lite (`auth_type: "lite"`) does not support binary vectors or binary index types (`BIN_FLAT`,
> `BIN_IVF_FLAT`). For binary vector storage, use a remote Milvus server (`auth_type` of `standalone`, `grpc`, `uri`
> or `token`).

#### How `index_type`, `metric_type` and `index_parameters` apply to each vector field

Whether a vector field is dense (`FLOAT_VECTOR`) or binary (`BINARY_VECTOR`) is decided only by the feature's own
type (`vector` vs `vector_binary`) -- never by `index_type`. The single `index_type` / `metric_type` /
`index_parameters` configuration is applied to every vector field according to that kind:

| Configured `index_type` | Dense field | Binary field |
|---|---|---|
| Dense (`HNSW`, `IVF_FLAT`, ...) | Used as configured | `BIN_FLAT` + `HAMMING` (dense metrics and parameters are not valid for binary fields) |
| Binary (`BIN_FLAT`, `BIN_IVF_FLAT`) | `HNSW` + `L2` defaults (mixed collections only) | Used as configured, with a binary `metric_type` |

A `BIN_*` `index_type` on a collection with no binary vector field is rejected, as is a dense `index_type` paired
with a binary-only `metric_type` (`HAMMING`, `JACCARD`). The `BIN_*`
check also runs during flow validation (`POST /api/v1/validation/validate_flow`): it fails when no upstream feature is
typed `vector_binary`, for example when the embeddings operator has no `quantization: "binary"` or `"ubinary"`.

When `EmbeddingsOperator` runs with `quantization: "binary"` or `"ubinary"`, the flow's feature propagation types its
`embeddings` feature as `vector_binary`, so the binary schema and index are selected automatically.

> [!NOTE]
> 1-bit quantization keeps only the sign of each dimension, so it works best with zero-centred (for example
> normalized) embedding models. `quantization: ubinary` behaves identically to `binary`. Set `quantization` on the
> embeddings node's `config`.

For a complete flow that quantizes embeddings and indexes them with `BIN_IVF_FLAT`, see
[`sample_flows/vectordb/milvus_binary_integration.json`](../../../sample_flows/vectordb/milvus_binary_integration.json).

### Similarity Metrics

| Metric | Applicable Vector Type | Description | Use Case |
|--------|------------------------|-------------|----------|
| L2 | Dense Float | Euclidean distance | General embeddings, default |
| IP | Dense Float | Inner product | Pre-normalized vectors |
| COSINE | Dense Float | Cosine similarity | Text embeddings, normalized similarity |
| HAMMING | Binary | Bitwise Hamming distance | General 1-bit quantized binary vector retrieval |
| JACCARD | Binary | Jaccard distance | Set similarity & binary token overlap |

> [!NOTE]
> Milvus 2.6 supports only `HAMMING` and `JACCARD` for binary indexes. The `TANIMOTO`, `SUBSTRUCTURE` and
> `SUPERSTRUCTURE` metrics were removed upstream and are rejected during validation.

## Configuration Parameters

### Operator-Level Settings

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `provider` | string | No | "milvus" | Vector database type |
| `doc_id_column` | string | No | "doc_id_hash" | Column containing document IDs |
| `batch_size` | integer | No | 100 | Documents per batch |
| `provider_config` | object | **Yes** | - | Provider-specific configuration including the collection name (see below) |

### provider_config Structure

Connection and index-specific parameters are configured inside the `provider_config` nested dictionary for architectural separation between generic and provider-specific settings.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `collection_name` | string | **Yes** | - | Name of the Milvus collection |
| `auth_type` | string | No | `"standalone"` | Authentication type: `lite` (Milvus Lite, embedded local — no Docker needed), `standalone`, `grpc`, `uri`, `token` |
| `uri` | string | Conditional | - | Local `.db` path for `lite`; full pre-constructed URI for `uri` auth_type |
| `host` | string | Conditional | - | Milvus server host (required for `standalone`, `grpc`, `token`) |
| `port` | integer | No | 19530 | Milvus server port |
| `username` | string | No | `"root"` | Username for authentication |
| `password` | string | No | `"Milvus"` | Password/API key for authentication |
| `database` | string | No | `"default"` | Database name (not used for `lite`) |
| `secure` | boolean | No | false | Enable TLS/SSL (not used for `lite`) |
| `vector_mode` | string | No | inferred | `dense`, `sparse`, `binary` or `gpu`. When omitted: `sparse` if `add_sparse_vector` is true, otherwise inferred from `index_type` (`BIN_*` gives `binary`, `GPU_*` gives `gpu`, else `dense`) |
| `index_type` | string | No | `"HNSW"` | Index type (HNSW, IVF_FLAT, `GPU_CAGRA`, `BIN_FLAT`, `BIN_IVF_FLAT`, etc.; only `FLAT` is supported for `lite`). Must belong to the `vector_mode` |
| `metric_type` | string | No | `"L2"` | Similarity metric: L2, IP, COSINE for dense vectors; L2, IP for GPU indexes; HAMMING, JACCARD for binary vectors. A `BIN_*` `index_type` requires a binary metric, so the default `L2` is rejected |
| `index_parameters` | object | No | {} | Custom index-specific parameters |
| `add_sparse_vector` | boolean | No | false | Backward-compatible alias for `vector_mode: "sparse"` (BM25 hybrid search, not supported for `lite`). Combining it with another `vector_mode` is rejected |

### Index Parameters

#### HNSW (Recommended)
```json
{
  "M": 16,
  "efConstruction": 256
}
```

#### IVF_FLAT
```json
{
  "nlist": 128
}
```

#### IVF_SQ8
```json
{
  "nlist": 128
}
```

#### BIN_FLAT
No parameters (exact search over binary vectors).

#### BIN_IVF_FLAT
```json
{
  "nlist": 128
}
```

## Multi-Model Embeddings

Milvus supports multiple embedding models with different dimensions in the same collection. This is useful when you want to:
- Compare different embedding models
- Use specialized embeddings for different content types
- Implement ensemble retrieval strategies

### Configuration

Configure multiple vector columns in `available_features`:

```json
{
  "available_features": {
    "doc_id_hash": {
      "available_for_vector_db": true,
      "mandatory_for_vector_db": true,
      "type": "string",
      "is_primary": true
    },
    "embeddings": {
      "available_for_vector_db": true,
      "mandatory_for_vector_db": true,
      "type": "vector"
    },
    "embeddings_alt": {
      "available_for_vector_db": true,
      "type": "vector"
    }
  },
  "feature_mappings": [
    {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
    {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
    {"feature_name": "embeddings_alt", "mapped_column_name": "vector_embeddings_alt"}
  ]
}
```

The operator automatically:
- Detects dimensions for each vector column
- Creates separate vector fields in the collection
- Creates indexes for all vector fields
- Handles insertion of documents with multiple embeddings

## Hybrid Search (Dense + Sparse)

Enable hybrid search by setting `add_sparse_vector: true` in `provider_config`. This creates:
- Dense vector field(s) for semantic similarity (user-configured)
- Sparse vector field for keyword matching (BM25, hardcoded)
- Content field with text analyzer enabled

### Configuration

```json
{
  "provider_config": {
    "add_sparse_vector": true,
    "index_type": "HNSW",
    "metric_type": "L2"
  }
}
```

**Note**: In hybrid mode:
- Sparse vectors use SPARSE_INVERTED_INDEX with BM25 (hardcoded, not user-configurable)
- Dense vectors use user-specified index_type and metric_type
- Content field has `enable_analyzer: true` for BM25 text analysis

## Usage Examples

### Example 1: Basic Milvus Configuration

```python
from docpipe.core.operators.vectordb import VectorDBOperator
from docpipe.core.constants.operator_constants import OperatorConstants
import pyarrow as pa
import numpy as np

config = {
    "provider": "milvus",
    OperatorConstants.Config.PROVIDER_CONFIG: {
        "collection_name": "my_documents",
        "auth_type": "standalone",
        "host": "localhost",
        "port": 19530,
        "username": "<USERNAME>",
        "password": "<PASSWORD>",  # pragma: allowlist secret
        "database": "default",
        "secure": False,
        "index_type": "HNSW",
        "metric_type": "L2",
        "batch_size": 100
    },
    "available_features": {
        "doc_id_hash": {
            "available_for_vector_db": True,
            "mandatory_for_vector_db": True,
            "type": "string",
            "is_primary": True
        },
        "content": {
            "available_for_vector_db": True,
            "type": "string"
        },
        "embeddings": {
            "available_for_vector_db": True,
            "mandatory_for_vector_db": True,
            "type": "vector"
        }
    },
    "feature_mappings": [
        {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
        {"feature_name": "content", "mapped_column_name": "text"},
        {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"}
    ]
}

# Create sample data
data = {
    "doc_id_hash": ["doc1", "doc2"],
    "content": ["First document", "Second document"],
    "embeddings": [np.random.rand(384).tolist(), np.random.rand(384).tolist()]
}

table = pa.table(data)

# Index documents
operator = VectorDBOperator(config)
result_tables, metadata = operator.transform(table)

print(f"Indexed {metadata['processed_docs']} documents")
```

### Example 1b: Milvus Lite (Container-Free Local)

No Docker, Podman, or Kubernetes required. Data persists to a local `.db` file.

```python
config = {
    "provider": "milvus",
    OperatorConstants.Config.PROVIDER_CONFIG: {
        "collection_name": "local_docs",
        "auth_type": "lite",
        "uri": "./data/milvus/local_docs.db",
        "index_type": "FLAT",
        "metric_type": "COSINE",
        "batch_size": 100
    },
    "available_features": {
        "doc_id_hash": {
            "available_for_vector_db": True,
            "mandatory_for_vector_db": True,
            "type": "string",
            "is_primary": True
        },
        "content": {
            "available_for_vector_db": True,
            "type": "string"
        },
        "embeddings": {
            "available_for_vector_db": True,
            "mandatory_for_vector_db": True,
            "type": "vector"
        }
    },
    "feature_mappings": [
        {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
        {"feature_name": "content", "mapped_column_name": "text"},
        {"feature_name": "embeddings", "mapped_column_name": "vector"}
    ]
}

operator = VectorDBOperator(config)
result_tables, metadata = operator.transform(table)
print(f"Indexed {metadata['processed_docs']} documents to local Milvus Lite store")
```

> **Note:** Set `enable_micro_batching: false` in `global_config` when using Milvus Lite in a flow — Lite holds a single-process file lock. Only `FLAT` index type is supported.

### Example 2: Multi-Model Embeddings

```python
config = {
    "provider": "milvus",
    OperatorConstants.Config.PROVIDER_CONFIG: {
        "collection_name": "multi_model_collection",
        "host": "localhost",
        "port": 19530,
        "index_type": "HNSW",
        "metric_type": "L2"
    },
    "available_features": {
        "doc_id_hash": {
            "available_for_vector_db": True,
            "mandatory_for_vector_db": True,
            "type": "string",
            "is_primary": True
        },
        "embeddings": {
            "name": "Primary Embeddings",
            "available_for_vector_db": True,
            "mandatory_for_vector_db": True,
            "type": "vector"
        },
        "embeddings_alt": {
            "name": "Alternative Embeddings",
            "available_for_vector_db": True,
            "type": "vector"
        }
    },
    "feature_mappings": [
        {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
        {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
        {"feature_name": "embeddings_alt", "mapped_column_name": "vector_embeddings_alt"}
    ]
}

# Data with two embedding models (different dimensions)
data = {
    "doc_id_hash": ["doc1", "doc2"],
    "embeddings": [np.random.rand(768).tolist(), np.random.rand(768).tolist()],
    "embeddings_alt": [np.random.rand(384).tolist(), np.random.rand(384).tolist()]
}

table = pa.table(data)
operator = VectorDBOperator(config)
result_tables, metadata = operator.transform(table)
```

### Example 3: Hybrid Search with BM25

```python
config = {
    "provider": "milvus",
    OperatorConstants.Config.PROVIDER_CONFIG: {
        "collection_name": "hybrid_search_collection",
        "host": "localhost",
        "port": 19530,
        "add_sparse_vector": True,  # Enable BM25 sparse vectors
        "index_type": "HNSW",
        "metric_type": "L2"
    },
    "available_features": {
        "doc_id_hash": {
            "available_for_vector_db": True,
            "mandatory_for_vector_db": True,
            "type": "string",
            "is_primary": True
        },
        "content": {
            "available_for_vector_db": True,
            "type": "text"
        },
        "embeddings": {
            "available_for_vector_db": True,
            "mandatory_for_vector_db": True,
            "type": "vector"
        }
    },
    "feature_mappings": [
        {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
        {"feature_name": "content", "mapped_column_name": "text"},
        {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"}
    ]
}
```

### Example 4: Custom Index Parameters

```python
config = {
    "provider": "milvus",
    OperatorConstants.Config.PROVIDER_CONFIG: {
        "collection_name": "custom_index",
        "host": "localhost",
        "port": 19530,
        "index_type": "HNSW",
        "metric_type": "COSINE",
        "index_parameters": {
            "M": 32,
            "efConstruction": 512
        }
    }
}
```

### Example 5: Binary Vector Indexing (1-bit Quantized)

Binary vectors store 1-bit quantized embeddings as raw byte strings (bit dimension must be a multiple of 8, e.g. 768 bits = 96 bytes).

```python
config = {
    "provider": "milvus",
    OperatorConstants.Config.PROVIDER_CONFIG: {
        "collection_name": "binary_docs",
        "host": "localhost",
        "port": 19530,
        "index_type": "BIN_IVF_FLAT",
        "metric_type": "HAMMING",
        "index_parameters": {
            "nlist": 128
        }
    },
    "available_features": {
        "doc_id_hash": {
            "available_for_vector_db": True,
            "mandatory_for_vector_db": True,
            "type": "string",
            "is_primary": True
        },
        "content": {
            "available_for_vector_db": True,
            "type": "string"
        },
        "embeddings": {
            "available_for_vector_db": True,
            "mandatory_for_vector_db": True,
            "type": "vector_binary"
        }
    },
    "feature_mappings": [
        {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
        {"feature_name": "content", "mapped_column_name": "text"},
        {"feature_name": "embeddings", "mapped_column_name": "binary_vector"}
    ]
}

# Ingest packed bytes (e.g. 384 bits = 48 bytes per document)
data = {
    "doc_id_hash": ["doc1", "doc2"],
    "content": ["First document", "Second document"],
    "embeddings": [b"\xff" * 48, b"\x00" * 48]
}

table = pa.table(data)
operator = VectorDBOperator(config)
result_tables, metadata = operator.transform(table)
```

## Flow Configuration

### Complete Flow Example

```json
{
  "id": "milvus-node",
  "name": "Store in Milvus",
  "operator": "vectordb",
  "config": {
    "provider": "milvus",
    "doc_id_column": "doc_id_hash",
    "provider_config": {
      "collection_name": "docpipe_documents",
      "auth_type": "standalone",
      "host": "localhost",
      "port": 19530,
      "username": "<USERNAME>",
      "password": "<PASSWORD>",
      "database": "default",
      "secure": false,
      "index_type": "HNSW",
      "metric_type": "L2",
      "batch_size": 100,
      "index_parameters": {
        "M": 16,
        "efConstruction": 256
      }
    },
    "available_features": {
      "doc_id_hash": {
        "name": "Document ID",
        "available_for_vector_db": true,
        "mandatory_for_vector_db": true,
        "type": "string",
        "is_primary": true
      },
      "content": {
        "name": "Content",
        "available_for_vector_db": true,
        "type": "string"
      },
      "embeddings": {
        "name": "Embeddings",
        "available_for_vector_db": true,
        "mandatory_for_vector_db": true,
        "type": "vector"
      }
    },
    "feature_mappings": [
      {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
      {"feature_name": "content", "mapped_column_name": "text"},
      {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"}
    ]
  }
}
```

### Multi-Model Flow Example

See [`sample_flows/vectordb/milvus_integration.json`](../../../sample_flows/vectordb/milvus_integration.json) for a complete Milvus pipeline example.

## Performance Tuning

### Batch Size Optimization

```python
config = {
    "batch_size": 500,  # Increase for better throughput
    OperatorConstants.Config.PROVIDER_CONFIG: {
        "batch_size": 500  # Also set in provider_config
    }
}
```

### Index-Specific Tuning

#### HNSW (Balanced)
```python
OperatorConstants.Config.PROVIDER_CONFIG: {
    "index_type": "HNSW",
    "metric_type": "L2",
    "index_parameters": {
        "M": 16,              # Higher = better accuracy, more memory
        "efConstruction": 256  # Higher = better accuracy, slower indexing
    }
}
```

#### IVF_FLAT (Speed Priority)
```python
OperatorConstants.Config.PROVIDER_CONFIG: {
    "index_type": "IVF_FLAT",
    "metric_type": "L2",
    "index_parameters": {
        "nlist": 128  # Number of clusters
    }
}
```

## GPU Indexes

Large collections can use GPU-accelerated indexes to improve build and query speed. Set `vector_mode: "gpu"` (or just a `GPU_*` `index_type`, which is inferred as `gpu` mode). GPU indexes apply to dense `FLOAT_VECTOR` fields on standalone or remote Milvus; the schema and ingestion path are the same as for CPU dense vectors. Milvus Lite supports only `FLAT`, and GPU mode with `auth_type: "lite"` raises a configuration error.

### Prerequisites

Per the Milvus GPU requirements:

1. A Linux host with an NVIDIA GPU of compute capability 6.0, 7.0, 7.5, 8.0, 8.6 or 9.0, and NVIDIA driver 545 or newer.
2. The NVIDIA Container Toolkit, and a GPU build of Milvus, for example the `milvusdb/milvus:<version>-gpu` image (such as `v2.6.16-gpu`). The regular image has no GPU index support.
3. The GPU device assigned to the Milvus service in Docker Compose:
   ```yaml
   milvus-standalone:
     image: milvusdb/milvus:v2.6.16-gpu
     deploy:
       resources:
         reservations:
           devices:
             - driver: nvidia
               capabilities: ["gpu"]
               device_ids: ["0"]
   ```
4. GPU memory large enough for the collection. Milvus loads the data into GPU memory, so `maxMemSize` in the Milvus config must be at least the data size.

macOS and Podman on Apple Silicon cannot run GPU indexes.

Docling Pipelines does not probe the pipeline host for a GPU. Index building runs on the Milvus server, so the configured GPU index type is always sent to the server as given. If the server is not a GPU build, index creation fails with the server error.

### GPU index types

| GPU index | Notes |
|-----------|-------|
| `GPU_CAGRA` | Graph-based index with the highest query throughput in Milvus benchmarks |
| `GPU_IVF_FLAT` | Good balance of speed and recall |
| `GPU_IVF_PQ` | Lower GPU memory through product quantization |
| `GPU_BRUTE_FORCE` | Exact search with recall of 1 |

### GPU index limits

- **Metrics: `L2` and `IP` only.** `COSINE` is rejected with a configuration error. Normalize the vectors and use `IP`, or use `L2`. This check applies to the configured settings, independent of the hardware.
- **Index type must be a GPU type.** A CPU index type such as `HNSW` with `vector_mode: "gpu"` is rejected, and a GPU index type with `vector_mode: "dense"` is rejected.
- **Dense vectors only.** GPU indexes apply to `FLOAT_VECTOR` fields. In a mixed dense and binary collection the binary fields use `BIN_FLAT` with `HAMMING`. If the only vector features are binary (for example embeddings with `quantization: binary`), `vector_mode: "gpu"` is rejected during flow validation because the GPU would never be used. With `vector_mode: "sparse"` (alone or hybrid with dense vectors) the sparse field keeps `SPARSE_INVERTED_INDEX` with `BM25`; in a hybrid collection the dense field's `index_type` (CPU dense or GPU), `metric_type` and `GPU_CAGRA` parameters are validated.
- **Validated without a Milvus connection.** The mode, index type, metric and `GPU_CAGRA` settings are checked before connecting, so flow validation reports them even when Milvus is unreachable.
- **Existing collections.** If the collection already exists it is not recreated, and `vector_mode`/`index_type` are not compared with its existing indexes; only vector dimensions are validated.
- **No leftover collection.** If index creation fails after the collection was created (for example the server has no GPU build), the collection is dropped and the original error is raised.
- For `GPU_CAGRA`, `graph_degree` must be less than or equal to `intermediate_graph_degree`; otherwise a configuration error is raised before the collection is created.
- GPU indexes do not support range search or grouping search.
- The maximum search `limit` is 1,024 for `GPU_IVF_FLAT`, `GPU_IVF_PQ` and `GPU_CAGRA`.
- A GPU index does not always lower latency compared with a CPU index. The gain is largest with heavy query load or large query batches.

### Example

```json
{
  "provider": "milvus",
  "provider_config": {
    "collection_name": "docs_gpu",
    "auth_type": "standalone",
    "host": "localhost",
    "vector_mode": "gpu",
    "index_type": "GPU_CAGRA",
    "metric_type": "IP",
    "index_parameters": {
      "intermediate_graph_degree": 64,
      "graph_degree": 32
    }
  }
}
```

A complete flow is in [`sample_flows/vectordb/milvus_gpu_integration.json`](../../../sample_flows/vectordb/milvus_gpu_integration.json).

### Tuning guidance

- `GPU_CAGRA`: raise `graph_degree` for recall at the cost of GPU memory and build time. `intermediate_graph_degree` must be at least `graph_degree`.
- `GPU_IVF_FLAT` and `GPU_IVF_PQ`: `nlist` defaults to 1024. Roughly `sqrt(n)` to `4*sqrt(n)` for `n` vectors is a common starting range.
- For small collections, `HNSW` on CPU is often as fast as a GPU index.
- Search-time parameters (for example `ef` for HNSW, `nprobe` for IVF, `itopk_size` for CAGRA) are query-time settings. This operator only ingests, so pass them in the `search()` call of your query client.

## Error Handling

The operator provides detailed error tracking:

```python
result_tables, metadata = operator.transform(table)

print(f"Total documents: {metadata['total_docs']}")
print(f"Processed: {metadata['processed_docs']}")
print(f"Failed: {metadata['failed_docs_count']}")
print(f"Skipped: {metadata['skipped_docs_count']}")
print(f"Batches: {metadata['number_of_batches']}")

# Check failed documents
for failed_doc in metadata['failed_docs']:
    print(f"Failed: {failed_doc['name']} - {failed_doc['reason']}")
```

## Best Practices

### 1. Index Selection
- **HNSW**: Recommended for most use cases (high accuracy, good speed)
- **IVF_FLAT**: Use for very large datasets where speed is critical
- **AUTOINDEX**: Let Milvus choose optimal index automatically

### 2. Similarity Metrics
- **L2**: Euclidean distance (default, works well for most embeddings)
- **COSINE**: Normalized similarity (good for text embeddings)
- **IP**: Inner product (for pre-normalized vectors)

### 3. Multi-Model Embeddings
- Use when comparing different embedding models
- Ensure all vector columns are properly mapped in feature_mappings
- Dimensions are auto-detected from data

### 4. Hybrid Search
- Enable `add_sparse_vector: true` for keyword + semantic search
- Sparse vectors use BM25 (hardcoded, optimized for text)
- Dense vectors use your specified index_type and metric_type

### 5. Nullable Fields
- Non-mandatory fields are automatically made nullable
- Prevents insertion failures when optional fields are missing
- Content field is always required (not nullable)

### 6. Batch Processing
- Default batch size (100) works well for most cases
- Increase for smaller documents, decrease for large documents
- Monitor memory usage with large batches

## Troubleshooting

### Schema Mismatch
```python
# Ensure vector dimensions match your embedding model
# Use auto-detection by not specifying vector_dimension
# Check that all mandatory fields are present in data
```

### Performance Issues
```python
# Increase batch_size for better throughput
# Tune index parameters (M, efConstruction for HNSW)
# Consider IVF_FLAT for very large datasets
```

## Related Operators

- **IngestSourceOperator**: Ingest documents from local filesystem or remote sources
- **ExtractOperator**: Extract content from documents
- **ChunkerOperator**: Chunk documents for vector storage
- **EmbeddingsOperator**: Generate embeddings from text

## References

- [Milvus Documentation](https://milvus.io/docs)
- [Milvus Python SDK](https://milvus.io/docs/install-pymilvus.md)
- [Index Types](https://milvus.io/docs/index.md)
- [Similarity Metrics](https://milvus.io/docs/metric.md)
