# Docling Pipelines Flow Configuration Guide

This guide explains how to create and configure Docling Pipelines pipeline flows using JSON configuration files.

## Table of Contents

1. [Flow Structure Overview](#flow-structure-overview)
2. [Required Top-Level Fields](#required-top-level-fields)
3. [Global Configuration Options](#global-configuration-options)
4. [Operator Configuration](#operator-configuration)
5. [Connecting Operators](#connecting-operators)
6. [Complete Examples](#complete-examples)

---

## Flow Structure Overview

Docling Pipelines pipelines are defined using JSON configuration files. Here's the basic structure:

```json
{
  "flow_name": "complete-document-pipeline",
  "description": "Complete document processing pipeline",
  "global_config": {
    "doc_column": "content",
    "disable_validation": false,
    "force_ingest": true,
    "storage": "in-memory",
    "execute_type": "local"
  },
  "flow": [
    // Operator definitions go here
  ]
}
```

---

## Required Top-Level Fields

| Field           | Type   | Description              | Example                                  |
| --------------- | ------ | ------------------------ | ---------------------------------------- |
| `flow_name`     | string | Human-readable flow name | `"complete-document-pipeline"`           |
| `description`   | string | Flow purpose description | `"Complete document processing pipeline"` |
| `global_config` | object | Global configuration     | See below                                |
| `flow`          | array  | Operator definitions     | See operator sections                    |

---

## Global Configuration Options

The `global_config` object supports the following options:

| Field                | Type     | Description                      | Default         | Example                 |
| -------------------- |----------| -------------------------------- |-----------------|-------------------------|
| `doc_column`         | string   | Column name for document content | `"content"`     | `"content"`             |
| `force_ingest`       | boolean  | Force re-ingestion of documents  | `false`         | `true`                  |
| `disable_validation` | boolean  | Disable flow validation          | `false`         | `true`                  |

**Example with global configuration**

```json
{
  "global_config": {
    "doc_column": "content",
    "force_ingest": true,
    "disable_validation": true
  }
}
```

### Flow Identification: flow_name and job_id

The `flow_name` field in your flow definition serves different purposes depending on how you execute the flow:

#### CLI Execution (`docling-pipelines`)

When using the `docling-pipelines` CLI, the `flow_name` is automatically used to generate a unique `job_id` for tracking flow executions and incremental processing.

**Automatic job_id Generation:**
- job_id is automatically generated from flow_name as a deterministic 36-character UUID (UUID v5)
- Format: Standard UUID (e.g., `a1b2c3d4-e5f6-5789-a012-b3c4d5e6f7a8`)
- The UUID is deterministic, so the same flow_name always produces the same job_id
- Compatible with all storage backends (filesystem, DuckDB, PostgreSQL)
- Generation process:
  1. Sanitize flow_name (lowercase, replace spaces/special chars with hyphens)
  2. Generate 8-character hash from original flow_name
  3. Create intermediate string: `{sanitized}_{hash}`
  4. Generate UUID v5 from intermediate string
- Example: flow_name "My Document Pipeline" → job_id "f8e3a1b2-c4d5-5678-9abc-def012345678"

**Important Considerations:**

> ⚠️ **flow_name Uniqueness**: Use a unique flow_name for each logically different pipeline. Reusing the same flow_name across different pipelines will generate the same job_id, causing incremental metadata conflicts where documents processed in one pipeline may be incorrectly marked as processed in another.

> ⚠️ **Incremental Processing Impact**: Since incremental ingestion metadata is associated with the job_id (derived from flow_name), changing a flow's flow_name will generate a new job_id, causing previously processed files to be reprocessed.

#### Python API (`DocpipeFlowManager`)

When using the Python API, you must provide a unique `job_id` parameter for each flow execution:

```python
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

# You must provide a unique job_id
manager = DocpipeFlowManager(
    flow_file="my_flow.json",
    job_id="my-unique-job-id-12345"  # Required for proper tracking
)
result = manager.execute()
```

If no `job_id` is provided, a random UUID will be generated, which means incremental processing will not work correctly across executions.

#### REST API

When creating flows via the REST API, a `flow_id` is automatically generated and used as the `job_id` for execution tracking.

---

## Operator Configuration

### Operator 1: IngestSourceOperator

Reads files from a local directory:

```json
{
  "name": "ingest",
  "type": "ingest_source",
  "config": {
    "provider": "filesystem",
    "provider_config": {"paths": ["./tests/fixtures/invoices"]},
    "include_filter": ".pdf"
  }
}
```

**Note:** Extension names should include the dot prefix and be comma-separated (e.g., `".pdf,.txt,.docx"` not `"*.pdf,*.txt"` or `"pdf,txt"`).

---

### Operator 2: ExtractOperator

The `extract_operator` handles both text extraction and entity extraction.

**Supported text extraction providers:**

- `docling_library`
- `docling_serve`

**Supported entity extraction providers:**

- `docling`
- `litellm`
- `watsonx`
- `none`

#### Basic Text Extraction (DEFAULT)

```json
{
  "name": "extract",
  "type": "extract_operator",
  "depends_on": ["ingest"],
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content"
    },
    "entity_extraction": {
      "provider": "none"
    }
  }
}
```

#### Advanced Template-Based Extraction

For structured data extraction with predefined schemas, use `entity_extraction.provider: "docling"`

**Important:** When using any entity extraction provider (not `none`), you must provide either:
- A `custom_schema` in the operator configuration (as shown below), OR
- A `document_type` column from an upstream classification operator (e.g., DocumentClassifierOperator)

If neither is provided, the operator will throw a `ConfigurationError`.

```json
{
  "name": "extract",
  "type": "extract_operator",
  "depends_on": ["ingest"],
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content"
    },
    "entity_extraction": {
      "provider": "docling",
      "expand_extracted_data": true,
      "custom_schema": {
        "invoice_number": "string",
        "invoice_date": "string",
        "vendor_name": "string",
        "total": "float"
      }
    }
  }
}
```

#### LLM-Based Entity Extraction with Ollama

For LLM-powered entity extraction using Ollama models, use `entity_extraction.provider: "litellm"` with the `openai/` prefix:

```json
{
  "name": "extract",
  "type": "extract_operator",
  "depends_on": ["ingest"],
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content"
    },
    "entity_extraction": {
      "provider": "litellm",
      "provider_config": {
        "model_id": "openai/llama3.1:latest",
        "api_base": "http://localhost:11434/v1"
      },
      "expand_extracted_data": true,
      "custom_schema": {
        "invoice_number": "string",
        "invoice_date": "string",
        "vendor_name": "string",
        "total": "float"
      }
    }
  }
}
```

This approach uses LiteLLM to access Ollama models for flexible, LLM-powered entity extraction. This is useful when you need to extract specific fields from structured documents like invoices, forms, or receipts.

#### GPU-Accelerated Text Extraction

For hardware-accelerated PDF and image extraction using a local GPU. The GPU `DocumentConverter` is taken from a process-wide converter pool and reused for every document and micro-batch, so GPU model weights are loaded once per configuration rather than once per batch.

> Requires `max_workers: 1` and `use_processes: false`. Cannot be combined with `vlm_pipeline`.

When `device` is omitted, the best available GPU is auto-detected via torch at runtime (CUDA → MPS → XPU). Specify `device` explicitly to pin a particular GPU.

```json
{
  "name": "extract",
  "type": "extract_operator",
  "depends_on": ["ingest"],
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content",
      "provider_config": {
        "standard_pipeline": {
          "accelerator": {
            "num_threads": 6
          }
        }
      }
    },
    "entity_extraction": {
      "provider": "none"
    },
    "max_workers": 1,
    "use_processes": false
  }
}
```

**Supported devices:** `mps` (Apple Silicon), `cuda` (NVIDIA), `cuda:<index>` (e.g. `cuda:0`), `xpu` (Intel). Auto-detected when `device` is not specified.

---

### Operator 3: ChunkerOperator

Splits documents into chunks:

```json
{
  "name": "chunk",
  "type": "chunker",
  "depends_on": ["extract"],
  "config": {
    "chunk_type": "hybrid",
    "doc_column": "content",
    "chunk_size": 512,
    "chunk_overlap": 128,
    "retain_original_content": false
  }
}
```

---

### Operator 4: EmbeddingsOperator

Generates vector embeddings:

```json
{
  "name": "embeddings",
  "type": "embeddings",
  "depends_on": ["chunk"],
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/granite4:latest",
      "api_base": "http://localhost:11434"
    },
    "embeddings_column": "embeddings",
    "overlap_ratio": 0.2,
    "doc_column": "content"
  }
}
```

**Note:** Use `ollama list` to see available models on your system. Common embedding models include `granite4:latest`, `nomic-embed-text`, and `mxbai-embed-large`.

---

### Operator 5: VectorDBOperator

Stores documents and embeddings in OpenSearch for vector similarity search.

#### Basic Configuration

```json
{
  "name": "vectordb",
  "type": "vectordb",
  "depends_on": ["embeddings"],
  "config": {
    "provider": "opensearch",
    "doc_id_column": "doc_id_hash",
    "embeddings_column": "embeddings",
    "create_index": true,
    "vector_dimension": 384,
    "provider_config": {
      "index_name": "documents",
      "host": "localhost",
      "port": 9200,
      "username": "admin",
      "password": "<your-opensearch-password>",
      "use_ssl": false,
      "verify_certs": false,
      "engine": "faiss",
      "algorithm": "hnsw",
      "space_type": "l2",
      "batch_size": 100
    },
    "feature_mappings": {
      "content": "content",
      "doc_name": "doc_name",
      "file_path": "file_path",
      "doc_id_hash": "doc_id_hash",
      "chunk_id": "chunk_id",
      "chunk_index": "chunk_index"
    },
    "available_features": {
      "embeddings": {
        "type": "vector",
        "available_for_vector_db": true
      },
      "content": {
        "type": "string",
        "available_for_vector_db": true
      },
      "doc_name": {
        "type": "string",
        "available_for_vector_db": true
      },
      "file_path": {
        "type": "string",
        "available_for_vector_db": true
      },
      "doc_id_hash": {
        "type": "string",
        "available_for_vector_db": true
      },
      "chunk_id": {
        "type": "string",
        "available_for_vector_db": true
      },
      "chunk_index": {
        "type": "integer",
        "available_for_vector_db": true
      }
    }
  }
}
```

#### Required Parameters

- **provider**: Type of vector database (uses "opensearch" by default)
- **provider_config**: All connection parameters and the resource name for the target backend. The resource name key is provider-specific.
- **available_features**: Defines which columns to store and their types. **Embeddings field is mandatory.**
  - Must include `embeddings` with `"type": "vector"` and `"available_for_vector_db": true`
  - Other fields are optional but recommended: content, doc_name, doc_id_hash
  - Supported types: vector, string, integer, float, boolean
- **feature_mappings**: Maps PyArrow column names to vector DB field names
  - Format: `{"pyarrow_column": "vector_db_field"}`
  - Must include all fields defined in available_features

#### Optional Provider Configurations (provider_config)

- **host**: OpenSearch server address (default: "localhost")
- **port**: Server port (default: 9200)
- **username/password**: Authentication credentials
- **use_ssl**: Enable SSL (default: true)
- **verify_certs**: Verify SSL certificates (default: true)
- **create_index**: Auto-create index if missing (default: true)
- **vector_dimension**: Embedding dimension (default: 384, auto-detected from data)
  - **Must match the embedding model's output dimension**
  - Common dimensions: `nomic-embed-text`: 768, `llama3.2`: 4096, `granite-embedding`: 384
  - The dimension in this configuration must exactly match the dimension produced by your embeddings operator
- **engine**: KNN engine - faiss, lucene, nmslib (default: faiss)
- **algorithm**: KNN algorithm - hnsw, ivf (default: hnsw)
- **space_type**: Distance metric - l2, cosine, inner_product (default: l2)
- **batch_size**: Documents per batch (default: 100)
- **engine_parameters**: Optional engine-specific parameters (e.g., {"ef_construction": 512, "m": 16} for HNSW)
- **schema_template_path**: Path to JSON schema template (relative to `src/docpipe/core/operators/vectordb/`)
  - Built-in templates: `schemas/default_schema.v1.json`, `schemas/template_with_content_analyzer.v1.json`
  - If not specified, schema is generated dynamically from `available_features`

> **⚠️ Important**: The embeddings column is mandatory. The operator validates embeddings exist in the input table and will fail if missing. You must explicitly configure embeddings in `available_features` for them to be stored in OpenSearch.

#### Using Schema Templates

Schema templates provide reusable index configurations with consistent settings across pipelines. Instead of defining `available_features` and `feature_mappings` manually, you can use a pre-configured template.

**Benefits of Schema Templates:**

- Consistent index structure across different flows
- Pre-configured analyzers and field types
- Automatic placeholder replacement for dynamic values
- Reduced configuration complexity

**Built-in Templates:**

1. **default_schema.v1.json**: Basic schema with standard field types
   - Suitable for general document storage
   - Includes standard text, numeric, and vector fields

2. **template_with_content_analyzer.v1.json**: Template with custom content analyzer
   - Custom content analyzer with stemming and stop words
   - Optimized for semantic search on document chunks

**Example with Schema Template:**

```json
{
  "name": "vectordb",
  "type": "vectordb",
  "depends_on": ["embeddings"],
  "config": {
    "provider": "opensearch",
    "doc_id_column": "doc_id_hash",
    "embeddings_column": "embeddings",
    "create_index": true,
    "vector_dimension": 384,
    "provider_config": {
      "index_name": "document_chunks",
      "schema_template_path": "schemas/template_with_content_analyzer.v1.json",
      "host": "localhost",
      "port": 9200,
      "username": "admin",
      "password": "<your-opensearch-password>",
      "use_ssl": false,
      "verify_certs": false,
      "engine": "faiss",
      "algorithm": "hnsw",
      "space_type": "l2"
    },
    "feature_mappings": {
      "content": "content",
      "doc_id_hash": "id",
      "embeddings": "embeddings"
    },
    "available_features": {
      "embeddings": {
        "type": "vector",
        "available_for_vector_db": true
      },
      "content": {
        "type": "content_text",
        "available_for_vector_db": true
      },
      "doc_id_hash": {
        "type": "string",
        "available_for_vector_db": true
      }
    }
  }
}
```

**Note:** When using schema templates, the template defines the index settings and field type mappings. You still need to specify `available_features` and `feature_mappings` to control which columns from your data are stored.

#### Automatic Metadata Aggregation

The VectorDBOperator automatically collects common metadata fields into a `metadata` object:

- `name`, `size`, `created_time`, `modified_time`, `source`, `mimetype`, `extension`, `page_count`
- Column name aliases are automatically applied (e.g., `path` → `source`, `pages_processed` → `page_count`)
- Missing fields like `extension` and `mimetype` are derived when possible

---

## Connecting Operators

Operators are connected using the `depends_on` field, which specifies which operators must complete before the current operator runs. Simply reference the `name` of the upstream operator(s).

**Example:**
```json
{
  "name": "extract",
  "type": "extract_operator",
  "depends_on": ["ingest"],
  "config": {...}
}
```

This creates a dependency where the `extract` operator will only run after the `ingest` operator completes successfully.

**Multiple Dependencies:**
```json
{
  "name": "merge",
  "type": "merge_operator",
  "depends_on": ["branch1", "branch2"],
  "config": {...}
}
```

---

## Complete Examples

### Example 1: Basic Document Processing Pipeline

```json
{
  "flow_name": "basic-document-pipeline",
  "description": "Basic document ingestion and extraction",
  "global_config": {
    "doc_column": "content",
    "force_ingest": false
  },
  "flow": [
    {
      "name": "ingest",
      "type": "ingest_source",
      "config": {
        "provider": "filesystem",
        "provider_config": {"paths": ["./documents"]},
        "include_filter": ".pdf,.txt"
      }
    },
    {
      "name": "extract",
      "type": "extract_operator",
      "depends_on": ["ingest"],
      "config": {
        "text_extraction": {
          "provider": "docling_library",
          "doc_column": "content"
        },
        "entity_extraction": {
          "provider": "none"
        }
      }
    }
  ]
}
```

### Example 2: Complete RAG Pipeline

```json
{
  "flow_name": "complete-rag-pipeline",
  "description": "Complete pipeline for RAG system",
  "global_config": {
    "doc_column": "content",
    "force_ingest": true
  },
  "flow": [
    {
      "name": "ingest",
      "type": "ingest_source",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["./documents"]},
        "include_filter": ".pdf"
      }
    },
    {
      "name": "extract",
      "type": "extract_operator",
      "depends_on": ["ingest"],
      "config": {
        "text_extraction": {
          "provider": "docling_library",
          "doc_column": "content"
        },
        "entity_extraction": {
          "provider": "none"
        }
      }
    },
    {
      "name": "chunk",
      "type": "chunker",
      "depends_on": ["extract"],
      "config": {
        "chunk_type": "hybrid",
        "chunk_size": 512,
        "chunk_overlap": 128
      }
    },
    {
      "name": "embeddings",
      "type": "embeddings",
      "depends_on": ["chunk"],
      "config": {
        "provider": "litellm",
        "provider_config": {
          "model_id": "openai/nomic-embed-text:latest",
          "api_base": "http://localhost:11434"
        },
        "embeddings_column": "embeddings"
      }
    },
    {
      "name": "vectordb",
      "type": "vectordb",
      "depends_on": ["embeddings"],
      "config": {
        "provider": "opensearch",
        "doc_id_column": "doc_id_hash",
        "embeddings_column": "embeddings",
        "vector_dimension": 768,
        "provider_config": {
          "index_name": "documents",
          "host": "localhost",
          "port": 9200,
          "username": "admin",
          "password": "<your-opensearch-password>"
        },
        "feature_mappings": {
          "content": "content",
          "doc_id_hash": "doc_id_hash",
          "embeddings": "embeddings"
        },
        "available_features": {
          "embeddings": {
            "type": "vector",
            "available_for_vector_db": true
          },
          "content": {
            "type": "string",
            "available_for_vector_db": true
          },
          "doc_id_hash": {
            "type": "string",
            "available_for_vector_db": true
          }
        }
      }
    }
  ]
}
```

---

## Related Documentation

- **[User Guide: Pipeline Setup](../../USER_GUIDE_PIPELINE_SETUP.md)** - Basic setup and first pipeline
- **[Operator Reference](../reference/OPERATORS.md)** - Complete operator parameter specifications
- **[Flow Authoring Format](FLOW_AUTHORING_FORMAT.md)** - Detailed flow authoring guide
- **[Sample Flows](../../sample_flows/)** - Example flow configurations
