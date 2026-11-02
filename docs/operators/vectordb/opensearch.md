# VectorDB Operator - OpenSearch Configuration

## Overview

The VectorDB operator stores documents and embeddings in vector databases for similarity search. This document covers OpenSearch-specific configuration.

When configured with `provider: "opensearch"`, the operator supports multiple KNN engines, algorithms, incremental updates, and query capabilities.

## Features

### Core Capabilities
- **Multiple KNN Engines**: FAISS, Lucene, nmslib, jVector
- **Multiple Algorithms**: HNSW, IVF
- **Vector Similarity Metrics**: L2, Cosine, Inner Product
- **Batch Processing**: Size-aware batching with configurable limits
- **Incremental Updates**: Query and delete capabilities
- **Error Handling**: Detailed failure tracking and retry logic
- **Version Compatibility**: Automatic version detection and validation

### Supported Engines

| Engine | Algorithms | Best For | Notes |
|--------|-----------|----------|-------|
| FAISS | HNSW, IVF | Large-scale similarity search | Recommended for production |
| Lucene | HNSW | Native OpenSearch integration | Good balance of speed and accuracy |
| nmslib | HNSW | Legacy support | Deprecated in OpenSearch 2.13+ |
| jVector | HNSW | Java-based implementation | Requires k-NN plugin |

### Algorithm Comparison

| Algorithm | Speed | Accuracy | Memory | Use Case |
|-----------|-------|----------|--------|----------|
| HNSW | Fast | High | Medium | General purpose, recommended |
| IVF | Very Fast | Medium | Low | Large datasets, speed priority |

## Configuration Parameters

### Operator-Level Settings

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `provider` | string | No | "opensearch" | Vector database type |
| `index_name` | string | Yes | - | Name of the OpenSearch index |
| `doc_id_column` | string | No | "doc_id_hash" | Column containing document IDs |
| `embeddings_column` | string | No | "embeddings" | Column containing embeddings |
| `vector_dimension` | integer | No | 384 | Dimension of vector embeddings |
| `batch_size` | integer | No | 100 | Documents per batch |
| `provider_config` | object | Yes | - | Provider-specific configuration (see below) |

### provider_config Structure

Connection and engine-specific parameters are configured inside the `provider_config` nested dictionary for architectural separation between generic and provider-specific settings.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `host` | string | Yes | - | OpenSearch server host |
| `port` | integer | No | 9200 | OpenSearch server port |
| `username` | string | No | - | Username for basic authentication |
| `password` | string | No | - | Password for basic authentication |
| `use_ssl` | boolean | No | false | Use SSL connection |
| `verify_certs` | boolean | No | false | Verify SSL certificates |
| `aws_auth` | boolean | No | false | Use AWS IAM authentication |
| `aws_region` | string | No | - | AWS region for authentication |
| `jwt_token` | string | No | - | JWT token for Bearer authentication |
| `engine` | string | No | "faiss" | KNN engine (faiss, lucene, nmslib, jvector) |
| `algorithm` | string | No | "hnsw" | KNN algorithm (hnsw, ivf) |
| `space_type` | string | No | "l2" | Similarity metric (l2, cosine, inner_product) |
| `engine_parameters` | object | No | {} | Custom engine-specific parameters |

**Note**: Only one authentication method can be used at a time: basic auth (username/password), AWS IAM (aws_auth), or JWT token (jwt_token).

### Engine Parameters

#### FAISS + HNSW
```json
{
  "ef_construction": 128,
  "m": 24
}
```

#### FAISS + IVF
```json
{
  "nlist": 128,
  "nprobe": 8
}
```

#### Lucene + HNSW
```json
{
  "ef_construction": 128,
  "m": 16
}
```

## Usage Examples

### Example 1: Basic Usage with FAISS

```python
from docpipe.core.operators.vectordb import VectorDBOperator
from docpipe.common.constants.operator_constants import OperatorConstants
import pyarrow as pa
import numpy as np

config = {
    "provider": "opensearch",
    "index_name": "my_documents",
    "vector_dimension": 384,
    OperatorConstants.Config.PROVIDER_CONFIG: {
        "host": "localhost",
        "port": 9200,
        "username": "admin",
        "password": "<your-opensearch-password>",
        "use_ssl": False,
        OperatorConstants.VectorDB.ENGINE: "faiss",
        OperatorConstants.VectorDB.ALGORITHM: "hnsw",
        OperatorConstants.VectorDB.SPACE_TYPE: "l2"
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
    "feature_mappings": {
        "doc_id_hash": "id",
        "content": "text",
        "embeddings": "vector"
    }
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

### Example 2: Lucene Engine with Cosine Similarity

```python
from docpipe.common.constants.operator_constants import OperatorConstants

config = {
    "provider": "opensearch",
    "index_name": "semantic_search",
    "vector_dimension": 768,
    OperatorConstants.Config.PROVIDER_CONFIG: {
        "host": "localhost",
        "port": 9200,
        OperatorConstants.VectorDB.ENGINE: "lucene",
        OperatorConstants.VectorDB.ALGORITHM: "hnsw",
        OperatorConstants.VectorDB.SPACE_TYPE: "cosine",
        OperatorConstants.VectorDB.ENGINE_PARAMETERS: {
            "ef_construction": 256,
            "m": 32
        }
    }
}
```

### Example 3: AWS OpenSearch with IAM Authentication

```python
from docpipe.common.constants.operator_constants import OperatorConstants

config = {
    "provider": "opensearch",
    "index_name": "production_docs",
    OperatorConstants.Config.PROVIDER_CONFIG: {
        "host": "search-mydomain.us-east-1.es.amazonaws.com",
        "port": 443,
        "use_ssl": True,
        OperatorConstants.VectorDB.ENGINE: "faiss",
        OperatorConstants.VectorDB.ALGORITHM: "hnsw",
        OperatorConstants.VectorDB.AWS_AUTH: True,
        OperatorConstants.VectorDB.AWS_REGION: "us-east-1"
    }
}

### Example 4: JWT Token Authentication

For AWS OpenSearch or custom deployments with JWT authentication:

```python
from docpipe.common.constants.operator_constants import OperatorConstants
import os

config = {
    "provider": "opensearch",
    "index_name": "jwt_secured_docs",
    "vector_dimension": 384,
    OperatorConstants.Config.PROVIDER_CONFIG: {
        "host": "search-mydomain.us-east-1.es.amazonaws.com",
        "port": 443,
        "use_ssl": True,
        "verify_certs": True,
        OperatorConstants.VectorDB.ENGINE: "faiss",
        OperatorConstants.VectorDB.ALGORITHM: "hnsw",
        OperatorConstants.VectorDB.JWT_TOKEN: os.getenv("OPENSEARCH_JWT_TOKEN")
    }
}
```

**Important**: Only one authentication method can be used at a time (basic auth, AWS IAM, or JWT token).

**Environment Variable Setup**:
```bash
# pragma: allowlist secret
export OPENSEARCH_JWT_TOKEN="your-jwt-token-here"
```

**Security Best Practices**:
- Store JWT tokens in environment variables, never in code
- Use short-lived tokens (< 1 hour recommended)
- Rotate tokens regularly
- Use HTTPS/SSL for all connections

```

### Example 4: Query Documents

```python
# Query documents by name
docs = operator.query_by_doc_names(["doc1", "doc2"], fields=["content", "embeddings"])
print(f"Found {len(docs)} documents")

# Get document count
count = operator.get_document_count()
print(f"Total documents: {count}")

# Delete documents
success, failed = operator.delete_documents_by_ids(["doc1", "doc2"])
print(f"Deleted {success} documents, {failed} failed")
```

## Flow Configuration

### Complete Flow Example

```json
{
  "flow_name": "complete-document-pipeline",
  "description": "Complete document processing pipeline: Ingest -> Extract -> Chunk -> Embed -> Store in OpenSearch",
  "global_config": {
    "doc_column": "content",
    "disable_validation": true,
    "force_ingest": true,
    "storage": "in-memory",
    "execute_type": "local"
  },
  "flow": [
    {
      "type": "ingest_source",
      "name": "ingest_source_filesystem",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["./sample_documents"]},
        "include_filter": "pdf,txt,docx"
      }
    },
    {
      "type": "extract_operator",
      "name": "extract_with_docling",
      "config": {
        "text_extraction": {
          "provider": "docling_library",
          "doc_column": "content"
        },
        "entity_extraction": {
          "provider": "none"
        }
      },
      "depends_on": [
        "ingest_source_filesystem"
      ]
    },
    {
      "type": "chunker",
      "name": "simple_chunker",
      "config": {
        "chunk_type": "simple",
        "chunk_size": 512,
        "chunk_overlap": 50,
        "retain_original_content": false
      },
      "depends_on": [
        "extract_with_docling"
      ]
    },
    {
      "type": "embeddings",
      "name": "ollama_embeddings",
      "config": {
        "provider": "litellm",
        "provider_config": {
          "model_id": "openai/nomic-embed-text",
          "api_base": "http://localhost:11434/v1",
          "api_key": "<ollama-api-key>"
        },
        "embeddings_column": "embeddings",
        "overlap_ratio": 0.1
      },
      "depends_on": [
        "simple_chunker"
      ]
    },
    {
      "type": "vectordb",
      "name": "opensearch_vector_store",
      "config": {
        "provider": "opensearch",
        "index_name": "sample-documents-index",
        "doc_id_column": "doc_id_hash",
        "embeddings_column": "embeddings",
        "vector_dimension": 768,
        "provider_config": {
          "host": "localhost",
          "port": 9200,
          "username": "${OPENSEARCH_USERNAME}",
          "password": "${OPENSEARCH_PASSWORD}",
          "use_ssl": false,
          "verify_certs": false,
          "batch_size": 100,
          "engine": "faiss",
          "algorithm": "hnsw",
          "space_type": "l2"
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
          "doc_name": {
            "name": "Document Name",
            "available_for_vector_db": true,
            "type": "string"
          },
          "file_path": {
            "name": "File Path",
            "available_for_vector_db": true,
            "type": "string"
          },
          "embeddings": {
            "name": "Embeddings",
            "available_for_vector_db": true,
            "mandatory_for_vector_db": true,
            "type": "vector"
          },
          "chunk_id": {
            "name": "Chunk ID",
            "available_for_vector_db": true,
            "type": "string"
          },
          "chunk_index": {
            "name": "Chunk Index",
            "available_for_vector_db": true,
            "type": "integer"
          }
        },
        "feature_mappings": {
          "doc_id_hash": "pk",
          "content": "text",
          "name": "doc_name",
          "path": "file_path",
          "embeddings": "vector_embeddings",
          "chunk_id": "chunk_id",
          "chunk_index": "chunk_index"
        }
      },
      "depends_on": [
        "ollama_embeddings"
      ]
    }
  ]
}
```

## Performance Tuning

### Batch Size Optimization

The operator uses size-aware batching with a default limit of 3MB per batch:

```python
config = {
    "batch_size": 500,  # Maximum documents per batch
    # Actual batch size may be smaller if 3MB limit is reached
}
```

### Engine-Specific Tuning

#### FAISS + HNSW (Balanced)
```python
from docpipe.common.constants.operator_constants import OperatorConstants

OperatorConstants.Config.PROVIDER_CONFIG: {
    OperatorConstants.VectorDB.ENGINE: "faiss",
    OperatorConstants.VectorDB.ALGORITHM: "hnsw",
    OperatorConstants.VectorDB.ENGINE_PARAMETERS: {
        "ef_construction": 128,  # Higher = better accuracy, slower indexing
        "m": 24                  # Higher = better accuracy, more memory
    }
}
```

#### FAISS + IVF (Speed Priority)
```python
OperatorConstants.Config.PROVIDER_CONFIG: {
    OperatorConstants.VectorDB.ENGINE: "faiss",
    OperatorConstants.VectorDB.ALGORITHM: "ivf",
    OperatorConstants.VectorDB.ENGINE_PARAMETERS: {
        "nlist": 128,  # Number of clusters
        "nprobe": 8    # Clusters to search (higher = more accurate, slower)
    }
}
```

#### Lucene + HNSW (Native)
```python
OperatorConstants.Config.PROVIDER_CONFIG: {
    OperatorConstants.VectorDB.ENGINE: "lucene",
    OperatorConstants.VectorDB.ALGORITHM: "hnsw",
    OperatorConstants.VectorDB.ENGINE_PARAMETERS: {
        "ef_construction": 128,
        "m": 16  # Lucene typically uses lower m values
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

### 1. Engine Selection
- **FAISS**: Best for production, supports both HNSW and IVF
- **Lucene**: Good for native OpenSearch integration
- **Avoid nmslib**: Deprecated in OpenSearch 2.13+

### 2. Algorithm Selection
- **HNSW**: Recommended for most use cases (high accuracy)
- **IVF**: Use for very large datasets where speed is critical

### 3. Similarity Metrics
- **L2**: Euclidean distance (default, works well for most embeddings)
- **Cosine**: Normalized similarity (good for text embeddings)
- **Inner Product**: For pre-normalized vectors

### 4. Index Management
- The index is created automatically on first run and its schema is validated on later runs
- Validate existing index configuration matches your settings
- Use consistent engine/algorithm across index lifecycle

### 5. Batch Processing
- Default batch size (100) works well for most cases
- Increase for smaller documents, decrease for large documents
- Monitor memory usage with large batches

## Troubleshooting

See [`docs/integrations/opensearch/`](../../integrations/opensearch/) for troubleshooting and setup guides.

## Related Operators

- **IngestSourceOperator**: Ingest documents from local filesystem or remote sources
- **ExtractOperator**: Extract content from documents
- **DoclingChunkerOperator**: Chunk documents for vector storage
- **EmbeddingsOperator**: Generate embeddings from text

## References

- [OpenSearch k-NN Plugin Documentation](https://opensearch.org/docs/latest/search-plugins/knn/index/)
- [FAISS Documentation](https://github.com/facebookresearch/faiss)
- [OpenSearch Python Client](https://opensearch.org/docs/latest/clients/python/)
