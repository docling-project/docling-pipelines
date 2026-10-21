# Global Configuration Reference

This document provides a comprehensive reference for all global configuration parameters that can be set in docpipe flow definitions. Global configuration parameters control flow-level behavior and are specified in the `global_config` section of your flow JSON.

## Overview

Global configuration parameters are set at the flow level and apply to all operators in the pipeline unless overridden at the operator level. These parameters control:

- **Execution behavior**: How the flow processes data
- **Batching strategy**: Whether and how to split data into batches
- **Incremental processing**: Tracking and processing only changed data
- **Orchestration**: Prefect-based workflow execution settings
- **Storage**: Where intermediate and final data is stored

---

## Configuration Structure

Global configuration is specified in the `global_config` section of your flow definition:

```json
{
  "flow_name": "My Pipeline",
  "description": "Example pipeline with global configuration",
  "global_config": {
    "force_ingest": false,
    "micro_batch_size": 50,
    "prefect": {
      "batch_execution": {
        "strategy": "thread-pool"
      }
    }
  },
  "flow": [
    {
      "type": "ingest_source",
      "name": "ingest",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["./documents"]}
      }
    },
    {
      "type": "extract_operator",
      "name": "extract",
      "config": {
        "text_extraction": {"provider": "docling_library"}
      },
      "depends_on": ["ingest"]
    }
  ]
}
```

---

## Execution Control

Parameters that control how the flow executes and processes data.

### `disable_validation`

**Type**: `boolean`  
**Default**: `false`  
**Description**: Disables flow validation before execution. Not recommended for production use.

**Valid Values**:
- `true`: Skip flow validation (faster startup, risky)
- `false`: Validate flow before execution (recommended)

**Example**:
```json
{
  "global_config": {
    "disable_validation": true
  }
}
```

**Warning**: Disabling validation skips the main flow validation pass and can lead to runtime errors that validation would normally catch.

**What Gets Skipped When `disable_validation: true`**:
1. **DAG structure validation**: Checks for empty DAG, unnamed operators, duplicate operator names
2. **First operator validation**: Verification that the first operator is an Ingest category operator
3. **ACL operator placement validation**: Checks that ACL operators are correctly positioned in the flow
4. **Disjoint operators validation**: Detection of disconnected or isolated operators in the flow
5. **Cycle detection**: Checks for circular dependencies in the DAG
6. **Operator availability validation**: Verification that all operator types are registered and available
7. **Node-level validation**: Individual operator configuration and parameter validation
8. **Last operator validation**: Warning if the last operator is not a VectorDB operator

---

### `skip_custom_op_validation`

**Type**: `boolean`  
**Default**: `false`  
**Description**: Skips validation for custom operators while still validating built-in operators.

**Valid Values**:
- `true`: Skip custom operator validation
- `false`: Validate all operators including custom ones

**Example**:
```json
{
  "global_config": {
    "skip_custom_op_validation": true
  }
}
```

---

### `output_folder`

**Type**: `string`  
**Description**: Directory for storing final output files. Can be either a relative path (relative to workspace directory) or an absolute path. If not specified, the system generates a unique path based on job execution IDs.  
**Valid Values**: Valid directory path (relative or absolute)

**Example**:
```json
{
  "global_config": {
    "data_local_config": {
      "output_folder": "./data/output"
    }
  }
}
```

---

### `data_storage_type`

**Type**: `string`  
**Description**: Controls intermediate execution data storage behavior during flow execution.  
**Valid Values**:
- `"memory"`: Use in-memory intermediate data handling
- `"local"`: Use local filesystem-backed intermediate data handling

**Example**:
```json
{
  "global_config": {
    "data_storage_type": "local"
  }
}
```

**Note**: Memory storage is fastest but limited by available RAM. Use `"local"` for large datasets.

---

### `memmap_threshold`

**Type**: `integer`  
**Default**: `100`  
**Description**: Threshold in MB after which persistent storage is used for chunks and embeddings.
**Valid Values**: Must be greater than 1.

**Example**:
```json
{
  "global_config": {
    "memmap_threshold": 100
  }
}
```

---

## Incremental Processing

Configuration for tracking and processing only changed documents.

### `force_ingest`

**Type**: `boolean`  
**Default**: `false`  
**Description**: Forces re-ingestion of all documents, even if they were previously processed. Useful for reprocessing data after operator configuration changes.

**Valid Values**:
- `true`: Re-ingest all documents regardless of previous processing
- `false`: Skip documents that were already processed (incremental mode)

**Example**:
```json
{
  "global_config": {
    "force_ingest": true
  }
}
```

**Use Cases**:
- Reprocessing entire dataset after fixing extraction logic
- Reprocess entire dataset when the target DB (ex: collection, table, etc.) is changed.
- Reprocess entire data set after modifying some changes to operator, examples: PII/HAP configuration is changed.
- Testing flow changes on full dataset
- Recovering from corrupted incremental metadata

---

### `retain_deleted_docs`

**Type**: `boolean`  
**Default**: `true`  
**Description**: Controls whether documents deleted from the source should be retained in the output or removed.

**Valid Values**:
- `true`: Keep documents in output even if deleted from source
- `false`: Remove documents from output when deleted from source

**Example**:
```json
{
  "global_config": {
    "retain_deleted_docs": false
  }
}
```

**Use Cases**:
- Maintaining historical records (set to `true`)
- Keeping output synchronized with source (set to `false`)

**Important Limitations**:
- This feature only works when the source directory/path still exists
- If you delete the entire source directory (e.g., `./sample_documents`), the system will report an error: `Path does not exist`
- To handle deleted directories, you must either:
  - Keep the source directory structure intact (even if empty)
  - Set `force_ingest: true` to reset incremental metadata

---

### Centralized Incremental Metadata Configuration

Docling Pipelines uses a centralized configuration system for incremental metadata storage. Instead of configuring incremental metadata in each flow JSON file, you configure it once in a repository-level `docling-pipelines-config.yaml` file.

#### Configuration Structure :

The incremental metadata configuration is defined in `docling-pipelines-config.yaml`:

**Option 1: Inherit from global_storage**
```yaml
global_storage:
   type: "filesystem"  # Options: filesystem, postgresql
   config:
      base_dir: "./data"
      lock_timeout: 30.0
   # PostgreSQL configuration (only needed if type is "postgres")
   postgres:
      host: "localhost"
      port: 5432
      database: "docpipe"
      user: "docpipe_user"
      password: "${POSTGRES_PASSWORD}" # pragma: allowlist secret
      schema: "incremental_metadata"

incremental_metadata: {} # inherit from global_storage
```

**Option 2: Override with service-specific configuration**
```yaml
global_storage:
  type: "filesystem"
  config:
    base_dir: "./data"
    lock_timeout: 30.0

# incremental_metadata overrides global_storage
incremental_metadata:
  storage:
    type: "filesystem"
    config:
      base_dir: "./incremental_data"  # Different path
      lock_timeout: 60.0
```

#### Supported Storage types :

Docling Pipelines supports two storage types for incremental metadata:

1. **Filesystem** (default)
   - Efficient columnar storage using Apache Parquet format
   - Best for: Development, small to medium-scale deployments
   - Configuration: Required `config.base_dir` and `config.lock_timeout`
   - Features: Thread-safe operations with file locking, atomic writes

2. **PostgreSQL**
   - Relational database storage
   - Best for: Production deployments, multi-user environments, high concurrency
   - Configuration: Requires database connection parameters

#### Environment Variables :

You can override configuration using environment variables:

- `DOCPIPE_INCREMENTAL_BASE_DIR`: Override the base directory for incremental metadata
- `DOCPIPE_INCREMENTAL_STORAGE_BACKEND`: Override the storage backend (filesystem, postgresql)
- `DOCPIPE_CONFIG_PATH`: Specify a custom path to docling-pipelines-config.yaml

**Example**:
```bash
export DOCPIPE_INCREMENTAL_BASE_DIR="/data/incremental"
export DOCPIPE_INCREMENTAL_STORAGE_BACKEND="filesystem"
docling-pipelines --flow-file my_flow.json
```

#### Configuration Precedence :

Configuration is resolved in the following order (highest to lowest priority):

1. **Environment variables** (`DOCPIPE_INCREMENTAL_BASE_DIR`, `DOCPIPE_INCREMENTAL_STORAGE_BACKEND`)
2. **Service-specific configuration** (e.g., `incremental_metadata.storage` in docling-pipelines-config.yaml)
3. **Global storage configuration** (e.g., `global_storage` in docling-pipelines-config.yaml)
4. **System defaults** (Filesystem backend with `./data`)

#### Flow JSON Configuration :

In your flow JSON files, you no longer need to specify incremental metadata configuration. The system automatically uses the centralized configuration:

```json
{
  "flow_name": "My Pipeline",
  "description": "Pipeline with centralized incremental metadata",
  "global_config": {
    "force_ingest": false,
    "retain_deleted_docs": true
  },
  "flow": [
    {
      "type": "ingest_source",
      "name": "ingest",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["./documents"]}
      }
    }
  ]
}
```

#### Migration from Flow-Level Configuration :

If you have existing flows with flow-level incremental metadata configuration, follow these steps:

1. **Create docling-pipelines-config.yaml** in your repository root:
   ```yaml
    incremental_metadata:
      storage:
        type: "filesystem"
        config:
          base_dir: "./incremental_data"
          lock_timeout: 60.0
   ```

2. **Remove incremental_metadata from flow JSON**:
   - Delete the `incremental_metadata` section from `global_config`
   - The system will automatically use the centralized configuration


3. **Verify configuration**:
   ```bash
   docling-pipelines --flow-file your_flow.json --validate
   ```

#### Use Cases :

- **Processing only new or modified documents**: Incremental metadata tracks document hashes and modification times
- **Resuming interrupted pipeline runs**: Metadata persists across runs, allowing pipelines to resume where they left off
- **Efficient updates to large document collections**: Only process changed documents, not the entire collection
- **Multi-flow coordination**: Share incremental metadata across multiple flows using the same base directory

**Related Documentation** :
- [Incremental Metadata Configuration](../guides/ADVANCED_CONFIGURATION.md)

---

## Ededup Registry Storage

The deduplication registry is configured separately from flow `global_config`, in
`docling-pipelines-config.yaml` under `ededup.storage`. It is persistent by default when the operator runs with job,
run, and flow-node context. `ededup.storage` takes precedence over `global_storage`, then the filesystem default.
Incremental metadata settings do not configure this registry.

```yaml
ededup:
  storage:
    type: postgresql
    config:
      postgres:
        schema: ededup_registry
```

PostgreSQL is suitable for workers on separate hosts or pods. The filesystem default is suitable only when all workers
share the same directory; see [Advanced Configuration](../guides/ADVANCED_CONFIGURATION.md#ededup-shared-storage-guidance)
for deployment requirements. See the [EdedupOperator reference](OPERATORS.md#ededupoperator) for backend settings,
registry scope, migration notes, and cleanup instructions.

## Orchestration configuration

### Prefect Configuration

Configuration for prefect-based workflow orchestration and batch execution strategies.

#### `prefect`

**Type**: `object`  
**Description**: Prefect orchestration settings including batch execution strategy and work pool configuration.

**Structure** :
```json
{
  "prefect": {
    "batch_execution": {
      "strategy": "thread-pool",
      "work_pool_name": "my-pool",
      "deployment_name": "my-deployment",
      "batch_storage": {
        "type": "local",
        "path": "./batch_data"
      }
    }
  }
}
```

---

### Batch Execution Strategy

The `batch_execution` section controls how batches are executed.

#### `strategy`

**Type**: `string`  
**Default**: `"thread-pool"`  
**Description**: Execution strategy for batch processing.

**Valid Values**:
- `"thread-pool"`: Local execution using ThreadPoolTaskRunner (default, simplest)
- `"work-pool-process"`: Distributed execution using Prefect process work pools
- `"work-pool-docker"`: Distributed execution using Docker containers

**Example - Thread Pool (Local)**:
```json
{
  "prefect": {
    "batch_execution": {
      "strategy": "thread-pool"
    }
  }
}
```

**Example - Docker Work Pool**:
```json
{
  "prefect": {
    "batch_execution": {
      "strategy": "work-pool-docker",
      "work_pool_name": "docpipe-docker-pool",
      "deployment_name": "batch-processor",
      "deployment_path": "/opt/docpipe",
      "image": "docpipe:latest",
      "batch_storage": {
        "type": "local",
        "path": "/data/batches"
      }
    }
  }
}
```

---

### Work Pool Configuration

Required when using work pool strategies (`work-pool-*`).

#### `work_pool_name`

**Type**: `string`  
**Required**: Yes (for work pool strategies)  
**Description**: Name of the Prefect work pool to use for batch execution.

**Example**:
```json
{
  "work_pool_name": "docpipe-production-pool"
}
```

---

#### `deployment_name`

**Type**: `string`  
**Required**: Yes (for work pool strategies)  
**Description**: Name for the Prefect deployment that will execute batches.

**Example**:
```json
{
  "deployment_name": "document-processing-v1"
}
```

---

#### `deployment_path`

**Type**: `string`  
**Default**: Current working directory  
**Description**: Runtime path where flow code is available in the worker environment.

**Example**:
```json
{
  "deployment_path": "/opt/docpipe"
}
```

---

#### `env`

**Type**: `object` (dictionary of string key-value pairs)  
**Default**: `{}`  
**Description**: Environment variables injected into the worker job process or container. Used to pass configuration, credentials, or runtime settings to workers.

**Example**:
```json
{
  "env": {
    "OLLAMA_HOST": "http://ollama-service:11434",
    "LOG_LEVEL": "INFO",
    "PREFECT_MODE": "cloud",
    "PREFECT_URL": "https://api.prefect.cloud",
    "DOCPIPE_STORAGE_BACKEND": "postgresql",
    "PYTHONPATH": "/app/src",
    "LOCAL_FLOWS_DIR": "/app/flows",
    "DOCPIPE_DATA_PATH": "/data/docpipe"
  }
}
```

**Note**: System-required environment variables (PREFECT_API_URL, PYTHONPATH, etc.) are automatically set by the adapter. User-provided `env` values supplement or override these defaults.

---

#### `image`

**Type**: `string`  
**Required**: Yes (for containerized work pools)  
**Description**: Container image for Docker work pools.

**Example**:
```json
{
  "image": "myregistry/docpipe:v1.2.3"
}
```

---

#### `image_pull_policy`

**Type**: `string`  
**Default**: `"Never"`  
**Description**: Policy for pulling container images.

**Valid Values**:
- `"Always"`: Always pull the image
- `"IfNotPresent"`: Pull only if not present locally
- `"Never"`: Never pull, use local image only

**Example**:
```json
{
  "image_pull_policy": "Never"
}
```

---

### Docker - Specific Configuration

#### `networks`

**Type**: `array of strings`  
**Default**: `[]`  
**Description**: Docker networks for spawned containers.

**Example**:
```json
{
  "networks": ["docpipe-network", "monitoring-network"]
}
```

---

### Batch Storage Configuration

The `batch_storage` section controls where batch data is stored during distributed execution.

#### `type`

**Type**: `string`  
**Default**: `"inline"`  
**Description**: Storage type for batch data.

**Valid Values**:
- `"inline"`: Serialize batch data directly in deployment parameters (small batches only)
- `"local"`: Store batch data on local filesystem

#### `path`

**Type**: `string`  
**Required**: Yes (when `type` is `"local"`)  
**Description**: Filesystem path for storing batch data when using local storage type.

**Example - Local Storage**:
```json
{
  "batch_storage": {
    "type": "local",
    "path": "/data/batches"
  }
}
```

---

**Related Documentation**: [Prefect Distributed Execution Guide](../integrations/prefect/DISTRIBUTED_EXECUTION_GUIDE.md)

---

### Micro-Batching Configuration

Parameters for controlling micro-batching behavior. Micro-batching must be explicitly enabled and splits large datasets into smaller batches for parallel processing.

#### `micro_batch_size`

**Type**: `integer`  
**Default**: `100`  
**Description**: Note that the batch_size is not strictly enforced. The files are adjusted in the batches to make the batch size uniform across the batches, but limiting the number of documents in a batch to the given batch_size.  
**Valid Values**: Positive integer

**Example**:
```json
{
  "global_config": {
    "micro_batch_size": 50
  }
}
```

**Tuning Guidelines**:
- **Small batches (10-50)**: Better for large documents or memory-constrained environments
- **Medium batches (50-200)**: Good balance for most use cases
- **Large batches (200-1000)**: Suitable for small documents with high throughput requirements

---

#### `max_concurrent_batches`

**Type**: `integer`  
**Default**: `10`  
**Description**: Maximum number of batches that can execute concurrently. Controls parallelism and resource usage.  
**Valid Values**: Positive integer

**Example**:
```json
{
  "global_config": {
    "max_concurrent_batches": 5
  }
}
```

**Tuning Guidelines**:
- **Low concurrency (1-5)**: Reduces memory usage, suitable for resource-constrained environments
- **Medium concurrency (5-15)**: Good balance for most systems
- **High concurrency (15-50)**: Maximizes throughput on high-resource systems

**Note**: Higher concurrency requires more memory and CPU resources.

---

## Operator Overrides

You can override configuration for specific operators using their name or ID.

### `<operator_name>` or `<operator_id>`

**Type**: `object`  
**Description**: Override configuration for a specific operator by its name or ID.

**Example**:
```json
{
  "global_config": {
    "doc_column": "content",
    "extract_operator": {
      "doc_column": "document",
      "max_workers": 8
    }
  }
}
```

In this example, all operators use `doc_column: "content"` except the `extract_operator` which uses `doc_column: "document"`.

---

## Complete Example

Here's a comprehensive example showing the separation between flow JSON and docling-pipelines-config.yaml:

### Flow JSON

```json
{
  "flow_name": "Production Document Processing Pipeline",
  "description": "Process documents with micro-batching and Docker execution",
  "global_config": {
    "force_ingest": false,
    "retain_deleted_docs": true,
    "micro_batch_size": 100,
    "max_concurrent_batches": 10,
    "data_local_config": {
        "output_folder": "./output"
    },
    "data_storage_type": "local",
    "prefect": {
      "batch_execution": {
        "strategy": "work-pool-docker",
        "work_pool_name": "docpipe-docker-pool",
        "deployment_name": "doc-processor-v1",
        "deployment_path": "/opt/docpipe",
        "image": "myregistry/docpipe:1.0.0",
        "env": {
          "OLLAMA_HOST": "http://ollama-service:11434",
          "LOG_LEVEL": "INFO"
        },
        "batch_storage": {
          "type": "local",
          "path": "/data/batches"
        }
      }
    }
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
        "doc_column": "content"
      },
      "depends_on": ["ingest_source_filesystem"]
    }
  ]
}
```

### Centralized Configuration (`docling-pipelines-config.yaml`)

```yaml
# Repository-level configuration for incremental metadata
incremental_metadata:
   storage:
      type: "filesystem"
      config:
         base_dir: "./incremental_data"
         lock_timeout: 60.0
#  PostgreSQL configuration (only needed if type is "postgres")
#  postgres:
#    host: "localhost"
#    port: 5432
#    database: "docpipe"
#    user: "docpipe_user"
#    password: "${POSTGRES_PASSWORD}" # pragma: allowlist secret
#    schema: "incremental_metadata"
```

### Execution

```bash
# The flow automatically uses the centralized incremental metadata configuration
docling-pipelines --flow-file production_pipeline.json
```

**Key Points**:
- Incremental metadata configuration is in `docling-pipelines-config.yaml`
- Flow JSON focuses on pipeline structure and execution parameters
- Centralized configuration is shared across all flows in the repository
- Environment variables can override configuration for specific runs
