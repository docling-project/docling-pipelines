# VectorDB Operator - Milvus Configuration

## Overview

The VectorDB operator stores documents and embeddings in vector databases for similarity search. This document covers Milvus-specific configuration.

When configured with `provider: "milvus"`, the operator supports multiple index types, hybrid search (dense + sparse vectors), multi-model embeddings, and incremental updates.

## Features

### Core Capabilities
- **Multiple Index Types**: HNSW, IVF_FLAT, IVF_SQ8, FLAT, AUTOINDEX
- **Vector Similarity Metrics**: L2, IP (Inner Product), COSINE
- **Hybrid Search**: Dense + sparse vector support with BM25
- **Multi-Model Embeddings**: Multiple embedding models with different dimensions in same collection
- **Batch Processing**: Configurable batch sizes for optimal performance
- **Incremental Updates**: Query and delete capabilities
- **Error Handling**: Detailed failure tracking and retry logic
- **Nullable Fields**: Support for optional fields to handle varying data schemas

### Supported Index Types

| Index Type | Speed | Accuracy | Memory | Use Case |
|-----------|-------|----------|--------|----------|
| HNSW | Fast | High | Medium | General purpose, recommended |
| IVF_FLAT | Very Fast | Medium | Low | Large datasets, speed priority |
| IVF_SQ8 | Very Fast | Medium | Very Low | Memory-constrained environments |
| FLAT | Slow | Perfect | High | Small datasets, exact search |
| AUTOINDEX | Varies | High | Varies | Automatic optimization |

### Similarity Metrics

| Metric | Description | Use Case |
|--------|-------------|----------|
| L2 | Euclidean distance | General embeddings, default |
| IP | Inner product | Pre-normalized vectors |
| COSINE | Cosine similarity | Text embeddings, normalized similarity |

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
| `index_type` | string | No | `"HNSW"` | Index type (HNSW, IVF_FLAT, etc.; only `FLAT` is supported for `lite`) |
| `metric_type` | string | No | `"L2"` | Similarity metric (L2, IP, COSINE) |
| `index_parameters` | object | No | {} | Custom index-specific parameters |
| `add_sparse_vector` | boolean | No | false | Enable hybrid search with BM25 sparse vectors (not supported for `lite`) |

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
