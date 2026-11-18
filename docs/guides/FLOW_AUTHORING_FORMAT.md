# Flow Authoring Format Guide

The Flow Authoring Format is a simplified, user-friendly way to define Docling Pipelines pipelines without managing UUIDs, edges, and low-level DAG details.

## Table of Contents

1. [Overview](#overview)
2. [Format Structure](#format-structure)
3. [Basic Example](#basic-example)
4. [Operator Definition](#operator-definition)
5. [Dependencies](#dependencies)
6. [Global Configuration](#global-configuration)
7. [Usage Methods](#usage-methods)
8. [Complete Examples](#complete-examples)
9. [Best Practices](#best-practices)

---

## Overview

### What is the Authoring Format?

The authoring format is a simplified JSON structure for defining Docling Pipelines flows that:
- **Simplifies dependencies** - Use operator names instead of node IDs
- **Removes edge management** - Edges are constructed automatically from dependencies
- **Improves readability** - Clear, declarative operator definitions

### When to Use

- **CLI execution** - All CLI flows use authoring format
- **Python API** - `DocpipeFlowManager` accepts authoring format
- **HTTP API** - `POST /api/v1/flows` (default format)
- **Notebooks** - Cleaner format for Jupyter/programmatic usage

### Format Comparison

**Authoring Format** (Recommended):
```json
{
  "flow_name": "My Pipeline",
  "flow": [
    {
      "name": "ingest",
      "type": "ingest_source",
      "config": {"provider": "filesystem", "provider_config": {"paths": ["./data"]}}
    },
    {
      "name": "extract",
      "type": "extract_operator",
      "depends_on": ["ingest"],
      "config": {}
    }
  ]
}
```

**Elyra Format** (UI/Legacy):
```json
{
  "doc_type": "pipeline",
  "pipelines": [{
    "nodes": [
      {
        "id": "30953cfb-a3a2-4688-9aea-ff9fff10f7bd",
        "app_data": {
          "component_parameters": {
            "operator": "ingest_source",
            "config": {"provider": "filesystem", "connection_params": {"paths": ["./data"]}}
          }
        },
        "outputs": [{
          "id": "7cfd7577-b061-4fc9-92d5-120ae0fbde89"
        }]
      }
    ]
  }]
}
```

> **Note**: Both formats are supported. Elyra format is used by the UI, while authoring format is recommended for CLI, Python API, and programmatic usage.

---

## Format Structure

### Required Fields

```json
{
  "flow_name": "string",           // Flow name (required)
  "flow": [                        // Array of operators (required)
    {
      "name": "string",            // Unique operator name (required)
      "type": "string",            // Operator type (required)
      "depends_on": ["string"],    // Dependencies (optional, default: [])
      "config": {}                 // Operator config (optional, default: {})
    }
  ]
}
```

### Optional Fields

```json
{
  "description": "string",         // Flow description
  "global_config": {},             // Global configuration
  "tags": ["string"],              // Flow tags (HTTP API only)
  "flow_source": "cli|api|programmatic|ui"  // Auto-set based on usage
}
```

---

## Basic Example

### Simple Two-Operator Flow

```json
{
  "flow_name": "Document Processing",
  "description": "Ingest and extract documents",
  "flow": [
    {
      "name": "ingest_docs",
      "type": "ingest_source",
      "config": {
        "provider": "filesystem",
        "provider_config": {"paths": ["./documents"]},
        "include_filter": "pdf,txt"
      }
    },
    {
      "name": "extract_text",
      "type": "extract_operator",
      "depends_on": ["ingest_docs"],
      "config": {
        "text_extraction": {"provider": "docling_library"}
      }
    }
  ],
  "global_config": {
    "doc_column": "content",
    "disable_validation": false
  }
}
```

---

## Operator Definition

### Operator Structure

Each operator in the `flow` array has:

```json
{
  "name": "unique_operator_name",     // Required: Unique identifier
  "type": "operator_type",            // Required: Operator class name
  "depends_on": ["parent1", "parent2"], // Optional: Dependencies
  "config": {                         // Optional: Operator-specific config
    "param1": "value1",
    "param2": "value2"
  }
}
```

### Naming Rules

- **Must be unique** within the flow
- **No spaces** allowed
- **No dots** (`.`) - reserved for branch references
- **Descriptive names** recommended (e.g., `ingest_pdfs`, `extract_entities`)

### Operator Types

Use the operator's class name or short name:

```json
{
  "type": "ingest_source"        // ✅ Short name
}
{
  "type": "IngestSourceOperator" // ✅ Class name (also works)
}
```

**List available operators:**
```bash
docling-pipelines --list-operators
```

---

## Dependencies

### Simple Dependencies

Reference operators by name:

```json
{
  "name": "chunk_docs",
  "type": "chunker",
  "depends_on": ["extract_text"],  // Depends on one operator
  "config": {}
}
```

### Multiple Dependencies

```json
{
  "name": "merge_results",
  "type": "merge",
  "depends_on": ["path_a", "path_b", "path_c"],  // Merge multiple inputs
  "config": {}
}
```

### Branch Dependencies

For branching operators, reference specific branches:

```json
{
  "name": "classifier",
  "type": "branching",
  "config": {
    "branches": {
      "invoices": {"condition": "type == 'invoice'"},
      "receipts": {"condition": "type == 'receipt'"}
    }
  }
},
{
  "name": "process_invoices",
  "type": "extract_operator",
  "depends_on": ["classifier.invoices"],  // Reference specific branch
  "config": {}
}
```

### Entry Points

At least one operator must have no dependencies (entry point):

```json
{
  "name": "start_here",
  "type": "ingest_source",
  "depends_on": [],  // Entry point - no dependencies
  "config": {}
}
```

---

## Global Configuration

### Common Global Settings

```json
{
  "global_config": {
    "doc_column": "content",           // Document content column
    "disable_validation": false,       // Enable/disable validation
    "force_ingest": true,              // Force re-ingestion
    "enable_micro_batching": true,     // Enable batching
    "micro_batch_size": 10,            // Batch size
    "data_storage_type": "local"       // Storage backend
  }
}
```

### Operator-Specific Overrides

Operators can override global settings in their `config`:

```json
{
  "global_config": {
    "doc_column": "content"
  },
  "flow": [
    {
      "name": "special_extract",
      "type": "extract_operator",
      "config": {
        "doc_column": "raw_text"  // Overrides global setting
      }
    }
  ]
}
```

---

## Usage Methods

### 1. CLI Execution

```bash
# Execute authoring format flow
docling-pipelines --flow-file my_flow.json

# Validate without executing
docling-pipelines validate-flow my_flow.json
```

### 2. Python API

```python
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

# From file
manager = DocpipeFlowManager(flow_file="my_flow.json")
result = manager.execute()

# From dictionary
flow_def = {
    "flow_name": "My Pipeline",
    "flow": [
        {
            "name": "ingest",
            "type": "ingest_source",
            "config": {"provider": "filesystem", "provider_config": {"paths": ["./data"]}}
        }
    ]
}
manager = DocpipeFlowManager(flow_def=flow_def)
result = manager.execute()
```

### 3. HTTP API

```bash
# Create flow with authoring format (default)
curl -X POST http://localhost:8000/api/v1/flows \
  -H "Content-Type: application/json" \
  -d @my_flow.json

# Explicitly specify authoring format
curl -X POST "http://localhost:8000/api/v1/flows?is_elyra=false" \
  -H "Content-Type: application/json" \
  -d @my_flow.json

# Use Elyra format (for UI compatibility)
curl -X POST "http://localhost:8000/api/v1/flows?is_elyra=true" \
  -H "Content-Type: application/json" \
  -d @elyra_flow.json
```

---

## Complete Examples

### Example 1: Document Extraction Pipeline

```json
{
  "flow_name": "PDF Extraction Pipeline",
  "description": "Extract text and entities from PDF documents",
  "flow": [
    {
      "name": "ingest_pdfs",
      "type": "ingest_source",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["./pdfs"]},
        "include_filter": "pdf"
      }
    },
    {
      "name": "extract_content",
      "type": "extract_operator",
      "depends_on": ["ingest_pdfs"],
      "config": {
        "text_extraction": {
          "provider": "docling_library"
        },
        "entity_extraction": {
          "provider": "litellm",
          "provider_config": {
            "model_id": "openai/llama3.2",
            "api_base": "http://localhost:11434/v1"
          }
        }
      }
    }
  ],
  "global_config": {
    "doc_column": "content",
    "disable_validation": false
  }
}
```

### Example 2: Complete RAG Pipeline

```json
{
  "flow_name": "RAG Pipeline",
  "description": "Complete pipeline for RAG: ingest, extract, chunk, embed, store",
  "flow": [
    {
      "name": "ingest",
      "type": "ingest_source",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["./documents"]},
        "include_filter": "pdf,txt,md"
      }
    },
    {
      "name": "extract",
      "type": "extract_operator",
      "depends_on": ["ingest"],
      "config": {
        "text_extraction": {"provider": "docling_library"}
      }
    },
    {
      "name": "chunk",
      "type": "chunker",
      "depends_on": ["extract"],
      "config": {
        "chunk_type": "semantic",
        "chunk_size": 512,
        "chunk_overlap": 50
      }
    },
    {
      "name": "embed",
      "type": "embeddings",
      "depends_on": ["chunk"],
      "config": {
        "provider": "litellm",
        "model_id": "openai/nomic-embed-text",
        "provider_config": {
          "api_base": "http://localhost:11434"
        }
      }
    },
    {
      "name": "store",
      "type": "vectordb",
      "depends_on": ["embed"],
      "config": {
        "provider": "opensearch",
        "vector_dimension": 768,
        "provider_config": {
          "index_name": "documents"
        }
      }
    }
  ],
  "global_config": {
    "doc_column": "content",
    "enable_micro_batching": true,
    "micro_batch_size": 10
  }
}
```

### Example 3: Branching Workflow

```json
{
  "flow_name": "Document Classification Pipeline",
  "description": "Classify and route documents by type",
  "flow": [
    {
      "name": "ingest",
      "type": "ingest_source",
      "config": {
        "provider": "filesystem",
        "provider_config": {"paths": ["./mixed_docs"]}
      }
    },
    {
      "name": "classify",
      "type": "branching",
      "depends_on": ["ingest"],
      "config": {
        "branches": {
          "invoices": {"condition": "doc_type == 'invoice'"},
          "contracts": {"condition": "doc_type == 'contract'"},
          "other": {"condition": "True"}
        }
      }
    },
    {
      "name": "process_invoices",
      "type": "extract_operator",
      "depends_on": ["classify.invoices"],
      "config": {
        "text_extraction": {
          "provider": "docling_library"
        },
        "entity_extraction": {
          "provider": "litellm",
          "provider_config": {
            "model_id": "openai/llama3.2",
            "api_base": "http://localhost:11434/v1"
          },
          "custom_schema": "invoice_template"
        }
      }
    },
    {
      "name": "process_contracts",
      "type": "extract_operator",
      "depends_on": ["classify.contracts"],
      "config": {
        "text_extraction": {
          "provider": "docling_library"
        },
        "entity_extraction": {
          "provider": "litellm",
          "provider_config": {
            "model_id": "openai/llama3.2",
            "api_base": "http://localhost:11434/v1"
          },
          "custom_schema": "contract_template"
        }
      }
    },
    {
      "name": "merge_results",
      "type": "merge",
      "depends_on": ["process_invoices", "process_contracts"],
      "config": {}
    }
  ]
}
```

### Example 4: High-Concurrency Pipeline with HuggingFace

```json
{
  "flow_name": "Scalability Test - HuggingFace Local",
  "description": "High-concurrency pipeline using native HuggingFace local inference",
  "flow": [
    {
      "name": "ingest",
      "type": "ingest_source",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["/data/documents"]},
        "include_filter": "txt,pdf",
        "max_files": 10000
      }
    },
    {
      "name": "extract",
      "type": "extract_operator",
      "depends_on": ["ingest"],
      "config": {
        "text_extraction": {
          "provider": "docling_library"
        }
      }
    },
    {
      "name": "chunk",
      "type": "chunker",
      "depends_on": ["extract"],
      "config": {
        "chunk_type": "simple",
        "chunk_size": 4000,
        "chunk_overlap": 300
      }
    },
    {
      "name": "embed",
      "type": "embeddings",
      "depends_on": ["chunk"],
      "config": {
        "provider": "huggingface",
        "model_id": "sentence-transformers/all-MiniLM-L6-v2",
        "provider_config": {
          "use_local": true,
          "device": "cpu",
          "batch_size": 16
        }
      }
    },
    {
      "name": "store",
      "type": "vectordb",
      "depends_on": ["embed"],
      "config": {
        "provider": "opensearch",
        "vector_dimension": 384,
        "provider_config": {
          "index_name": "documents"
        }
      }
    }
  ],
  "global_config": {
    "enable_micro_batching": true,
    "micro_batch_size": 10,
    "max_concurrent_batches": 600
  }
}
```

---

## Best Practices

1. **Use descriptive names** - `ingest_customer_docs` vs `op1`
2. **Group related operators** - Keep logical flow sections together
3. **Document complex flows** - Add description field
4. **Test incrementally** - Build flows operator by operator
5. **Validate early** - Use `validate-flow` before execution
6. **Version control** - Track flow changes in git
7. **Start simple** - Begin with 2-3 operators, then expand
8. **Use global config** - Set common parameters once

## See Also

- [Complete Pipeline Setup Guide](../../USER_GUIDE_PIPELINE_SETUP.md)
- [Quick Start Guide](../../QUICKSTART.md)
- [Operator Reference](../reference/OPERATORS.md)
- [Sample Flows](../../sample_flows/)
