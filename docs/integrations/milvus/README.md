# Milvus Vector Database Integration

## Overview

The Milvus adapter provides vector database capabilities for the docpipe project, supporting Milvus Lite (embedded local `.db` file), standalone Milvus deployments, and IBM watsonx.data (wx.data) managed Milvus instances. This integration follows the hexagonal architecture pattern, implementing the `VectorStorePort` interface for seamless integration with the VectorDBOperator.

## Features

- **Milvus Lite (container-free)**: Run locally without Docker, Podman, or Kubernetes — data persists to a local `.db` file
- **Dual Deployment Support**: Works with standalone Milvus and wx.data in addition to Lite
- **Multiple Index Types**: HNSW, IVF_FLAT, IVF_SQ8, IVF_PQ, FLAT, DISKANN, AUTOINDEX, SPARSE_INVERTED_INDEX, SPARSE_WAND
- **Flexible Similarity Metrics**: L2, Inner Product (IP), COSINE, BM25 (only for sparse vectors)
- **Dense and Sparse Vectors**: Support for both dense embeddings and BM25 sparse vectors
- **Batch Processing**: Efficient bulk operations with size-aware batching
- **Automatic Schema Management**: Dynamic collection creation based on feature mappings
- **Authentication Options**: Token-based (wx.data), username/password (standalone), or local path (Lite)

## Architecture

### Components

```
MilvusAdapter (VectorStorePort)
├── MilvusClient - Connection management
├── MilvusIndexManager - Collection/schema operations
└── MilvusBatchProcessor - Bulk data operations
```

### Key Classes

1. **MilvusClient** (`adapters/outbound/milvus/client.py`)
   - Manages connections to Milvus
   - Always constructs a URI internally from host/port (PyMilvusClient only accepts `uri`, not `host`/`port` directly)
   - Handles authentication via `token="user:password"`

2. **MilvusIndexManager** (`adapters/outbound/milvus/index_manager.py`)
   - Creates and manages collections
   - Configures index types and parameters
   - Maps PyArrow schema to Milvus schema

3. **MilvusBatchProcessor** (`adapters/outbound/milvus/batch_processor.py`)
   - Handles bulk insert, query, and delete operations
   - Implements size-aware batching
   - Prepares documents for indexing

4. **MilvusAdapter** (`adapters/outbound/milvus/adapter.py`)
   - Implements VectorStorePort interface
   - Registered with VectorStoreFactory
   - Coordinates between client, index manager, and batch processor

## Configuration

### Authentication Types

Milvus adapter supports five authentication types via the `auth_type` parameter:

1. **lite**: Milvus Lite — embedded local database, no external service required. `uri` must be a local `.db` file path. Only `FLAT` index type is supported.
2. **standalone**: Local Milvus with optional username/password
3. **grpc**: IBM wx.data with gRPC (requires username with `ibmlhapikey_` prefix and API key as password)
4. **uri**: Pre-constructed URI with embedded API key
5. **token**: IAM token-based (constructs URI internally from host/port/username/token)

### Milvus Lite (Container-Free Local)

No Docker, Podman, or Kubernetes required. Data is persisted to a local `.db` file.

**Installation:** `milvus-lite` is included as a core dependency — no separate installation needed.

**Constraints:**
- Only `FLAT` index type is supported (other index types are rejected at initialisation with an actionable error)
- Set `enable_micro_batching: false` in `global_config` — Milvus Lite holds a single-process file lock
- Not intended for production-scale workloads; use standalone or remote Milvus for those

```json
{
  "type": "vectordb",
  "name": "store_locally",
  "config": {
    "provider": "milvus",
    "doc_id_column": "doc_id_hash",
    "add_sparse_vector": false,
    "provider_config": {
      "collection_name": "documents",
      "auth_type": "lite",
      "uri": "./data/milvus/documents.db",
      "index_type": "FLAT",
      "metric_type": "COSINE",
      "batch_size": 100
    }
  },
  "depends_on": ["embed"]
}
```

**Path resolution:** relative paths (e.g. `./data/milvus/docs.db`) are resolved from the working directory where `docling-pipelines` is invoked. The parent directory is created automatically if it does not exist. Use an absolute path to avoid ambiguity.

**Persistence:** data survives process restart — reopen the same `.db` file path to query or extend the collection.

**Migration path:** swap `auth_type: "lite"` for `auth_type: "standalone"` (and add `host`/`port`) to move from Milvus Lite to a standalone deployment without any other flow changes.

### Standalone Milvus

```json
{
  "id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
  "name": "milvus_vector_store",
  "operator": "vectordb",
  "config": {
    "provider": "milvus",
    "embeddings_column": "embeddings",
    "vector_dimension": 384,
    "add_sparse_vector": false,
    "available_features": {
      "doc_id_hash": {
        "type": "keyword",
        "available_for_vector_db": true
      },
      "content": {
        "type": "text",
        "available_for_vector_db": true
      },
      "embeddings": {
        "type": "vector",
        "available_for_vector_db": true
      }
    },
    "feature_mappings": {
      "doc_id_hash": "pk",
      "content": "text",
      "embeddings": "vector"
    },
    "provider_config": {
      "collection_name": "my_collection",
      "auth_type": "standalone",
      "host": "localhost",
      "port": 19530,
      "username": "root",
      "password": "<your-milvus-password>",
      "database": "default",
      "index_type": "HNSW",
      "metric_type": "L2",
      "secure": false,
      "index_parameters": {
        "M": 16,
        "efConstruction": 200
      }
    }
  }
}
```

### wx.data with gRPC (API Key)

```json
{
  "id": "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e",
  "name": "wxdata_grpc_store",
  "operator": "vectordb",
  "config": {
    "provider": "milvus",
    "embeddings_column": "embeddings",
    "vector_dimension": 384,
    "add_sparse_vector": false,
    "provider_config": {
      "collection_name": "my_collection",
      "auth_type": "grpc",
      "host": "your-wxdata-instance.cloud.ibm.com",
      "port": 19530,
      "username": "ibmlhapikey_your_username",
      "password": "<your-api-key>",
      "database": "default",
      "index_type": "HNSW",
      "metric_type": "COSINE",
      "secure": true
    },
    "available_features": {
      "doc_id_hash": {
        "type": "keyword",
        "available_for_vector_db": true
      },
      "content": {
        "type": "text",
        "available_for_vector_db": true
      },
      "embeddings": {
        "type": "vector",
        "available_for_vector_db": true
      }
    },
    "feature_mappings": {
      "doc_id_hash": "pk",
      "content": "text",
      "embeddings": "vector"
    }
  }
}
```

### wx.data with URI (API Key Embedded)

```json
{
  "id": "c3d4e5f6-a7b8-4c9d-0e1f-2a3b4c5d6e7f",
  "name": "wxdata_uri_store",
  "operator": "vectordb",
  "config": {
    "provider": "milvus",
    "embeddings_column": "embeddings",
    "vector_dimension": 384,
    "add_sparse_vector": false,
    "available_features": {
      "doc_id_hash": {
        "type": "keyword",
        "available_for_vector_db": true
      },
      "content": {
        "type": "text",
        "available_for_vector_db": true
      },
      "embeddings": {
        "type": "vector",
        "available_for_vector_db": true
      }
    },
    "feature_mappings": {
      "doc_id_hash": "pk",
      "content": "text",
      "embeddings": "vector"
    },
    "provider_config": {
      "collection_name": "my_collection",
      "auth_type": "uri",
      "uri": "https://ibmlhapikey_your_username:<your-api-key>@your-wxdata-instance.cloud.ibm.com:19530",
      "database": "default",
      "index_type": "HNSW",
      "metric_type": "COSINE"
    }
  }
}
```

### wx.data with IAM Token

```json
{
  "id": "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a",
  "name": "wxdata_token_store",
  "operator": "vectordb",
  "config": {
    "provider": "milvus",
    "embeddings_column": "embeddings",
    "vector_dimension": 384,
    "add_sparse_vector": false,
    "available_features": {
      "doc_id_hash": {
        "type": "keyword",
        "available_for_vector_db": true
      },
      "content": {
        "type": "text",
        "available_for_vector_db": true
      },
      "embeddings": {
        "type": "vector",
        "available_for_vector_db": true
      }
    },
    "feature_mappings": {
      "doc_id_hash": "pk",
      "content": "text",
      "embeddings": "vector"
    },
    "provider_config": {
      "collection_name": "my_collection",
      "auth_type": "token",
      "host": "your-wxdata-instance.cloud.ibm.com",
      "port": 19530,
      "username": "your_username",
      "token": "your-iam-token",
      "database": "default",
      "index_type": "HNSW",
      "metric_type": "COSINE"
    }
  }
}
```

## Configuration Parameters

### Connection Parameters

| Parameter   | Type    | Required         | Default   | Description |
|-------------|---------|------------------|-----------|-------------|
| `auth_type` | string  | Yes              | -         | Authentication type: `lite`, `standalone`, `grpc`, `uri`, or `token` |
| `uri`       | string  | Conditional*     | -         | Local `.db` file path (for `lite`) or full remote URI (for `uri` auth_type) |
| `host`      | string  | Conditional**    | -         | Milvus server host |
| `port`      | integer | Conditional**    | 19530     | Milvus server port |
| `token`     | string  | Conditional***   | -         | IAM token (for `token` auth_type) |
| `username`  | string  | Conditional****  | -         | Username for authentication |
| `password`  | string  | Conditional***** | -         | Password/API key for authentication |
| `database`  | string  | No               | "default" | Database name (not used for `lite`) |
| `secure`    | bool    | No               | false     | Enable TLS/SSL (not used for `lite`) |

#### Auth Type Requirements

| auth_type    | Required Parameters                    | Description |
|--------------|----------------------------------------|-------------|
| `lite`       | `uri` (local `.db` path)               | Milvus Lite — embedded local database. No external service. Only `FLAT` index supported. |
| `standalone` | `host`, `port`                         | Local Milvus. Optional: `username`, `password` |
| `grpc`       | `host`, `port`, `username`, `password` | IBM wx.data with gRPC. Username must have `ibmlhapikey_` prefix, password is API key |
| `uri`        | `uri`                                  | Pre-constructed URI with embedded API key (format: `https://ibmlhapikey_<username>:<api-key>@<host>:<port>`) |
| `token`      | `host`, `port`, `username`, `token`    | IAM token-based. Constructs URI internally (format: `https://ibmlhtoken_<username>:<token>@<host>:<port>`) |

*Required for `lite` and `uri` auth types
**Required for `standalone`, `grpc`, and `token` auth types
***Required for `token` auth_type
****Required for `grpc` and `token` auth types
*****Required for `grpc` auth_type (should be API key)

### Index Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `index_type` | string | No | "HNSW" | Index type (HNSW, IVF_FLAT, etc. Auto-set to SPARSE_INVERTED_INDEX in sparse mode) |
| `metric_type` | string | No | "L2" | Similarity metric (L2, IP, COSINE for dense; BM25 for sparse) |
| `index_parameters` | object | No | {} | Index-specific parameters |

### Operator Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `provider` | string | Yes | - | Must be "milvus" |
| `provider_config.collection_name` | string | Yes | - | Name of the Milvus collection |
| `embeddings_column` | string | No | "embeddings" | Column containing vectors |
| `vector_dimension` | integer | No | 384 | Vector dimension (dense mode only) |
| `add_sparse_vector` | boolean | No | false | Use BM25 sparse vectors instead of dense |
| `batch_size` | integer | No | 100 | Batch size for operations |
| `primary_key_field` | string | No | "pk" | Primary key field name |
| `auto_id` | boolean | No | false | Auto-generate IDs |

## Index Types

### HNSW (Hierarchical Navigable Small World)
- **Best for**: High recall, fast search
- **Parameters**:
  - `M`: Number of connections (default: 16)
  - `efConstruction`: Build-time search depth (default: 200)

```json
{
  "index_type": "HNSW",
  "index_parameters": {
    "M": 16,
    "efConstruction": 200
  }
}
```

### IVF_FLAT (Inverted File with Flat Compression)
- **Best for**: Balance between speed and accuracy
- **Parameters**:
  - `nlist`: Number of clusters (default: 128)

```json
{
  "index_type": "IVF_FLAT",
  "index_parameters": {
    "nlist": 128
  }
}
```

### IVF_SQ8 (Inverted File with Scalar Quantization)
- **Best for**: Memory efficiency
- **Parameters**:
  - `nlist`: Number of clusters (default: 128)

### IVF_PQ (Inverted File with Product Quantization)
- **Best for**: Maximum compression
- **Parameters**:
  - `nlist`: Number of clusters (default: 128)
  - `m`: Number of subquantizers (default: 8)
  - `nbits`: Bits per subquantizer (default: 8)

### FLAT
- **Best for**: Exact search, small datasets
- **Parameters**: None

### AUTOINDEX
- **Best for**: Automatic optimization
- **Parameters**: None (Milvus chooses optimal settings)

## Similarity Metrics

| Metric | Description | Use Case | Vector Type |
|--------|-------------|----------|-------------|
| `L2` | Euclidean distance | General purpose, normalized vectors | Dense only |
| `IP` | Inner product | Cosine similarity with normalized vectors | Dense only |
| `COSINE` | Cosine similarity | Text embeddings, semantic search | Dense only |
| `BM25` | BM25 text scoring | Sparse vectors, keyword search | Sparse only (required) |

## Deployment Scenarios

Docling Pipelines provides two example pipeline flows demonstrating different Milvus deployment scenarios:

### 1. Standalone Milvus (Local/Docker) - Sparse Vectors
**Example Flow**: [`sample_flows/vectordb/milvus_integration.json`](../../../sample_flows/vectordb/milvus_integration.json)

**Use Case**: Local development, testing, or self-hosted Milvus

**Key Configuration:**
```json
{
  "provider": "milvus",
  "doc_id_column": "doc_id_hash",
  "embeddings_column": "embeddings",
  "add_sparse_vector": true,
  "provider_config": {
    "collection_name": "sample_documents_sparse",
    "auth_type": "standalone",
    "host": "localhost",
    "port": 19530,
    "secure": false,
    "username": "root",
    "password": "<YOUR_PASSWORD>",
    "metric_type": "BM25",
    "index_type": "SPARSE_INVERTED_INDEX"
  }
}
```

**Features:**
- No SSL/TLS required (`secure` parameter not needed)
- Simple username/password authentication
- Demonstrates sparse + dense vector storage with BM25

### 2. IBM watsonx.data Milvus (Cloud) - Dense Vectors
**Example Flow**: [`sample_flows/vectordb/milvus_integration.json`](../../../sample_flows/vectordb/milvus_integration.json)

**Use Case**: Enterprise deployment with IBM watsonx.data managed Milvus

**Key Configuration:**
```json
{
  "provider": "milvus",
  "doc_id_column": "doc_id_hash",
  "embeddings_column": "embeddings",
  "add_sparse_vector": false,
  "provider_config": {
    "collection_name": "sample_documents_collection_dense",
    "auth_type": "grpc",
    "host": "<YOUR_WXDATA_HOST>",
    "port": "<YOUR_PORT>",
    "username": "<YOUR_USERNAME>",
    "password": "<YOUR_API_KEY>",
    "secure": true,
    "metric_type": "L2",
    "index_type": "HNSW"
  }
}
```

**CRITICAL REQUIREMENTS:**

⚠️ **`secure: true` is MANDATORY** for watsonx.data connections

IBM watsonx.data is a cloud-managed service that requires encrypted communication. The `secure: true` parameter enables SSL/TLS encryption for gRPC connections, which is essential for:
- **Security**: Encrypts data in transit between your application and watsonx.data
- **Authentication**: Required by watsonx.data's gRPC endpoint to establish trusted connections
- **Compliance**: Meets enterprise security standards for cloud deployments

Without `secure: true`, the connection attempt will fail with `HTTPConnectionError` because watsonx.data's gRPC endpoint rejects unencrypted connections.

**Additional Requirements:**
- **macOS Users**: Set `GRPC_DNS_RESOLVER=native` environment variable before running the pipeline. This resolves a known gRPC DNS resolution issue on macOS when connecting through VPNs or to cloud services.
- **Password**: For grpc authentication type use your IBM Cloud API key, not your account password

## Vector Types

### Dense Vectors (Default)

Dense vectors are traditional embeddings generated by models like Ollama, OpenAI, or HuggingFace. They require an upstream embeddings operator.

**Configuration:**
```json
{
  "embeddings_column": "embeddings",
  "add_sparse_vector": false,
  "vector_dimension": 768,
  "feature_mappings": {
    "embeddings": "dense_embeddings"
  },
  "provider_config": {
    "index_type": "HNSW",
    "metric_type": "COSINE"
  }
}
```

**Pipeline Requirements:**
- Must include embeddings operator upstream
- Vector dimension must match embeddings model output
- Supports HNSW, IVF_FLAT, IVF_SQ8, IVF_PQ, FLAT indexes

### Sparse Vectors (BM25)

Sparse vectors are automatically generated from text content using Milvus's built-in BM25 function during insertion. The pipeline still requires an embeddings operator for dense embeddings, but the BM25 function generates additional sparse vectors from the text content.

**Configuration:**
```json
{
  "embeddings_column": "embeddings",
  "add_sparse_vector": true,
  "feature_mappings": {
    "doc_id_hash": "pk",
    "content": "text",
    "embeddings": "vector",
    "sparse_embeddings": "sparse_vector"
  },
  "provider_config": {
    "auth_type": "standalone",
    "index_type": "SPARSE_INVERTED_INDEX",
    "metric_type": "BM25"
  }
}
```

**Key Differences:**
- **Embeddings operator still required** - Pipeline includes both dense and sparse vectors
- **Content field required** - Must map content column to Milvus text field for BM25 function
- **Auto-set index type** - Automatically set to SPARSE_INVERTED_INDEX in sparse mode
- **Required metric** - Must use BM25 (validated and enforced)
- **No dimension parameter** - Sparse vectors have variable dimensions
- **Dual vector storage** - Stores both dense embeddings and BM25-generated sparse vectors

**How It Works:**
1. Pipeline generates dense embeddings via embeddings operator
2. User provides text content in PyArrow table
3. Milvus BM25 function automatically converts text to sparse vectors during insertion
4. Both dense and sparse vectors stored in collection
5. Search can use either dense (semantic) or sparse (keyword) vectors

## Usage Examples

### Basic Pipeline with Milvus (Dense Vectors)

For a complete working example, see [`sample_flows/vectordb/milvus_integration.json`](../../../sample_flows/vectordb/milvus_integration.json).

**Key Configuration:**
```json
{
  "type": "vectordb",
  "config": {
    "provider": "milvus",
    "embeddings_column": "embeddings",
    "vector_dimension": 384,
    "add_sparse_vector": false,
    "feature_mappings": {
      "doc_id_hash": "pk",
      "embeddings": "vector",
      "content": "text"
    },
    "provider_config": {
      "collection_name": "documents",
      "auth_type": "standalone",
      "host": "localhost",
      "port": 19530,
      "username": "root",
      "password": "<YOUR_PASSWORD>",
      "database": "default",
      "index_type": "HNSW",
      "metric_type": "L2",
      "index_parameters": {
        "M": 16,
        "efConstruction": 256
      }
    }
  }
}
```

**Pipeline Structure:**
1. Ingest documents
2. Extract text with Docling
3. Chunk documents
4. Generate embeddings (Ollama/HuggingFace/etc.)
5. Store in Milvus with dense vectors only

### Sparse Vector Pipeline (BM25)

For a complete working example, see [`sample_flows/vectordb/milvus_integration.json`](../../../sample_flows/vectordb/milvus_integration.json).

**Key Configuration:**
```json
{
  "type": "vectordb",
  "config": {
    "provider": "milvus",
    "embeddings_column": "embeddings",
    "add_sparse_vector": true,
    "feature_mappings": {
      "doc_id_hash": "pk",
      "embeddings": "vector",
      "sparse_embeddings": "sparse_vector",
      "content": "text"
    },
    "provider_config": {
      "collection_name": "documents_sparse",
      "auth_type": "standalone",
      "host": "localhost",
      "port": 19530,
      "username": "root",
      "password": "<YOUR_PASSWORD>",
      "database": "default",
      "index_type": "SPARSE_INVERTED_INDEX",
      "metric_type": "BM25"
    }
  }
}
```

**Pipeline Structure:**
1. Ingest documents
2. Extract text with Docling
3. Chunk documents
4. Generate embeddings (Ollama/HuggingFace/etc.)
5. Store in Milvus with both dense and sparse vectors

**Note:** Sparse vector pipeline INCLUDES embeddings operator - both dense embeddings and BM25 sparse vectors are stored together.

### Python Integration Example

For a comprehensive Python example demonstrating Milvus operator usage, see [`examples/milvus_integration_example.py`](../../../examples/milvus_integration_example.py). This example includes:

1. **Basic Document Indexing** - HNSW index with metadata fields
2. **IVF_FLAT Index** - Optimized for large datasets
3. **COSINE Similarity** - Alternative metric type
4. **Query and Delete Operations** - Document retrieval and deletion
5. **Large Batch Processing** - Efficient bulk operations
6. **Error Handling** - Graceful handling of missing data

Run the example:
```bash
# Set up environment variables in .env file
export MILVUS_HOST=localhost
export MILVUS_PORT=19530
export MILVUS_USERNAME=root
export MILVUS_PASSWORD=your-milvus-password

# Run the example
python examples/milvus_integration_example.py
```

### wx.data Configuration

```json
{
  "id": "b8c9d0e1-f2a3-4b4c-5d6e-7f8a9b0c1d2e",
  "name": "wxdata_vector_store",
  "operator": "vectordb",
  "config": {
    "provider": "milvus",
    "embeddings_column": "embeddings",
    "vector_dimension": 768,
    "add_sparse_vector": false,
    "available_features": {
      "doc_id_hash": {
        "type": "keyword",
        "available_for_vector_db": true
      },
      "content": {
        "type": "text",
        "available_for_vector_db": true
      },
      "embeddings": {
        "type": "vector",
        "available_for_vector_db": true
      }
    },
    "feature_mappings": {
      "doc_id_hash": "pk",
      "content": "text",
      "embeddings": "vector"
    },
    "provider_config": {
      "collection_name": "enterprise_docs",
      "uri": "https://milvus.wxdata.ibm.com:19530",
      "token": "${WXDATA_TOKEN}",
      "db_name": "production",
      "secure": true,
      "index_type": "HNSW",
      "metric_type": "COSINE",
      "index_parameters": {
        "M": 32,
        "efConstruction": 400
      }
    }
  }
}
```

## Feature Mappings

Feature mappings define which PyArrow table columns are stored in Milvus:

```json
{
  "available_features": {
    "embeddings": {
      "type": "vector",
      "available_for_vector_db": true
    },
    "content": {
      "type": "text",
      "available_for_vector_db": true
    },
    "doc_id_hash": {
      "type": "keyword",
      "available_for_vector_db": true
    }
  },
  "feature_mappings": {
    "embeddings": "vector_field",
    "content": "text_content",
    "doc_id_hash": "document_id"
  }
}
```

## Performance Tuning

### Batch Size
- **Small datasets (<10K)**: 100-500
- **Medium datasets (10K-1M)**: 500-1000
- **Large datasets (>1M)**: 1000-5000

### Index Selection
- **High accuracy required**: HNSW or FLAT
- **Memory constrained**: IVF_SQ8 or IVF_PQ
- **Balanced**: IVF_FLAT
- **Uncertain**: AUTOINDEX

### HNSW Parameters
- **Higher M**: Better recall, more memory
- **Higher efConstruction**: Better index quality, slower build
- Recommended: M=16-32, efConstruction=200-400

## Troubleshooting

### Connection Issues

**Problem**: Cannot connect to Milvus
```
MilvusDB Error: Failed to connect using standalone auth_type: Fail connecting to server on localhost:19530, illegal connection params or server unavailable
```

**Solutions**:
1. Verify Milvus is running: `curl http://localhost:9091/healthz` (should return `OK`)
2. Start with Docker: `docker compose -f docker/docker-compose.milvus.yml up -d`
3. Check port accessibility: `telnet localhost 19530`
4. Verify credentials match your Milvus setup (default: `root` / `Milvus`)
5. For wx.data, check token validity

### macOS gRPC DNS Resolution Issue

**Problem**: Connection fails on macOS when accessing Milvus through VPN or watsonx.data
```
MilvusException: (code=2, message=Fail connecting to server on your-host-name:443,
illegal connection params or server unavailable)
```

**Cause**: macOS gRPC DNS resolver incompatibility with certain network configurations

**Solution**: Set the `GRPC_DNS_RESOLVER` environment variable before running your application:

```bash
export GRPC_DNS_RESOLVER=native
```

Or in Python code before importing Milvus libraries:
```python
import os
os.environ["GRPC_DNS_RESOLVER"] = "native"

# Then import and use docpipe
from docpipe.core.operators.vectordb import VectorDBOperator
```

**Verification Steps**:
1. Check if the Milvus instance was deleted and recreated (host URL may have changed)
2. Verify the certificate is a gRPC certificate, not an HTTPS certificate
3. Apply the `GRPC_DNS_RESOLVER=native` environment variable
4. Retry the connection

**Note**: This issue primarily affects:
- macOS systems (not Linux or Windows)
- VPN connections
- IBM watsonx.data Milvus instances
- Non-VM macOS environments

### Collection Creation Failures

**Problem**: Collection creation fails
```
Failed to create collection 'my_collection'
```

**Solutions**:
1. Check collection name (alphanumeric, underscores only)
2. Verify vector dimension matches embeddings
3. Ensure sufficient permissions
4. Check Milvus server logs

### Index Build Errors

**Problem**: Index parameters invalid
```
Invalid index type 'HNSW'. Supported: [...]
```

**Solutions**:
1. Verify index type spelling (case-sensitive)
2. Check index parameters for selected type
3. Ensure metric type is compatible with index

### Memory Issues

**Problem**: Out of memory during indexing
```
Memory allocation failed
```

**Solutions**:
1. Reduce batch_size
2. Use memory-efficient index (IVF_SQ8, IVF_PQ)
3. Increase Milvus memory limits
4. Process data in smaller chunks

## Testing

### Unit Tests

```bash
cd /path/to/docling-pipelines
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
uv run pytest tests/unit/operators/vectordb/test_milvus_client.py -v
```

### Integration Tests

#### Milvus Lite (no external service required)

The full end-to-end integration test (ingest → extract → chunk → embed → Milvus Lite) requires no running server:

```bash
source .venv/bin/activate
pytest tests/integration/test_ingest_extract_chunk_embed_milvus_lite.py -v
```

This test covers:
- `test_full_pipeline_with_feature_mappings` — E2E flow; verifies row count, schema fields, and content stored correctly
- `test_incremental_reindex_no_duplicates` — runs twice against the same `.db`; confirms row count is stable (no duplicates)
- `test_unsupported_index_type_rejected` — confirms non-FLAT index types are rejected at initialisation with a clear error

#### Standalone Milvus (requires running instance)

```bash
# Start Milvus (Docker)
docker run -d --name milvus \
  -p 19530:19530 \
  -p 9091:9091 \
  milvusdb/milvus:latest

# Run tests
uv run pytest tests/integration/milvus/ -v
```

## Migration from OpenSearch

To migrate from OpenSearch to Milvus:

1. **Update flow configuration**:
   ```json
   {
     "provider": "milvus",  // Changed from "opensearch"
     "provider_config": {
       "collection_name": "my_collection",
       "auth_type": "standalone",  // Required: standalone, grpc, uri, or token
       "host": "localhost",
       "port": 19530,  // Changed from 9200
       "username": "root",
       "password": "<YOUR_PASSWORD>",
       "index_type": "HNSW",  // Instead of "engine"
       "metric_type": "L2"  // Instead of "space_type"
     }
   }
   ```

2. **Index type mapping**:
   - OpenSearch `faiss/hnsw` → Milvus `HNSW`
   - OpenSearch `faiss/ivf` → Milvus `IVF_FLAT`
   - OpenSearch `lucene/hnsw` → Milvus `HNSW`

3. **Metric type mapping**:
   - OpenSearch `l2` → Milvus `L2`
   - OpenSearch `cosine` → Milvus `COSINE`
   - OpenSearch `inner_product` → Milvus `IP`

## References

- [Milvus Documentation](https://milvus.io/docs)
- [PyMilvus SDK](https://github.com/milvus-io/pymilvus)
- [IBM watsonx.data](https://www.ibm.com/products/watsonx-data)
- [Docling Pipelines Architecture](../../../ARCHITECTURE.md)

## Support

For issues or questions:
1. Check Milvus server logs
2. Review Docling Pipelines logs for detailed error messages
3. Consult Milvus documentation for index-specific issues
4. For wx.data issues, contact IBM support
