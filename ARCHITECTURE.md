# Docling-pipelines Architecture

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Core Concepts](#core-concepts)
4. [Component Deep Dive](#component-deep-dive)
5. [Distributed Execution Architecture](#distributed-execution-architecture)
6. [Operator Lifecycle](#operator-lifecycle)
7. [Data Flow Architecture](#data-flow-architecture)
8. [Integration Patterns](#integration-patterns)
9. [Deployment Patterns](#deployment-patterns)
10. [Security Architecture](#security-architecture)
11. [Design Decisions](#design-decisions)
12. [Repository Structure](#repository-structure)
13. [Development Guidelines](#development-guidelines)

---

This document describes the architecture and organization of the Docling-pipelinesrepository.

## Overview

Docling-pipelines is a modular, operator-based data processing framework designed for building flexible document curation pipelines. It enables advanced RAG (Retrieval-Augmented Generation) workflows by combining structured data extraction, semantic chunking, vector embeddings, and hybrid search capabilities. It uses a mixed architecture approach comprising of dynamic plugin discovery across operators, hexagonal architecture in subsystems that need interchangeable external services.

### Key Capabilities

- **Operator-Based Architecture**: 20+ specialized operators organized into 6 categories (Extract, Ingest, Functional, Quality, VectorDB, Storage)
- **PyArrow Data Format**: All data flows through the pipeline as PyArrow tables, ensuring efficient memory usage and interoperability
- **DAG-Based Workflow Execution**: Flows are defined as JSON configurations representing directed acyclic graphs (DAGs) of operator nodes
- **Prefect Orchestration**: Workflow execution managed by Prefect with support for both ephemeral (local) and distributed execution via work pools (Docker)
- **Modern AI/ML Integrations**: Native support for Ollama (LLM operations), Docling (document processing), OpenSearch (vector and scalar storage) and Milvus (vector storage)

### Architectural Patterns

Docling-pipelines intentionally employs a **mixed architectural approach** rather than adhering to a single dominant pattern. This diversity enables flexibility, modularity, and maintainability across different system layers:

- **Hexagonal Architecture (Ports & Adapters)**: Core domain logic and operator abstractions are isolated from external dependencies, allowing operators to be framework-agnostic and easily testable. The Prefect orchestration module specifically uses hexagonal architecture with ports and adapters for batch execution strategies, enabling seamless switching between local and distributed execution modes. Quality operators such as the PII/HAP stack use runtime-native ports-and-adapters packages under [`src/docpipe/core/operators/quality`](src/docpipe/core/operators/quality).
- **Factory Pattern**: `OrchestratorFactory` and `OperatorFactory` provide centralized instantiation logic for orchestrators and operators
- **Strategy Pattern**: Different operator implementations can be swapped based on configuration without changing the orchestration logic
- **Observer Pattern**: Event handling system (`AbstractFlowExecutionEventHandler`, `FlowExecutionEventHandler`) enables monitoring and logging of flow execution
- **Template Method Pattern**: `AbstractOperator` defines the execution flow template while concrete operators implement specific behavior

This architectural diversity is a deliberate design choice that supports the framework's goal of being extensible, testable, and adaptable to various data processing scenarios.

### Use Cases

- Extract text and structured information from tables within unstructured documents (PDFs, DOCX, etc.)
- Combine vector similarity search with structured data filtering for improved retrieval accuracy
- Build custom document processing pipelines with configurable operators

### Technology Stack

| Layer                   | Technologies                                                                                                                                          |
| ----------------------- |-------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Orchestration**       | Prefect, Python 3.12+                                                                                                                                 |
| **Data Processing**     | PyArrow                                                                                                                                               |
| **Storage**             | DuckDB (metadata and tables), Filesystem (metadata only)                                                                                              |
| **Document Processing** | Docling (with ASR support for audio/video via ffmpeg)                                                                                                 |
| **LLM Integration**     | Ollama, Watsonx.ai, LiteLLM (unified interface supporting 100+ LLM providers including OpenAI, Anthropic, Google, AWS Bedrock, and more), HuggingFace (native local/API support) |
| **Vector Storage**      | OpenSearch, Milvus, NMSLIB, Faiss                                                                                                                     |
| **Language Detection**  | FastText, langdetect                                                                                                                                  |
| **Web Framework**       | FastAPI (optional)                                                                                                                                    |
| **Testing**             | pytest, pytest-cov                                                                                                                                    |
| **Package Management**  | uv                                                                                                                                                    |

---

## System Architecture

### High-Level Architecture Diagram

```mermaid
graph TB
    subgraph "Interface Layer"
        CLI[CLI Application]
        API[Python API]
    end

    subgraph "Orchestration Layer"
        FE[FlowExecutor]
        FV[FlowValidator]
        ORCH[PythonOrchestrator]
        PE[PrefectEngine]
        BM[BatchManager]
    end

    subgraph "Operator Layer"
        subgraph "Extract"
            EXT[ExtractOperator]
        end
        subgraph "Ingest"
            ISO[IngestSourceOperator]
        end
        subgraph "Functional"
            BR[BranchingOperator]
            MRG[MergeOperator]
            CH[Chunker]
            EC[EntityCurationOperator]
            EMB[EmbeddingsOperator]
            NOOP[NoopOperator]
        end
        subgraph "Quality"
            DC[DocumentClassifier]
            DD[Dedup]
            DQ[DocQuality]
            MLE[MLEnrichment]
            RB[Readability]
            RD[Redaction]
            SF[SQLFilter]
            LD[LanguageDetection]
        end
        subgraph "VectorDB"
            VDB[VectorDBOperator]
        end
        subgraph "Storage"
            DSO[DocumentSetOperator]
            SOO[StorageOutputOperator]
        end
    end

    subgraph "Integration Layer"
        OLL[Ollama Client]
        DOC[Docling Client]
        OS[OpenSearch Adapter]
        LLM[LiteLLM Client]
    end

    subgraph "Data Layer"
        PA[PyArrow Tables]
        FS[File System]
        OBJ[Object Storage]
        VEC[Vector Store]
    end

    CLI --> FE
    API --> FE
    FE --> FV
    FE --> ORCH
    ORCH --> PE
    ORCH --> BM
    PE --> Extract
    PE --> Ingest
    PE --> Functional
    PE --> Quality
    PE --> VectorDB

    EXT --> DOC
    EXT --> OLL
    EXT --> LLM
    EMB --> OLL
    VDB --> OS

    Ingest --> PA
    Extract --> PA
    Functional --> PA
    Quality --> PA
    VectorDB --> PA

    PA --> FS
    PA --> OBJ
    OS --> VEC

    style CLI fill:#e1f5ff
    style API fill:#e1f5ff
    style ORCH fill:#fff4e1
    style PE fill:#fff4e1
    style PA fill:#e8f5e9
    style VEC fill:#e8f5e9
```

### Architecture Layers

**1. Interface Layer**

- CLI application for command-line flow execution
- Python API for programmatic access

**2. Orchestration Layer**

- FlowExecutor: Entry point for flow execution
- FlowValidator: Validates flow definitions
- PythonOrchestrator: Coordinates operator execution
- PrefectEngine: Manages workflow execution with Prefect
- BatchManager: Handles batch processing

**3. Operator Layer**

- 20+ specialized operators organized by category
- Each operator processes PyArrow tables
- Chainable in DAG workflows

**4. Integration Layer**

- Client abstractions for external services
- Ollama for LLM operations
- Docling for document processing
- OpenSearch for vector storage

**5. Data Layer**

- PyArrow tables for efficient data flow
- File system and object storage
- Vector database for embeddings

---

## Job Management and Execution Tracking

docling-pipelines includes a dedicated job management subsystem under [`core/job_management`](src/docpipe/core/job_management) that separates orchestration concerns, persistent job statistics, and read-side aggregation.

### Hexagonal Architecture for Job Stats

The job stats implementation follows a ports-and-adapters design:

- **Domain ports**
  - [`JobStatsService`](src/docpipe/core/job_management/domain/ports/job_stats_service.py) defines the orchestration-facing contract for starting jobs, updating node execution state, listing runs, and cancellation/deletion workflows.
  - [`JobStatsStore`](src/docpipe/core/job_management/domain/ports/job_stats_store.py) defines persistence operations for job-level and node-level statistics.
- **Application services**
  - [`NodeStatsAggregator`](src/docpipe/core/job_management/application/services/node_stats_aggregator.py) performs read-side aggregation of raw node stats records.
  - [`JobManagementService`](src/docpipe/core/job_management/application/services/job_management_service.py) coordinates APIs, job execution, and framework integration.
- **Adapters**
  - [`JobTrackerService`](src/docpipe/core/job_management/adapters/services/job_tracker_service.py) is the production implementation of [`JobStatsService`](src/docpipe/core/job_management/domain/ports/job_stats_service.py).
  - Storage adapters include JSON, in-memory, DuckDB, and PostgreSQL implementations created by [`JobManagementFactory`](src/docpipe/core/job_management/adapters/config/job_management_factory.py).

The active job stats path uses the new `core/job_management` module.

### Persistence and Aggregation Split

A key architectural rule is that persistence adapters only store and retrieve raw records.

- [`JobStatsStore`](src/docpipe/core/job_management/domain/ports/job_stats_store.py) implementations must persist job stats and raw node stats.
- Store adapters must **not** perform node aggregation.
- [`NodeStatsAggregator`](src/docpipe/core/job_management/application/services/node_stats_aggregator.py) is the only layer responsible for combining batch-level node stats into an aggregated node view.

This separation keeps write paths simple and makes aggregation behavior explicit, testable, and replaceable.

### Micro-Batching Model

For micro-batch execution, Docling-pipelines stores node statistics at batch granularity.

- Every batch execution can produce a separate [`NodeStatsDto`](src/docpipe/api/dto/node_stats_dto.py) record.
- Batch records are keyed by `job_run_id`, `node_id`, and `batch_id`.
- Read APIs can return:
  - an aggregated per-node view
  - detailed batch-level stats for the same node
- Non-batch operators still produce a single node stats record.

This design allows:

- accurate per-batch progress tracking
- bulk creation of pending node stats before execution
- failure/cancel/abort handling at node-batch granularity
- aggregation of document counts and metadata after execution

### Prefect Execution Semantics

The Prefect orchestration layer must keep the outer flow alive until submitted batch futures are resolved. This avoids a failure mode where the outer flow exits early, the task runner begins shutdown, and in-flight batch tasks are canceled or marked as crashed before the job-management layer can record final state consistently.

Relevant implementation points:

- [`PrefectEngine`](src/docpipe/core/orchestration/prefect/prefect_engine.py) waits for submitted batch work before the outer flow completes.
- [`JobTrackerService`](src/docpipe/core/job_management/adapters/services/job_tracker_service.py) updates terminal job state separately from node-state persistence.
- The job-management layer is responsible for persisting terminal states such as completed, failed, canceled, and aborted.

### Metadata Aggregation Contract

Operators often emit custom metadata that is later aggregated across batches. Aggregation behavior is defined centrally in [`strategies.py`](src/docpipe/core/job_management/application/aggregation/strategies.py).

Maintainer rule:

- if a new operator adds metadata fields that need anything other than the default `LAST` behavior, update [`DEFAULT_STRATEGIES`](src/docpipe/core/job_management/application/aggregation/strategies.py)
- add or update tests covering the new aggregation behavior
- document the field in [`docs/internals/NODE_METADATA_AGGREGATION_STRATEGY.md`](docs/internals/NODE_METADATA_AGGREGATION_STRATEGY.md)

See [`docs/internals/NODE_METADATA_AGGREGATION_STRATEGY.md`](docs/internals/NODE_METADATA_AGGREGATION_STRATEGY.md) for detailed aggregation rules and maintainer guidance.

## Core Concepts

### 1. Operator Pattern

Operators are the fundamental building blocks of Docling Pipelines. Each operator is a self-contained unit that performs a specific data processing task.

**Key Characteristics:**

- Inherits from [`AbstractOperator`](src/docpipe/core/operators/abstract_operator.py)
- Implements the Template Method pattern
- Receives PyArrow tables as input
- Returns PyArrow tables as output
- Configurable via JSON parameters
- Chainable in DAG workflows
- Exposes metadata via static methods (see [Operator Metadata Architecture](#2-operator-metadata-architecture))

**Operator Categories:**

```mermaid
graph LR
    OP[Operator Categories]
    OP --> ING[Ingest]
    OP --> EXT[Extract]
    OP --> FUN[Functional]
    OP --> QUA[Quality]
    OP --> VDB[VectorDB]
    OP --> STO[Storage]

    ING --> I2[IngestSourceOperator]

    EXT --> E1[ExtractOperator]

    FUN --> F1[BranchingOperator]
    FUN --> F2[MergeOperator]
    FUN --> F3[Chunker]
    FUN --> F4[EmbeddingsOperator]
    FUN --> F5[NoopOperator]

    QUA --> Q1[DocumentClassifier]
    QUA --> Q2[Dedup]
    QUA --> Q3[DocQuality]
    QUA --> Q4[MLEnrichment]
    QUA --> Q5[Readability]
    QUA --> Q6[Redaction]
    QUA --> Q7[SQLFilter]
    QUA --> Q8[LanguageDetection]

    VDB --> V1[VectorDBOperator]

    STO --> S1[DocumentSetOperator]
    STO --> S2[StorageOutputOperator]

    style OP fill:#f9f9f9
    style EXT fill:#ffe6e6
    style ING fill:#e6f3ff
    style FUN fill:#fff4e6
    style QUA fill:#e6ffe6
    style VDB fill:#f3e6ff
    style STO fill:#e6f9f9
```

### Custom Operator Ownership and Priority

All operators must properly identify themselves using the `owner` attribute to ensure correct priority resolution in the operator factory.

**Owner Attribute:**
- **Docling-pipelines operators**: `owner = DocpipeConstants.OWNER_DOCPIPE` (must be explicitly set for all built-in operators)
- **Custom operators**: `owner = "custom"` (must be explicitly set)
- **Default**: `owner = None` (inherited from [`AbstractOperator`](src/docpipe/core/operators/abstract_operator.py), treated as custom)

**Priority Resolution:**

When multiple operators share the same `short_name`, the operator factory uses priority-based resolution:
- **Priority 100**: Custom operators (`owner="custom"` or `owner=None`)
- **Priority 200**: Docling-pipelines operators (`owner="docpipe"`)

Additional tiers can be registered at runtime via `OperatorFactory.register_owner_priority()`. Built-in values are spaced at intervals of 100, leaving room for consumer tiers without requiring magic numbers.

**Important:** Lower priority numbers carry higher precedence. Custom operators with `owner="custom"` will override Docling-pipelines operators with the same `short_name`.

**Example — Built-in Docling-pipelines Operator:**

```python
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.constants.constants import DocpipeConstants

class MyDocpipeOperator(AbstractOperator):
    short_name: str = "my_operator"
    category: OperatorCategory = OperatorCategory.Functional
    owner: str = DocpipeConstants.OWNER_DOCPIPE  # REQUIRED for built-in operators

    def __init__(self, *, config: dict[str, Any]) -> None:
        super().__init__(config=config)
```

For writing custom operators, loading sources, and the `DOCPIPE_CUSTOM_OPERATORS` environment variable, see the [Custom Operators Guide](docs/guides/CUSTOM_OPERATORS_GUIDE.md).

See [`OperatorFactory`](src/docpipe/core/orchestration/operator_factory.py:35) for implementation details.

**Package Adapter:**

The [`PackageAdapter`](src/docpipe/core/orchestration/operator_loader/adapters/package_adapter.py) enables loading operators from pip-installed Python packages using standard Python packaging:

- **Entry Point Discovery**: Operators registered via `pyproject.toml` entry points under `docpipe.operators` group
- **Module Inspection**: Automatic discovery of operators in the package's operator module
- **Standard Packaging**: Uses `importlib.metadata` for package discovery

See [`CustomOperatorLoader`](src/docpipe/core/orchestration/operator_loader/loader_service.py) for implementation details and [CUSTOM_OPERATORS_GUIDE.md](docs/guides/CUSTOM_OPERATORS_GUIDE.md) for complete usage documentation.

### 2. Operator Metadata Architecture

The [`OperatorMetadata`](src/docpipe/core/operators/operator_metadata.py) class is the **primary API** for accessing metadata from all operators in the system. It provides a unified interface for discovering operators, querying their capabilities, and understanding their requirements.

**Primary API Pattern:**

```python
from core.operators.operator_metadata import OperatorMetadata

# Initialize metadata manager
metadata = OperatorMetadata()

# Get metadata for all operators
all_operators = metadata.get_operator_metadata()

# Access specific operator metadata
extract_metadata = all_operators['extract_operator']
print(extract_metadata['label'])           # "Extract Operator"
print(extract_metadata['category'])        # OperatorCategory.Extract
print(extract_metadata['features'])        # Dict of output features
print(extract_metadata['required_features'])  # List of required inputs

# Query features from specific operator
features = metadata.get_features(short_name='extract_operator')
required = metadata.required_feature_names(short_name='chunker')

# Get reverse mapping: which operators produce a feature?
feature_map = metadata.get_feature_operators_map()
print(feature_map['content'])  # ['Extract Operator', 'Chunker', ...]
```

**Key Capabilities:**

1. **Operator Discovery**: Automatically discovers all registered operators via [`OperatorFactoryProvider`](src/docpipe/core/orchestration/operator_factory.py)
2. **Metadata Aggregation**: Collects metadata from all operators in a single call
3. **Feature Filtering**: Filters internal features (like `doc_id_hash`) from public API
4. **Caching**: Caches metadata after first retrieval for performance
5. **Utility Methods**: Provides convenience methods for common queries

**Usage in Docling Pipelines:**

The `OperatorMetadata` class is used throughout the system:

- **CLI**: [`list_operators`](src/docpipe/utils/operators/display.py) command uses it to display available operators
- **Flow Validation**: [`FlowValidator`](src/docpipe/core/orchestration/flow_validator.py) uses it to validate operator connections
- **Flow Manager**: [`DocpipeFlowManager`](src/docpipe/lib/docpipe_flow_manager.py) uses it for programmatic access
- **UI/API**: Future UI components will use it to build flow editors

**Common Use Cases:**

```python
# 1. List all available operators
metadata = OperatorMetadata()
all_ops = metadata.get_operator_metadata()
for short_name, meta in all_ops.items():
    print(f"{meta['label']}: {meta['description']}")

# 2. Check what features an operator produces
extract_features = metadata.get_features(short_name='extract_operator')
for feature_name, feature_def in extract_features.items():
    print(f"{feature_name}: {feature_def['type']}")

# 3. Validate operator compatibility
chunker_required = metadata.required_feature_names(short_name='chunker')
extract_features = metadata.get_features(short_name='extract_operator')
can_connect = all(req in extract_features for req in chunker_required)

# 4. Find operators that produce a specific feature
feature_map = metadata.get_feature_operators_map()
content_producers = feature_map.get('embeddings', [])
print(f"Operators producing 'embeddings': {content_producers}")
```

**Implementation Details:**

Internally, `OperatorMetadata` calls static methods on operator classes:

```python
# How OperatorMetadata works internally (simplified)
for short_name, operator_class in operator_factory.operators.items():
    # Call static methods on each operator class
    metadata_dict = operator_class.get_metadata()
    required_features = operator_class.get_required_features()

    # Aggregate into unified structure
    all_metadata[short_name] = {
        **metadata_dict,
        'required_features': required_features
    }
```

Each operator implements two static methods:

```python
class ExtractOperator(AbstractOperator):
    @staticmethod
    def get_metadata():
        return {
            "label": "Extract Operator",
            "category": OperatorCategory.Extract,
            "description": "Extracts text and entities from documents",
            "features": {
                "content": {
                    "type": "string",
                    "description": "Extracted document text",
                    "required": False,
                    "available_for_filter": True,
                    "available_for_vector_db": True
                }
            }
        }

    @staticmethod
    def get_required_features() -> list[str]:
        return ["doc_id", "file_path"]
```

**Note:** While operators expose `get_metadata()` and `get_required_features()` as static methods, **users should not call these directly**. Always use the `OperatorMetadata` class as the primary API, which handles discovery, aggregation, filtering, and caching.

**Metadata Structure:**

Each operator's metadata dictionary contains:

| Field               | Type             | Description                                                        |
| ------------------- | ---------------- | ------------------------------------------------------------------ |
| `label`             | string           | Human-readable operator name                                       |
| `category`          | OperatorCategory | Operator category (Extract, Ingest, Functional, Quality, VectorDB) |
| `description`       | string           | Operator purpose and functionality                                 |
| `features`          | dict             | Output features produced by the operator                           |
| `required_features` | list             | Input feature names required by the operator                       |

**Feature Metadata:**

Each feature in the `features` dictionary contains:

| Field                     | Type    | Description                                                 |
| ------------------------- | ------- | ----------------------------------------------------------- |
| `type`                    | string  | Data type (string, int64, double, boolean, list)            |
| `description`             | string  | Feature description                                         |
| `required`                | boolean | Whether feature is always produced                          |
| `available_for_filter`    | boolean | Can be used in SQL WHERE clauses                            |
| `available_for_vector_db` | boolean | Can be stored in vector databases                           |
| `tags`                    | list    | Optional tags (e.g., "internal" for internal-only features) |

**Design Rationale:**

1. **Unified API**: Single entry point (`OperatorMetadata`) for all metadata queries
2. **Automatic Discovery**: Discovers all operators without manual registration
3. **Performance**: Caches metadata after first retrieval; no repeated instantiation
4. **Separation of Concerns**:
   - Metadata API (what operators produce/need) vs operator implementation (how they process data)
   - Static information vs runtime configuration
5. **Filtering**: Automatically filters internal features from public API
6. **Extensibility**: New operators are automatically discovered when added to the system

**Metadata vs Configuration:**

| Aspect            | Operator Metadata                            | Configuration                        |
| ----------------- | -------------------------------------------- | ------------------------------------ |
| **Access**        | `OperatorMetadata().get_operator_metadata()` | `operator_instance.config`           |
| **Instantiation** | No operator instantiation required           | Full operator instantiation required |
| **Represents**    | What operator _produces_ and _needs_         | What instance _will do_              |
| **Scope**         | Class-level capabilities and requirements    | Instance-specific parameters         |
| **Mutability**    | Immutable (cached)                           | Mutable per instance                 |
| **Examples**      | Output features, required inputs, category   | Batch size, model name, file paths   |
| **Use Cases**     | Flow validation, UI generation, discovery    | Runtime execution, data processing   |

### 3. Flow/Pipeline Concept

A **Flow** is a JSON-defined configuration that specifies a pipeline of operators connected in a directed acyclic graph (DAG).

**Flow Authoring Format vs Runtime DAG:**


Docling-pipelines uses two distinct representations:

1. **Authoring Format** (User-facing): Simplified JSON structure for defining flows
   - Uses `flow` array with operator definitions
   - Uses `depends_on` to declare dependencies by operator name
   - Uses `type` with short operator names (e.g., `ingest_source`, `extract_operator`)
   - Uses `config` for operator-specific parameters

2. **Runtime DAG** (Internal): Compiled execution graph with nodes and edges
   - Generated automatically from authoring format
   - Contains UUIDs, edge connections, and execution metadata
   - Used by the orchestration engine for execution

**Example Flow Authoring Format:**

```json
{
  "flow_name": "Document Processing Pipeline",
  "description": "Ingest, extract, chunk, and embed documents",
  "flow": [
    {
      "name": "ingest_source_filesystem",
      "type": "ingest_source",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["./sample_documents"]}
      }
    },
    {
      "name": "extract_with_docling",
      "type": "extract_operator",
      "depends_on": ["ingest_source_filesystem"],
      "config": {
        "text_extraction": {
          "provider": "docling_library"
        },
        "entity_extraction": {
          "provider": "none"
        }
      }
    }
  ],
  "global_config": {
    "doc_column": "content"
  }
}
```

**Key Authoring Format Elements:**

- **flow_name**: Human-readable flow identifier
- **flow**: Array of operator definitions with unique names
- **depends_on**: Array of operator names that must execute before this operator
- **type**: Short operator name (e.g., `ingest_source`, `chunker`, `embeddings`, `vectordb`)
- **config**: Operator-specific configuration parameters
- **Automatic Compilation**: The system automatically generates the runtime DAG from the authoring format

### Flow Definition Storage

When a flow is executed, the **original flow definition** (before compilation to runtime DAG format) is automatically saved to the filesystem for audit and reproducibility purposes.

**Storage Location:**
```
{data_path}/{job_id}/{job_run_id}/flow_definition.json
```

**Key Details:**
- The original flow definition is stored at the start of each job run execution
- This preserves the exact flow configuration used for that specific execution
- Enables audit trails and reproducibility of past executions
- The file is saved as `flow_definition.json` in the job run's data directory
- Storage occurs in [`FlowExecutor`](src/docpipe/core/orchestration/flow_executor.py) via the job stats service

**Example Path:**
```
/path/to/data/my-job-id/run-12345/flow_definition.json
```

This behavior ensures that even if the original flow file is modified or deleted, the exact configuration used for each execution is preserved and can be retrieved for debugging, auditing, or re-execution purposes.

### 4. DAG-Based Execution Model

The execution model follows these principles:

1. **Topological Ordering**: Operators execute in dependency order
2. **Parallel Execution**: Independent operators run concurrently
3. **Data Passing**: PyArrow tables flow between operators
4. **Error Handling**: Failed operators propagate errors appropriately
5. **Batch Processing**: Large datasets processed in configurable batches

```mermaid
graph LR
    A[Ingest] --> B[DocumentClassifier]
    B --> C[Extract]
    C --> D[Chunk]
    D --> E[Embed]
    E --> F[VectorDB]

    style A fill:#e1f5ff
    style B fill:#e6ffe6
    style C fill:#ffe1f5
    style D fill:#f5ffe1
    style E fill:#fff5e1
    style F fill:#e1fff5
```

### 5. PyArrow Data Format Rationale

PyArrow tables serve as the universal data format throughout the pipeline:

**Benefits:**

- **Columnar Storage**: Efficient memory usage and fast column-wise operations
- **Zero-Copy Reads**: Minimal memory overhead when passing data between operators
- **Type Safety**: Strong schema enforcement with rich type system
- **Interoperability**: Native support for Parquet, CSV, and other formats
- **Performance**: Optimized for analytical workloads and batch processing

**Schema Preservation:**

- Column schemas maintained across all operators
- Automatic type inference and validation
- Support for nested structures and complex types

## Component Deep Dive

### 1. Orchestrator Architecture

The orchestrator coordinates flow execution using Prefect for workflow management.

```mermaid
graph TB
    subgraph "Orchestrator Components"
        AO[AbstractOrchestrator]
        PO[PythonOrchestrator]
        FE[FlowExecutor]
        FV[FlowValidator]
        PE[PrefectEngine]
        BM[BatchManager]
        EH[EventHandler]
        JT[JobTracker]
    end

    subgraph "Execution Flow"
        START[Start] --> LOAD[Load Flow JSON]
        LOAD --> VALIDATE[Validate Flow]
        VALIDATE --> INIT[Initialize Orchestrator]
        INIT --> EXEC[Execute DAG]
        EXEC --> MONITOR[Monitor Progress]
        MONITOR --> COMPLETE[Complete]
    end

    FE --> FV
    FE --> PO
    PO --> PE
    PO --> BM
    PO --> EH
    PO --> JT

    LOAD --> FE
    VALIDATE --> FV
    INIT --> PO
    EXEC --> PE
    MONITOR --> EH

    style AO fill:#fff4e1
    style PO fill:#fff4e1
    style PE fill:#ffe1e1
    style START fill:#e1f5ff
    style COMPLETE fill:#e1ffe1
```

**Key Components:**

#### AbstractOrchestrator

- Base interface for all orchestrators
- Manages job lifecycle (initialization, execution, cleanup)
- Coordinates with Prefect engine
- Handles batch processing

#### Work Pool Configuration

The `WorkPoolConfig` model defines configuration for distributed execution modes:

```python
@dataclass
class WorkPoolConfig:
    enabled: bool = False
    type: str = "process"  # "process", "docker"
    name: str = "default-pool"
    max_workers: Optional[int] = None
    image: Optional[str] = None
    namespace: Optional[str] = None
    batch_storage: Optional[BatchStorageConfig] = None
```

**Configuration Parameters:**

| Parameter       | Type   | Description                                       | Required   |
| --------------- | ------ | ------------------------------------------------- | ---------- |
| `enabled`       | bool   | Enable work pool execution                        | Yes        |
| `type`          | str    | Execution type: "process", "docker"               | Yes        |
| `name`          | str    | Work pool name in Prefect                         | Yes        |
| `max_workers`   | int    | Maximum concurrent workers (process pool only)    | No         |
| `image`         | str    | Docker image name                                 | Docker     |
| `batch_storage` | object | Batch storage configuration                       | Docker     |

**Batch Storage Configuration:**

```python
@dataclass
class BatchStorageConfig:
    type: str = "local"  # Only "local" supported
    base_path: str = "/tmp/docpipe/batches"
```

**Configuration Examples:**

**Process Pool:**

```json
{
  "work_pool": {
    "enabled": true,
    "type": "process",
    "name": "docpipe-process-pool",
    "max_workers": 4
  }
}
```

**Docker:**

```json
{
  "work_pool": {
    "enabled": true,
    "type": "docker",
    "name": "docpipe-docker-pool",
    "image": "docpipe:latest",
    "batch_storage": {
      "type": "local",
      "base_path": "/app/data/batches"
    }
  }
}
```

**Work Pool Setup:**

Before using distributed execution, create the corresponding Prefect work pool:

```bash
# Process pool (managed automatically)
# No setup required

# Docker pool
prefect work-pool create docpipe-docker-pool --type docker
```

**Worker Deployment:**

Start workers to process tasks from the work pool:

```bash
# Docker worker
prefect worker start --pool docpipe-docker-pool
```

- Tracks deleted rows and metadata

#### PythonOrchestrator

- Concrete implementation of [`AbstractOrchestrator`](src/docpipe/core/orchestration/abstract_orchestrator.py)
- Used by both CLI and Python API
- Instantiated via [`OrchestratorFactory`](src/docpipe/core/orchestration/orchestrator_factory.py)
- Manages operator execution through Prefect

#### FlowExecutor

- Entry point for flow execution
- Loads flow definitions from JSON files or dictionaries
- Validates flows before execution
- Manages memory diagnostics
- Handles cancellation requests

#### FlowValidator

- Validates operator configurations and parameters
- Checks data dependencies and DAG structure
- Verifies operator availability and compatibility
- Produces actionable errors and warnings

#### PrefectEngine

- Wraps Prefect workflow execution
- Manages task dependencies
- Handles parallel execution
- Provides retry logic
- Tracks execution state

#### BatchManager

- Coordinates batch processing
- Manages batch size configuration
- Handles batch splitting and merging
- Optimizes memory usage

### 2. Operator Base Classes

```mermaid
classDiagram
    class AbstractTableTransform {
        <<abstract>>
        +transform(table: Table) tuple[list[Table], dict]
    }

    class AbstractOperator {
        <<abstract>>
        +short_name: str
        +category: OperatorCategory
        +transform(table: Table) tuple[list[Table], dict]
        +validate(errors, warnings, features)
        +get_required_features()$ list
        +get_metadata()$ dict
        +is_available()$ bool
    }

    class ConcreteOperator {
        +transform(table: Table) tuple[list[Table], dict]
        +validate(errors, warnings, features)
        +get_required_features()$ list
    }

    AbstractTableTransform <|-- AbstractOperator
    AbstractOperator <|-- ConcreteOperator

    note for AbstractOperator "Template Method Pattern:\n- Defines execution flow\n- Subclasses implement specifics"
```

**AbstractOperator Responsibilities:**

1. **Configuration Management**: Parse and store operator parameters
2. **Validation**: Validate input data and configuration
3. **Execution**: Process PyArrow tables
4. **Metadata**: Track processing statistics
5. **Error Handling**: Record failed and skipped documents
6. **Feature Management**: Declare required input columns

**Class-Level vs Instance-Level Methods:**

Operators distinguish between class-level capabilities and instance-level configuration:

- **Static Methods** (`@staticmethod`):
  - [`get_metadata()`](src/docpipe/core/operators/abstract_operator.py:61): Returns operator-level metadata (category, features, description)
  - [`get_required_features()`](src/docpipe/core/operators/abstract_operator.py:56): Returns required input features
  - [`is_available()`](src/docpipe/core/operators/abstract_operator.py:47): Checks if operator dependencies are available
  - Accessed via `OperatorClass.method_name()` without instantiation
  - Represent operator capabilities independent of any specific configuration

- **Instance Methods**:
  - `validate()`: Validates instance-specific parameters and configuration
  - `transform()`: Processes data using instance configuration
  - Require operator instantiation with specific configuration

**Rationale for Static Methods:**

Both [`get_metadata()`](src/docpipe/core/operators/abstract_operator.py:61) and [`get_required_features()`](src/docpipe/core/operators/abstract_operator.py:56) are static because:

1. They represent operator-level information, not instance-specific configuration
2. Enable metadata discovery without instantiation overhead
3. Information is constant across all instances of an operator class
4. Support efficient operator registry and discovery mechanisms
5. Align with the principle that metadata describes "what the operator can do" rather than "what this instance is configured to do"

### 3. Data Flow Between Operators

```mermaid
sequenceDiagram
    participant O1 as Operator 1
    participant DA as DataAccess
    participant FS as File System
    participant O2 as Operator 2

    O1->>O1: Process Data
    O1->>DA: Write PyArrow Table
    DA->>FS: Save Parquet File
    Note over DA,FS: Efficient columnar storage

    O2->>DA: Request Input Data
    DA->>FS: Read Parquet File
    FS->>DA: Return PyArrow Table
    DA->>O2: Provide Input Table
    O2->>O2: Process Data
```

**Key Features:**

1. **Schema Preservation**: Column schemas maintained across all operators
2. **Efficient Storage**: Columnar Parquet format for disk-based operations

**Processing Mechanisms:**

1. **In-Memory Passing**: Small datasets passed directly as PyArrow tables
2. **Disk-Based Storage**: Large datasets written to Parquet files for memory efficiency
3. **Batch Processing**: Large datasets split into configurable batches for parallel execution

### 4. Configuration Management

Configuration flows through multiple layers:

```mermaid
graph TD
    JSON[Flow JSON] --> FE[FlowExecutor]
    YAML[docling-pipelines-config.yaml] --> ORCH[Orchestrator]
    FE --> PARAMS[Runtime Parameters]
    PARAMS --> ORCH
    ORCH --> OP_CONFIG[Operator Config]
    OP_CONFIG --> OP[Operator Instance]

    ENV[Environment Variables] --> YAML
    DEFAULTS[Default Values] --> OP_CONFIG

    style JSON fill:#e1f5ff
    style YAML fill:#f3e5ff
    style PARAMS fill:#fff4e1
    style OP fill:#e1ffe1
```

**Configuration Hierarchy:**

1. Flow JSON for flow topology and operator parameters
2. `docling-pipelines-config.yaml` for centralized system configuration
3. Environment variables for deployment-specific overrides
4. Default values for unspecified settings

Flow JSON remains the source for DAG structure and operator-specific behavior, while shared runtime infrastructure such as job management, asset repositories, and incremental metadata is configured centrally through `docling-pipelines-config.yaml`.

#### Incremental Metadata Configuration

Incremental metadata configuration is YAML-first and uses `docling-pipelines-config.yaml` as the single source of truth. Flow-level `incremental_metadata` settings are no longer part of the supported configuration model.

The centralized configuration shape is:

```yaml
incremental_metadata:
  storage:
    type: "filesystem"  # Options: filesystem, postgresql
    config:
      base_dir: "./data"
      lock_timeout: 30.0
```

When `storage.type` is `postgresql`, the configuration also includes a dedicated `postgres` section for connection settings and schema selection.

Supported storage backends:

- **Filesystem** - file-backed storage using Parquet format for development and single-host execution
- **PostgreSQL** - centralized durable storage for concurrent and distributed execution

Environment variable substitution is supported inside `docling-pipelines-config.yaml`, allowing secrets such as database passwords to be supplied at deployment time rather than committed to source control.

#### Incremental Metadata Hexagonal Architecture

Incremental metadata is implemented as a hexagonal subsystem under [`src/docpipe/core/incremental_metadata/`](src/docpipe/core/incremental_metadata/):

- `domain/models/incremental_record.py` defines the domain record model
- `domain/ports/incremental_metadata_store.py` defines the storage port
- `adapters/config/` resolves backend configuration from `docling-pipelines-config.yaml`
- `adapters/stores/filesystem/` contains the Filesystem storage adapter (using Parquet format)
- `adapters/stores/postgres/` contains the PostgreSQL storage adapter

This structure separates domain contracts from infrastructure concerns and allows backend selection without changing ingest operator code. The orchestration layer resolves the configured incremental metadata store once and passes that capability to the ingest path that performs incremental change detection.

---

## Distributed Execution Architecture

Docling Pipelines supports multiple execution modes through a hexagonal architecture pattern that decouples the orchestration logic from the execution strategy. This enables seamless switching between local development and distributed production deployments.

### Execution Modes

The framework supports four execution modes:

1. **Thread Pool (Local Development)**: Uses Python's ThreadPoolExecutor for lightweight parallelism within a single process
2. **Process Pool (Single-Node Production)**: Uses Python's ProcessPoolExecutor for CPU-bound workloads on a single machine
3. **Docker (Distributed)**: Deploys batch processing tasks as Docker containers via Prefect work pools

### Hexagonal Architecture Pattern

The distributed execution system follows hexagonal architecture (ports and adapters) to maintain clean separation between business logic and infrastructure:

```mermaid
graph TB
    subgraph "Core Domain"
        PE[PrefectEngine]
        BM[BatchManager]
    end

    subgraph "Port Layer"
        BEP[BatchExecutionPort<br/>Interface]
    end

    subgraph "Adapter Layer"
        TPA[ThreadPoolAdapter]
        WPA[WorkPoolAdapter]
    end

    subgraph "Infrastructure"
        TP[ThreadPoolExecutor]
        PP[ProcessPoolExecutor]
        DW[Docker Work Pool]
    end

    PE --> BEP
    BM --> BEP
    BEP --> TPA
    BEP --> WPA
    TPA --> TP
    WPA --> PP
    WPA --> DW

    style PE fill:#fff4e1
    style BEP fill:#e1f5ff
    style TPA fill:#e1ffe1
    style WPA fill:#e1ffe1
```

**Key Components:**

#### BatchExecutionPort (Interface)

- Defines the contract for batch execution strategies
- Methods: `execute_batches()`, `shutdown()`
- Enables strategy pattern for execution modes

#### ThreadPoolAdapter

- Implements BatchExecutionPort for local execution
- Uses Python's ThreadPoolExecutor
- Best for I/O-bound operations and development
- No external infrastructure required

#### WorkPoolAdapter

- Implements BatchExecutionPort for distributed execution
- Supports process pool and Docker work pools
- Configurable via WorkPoolConfig
- Handles batch serialization and result aggregation

### Batch Storage Strategies

Distributed execution requires serializing batches for cross-process/container communication:

1. **Inline Storage**: Batches passed directly in memory (thread pool only)
2. **Local Filesystem**: Batches written to Parquet files on shared storage (process pool, Docker with volumes)

**Note:** S3 and other cloud storage backends are not currently supported.

### Execution Flow

```mermaid
sequenceDiagram
    participant FE as FlowExecutor
    participant PE as PrefectEngine
    participant BM as BatchManager
    participant Adapter as BatchExecutionAdapter
    participant Worker as Worker Process/Container

    FE->>PE: Execute Flow
    PE->>BM: Split into Batches
    BM->>Adapter: execute_batches()

    alt Thread Pool Mode
        Adapter->>Worker: Submit to ThreadPool
        Worker->>Worker: Process Batch (in-memory)
        Worker-->>Adapter: Return Results
    else Work Pool Mode
        Adapter->>Adapter: Serialize Batches to Disk
        Adapter->>Worker: Submit to Work Pool
        Worker->>Worker: Load Batch from Disk
        Worker->>Worker: Process Batch
        Worker->>Worker: Write Results to Disk
        Worker-->>Adapter: Signal Completion
        Adapter->>Adapter: Load Results from Disk
    end

    Adapter-->>BM: Aggregated Results
    BM-->>PE: Complete
    PE-->>FE: Flow Complete
```

### Configuration

Execution mode is configured via the `work_pool` section in flow JSON:

**Thread Pool (Default):**

```json
{
  "work_pool": {
    "enabled": false
  }
}
```

**Process Pool:**

```json
{
  "work_pool": {
    "enabled": true,
    "type": "process",
    "name": "my-process-pool",
    "max_workers": 4
  }
}
```

**Docker:**

```json
{
  "work_pool": {
    "enabled": true,
    "type": "docker",
    "name": "my-docker-pool",
    "image": "docpipe:latest",
    "batch_storage": {
      "type": "local",
      "base_path": "/shared/batches"
    }
  }
}
```

---

## Operator Lifecycle

### Complete Lifecycle Diagram

```mermaid
stateDiagram-v2
    [*] --> Instantiation
    Instantiation --> Configuration
    Configuration --> Validation
    Validation --> Initialization
    Initialization --> Execution
    Execution --> DataProcessing
    DataProcessing --> MetadataCollection
    MetadataCollection --> OutputGeneration
    OutputGeneration --> Cleanup
    Cleanup --> [*]

    Validation --> Error: Validation Failed
    Execution --> Error: Execution Failed
    DataProcessing --> Error: Processing Failed
    Error --> Cleanup

    note right of Instantiation
        OperatorFactory creates
        operator instance from
        flow configuration
    end note

    note right of Validation
        Validate parameters,
        check dependencies,
        verify data schema
    end note

    note right of Execution
        Process PyArrow table,
        apply transformations,
        handle errors
    end note
```

### Detailed Lifecycle Stages

#### 1. Instantiation

**Process:**

```python
# OperatorFactory creates operator from config
operator_class = import_operator_class(operator_type)

# Access class-level metadata without instantiation
metadata = operator_class.get_metadata()
is_available = operator_class.is_available()

# Create instance with configuration
operator_instance = operator_class(config)
```

**Configuration Injection:**

- Operator type (fully qualified class name)
- Operator parameters (from flow JSON)
- Job metadata (job_id, job_run_id, context_id)
- Runtime parameters

**Metadata Access Pattern:**

- Operator metadata is accessed at the class level via static method [`OperatorClass.get_metadata()`](src/docpipe/core/operators/abstract_operator.py:59)
- No instantiation required for metadata discovery
- Enables efficient operator registry and capability queries

#### 2. Configuration

**Operator receives:**

```python
config = {
    "name": "extract_1",
    "id": "extract_1",
    "job_id": "job_123",
    "job_run_id": "run_456",
    "config": {
        "docling_url": "http://localhost:5000",
        "batch_size": 10
    }
}
```

**Parsed into operator attributes:**

- `self.name`: Operator name
- `self.id`: Unique operator ID
- `self.job_id`: Job identifier
- `self.job_run_id`: Job run identifier
- Custom parameters from `config`

#### 3. Validation

**Two-Phase Validation:**

**Phase 1: Flow Validation (Pre-Execution)**

```python
def validate(self, errors: list, warnings: list, available_features: list):
    # Check required features exist
    OperatorUtils.validate_columns(
        available_features,
        self.get_required_features(),
        self.short_name,
        errors
    )
    # Validate operator-specific parameters
    self._validate_params(errors, warnings)
```

**Phase 2: Runtime Validation (During Execution)**

- Input data schema validation
- Parameter value validation
- External service availability checks

#### 4. Execution

**Main execution flow:**

```mermaid
graph TD
    START[Receive Input Table] --> CHECK{Validate Input}
    CHECK -->|Valid| PROCESS[Process Data]
    CHECK -->|Invalid| ERROR[Record Error]

    PROCESS --> BATCH{Batch Processing?}
    BATCH -->|Yes| SPLIT[Split into Batches]
    BATCH -->|No| TRANSFORM[Transform Data]

    SPLIT --> LOOP[Process Each Batch]
    LOOP --> TRANSFORM
    TRANSFORM --> MERGE[Merge Results]
    MERGE --> OUTPUT[Generate Output Table]

    ERROR --> METADATA[Update Metadata]
    OUTPUT --> METADATA
    METADATA --> RETURN[Return Results]

    style START fill:#e1f5ff
    style PROCESS fill:#fff4e1
    style OUTPUT fill:#e1ffe1
    style ERROR fill:#ffe1e1
```

#### 5. Metadata Collection

**Two Types of Metadata:**

**1. Operator Metadata (Class-Level, Static):**

```python
# Accessed without instantiation
operator_metadata = ExtractOperator.get_metadata()
# Returns:
# {
#     "label": "Extract Operator",
#     "category": "Extract",
#     "description": "Extracts text and entities from documents",
#     "features": {
#         "content": {"type": "string", "description": "Extracted text"},
#         "entities": {"type": "list", "description": "Extracted entities"}
#     }
# }
```

**2. Execution Metadata (Instance-Level, Runtime):**

```python
# Generated during operator execution
execution_metadata = {
    "total_docs": 100,
    "processed_docs": 95,
    "failed_docs_count": 3,
    "failed_docs": [
        {"id": "doc_1", "name": "file1.pdf", "reason": "Parse error"}
    ],
    "skipped_docs_count": 2,
    "skipped_docs": [
        {"id": "doc_3", "name": "file3.pdf", "reason": "Empty content"}
    ],
    "node_status": "COMPLETED"
}
```

**Key Distinction:**

- **Operator metadata**: Describes what the operator _can do_ (capabilities, features, requirements)
- **Execution metadata**: Describes what the operator _did_ (processing results, statistics, errors)

---

## Data Flow Architecture

### End-to-End Data Flow

The platform supports multiple input sources and optional quality operators, but the core document-processing path is a linear sequence from ingestion through vector storage:

```mermaid
graph LR
    SRC[Input Source]
    ING[IngestSourceOperator]
    EXT[ExtractOperator]
    CHK[Chunker]
    EMB[EmbeddingsOperator]
    VDB[VectorDBOperator]

    SRC --> ING --> EXT --> CHK --> EMB --> VDB

    style SRC fill:#e1f5ff
    style ING fill:#e1f5ff
    style EXT fill:#ffe1e1
    style CHK fill:#fff4e1
    style EMB fill:#fff5e1
    style VDB fill:#f3e6ff
```

## Integration Patterns

### 1. Ollama Integration Architecture

```mermaid
graph TB

    subgraph "Docling-pipelines Operators"
        EXT[ExtractOperator]
        EMB[EmbeddingsOperator]
    end

    subgraph "Client Layer"
        OC[OllamaClient]
        OEA[OllamaEmbeddingsAdapter]
    end

    subgraph "Ollama Service"
        OS[Ollama Server<br/>localhost:11434]
        M1[llama3.2]
        M2[nomic-embed-text]
        M3[mistral]
    end

    EE --> OC
    EMB --> OEA
    OC --> OS
    OEA --> OS
    OS --> M1
    OS --> M2
    OS --> M3

    style EE fill:#ffe1e1
    style EMB fill:#ffe1e1
    style OC fill:#fff4e1
    style OS fill:#e1f5ff
```

**Integration Points:**

1. **Entity Extraction**: Supports Ollama via LiteLLM for LLM-based entity extraction (using OpenAI-compatible API)
2. **Embeddings**: Generates vector embeddings using Ollama models
3. **Configuration**: Model selection, temperature, context window
4. **Error Handling**: Retry logic, timeout management

**Note:** Ollama models are supported via LiteLLM provider. Use `openai/` model prefix and configure `api_base` to point to Ollama's OpenAI-compatible endpoint.

**Example Configuration:**

```json
{
  "type": "extract_operator",
  "name": "extract_entities_ollama",
  "config": {
    "entity_extraction": {
      "provider": "litellm",
      "provider_config": {
        "model_id": "openai/llama3.2",
        "api_base": "http://localhost:11434/v1",
        "temperature": 0.7,
        "max_tokens": 2000
      }
    }
  }
}
```

### 2. Watsonx.ai Integration Architecture

```mermaid
graph TB
    subgraph "Docling-pipelines Operators"
        EXT[ExtractOperator]
        DC[DocumentClassifier]
    end

    subgraph "Client Layer"
        WC[WatsonxClient]
        WEA[WatsonxEntityAdapter]
        WCA[Watsonx Classification Adapter]
    end

    subgraph "IBM watsonx.ai"
        IAM[IBM Cloud IAM]
        API[watsonx.ai API]
        M1[ibm/granite-13b-chat-v2]
        M2[ibm/granite-3-8b-instruct]
        M3[Other hosted models]
    end

    EXT --> WEA
    DC --> WCA
    WEA --> WC
    WCA --> WC
    WC --> IAM
    WC --> API
    API --> M1
    API --> M2
    API --> M3

    style EXT fill:#ffe1e1
    style DC fill:#e6ffe6
    style WC fill:#fff4e1
    style API fill:#e1f5ff
    style IAM fill:#e1f5ff
```

**Integration Points:**

1. **Entity Extraction**: Uses Watsonx.ai for LLM-based entity extraction in `ExtractOperator`
2. **Document Classification**: Uses Watsonx.ai for category classification in `DocumentClassifier`
3. **Authentication**: IBM Cloud IAM token flow using `WATSONX_API_KEY`
4. **Configuration**: `provider_config` carries non-sensitive settings such as `api_base`, `container_kind`, and `timeout`
5. **Container Targeting**: Requests are scoped to a project or deployment space via `WATSONX_CONTAINER_ID`
6. **Error Handling**: Client-managed retries, timeout control, and provider error normalization

**Required Environment Variables:**

- `WATSONX_API_KEY`: IBM Cloud API key used to obtain IAM access tokens
- `WATSONX_CONTAINER_ID`: Watsonx.ai project ID or space ID
- `WATSONX_API_BASE_URL`: Optional API base URL such as `https://us-south.ml.cloud.ibm.com`
- `WATSONX_CONTAINER_KIND`: Optional container type, defaults to `project`

**Supported Models:**

- **IBM Granite**: Hosted Granite chat and instruct models such as `ibm/granite-13b-chat-v2`
- **Other watsonx.ai models**: Any compatible model exposed through the configured watsonx.ai deployment

**Example Configuration:**

```json
{
  "operator_type": "ExtractOperator",
  "operator_params": {
    "entity_extraction": {
      "provider": "watsonx",
      "provider_config": {
        "model_id": "ibm/granite-13b-chat-v2",
        "api_base": "https://us-south.ml.cloud.ibm.com",
        "container_kind": "project",
        "timeout": 60
      },
      "custom_schema": {
      "invoice_number": "string",
      "total_amount": "float"
    }
  }
}
```

**Note:** When using entity extraction (any mode except `none`), you must provide either:
- A `custom_schema` in the operator configuration (as shown above), OR
- A `document_type` column from an upstream classification operator (e.g., DocumentClassifierOperator)

If neither is provided, a `ConfigurationError` will be thrown.

### 3. OpenSearch Integration Architecture

```mermaid
graph TB
    subgraph "Docling-pipelines Layer"
        VDB[VectorDBOperator]
    end

    subgraph "Adapter Layer (Hexagonal)"
        PORT[VectorDB Port<br/>Interface]
        OSA[OpenSearch Adapter]
    end

    subgraph "OpenSearch Service"
        OS[OpenSearch<br/>localhost:9200]
        IDX[Indices]
        KNN1[NMSLIB Engine]
        KNN2[Faiss Engine]
        KNN3[Lucene Engine]
    end

    VDB --> PORT
    PORT --> OSA
    OSA --> OS
    OS --> IDX
    IDX --> KNN1
    IDX --> KNN2
    IDX --> KNN3

    style VDB fill:#ffe1e1
    style PORT fill:#fff4e1
    style OSA fill:#e1ffe1
    style OS fill:#e1f5ff
```

**Hexagonal Architecture Benefits:**

1. **Decoupling**: VectorDBOperator independent of OpenSearch specifics
2. **Testability**: Easy to mock adapters for testing
3. **Extensibility**: Add new vector DB adapters without changing operator
4. **Flexibility**: Switch vector databases via configuration

**Supported KNN Engines:**

- **NMSLIB**: Fast approximate nearest neighbor search
- **Faiss**: Facebook's similarity search library
- **Lucene**: Native Lucene KNN implementation

**Example Configuration:**

```json
{
  "type": "vectordb",
  "name": "opensearch_vector_store",
  "config": {
    "provider": "opensearch",
    "index_name": "documents",
    "provider_config": {
      "host": "localhost",
      "port": 9200,
      "engine": "nmslib",
      "algorithm": "hnsw",
      "space_type": "cosinesimil"
    }
  }
}
```

**Note:** Vector dimensions are auto-detected from embedding data. OpenSearch supports multiple vector columns with different dimensions in a single index.

### 4. OpenSearch Schema Templates and Metadata Normalization

The OpenSearch adapter supports a flexible schema template system that enables reusable index configurations with placeholder-based dynamic values, along with automatic metadata column normalization.

#### Schema Template System

**Purpose**: Provide consistent, reusable OpenSearch index schemas across different pipelines.

**Key Features**:

1. **JSON-Based Templates**: Schema templates are stored as JSON files in `src/docpipe/core/operators/vectordb/schemas/`
2. **Placeholder Replacement**: Dynamic values are injected at runtime using placeholder strings
3. **Graceful Fallback**: If template is not found or invalid, falls back to dynamic schema generation
4. **Validation**: Comprehensive schema validation with detailed error messages
5. **Indexing Rules**: Field-level overrides for customizing field types and properties without full schema definitions

**Built-in Templates**:

- `default_schema.v1.json`: Basic schema with standard field types
- `template_with_content_analyzer.v1.json`: Template with custom content analyzer and indexing rules
- `full_schema.v1.json`: Example of full schema format with complete mappings

**Supported Placeholders**:

| Placeholder             | Description                | Example Value                          |
| ----------------------- | -------------------------- | -------------------------------------- |
| `__VECTOR_DIMENSION__`  | Vector embedding dimension | `384`, `768`, `1536`                   |
| `__ENGINE__`            | KNN engine name            | `faiss`, `lucene`, `nmslib`, `jvector` |
| `__ALGORITHM__`         | KNN algorithm              | `hnsw`, `ivf`                          |
| `__SPACE_TYPE__`        | Similarity metric          | `l2`, `cosine`, `inner_product`        |
| `__ENGINE_PARAMETERS__` | Engine-specific parameters | `{"ef_construction": 128, "m": 24}`    |

**Schema Format Options**:

Templates support two formats:

1. **Template Schema** (with `field_types` + optional `indexing_rules`): Dynamic field mapping with type templates
2. **Full Schema** (with `mappings`): Complete OpenSearch mapping definition

**Template Schema Structure**:

```json
{
  "schema_name": "default",
  "schema_version": 1,
  "settings": {
    "index": {
      "knn": true,
      "number_of_shards": 2,
      "number_of_replicas": 1
    }
  },
  "field_types": {
    "vector": {
      "type": "knn_vector",
      "dimension": "__VECTOR_DIMENSION__",
      "method": {
        "name": "__ALGORITHM__",
        "space_type": "__SPACE_TYPE__",
        "engine": "__ENGINE__",
        "parameters": "__ENGINE_PARAMETERS__"
      }
    },
    "string": {
      "type": "text",
      "fields": {
        "keyword": {
          "type": "keyword",
          "ignore_above": 256
        }
      }
    }
  },
  "indexing_rules": {
    "content": {
      "field_type": "content_text",
      "boost": 2.0,
      "copy_to": ["all_text"]
    }
  }
}
```

**Usage Example**:

```json
{
  "operator_type": "docpipe.core.operators.vectordb.vectordb_operator.VectorDBOperator",
  "operator_params": {
    "provider": "opensearch",
    "index_name": "document_chunks",
    "provider_config": {
      "schema_template_path": "schemas/template_with_content_analyzer.v1.json",
      "host": "localhost",
      "port": 9200,
      "engine": "faiss",
      "algorithm": "hnsw"
    }
  }
}
```

**Note:** Vector dimensions are auto-detected from embedding data.

#### Indexing Rules System

**Purpose**: Enable flexible field-level customization without requiring full schema definitions. Indexing rules allow overriding field types and properties for specific fields while using template-based field type definitions for the rest.

**Key Features**:

1. **Field Type Override**: Map specific fields to custom field types defined in `field_types`
2. **Property Overrides**: Add or override specific OpenSearch mapping properties for individual fields without redefining the entire field type
3. **Dual Lookup Resolution**: Supports both feature names and mapped names for field resolution
4. **Allowlist Protection**: Only safe properties can be overridden to prevent schema corruption
5. **Deep Merging**: Nested properties are recursively merged with field type definitions

**Property Overrides Explained**:

Property overrides let you customize specific OpenSearch mapping properties for individual fields. Instead of creating a new field type for every variation, you can reuse a base field type and override just the properties you need.

**Common Use Cases**:

- **`boost`**: Increase relevance score for important fields (e.g., title gets boost of 3.0, content gets 2.0)
- **`copy_to`**: Copy field values to a combined search field (e.g., copy title and content to "all_text" for unified search)
- **`analyzer`**: Use different text analysis for specific fields (e.g., use "keyword_analyzer" for product codes)
- **`fields`**: Add sub-fields with different analysis (e.g., add "exact" keyword sub-field for case-sensitive matching)

**Supported Properties**: `analyzer`, `search_analyzer`, `copy_to`, `boost`, `index`, `store`, `similarity`, `normalizer`, `fields`

**Example - Boosting Important Fields**:

```json
{
  "indexing_rules": {
    "title": {
      "field_type": "string",
      "boost": 3.0,
      "copy_to": ["all_text"]
    },
    "content": {
      "field_type": "string",
      "boost": 2.0,
      "copy_to": ["all_text"]
    },
    "summary": {
      "field_type": "string",
      "boost": 1.5,
      "copy_to": ["all_text"]
    }
  }
}
```

In this example, all three fields use the same `string` field type, but each has different boost values to control search relevance. The `title` field is 3x more important than unboost fields, `content` is 2x, and `summary` is 1.5x.

**Indexing Rules Structure**:

```json
{
  "indexing_rules": {
    "field_name": {
      "field_type": "custom_type",
      "boost": 2.0,
      "copy_to": ["all_text"],
      "analyzer": "custom_analyzer"
    }
  }
}
```

**Example: Content Field with Custom Analyzer**:

```json
{
  "schema_name": "document_chunks",
  "schema_version": 1,
  "settings": {
    "analysis": {
      "analyzer": {
        "content_analyzer": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": ["lowercase", "stop", "snowball"]
        }
      }
    }
  },
  "field_types": {
    "string": {
      "type": "text",
      "fields": {
        "keyword": {
          "type": "keyword",
          "ignore_above": 256
        }
      }
    },
    "content_text": {
      "type": "text",
      "analyzer": "content_analyzer",
      "fields": {
        "keyword": {
          "type": "keyword",
          "ignore_above": 256
        }
      }
    }
  },
  "indexing_rules": {
    "content": {
      "field_type": "content_text"
    }
  }
}
```

In this example:

- The `content` field uses `content_text` field type instead of the default `string` type
- The `content_text` type applies a custom analyzer with stemming and stop word removal
- Other string fields continue using the default `string` field type

**Lookup Priority**:

When resolving field configurations, the system follows this priority:

1. Check `indexing_rules` for the feature name (e.g., `content`)
2. Check `indexing_rules` for the mapped name (e.g., `doc_content`)
3. Fall back to `system_type` from `available_features` configuration
4. Use default field type if no match found

**Reserved Fields Protection**:

System fields cannot be overridden via indexing rules:

- `_id`
- `_index`
- `_source`
- `_type`
- `_meta`

**Validation and Safety**:

- Property overrides are validated against an allowlist to prevent invalid configurations
- Invalid field types in indexing rules raise clear error messages
- Empty analysis blocks are automatically removed to prevent OpenSearch errors
- Mapping explosion protection limits total fields to 2000 by default

**Implementation Details**:

The indexing rules system is implemented in `OpenSearchIndexManager._build_index_body_from_field_type_template()`:

1. **Field Type Resolution**: Looks up field type from `indexing_rules` or falls back to `system_type`
2. **Base Mapping Creation**: Retrieves field type definition from `field_types` section
3. **Property Override Application**: Deep merges allowlisted properties from indexing rules
4. **Dual Lookup Support**: Checks both feature name and mapped name for maximum flexibility
5. **Validation**: Ensures field types exist and properties are safe to override

**Benefits**:

- **Flexibility**: Customize specific fields without duplicating entire schema
- **Maintainability**: Centralized field type definitions with per-field overrides
- **Safety**: Allowlist protection prevents accidental schema corruption
- **Backward Compatibility**: Existing schemas without indexing rules continue to work
- **Clarity**: Clear separation between field type templates and field-specific customizations

#### Metadata Column Normalization

**Purpose**: Automatically normalize metadata column names and derive missing fields to ensure consistent document metadata across different data sources.

**Column Name Aliases**:

The system automatically maps common column name variations to standard names:

| Target Field | Source Aliases                          | Description          |
| ------------ | --------------------------------------- | -------------------- |
| `source`     | `source`, `path`                        | Document source path |
| `page_count` | `page_count`, `pages_processed`         | Number of pages      |
| `mimetype`   | `mimetype`, `mime_type`, `content_type` | MIME type            |

**Field Derivation**:

Missing metadata fields are automatically derived when possible:

- **extension**: Derived from `name` or `source` filename if missing
- **mimetype**: Derived from `extension` using standard MIME type mappings

**Predefined Metadata Fields**:

The following fields are automatically collected into a `metadata` object:

- `name`: Document filename
- `size`: File size in bytes
- `created_time`: Creation timestamp
- `modified_time`: Modification timestamp
- `source`: Document source path
- `mimetype`: MIME type
- `extension`: File extension
- `page_count`: Number of pages

**Example Transformation**:

```python
# Input row data
{
  "path": "/docs/report.pdf",
  "name": "report.pdf",
  "pages_processed": 10,
  "content": "..."
}

# Automatically normalized to
{
  "content": "...",
  "metadata": {
    "source": "/docs/report.pdf",
    "name": "report.pdf",
    "page_count": 10,
    "extension": "pdf",
    "mimetype": "application/pdf"
  }
}
```

#### Schema Validation

The system performs comprehensive validation of schema templates:

1. **Structure Validation**: Ensures required schema components are present
2. **Vector Field Validation**: Validates KNN vector configuration
3. **Parameter Range Validation**: Checks engine parameters are within valid ranges
4. **Analyzer Validation**: Validates custom analyzer configurations

**Validation Example**:

```python
# Invalid schema - missing required fields
{
  "settings": {},
  "field_types": {}
}
# Error: Schema missing required 'schema_name' field

# Invalid vector configuration
{
  "field_types": {
    "vector": {
      "type": "knn_vector",
      "dimension": -1  # Invalid dimension
    }
  }
}
# Error: Vector dimension must be positive
```

#### Implementation Architecture

```mermaid
graph TB
    subgraph "VectorDBOperator"
        VDB[VectorDBOperator]
    end

    subgraph "OpenSearch Adapter"
        OSA[OpenSearchAdapter]
        IM[IndexManager]
        BP[BatchProcessor]
    end

    subgraph "Schema Management"
        ST[Schema Templates]
        PH[Placeholder Replacement]
        VAL[Schema Validation]
    end

    subgraph "Metadata Processing"
        NORM[Column Normalization]
        DERIV[Field Derivation]
        AGG[Metadata Aggregation]
    end

    VDB --> OSA
    OSA --> IM
    OSA --> BP
    IM --> ST
    ST --> PH
    PH --> VAL
    BP --> NORM
    NORM --> DERIV
    DERIV --> AGG

    style VDB fill:#ffe1e1
    style IM fill:#e1ffe1
    style BP fill:#e1ffe1
    style ST fill:#fff4e1
    style NORM fill:#e1f5ff
```

**Key Components**:

- **OpenSearchIndexManager**: Handles schema template loading, placeholder replacement, and validation
- **OpenSearchBatchProcessor**: Handles metadata normalization, field derivation, and aggregation
- **Schema Templates**: JSON files defining reusable index configurations
- **Validation System**: Ensures schema correctness before index creation

### 5. Milvus Integration Architecture

```mermaid
graph TB

    subgraph "Docling-pipelines Layer"
        VDB[VectorDBOperator]
    end

    subgraph "Adapter Layer (Hexagonal)"
        PORT[VectorDB Port<br/>Interface]
        MA[Milvus Adapter]
    end

    subgraph "Milvus Service"
        MS[Milvus Server<br/>localhost:19530]
        COLL[Collections]
        IDX1[HNSW Index]
        IDX2[IVF_FLAT Index]
        IDX3[FLAT Index]
    end

    VDB --> PORT
    PORT --> MA
    MA --> MS
    MS --> COLL
    COLL --> IDX1
    COLL --> IDX2
    COLL --> IDX3

    style VDB fill:#ffe1e1
    style PORT fill:#fff4e1
    style MA fill:#e1ffe1
    style MS fill:#e1f5ff
```

**Hexagonal Architecture Benefits:**

1. **Decoupling**: VectorDBOperator independent of Milvus specifics
2. **Testability**: Easy to mock adapters for testing
3. **Extensibility**: Add new vector DB adapters without changing operator
4. **Flexibility**: Switch vector databases via configuration

**Supported Index Types:**
- **Dense Vectors**: HNSW, IVF_FLAT, IVF_SQ8, IVF_PQ, FLAT, DISKANN, AUTOINDEX
- **Sparse Vectors**: SPARSE_INVERTED_INDEX, SPARSE_WAND

**Supported Metric Types:**
- **Dense Vectors**: L2 (Euclidean), IP (Inner Product), COSINE (Cosine similarity)
- **Sparse Vectors**: BM25 (required for sparse mode)

**Vector Modes:**
- **Dense Only** (default): Stores only dense embeddings from embeddings operator
- **Sparse + Dense**: Dual storage mode with BM25 function generating sparse vectors from content
  - Requires `add_sparse_vector: true` and `metric_type: "BM25"`
  - Still requires embeddings operator in pipeline
  - Stores both dense embeddings and BM25-generated sparse vectors

**Example Configuration (Dense Vectors):**
```json
{
  "type": "vectordb",
  "name": "milvus_dense_store",
  "config": {
    "provider": "milvus",
    "index_name": "my_collection",
    "create_index": true,
    "add_sparse_vector": false,
    "provider_config": {
      "auth_type": "standalone",
      "host": "localhost",
      "port": 19530,
      "uri": null,
      "token": null,
      "username": "root",
      "password": "<your-milvus-password>"
      "database": "default",
      "secure": false,
      "index_type": "HNSW",
      "metric_type": "L2",
      "index_parameters": {
        "M": 16,
        "efConstruction": 256
      },
      "batch_size": 100,
      "primary_key_field": "pk"
    }
  }
}
```

**Note:** Vector dimension is auto-detected from `embeddings` column data. Milvus currently supports single vector column (multi-model support planned for future update).

**Example Configuration (Sparse Vectors):**
```json
{
  "type": "vectordb",
  "name": "milvus_sparse_store",
  "config": {
    "provider": "milvus",
    "index_name": "documents_sparse",
    "add_sparse_vector": true,
    "provider_config": {
      "auth_type": "standalone",
      "host": "localhost",
      "port": 19530,
      "username": "root",
      "password": "<your-milvus-password>"
      "index_type": "SPARSE_INVERTED_INDEX",
      "metric_type": "BM25",
      "primary_key_field": "pk"
    }
  }
}
```

**Authentication Types:**
- `standalone`: Local Milvus with optional username/password
- `grpc`: IBM wx.data with gRPC (username with `ibmlhapikey_` prefix, password is API key)
- `uri`: Pre-constructed URI with embedded API key
- `token`: IAM token-based authentication

**Deployment Support:**
- **Standalone Milvus**: Single-node deployment for development and testing
- **wx.data**: IBM watsonx.data integration for enterprise deployments with multiple auth options

### 6. Embeddings Operator Integration Architecture

The Embeddings Operator uses a unified hexagonal architecture with centralized LLM adapters, supporting three primary providers:

**Supported Providers:**
- **LiteLLM** - Unified API for 100+ providers (OpenAI, Azure, Cohere, AWS, Ollama, HuggingFace API, etc.)
- **Watsonx** - IBM watsonx.ai cloud service with IAM authentication
- **HuggingFace** - Native local or API-based inference with sentence-transformers models

**Architecture Pattern:**

```mermaid
graph TB
    subgraph "Core Layer"
        EMB[EmbeddingsOperator]
    end

    subgraph "Adapter Factory"
        FAC[LLMAdapterFactory]
    end

    subgraph "Unified Adapter Layer"
        LLA[LiteLLMAdapter]
        WXA[WatsonxAdapter]
        HFA[HuggingFaceAdapter]
    end

    subgraph "Port Interface"
        PORT[LLMEmbeddingPort]
    end

    subgraph "Client Layer"
        LLC[LiteLLMClient]
        WRC[WatsonxRestClient]
        HFC[HuggingFaceLLMClient]
    end

    subgraph "External Services"
        LLS[LiteLLM Providers:<br/>OpenAI, Azure, Cohere,<br/>Ollama, HuggingFace API, etc.]
        WXS[Watsonx.ai API]
        HFS[HuggingFace:<br/>Local Models or API]
    end

    EMB --> FAC
    FAC --> PORT
    PORT --> LLA
    PORT --> WXA
    PORT --> HFA

    LLA --> LLC --> LLS
    WXA --> WRC --> WXS
    HFA --> HFC --> HFS
```

**Configuration Examples:**

LiteLLM with OpenAI:
```json
{
  "provider": "litellm",
  "provider_config": {
    "model_id": "openai/text-embedding-3-small",
    "api_key": "${OPENAI_API_KEY}"
  },
  "embeddings_column": "embeddings"
}
```

LiteLLM with Ollama (via openai/ prefix):
```json
{
  "provider": "litellm",
  "provider_config": {
    "model_id": "openai/nomic-embed-text",
    "api_base": "http://localhost:11434"
  },
  "embeddings_column": "embeddings"
}
```

LiteLLM with HuggingFace API (via huggingface/ prefix):
```json
{
  "provider": "litellm",
  "provider_config": {
    "model_id": "huggingface/sentence-transformers/all-MiniLM-L6-v2",
    "api_key": "${HUGGINGFACE_API_KEY}"
  },
  "embeddings_column": "embeddings"
}
```

Native HuggingFace (local inference):
```json
{
  "provider": "huggingface",
  "model_id": "sentence-transformers/all-MiniLM-L6-v2",
  "embeddings_column": "embeddings",
  "provider_config": {
    "use_local": true,
    "device": "cpu",
    "batch_size": 16
  }
}
```

Watsonx (IBM Cloud):
```json
{
  "provider": "watsonx",
  "provider_config": {
    "model_id": "ibm/slate-125m-english-rtrvr",
    "api_key": "${WATSONX_API_KEY}",
    "api_base": "${WATSONX_API_BASE}",
    "container_id": "${WATSONX_PROJECT_ID}",
    "container_kind": "project"
  },
  "embeddings_column": "embeddings"
}
```

**Key Features:**
- Unified hexagonal architecture with centralized LLMAdapterFactory
- Consistent interface across all LLM-based operators (embeddings, classification, PII/HAP)
- LiteLLM provides access to 100+ providers through a single interface
- Native HuggingFace support for local model inference (no API costs, offline capable)
- Automatic retry logic and error handling
- Batch processing support with keyword arguments
- Provider-specific optimizations

### 7. Extract Operator Hexagonal Architecture

The ExtractOperator uses hexagonal architecture (ports and adapters pattern) to support multiple extraction strategies with clear separation of concerns.

```mermaid
graph TB
    subgraph "Operator Layer"
        EXT[ExtractOperator<br/>Orchestrator]
    end

    subgraph "Domain Layer"
        TES[TextExtractionService]
        EES[EntityExtractionService]
        MODELS[Domain Models<br/>TextExtractionMode<br/>EntityExtractionMode<br/>ExtractionRequest/Result]
    end

    subgraph "Port Layer (Interfaces)"
        TEP[TextExtractionPort]
        EEP[EntityExtractionPort]
    end

    subgraph "Adapter Layer (Implementations)"
        DA[DoclingAdapter<br/>docling_library provider]
        DSA[DoclingServeAdapter<br/>docling_serve provider]
        LEA[LLMEntityAdapter<br/>litellm/watsonx providers]
        DEA[DoclingEntityAdapter<br/>docling provider]
    end

    subgraph "Factory Layer"
        TEF[TextExtractionAdapterFactory]
        EEF[EntityExtractionAdapterFactory]
    end

    EXT --> TES
    EXT --> EES
    TES --> TEP
    EES --> EEP
    TEP -.implements.- DA
    TEP -.implements.- DSA
    EEP -.implements.- LEA
    EEP -.implements.- DEA
    TEF --> DA
    TEF --> DSA
    EEF --> LEA
    EEF --> DEA

    style EXT fill:#ffe1e1
    style TES fill:#fff4e1
    style EES fill:#fff4e1
    style TEP fill:#e1f5ff
    style EEP fill:#e1f5ff
    style DA fill:#e1ffe1
    style DSA fill:#e1ffe1
    style LEA fill:#e1ffe1
    style DEA fill:#e1ffe1
```

**Architecture Components:**

1. **Domain Layer**:
   - `EntityExtractionService`: Core business logic for entity extraction (prompt building, schema validation, response parsing)
   - Domain models define extraction providers, requests, and results

2. **Port Layer** (Interfaces):
   - `TextExtractionPort`: Interface for text extraction strategies
   - `EntityExtractionPort`: Interface for entity extraction strategies

3. **Adapter Layer** (Implementations):
   - **Text Extraction Adapters**:
     - `DoclingAdapter`: Local extraction using Docling library (supports VLM and ASR pipelines)
     - `DoclingServeAdapter`: Remote extraction via Docling Serve API (supports OCR)
   - **Entity Extraction Adapters**:
     - `LLMEntityAdapter`: Unified adapter for LiteLLM and WatsonX (uses shared LLM infrastructure)
     - `DoclingEntityAdapter`: Template-based extraction using Docling

4. **Factory Layer**:
   - `TextExtractionAdapterFactory`: Creates text extraction adapters based on provider
   - `EntityExtractionAdapterFactory`: Creates entity extraction adapters based on provider

**Key Benefits:**

- **Separation of Concerns**: Clear boundaries between business logic, interfaces, and implementations
- **Extensibility**: Easy to add new extraction strategies by implementing ports
- **Testability**: Each layer can be tested independently with mocks
- **Flexibility**: Text and entity extraction providers can be combined independently
- **Unified LLM Support**: Both LiteLLM and WatsonX use the same adapter for consistent behavior

**Extraction Providers:**

**Text Extraction:**
- `docling_library`: Local extraction with optional VLM (Vision-Language Model) and ASR (Automatic Speech Recognition)
- `docling_serve`: Remote extraction via Docling Serve API with OCR support

**Entity Extraction:**
- `litellm`: Multi-provider LLM extraction (OpenAI, Anthropic, Cohere, Ollama via openai/ prefix, etc.). **Note:** `model_id` must include provider prefix (e.g., `openai/llama3.2`, `anthropic/claude-3-opus`)
- `watsonx`: IBM WatsonX.ai extraction (uses same LLMEntityAdapter as litellm)
- `docling`: Template-based extraction using Docling templates
- `none`: No entity extraction (default)

**Example Configuration:**

```json
{
  "type": "extract_operator",
  "name": "extract_with_docling",
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content",
      "provider_config": {
      }
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
```

### 8. Docling Integration Architecture

```mermaid
graph TB

    subgraph "Docling-pipelines Layer"
        EXT[ExtractOperator]
    end

    subgraph "Client Layer"
        DC[DoclingServeClient]
        RC[RestClient]
    end

    subgraph "Docling Service"
        DS[Docling Server<br/>localhost:5000]
        PDF[PDF Parser]
        DOCX[DOCX Parser]
        TABLE[Table Extractor]
    end

    EXT --> DC
    DC --> RC
    RC --> DS
    DS --> PDF
    DS --> DOCX
    DS --> TABLE

    style EXT fill:#ffe1e1
    style DC fill:#fff4e1
    style DS fill:#e1f5ff
```

**Integration Features:**

1. **Document Parsing**: Extract text and structure from PDFs, DOCX
2. **Table Extraction**: Identify and extract tables with structure
3. **Metadata Extraction**: Document properties, page count, etc.
4. **Batch Processing**: Process multiple documents efficiently

**Supported Providers:**

- **Docling Library (Local)**: Local document processing and chunking using the Docling library
  - Used by ExtractOperator with `text_extraction.provider: "docling_library"` for document parsing
  - Used by Chunker operator with `provider: "docling_library"` for local Hybrid chunking
- **Docling-serve (Remote)**: Remote extraction and chunking via docling-serve API
  - Used by ExtractOperator with `text_extraction.provider: "docling_serve"` for distributed extraction
  - Used by Chunker operator with `provider: "docling_serve"` for distributed Hybrid chunking
  - Enables offloading computation to dedicated service
  - Only supports Hybrid chunking strategy for Chunker

### 8. DocumentClassifier Pattern

The DocumentClassifier operator classifies documents into predefined categories using Large Language Models. It uses a simplified service-based architecture that leverages the shared LLM adapter infrastructure for multi-provider support.

**Typical Workflow Position:**

```mermaid
graph LR
    A[Ingest] --> B[DocumentClassifier]
    B --> C[Extract]
    C --> D[Chunk]
    D --> E[Embed]
    E --> F[VectorDB]

    style A fill:#e1f5ff
    style B fill:#e6ffe6
    style C fill:#ffe1f5
    style D fill:#f5ffe1
    style E fill:#fff5e1
    style F fill:#e1fff5
```

**Simplified Architecture:**

```
┌─────────────────────────────────────────────────────────────┐
│                   DocumentClassifierOperator                │
│                     (Main Operator)                         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  ClassificationService                      │
│              (Business Logic Layer)                         │
│  ┌─────────────────────────────────────────────────-─────┐  │
│  │  Domain Models:                                       │  │
│  │  - ClassificationRequest                              │  │
│  │  - ClassificationResponse                             │  │
│  │  - build_classification_prompt()                      │  │
│  └───────────────────────────────────────────────-───────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Shared LLM Adapter Infrastructure              │
│                  (LLMAdapterFactory)                        │
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   LiteLLM    │  │  Watsonx.ai  │  │ HuggingFace  │
│   Client     │  │   Client     │  │   Client     │
└──────────────┘  └──────────────┘  └──────────────┘
```

**Classification Features:**

1. **LLM-Based Classification**: Uses Large Language Models for intelligent document classification
2. **Multi-Provider Support**: LiteLLM (100+ providers) and IBM watsonx.ai via shared LLM infrastructure
3. **Simplified Architecture**: Direct service-based design without port/adapter overhead
4. **Confidence Scoring**: 1-10 scale confidence scores for each classification
5. **Reasoning Output**: Optional explanations for classification decisions
6. **Shared Infrastructure**: Leverages common LLM adapter factory for consistency

**Supported Providers:**

- **LiteLLM**: Unified interface for 100+ providers (OpenAI, Anthropic, Azure, AWS Bedrock, Google, etc.)
  - Use with Ollama via OpenAI-compatible API: `provider='litellm'`, `api_base='http://localhost:11434/v1'`
- **Watsonx**: IBM watsonx.ai enterprise LLM platform

**Example Configuration:**

```json
{
  "operator_type": "DocumentClassifier",
  "operator_params": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/gpt-4o-mini",
      "api_key": "${OPENAI_API_KEY}"
    },
    "document_types": {
      "invoice": "Business invoice with line items and totals",
      "contract": "Legal contract or agreement",
      "receipt": "Payment receipt or confirmation",
      "report": "Business or technical report"
    },
    "confidence_threshold": 7.0,
    "include_confidence": true,
    "include_reasoning": true
  }
}
```

**Architecture Benefits:**

- **Testability**: Domain logic can be tested independently of LLM providers
- **Flexibility**: Easy to switch between providers or add new ones
- **Maintainability**: Clear separation of concerns
- **Extensibility**: New adapters can be added without modifying core logic

**Use Cases:**

- Route documents to specialized extraction pipelines based on type
- Filter documents by category before expensive processing
- Enrich metadata with document type information
- Enable type-specific chunking or embedding strategies

**Watsonx.ai Configuration Notes:**

- **Authentication**: IAM token-based authentication using `WATSONX_API_KEY`
- **Container Targeting**: Set `WATSONX_CONTAINER_ID` to a project ID or space ID
- **Optional Overrides**: Use `WATSONX_API_BASE_URL` and `WATSONX_CONTAINER_KIND` when the default region or container type is not appropriate
- **Non-Sensitive Settings**: Keep runtime options such as `api_base`, `container_kind`, and `timeout` in `provider_config`

### 9. External Service Pattern

**Common Pattern for All Integrations:**

```mermaid
sequenceDiagram
    participant OP as Operator
    participant CL as Client
    participant SVC as External Service

    OP->>CL: Initialize client
    CL->>SVC: Check availability
    SVC-->>CL: Service ready

    loop For each document
        OP->>CL: Process request
        CL->>SVC: API call
        alt Success
            SVC-->>CL: Return result
            CL-->>OP: Processed data
        else Failure
            SVC-->>CL: Error response
            CL->>CL: Retry logic
            alt Retry succeeds
                SVC-->>CL: Return result
                CL-->>OP: Processed data
            else Retry fails
                CL-->>OP: Error
                OP->>OP: Record failure
            end
        end
    end
```

**Client Responsibilities:**

1. Connection management
2. Request/response handling
3. Retry logic with exponential backoff
4. Error handling and logging
5. Timeout management

### 10. PIIAndHAPAnnotator Hexagonal Architecture Pattern

The PIIAndHAPAnnotator operator detects Personally Identifiable Information (PII) and Hate, Abuse, and Profanity (HAP) content using a decorator-based adapter registry. Each provider adapter self-registers with `PIIAndHAPDetectionFactory` and encapsulates its own detection path behind the unified `PIIAndHAPDetectionPort` interface.

```mermaid
graph TB

    subgraph "Docling-pipelines Layer"
        PIIHAP[PIIAndHAPAnnotator]
        FACTORY[PIIAndHAPDetectionFactory]
    end

    subgraph "Adapter Layer"
        PORT[PIIAndHAPDetectionPort]
        SERVICE[PIIHAPService<br/>thin wrapper]
        WATSONXADAPTER[WatsonxPIIAndHAPAdapter<br/>wraps TextDetectionPort]
        LITELLMADAPTER[LiteLLMPIIAndHAPAdapter<br/>wraps LLMInferencePort]
    end

    subgraph "External Services"
        LITELLMAPI[LiteLLM / OpenAI-compatible APIs<br/>100+ Providers]
        WATSONXAPI[WatsonX.ai /ml/v1/text/detection<br/>IBM Cloud]
    end

    PIIHAP --> FACTORY
    FACTORY --> PORT
    PORT --> WATSONXADAPTER
    PORT --> LITELLMADAPTER
    PORT --> SERVICE

    LITELLMADAPTER --> LITELLMAPI
    WATSONXADAPTER --> WATSONXAPI

    style PIIHAP fill:#ffe1e1
    style FACTORY fill:#ffe1e1
    style SERVICE fill:#fff4e1
    style PORT fill:#fff4e1
    style WATSONXADAPTER fill:#e1ffe1
    style LITELLMADAPTER fill:#e1ffe1
```

**Supported Providers:**

1. **WatsonX.ai**: IBM's enterprise AI platform
   - IAM-based authentication
   - Enterprise-grade SLAs
   - Compliance certifications
   - Managed infrastructure

2. **LiteLLM**: Multi-provider unified interface
   - 100+ LLM providers supported
   - OpenAI (gpt-4, gpt-3.5-turbo)
   - Anthropic (claude-3-opus, claude-3-sonnet)
   - Azure OpenAI, Cohere, AWS Bedrock, Google Vertex AI
   - Easy provider switching

**Configuration Examples:**

**WatsonX.ai (Enterprise):**

```json
{
  "type": "pii_and_hap",
  "name": "pii_hap_watsonx",
  "config": {
    "provider": "watsonx",
    "provider_config": {
      "model_id": "ibm/granite-13b-chat-v2",
      "api_key": "your-ibm-cloud-api-key",  # pragma: allowlist secret
      "url": "https://us-south.ml.cloud.ibm.com",
      "container_id": "your-project-id",
      "container_kind": "project",
      "timeout": 300
    }
  }
}
```

**LiteLLM (Multi-Provider):**

```json
{
  "type": "pii_and_hap",
  "name": "pii_hap_litellm",
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/gpt-4",
      "api_key": "sk-..."  # pragma: allowlist secret
    }
  }
}
```

**Key Features:**

1. **Detection Types**:
   - **PII**: Email, phone, SSN, credit cards, addresses, names, DOB, medical records
   - **HAP**: Hate speech, abuse, profanity, discrimination, threats, harassment

2. **Output Format**:
   - Structured JSON with detection type, score, location (start/end), and matched text
   - Confidence scores for each detection
   - Compatible with downstream redaction operators

3. **Provider Flexibility**:
   - Switch providers without code changes
   - Configuration-driven provider selection
   - Ollama can be accessed through LiteLLM via an OpenAI-compatible `api_base`
   - Production deployment with WatsonX or LiteLLM

4. **Extensibility**:
   - Add a new provider with a single file: create the adapter, decorate with `@register_pii_and_hap_detection_adapter`, and it is automatically discoverable
   - Each adapter fully encapsulates its own detection path — no changes to `PIIHAPService` or the operator required

**Use Cases:**

1. **Compliance Scanning**: Detect PII in documents for GDPR/CCPA compliance
2. **Content Moderation**: Identify HAP content in user-generated content
3. **Data Loss Prevention**: Prevent sensitive information leakage
4. **Document Sanitization**: Prepare documents for public release
5. **Risk Assessment**: Evaluate content risk before processing
6. **Audit Trail**: Track PII/HAP detections for compliance reporting

**Integration with Other Operators:**

```mermaid
graph LR
    A[IngestSource] --> B[ExtractOperator]
    B --> C[PIIAndHAPAnnotator]
    C --> D[Redaction]
    D --> E[Chunker]
    E --> F[EmbeddingsOperator]
    F --> G[VectorDBOperator]

    style A fill:#e1f5ff
    style B fill:#ffe1f5
    style C fill:#f5ffe1
    style D fill:#fff5e1
    style E fill:#e1fff5
    style F fill:#ffe1e1
    style G fill:#e1ffe1
```

**Typical Pipeline:**

1. **IngestSource**: Load documents from storage
2. **ExtractOperator**: Extract text content
3. **PIIAndHAPAnnotator**: Detect sensitive content
4. **Redaction**: Mask or remove detected PII/HAP
5. **Chunker**: Split sanitized documents into chunks
6. **EmbeddingsOperator**: Generate vector embeddings
7. **VectorDBOperator**: Store embeddings in vector database

See [PII and HAP Operator Documentation](docs/operators/quality/pii_and_hap_readme.md) for detailed usage guide.

---

### 7. IngestSource Multi-Provider Pattern

The IngestSource operator provides a unified interface for ingesting documents from multiple storage providers and data sources. It uses an adapter-based architecture for extensibility and supports both LangChain loaders and custom adapters.

```mermaid
graph TB

    subgraph "Docling-pipelines Layer"
        ISO[IngestSourceOperator]
    end

    subgraph "Adapter Architecture"
        SAF[SourceAdapterFactory]
        OBJA[Object Storage Adapter]
        IBMA[IBM COS Adapter]
        GDA[Google Drive Adapter]
        SPA[SharePoint Adapter]
        ODA[OneDrive Adapter]
        WPA[WebPageSourceAdapter]
        CUST[Custom Loaders]
    end

    subgraph "External Services"
        OBJ[Object Storage]
        IBM[IBM Cloud Object Storage]
        GD[Google Drive API]
        MS[Microsoft Graph API]
        CUSTOM[Custom Data Sources]
    end

    ISO --> SAF
    SAF --> OBJA
    SAF --> IBMA
    SAF --> GDA
    SAF --> SPA
    SAF --> ODA
    SAF --> WPA
    SAF --> CUST

    OBJA --> OBJ
    IBMA --> IBM
    GDA --> GD
    SPA --> MS
    ODA --> MS
    WPA --> CUSTOM
    CUST --> CUSTOM

    style ISO fill:#ffe1e1
    style SAF fill:#fff4e1
    style OBJA fill:#e1ffe1
    style IBMA fill:#e1ffe1
    style GDA fill:#e1ffe1
    style SPA fill:#e1ffe1
    style ODA fill:#e1ffe1
    style WPA fill:#e1ffe1
```

**Supported Providers:**

1. **Object Storage**: S3-compatible object storage
   - Bucket-based access
   - Prefix-based filtering
   - Binary content download via boto3

2. **IBM Cloud Object Storage (COS)**: IBM's S3-compatible storage
   - Custom endpoint configuration
   - S3-compatible API
   - Enterprise-grade storage

3. **Microsoft SharePoint**: Document management and collaboration
   - Microsoft Graph API integration
   - App-only (client credentials) authentication
   - Drive and folder-based access
   - Recursive directory traversal

4. **Microsoft OneDrive**: Personal and business cloud storage
   - Microsoft Graph API integration
   - Same authentication as SharePoint
   - Personal and shared drives support

5. **Google Drive**: Google's cloud storage service
   - OAuth2 authentication
   - Service account support
   - Folder hierarchy navigation
   - Shared drive access

6. **Web Pages**: Recursive website and documentation crawling
   - Backed by LangChain `RecursiveUrlLoader`
   - Multi-URL crawl entry points
   - Domain-bound crawling with optional external link following
   - URL path exclusion patterns and configurable request timeouts

7. **Custom Loaders**: Extensible loader framework
   - Dynamic loader import
   - LangChain-compatible interface
   - Provider-specific implementations

**Architecture Features:**

1. **Adapter Pattern**: Decouples operator from provider-specific implementations
2. **Factory Pattern**: Automatic adapter selection based on provider name
3. **Async Support**: Efficient document fetching with async/await
4. **Binary Content Handling**: Pre-fetches binary content for downstream processing
5. **Incremental Updates**: Tracks processed documents to avoid re-ingestion
6. **Metadata Enrichment**: Extracts file metadata (size, modified time, mimetype)

**Configuration Examples:**

**Object Storage:**

```json
{
  "type": "ingest_source",
  "name": "ingest_s3",
  "config": {
    "provider": "s3",
    "provider_config": {
      "bucket": "my-documents",
      "prefix": "invoices/"
    },
    "credentials": {
      "access_key": "your-access-key",  # pragma: allowlist secret
      "secret_key": "your-secret-key"  # pragma: allowlist secret
    },
    "max_files": 100,
    "include_filter": ".pdf,.docx",
    "ignore_hidden_files": true
  }
}
```

**IBM Cloud Object Storage:**

```json
{
  "type": "ingest_source",
  "name": "ingest_ibm_cos",
  "config": {
    "provider": "ibm_cos",
    "provider_config": {
      "bucket": "enterprise-docs",
      "endpoint_url": "https://s3.us-south.cloud-object-storage.appdomain.cloud",
      "prefix": "contracts/"
    },
    "credentials": {
      "access_key": "your-access-key",  # pragma: allowlist secret
      "secret_key": "your-secret-key"  # pragma: allowlist secret
    },
    "max_files": 500
  }
}
```

**Microsoft SharePoint:**

```json
{
  "type": "ingest_source",
  "name": "ingest_sharepoint",
  "config": {
    "provider": "sharepoint",
    "provider_config": {
      "drive_id": "b!abc123...",
      "folder_path": "/Shared Documents/Projects",
      "recursive": true
    },
    "credentials": {
      "client_id": "your-app-client-id",
      "client_secret": "your-app-secret",  # pragma: allowlist secret
      "tenant_id": "your-tenant-id"
    },
    "include_filter": ".pdf,.docx,.xlsx",
    "max_files": 200
  }
}
```

**Microsoft OneDrive:**

```json
{
  "type": "ingest_source",
  "name": "ingest_onedrive",
  "config": {
    "provider": "onedrive",
    "provider_config": {
      "drive_id": "b!xyz789...",
      "folder_path": "/Documents/Reports",
      "recursive": false
    },
    "credentials": {
      "client_id": "your-app-client-id",
      "client_secret": "your-app-secret",  # pragma: allowlist secret
      "tenant_id": "your-tenant-id"
    },
    "exclude_filter": ".tmp,.bak"
  }
}
```

**Google Drive:**

```json
{
  "type": "ingest_source",
  "name": "ingest_google_drive",
  "config": {
    "provider": "google_drive",
    "provider_config": {
      "folder_id": "1a2b3c4d5e6f7g8h9i0j",
      "recursive": true
    },
    "credentials": {
      "service_account_key": "/path/to/service-account-key.json"
    },
    "max_files": 150
  }
}
```

**Web Pages:**
```json
{
  "type": "ingest_source",
  "name": "ingest_web",
  "config": {
    "provider": "web",
    "provider_config": {
      "urls": ["https://example.com", "https://www.iana.org/domains/reserved"],
      "max_depth": 2,
      "prevent_outside": true,
      "exclude_patterns": ["/admin", "/login", "/api"],
      "timeout": 30
    }
  }
}
```

**Key Features:**

1. **Authentication Methods**:
   - Access key credentials (object storage, IBM COS)
   - OAuth2 client credentials (SharePoint, OneDrive)
   - Service account keys (Google Drive)
   - No credentials required for public web crawling with the web adapter
   - Custom authentication for extensible loaders

2. **Filtering Capabilities**:
   - Extension-based include/exclude filters
   - Hidden file filtering (files starting with '.')
   - Prefix-based path filtering
   - Maximum file count limits

3. **Metadata Extraction**:
   - File name, size, and modified time
   - MIME type and file extension
   - Source URL and unique identifiers
   - Provider-specific metadata

4. **Binary Content Handling**:
   - Pre-fetches binary content for downstream operators
   - Efficient memory management
   - Fallback to text content when binary unavailable
   - Compatible with ExtractOperator and other extract operators

5. **Incremental Processing**:
   - Tracks previously processed documents
   - Skips unchanged files on subsequent runs
   - Force re-ingestion option available
   - Job-based tracking for multi-run workflows

**Use Cases:**

1. **Multi-Source Document Ingestion**: Ingest documents from multiple storage providers in a single pipeline
2. **Enterprise Content Migration**: Migrate documents from SharePoint/OneDrive to vector databases
3. **Compliance Document Processing**: Process regulatory documents from object storage or IBM COS with audit trails
4. **Knowledge Base Construction**: Build searchable knowledge bases from Google Drive folders or recursively crawled websites
5. **Documentation Site Ingestion**: Crawl public documentation portals and marketing sites with `RecursiveUrlLoader`
6. **Hybrid Workflows**: Combine on-premises, cloud storage, and web content sources
7. **Incremental Updates**: Efficiently process only new or modified documents

**Integration with Other Operators:**

```mermaid
graph LR
    A[IngestSource] --> B[ExtractOperator]
    B --> C[Chunker]
    C --> D[EmbeddingsOperator]
    D --> E[VectorDBOperator]

    style A fill:#e1f5ff
    style B fill:#ffe1f5
    style C fill:#f5ffe1
    style D fill:#fff5e1
    style E fill:#e1fff5
```

**Typical Pipeline:**

1. **IngestSource**: Load documents from cloud storage
2. **ExtractOperator**: Extract structured content from binary files
3. **Chunker**: Split documents into manageable chunks
4. **EmbeddingsOperator**: Generate vector embeddings
5. **VectorDBOperator**: Store in OpenSearch or other vector databases

---

### 8. Chunker Summarization Service Layer Pattern

The Chunker operator's summarization feature follows a service layer architecture pattern, separating business logic from orchestration and using hexagonal architecture for LLM provider flexibility.

#### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    ChunkerOperator                          │
│              (Orchestration Layer)                          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ uses
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              SummarizationService                           │
│              (Business Logic Layer)                         │
│  • Prompt engineering                                       │
│  • Response parsing                                         │
│  • Sliding window processing                                │
│  • Sentence splitting (NLTK)                                │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ depends on
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              LLMInferencePort                               │
│              (Interface/Port)                               │
│  • generate(prompt, **kwargs) -> str                        │
└────────────────────┬────────────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
         ▼                       ▼
┌──────────────────┐    ┌──────────────────┐
│ LiteLLMInference │    │ WatsonXInference │
│ Adapter          │    │ Adapter          │
│ (100+ providers) │    │ (IBM Watsonx.ai) │
└──────────────────┘    └──────────────────┘
```

#### Components

**1. ChunkerOperator** (`src/docpipe/core/operators/functional/chunker.py`)
- **Responsibility**: Orchestrates chunking workflow
- **Summarization Integration**:
  - Lazy initialization of `SummarizationService` during `transform()`
  - Delegates all summarization logic to service
  - Handles configuration and provider setup

**2. SummarizationService** (`src/docpipe/core/operators/functional/summarization_service.py`)
- **Responsibility**: Encapsulates summarization business logic
- **Key Methods**:
  - `generate_summaries_for_chunks()`: Main entry point
  - `_generate_summaries()`: Batch processing with sliding windows
  - `_call_llm_for_summary()`: LLM interaction via port
  - `_generate_summary_prompt()`: Prompt engineering
  - `_parse_summaries()`: Response parsing and validation
  - `_sliding_text_chunks()`: Sliding window text processing
  - `_split_into_sentences()`: NLTK-based sentence tokenization
- **Configuration**: Accepts `max_input_tokens`, `overlap_ratio`, `summary_sentences`, `summary_max_words`

**3. LLMInferencePort** (`src/docpipe/core/ports/llm_inference_port.py`)
- **Responsibility**: Abstract interface for LLM providers
- **Method**: `generate(prompt: str, **kwargs) -> str`
- **Implementations**:
  - `LiteLLMInferenceAdapter`: Supports 100+ LLM providers (OpenAI, Anthropic, Google, AWS Bedrock, etc.)
  - `WatsonXInferenceAdapter`: IBM Watsonx.ai integration

#### Benefits

1. **Separation of Concerns**: Business logic isolated from operator orchestration
2. **Testability**: Service can be unit tested independently
3. **Maintainability**: Single responsibility for summarization logic
4. **Extensibility**: Easy to add new summarization strategies
5. **Reusability**: Service can be used by other operators
6. **Provider Flexibility**: Hexagonal architecture enables easy provider switching

#### Backward Compatibility

Legacy Ollama-only configurations are automatically converted to LiteLLM:
- Model IDs without `openai/` prefix are auto-prefixed
- Default `api_base` set to `http://localhost:11434/v1`
- Default `api_key` set to `ollama`

---

### 9. Document Set Hexagonal Architecture Pattern

The Document Set operator follows hexagonal architecture (ports and adapters pattern) for flexible storage backend support. It uses the storage layer interfaces (KeyValueStorage and TableStorage) for persistence.

#### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    DocumentSetOperator                      │
│         (Orchestrates via DocumentSetService)               │
└──────────────┬──────────────────────────────────────────────┘
               │
   ┌───────────┼───────────────────┐
   │           │                   │
   ▼           ▼                   ▼
┌──────────┐ ┌──────────────┐ ┌──────────────────┐
│ Metadata │ │ Data Store   │ │ Attachment Repo  │
│ Factory  │ │ Factory      │ │ Factory          │
└────┬─────┘ └──────┬───────┘ └────────┬─────────┘
     │               │                  │
     ▼               ▼                  ▼
┌──────────┐ ┌──────────────┐ ┌──────────────────┐
│ Metadata │ │ Data Store   │ │ Attachment Repo  │
│ Port     │ │ Port         │ │ Port             │
└────┬─────┘ └──────┬───────┘ └────────┬─────────┘
     │               │                  │
     ▼               ▼                  ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│ DuckDB       │ │ DuckDB Data  │ │ DuckDB           │
│ Metadata     │ │ Adapter      │ │ Attachment Repo  │
│ Adapter      │ └──────┬───────┘ └────────┬─────────┘
└──────┬───────┘        │                  │
       │                ▼                  ▼
       ▼         ┌──────────────┐ ┌──────────────────┐
┌──────────────┐ │ TableStorage │ │ KeyValueStorage  │
│ KeyValue     │ │ (Interface)  │ │ (Interface)      │
│ Storage      │ └──────────────┘ └──────────────────┘
│ (Interface)  │
└──────────────┘
```

#### Components

**1. Domain Layer** (`src/docpipe/core/assets/document_sets/domain/`)

- **Models** (`models/`): Pure Python domain entities
  - `DocumentSet`: Core entity for document collections
  - `DataCard`: Lineage and provenance tracking
- **Ports** (`ports/`): Abstract interfaces defining contracts
  - `AssetRepository[DocumentSet]`: Metadata CRUD operations
  - `DocumentSetStorage`: PyArrow table data operations
- **Types** (`types/`): TypedDict-based configuration types
  - `RepositoryConfig`: Metadata repository configuration
  - `DataStoreConfig`: Data store configuration
  - `HealthCheckResult`: Health check response structure

**1a. Common Domain Layer** (`src/docpipe/core/assets/common/`)

- **Models** (`common/domain/models/`):
  - `AttachmentRef`: Backend-agnostic storage coordinate. Holds a common envelope (`backend_type`, `name`) readable by the service and operator layers, plus a `details` dict opaque to everything except the adapter that created it.
- **Ports** (`common/domain/ports/`):
  - `AttachmentRepository`: Lifecycle management for `AttachmentRef` records — `save`, `get`, `delete`, `exists`.

**2. Application Layer** (`src/docpipe/core/assets/document_sets/application/`)

- **DocumentSetService** (`services/`): Business logic using port interfaces
- Orchestrates metadata and data operations
- Handles idempotent create-or-get behavior, data storage, preview, delete, and metric recomputation
- Independent of concrete storage implementation
- Injected with metadata repository and data store adapters

**3. Adapter Layer**

- **DuckDB document set adapters** (`document_sets/adapters/duckdb/`):
  - **DuckDBAssetRepository** (`common/adapters/repositories/`): Generic metadata persistence using `KeyValueStorage`; stores in the collection returned by `DocumentSet.get_collection_name()` (i.e. `document_sets`)
  - **DuckDBDocumentSetStorage**: Data persistence using `TableStorage`; handles schema creation, upsert, preview, deletion; returns `AttachmentRef` from `store()`
- **Common adapters** (`common/adapters/repositories/`):
  - **DuckDBAttachmentRepository**: Persists `AttachmentRef` records in the `document_set_attachments` KV collection. Registered via `@AttachmentRepositoryFactory.register(name="duckdb")` and self-wires via its `create(*, config)` classmethod.
- `DuckDBAssetRepository` is registered in `RepositoryFactory.get_available_repository_types()` as a dict entry (not a decorator). `DuckDBAttachmentRepository` uses the `@AttachmentRepositoryFactory.register()` decorator.

**4. Factory Layer**

- **RepositoryFactory** (`common/factories/`): Creates `AssetRepository[DocumentSet]` adapters; reads backend type from `assets_management.document_set_repository.type` in `docling-pipelines-config.yaml`
- **DataStoreFactory** (`document_sets/factories/`): Creates data store adapters
- **AttachmentRepositoryFactory** (`common/factories/`): Decorator-registry factory for attachment repository adapters; adapter is selected by name matching `document_set_repository.type` in `docling-pipelines-config.yaml`

#### Entry Points

Document sets can be managed through multiple entry points that share the same application and adapter layers:

1. **Pipeline execution** via `DocumentSetOperator`
   - Persists PyArrow tables during flow execution
   - Returns the original input table unchanged for downstream operators
   - Uses factory-created metadata and data adapters
   - Storage backend configured via `assets_management.document_set_repository.type` in `docling-pipelines-config.yaml`

2. **REST API** via `/api/v1/document-sets`
   - Creates, lists, retrieves, updates, deletes, and previews document sets
   - Uses `DocumentSetService` with factory-created adapters
   - Storage backend determined by API configuration

3. **Flow definitions**
   - Use the `document_set` operator in DAG JSON
   - Typical pattern: `Ingest → Extract → [Other Operators] → DocumentSetOperator`

#### Adding New Storage Backends

To add PostgreSQL, MongoDB, or other backends:

1. **Implement Storage Layer Interfaces** (if needed):

```python
# Implement KeyValueStorage for metadata
class PostgreSQLKeyValueStorage(KeyValueStorage):
    def save_record(self, *, collection: str, key: str, data: dict[str, Any]) -> None:
        pass
    # ... other methods

# Implement TableStorage for data
class PostgreSQLTableStorage(TableStorage):
    def create_table(self, *, table_name: str, schema: pa.Schema) -> None:
        pass
    # ... other methods
```

2. **Register Storage in Factory**:

```python
# In StorageFactory
@staticmethod
def create_key_value_storage(*, storage_type: str, **config: Any) -> KeyValueStorage:
    if storage_type == "postgresql":
        return PostgreSQLKeyValueStorage(**config)
    # ... existing types
```

3. **Implement Document Set Adapters**:

```python
@MetadataRepositoryFactory.register(name="postgresql", display_name="PostgreSQL")
class PostgreSQLMetadataRepository(DocumentSetMetadataRepository):
    def __init__(self, *, key_value_storage: KeyValueStorage):
        self.storage = key_value_storage
    # ... implement port methods

@DataStoreFactory.register(name="postgresql", display_name="PostgreSQL")
class PostgreSQLDataStore(DocumentSetDataStore):
    def __init__(self, *, table_storage: TableStorage):
        self.storage = table_storage
    # ... implement port methods
```

4. **Update Configuration** in `docling-pipelines-config.yaml`:

```yaml
assets_management:
  document_set_repository:
    type: postgresql
    config:
      database_path: ./data/document_sets/extracted_docs.duckdb
```

And the flow JSON:

```json
{
  "flow_name": "ingest-extract-documentset",
  "flow": [
    {
      "type": "document_set",
      "name": "documents",
      "config": {
        "document_set_name": "documents_collection",
        "description": "Persistent storage of extracted document content with metadata tracking",
        "database_path": "./data/document_sets/extracted_docs.duckdb",
        "data_backend": "postgresql"
      }
    }
  ]
}
```

#### Benefits

- **Pluggable Storage**: Easy to swap storage backends via configuration
- **Testability**: Mock adapters can satisfy port contracts in unit tests
- **Maintainability**: Clear separation of domain, application, adapters, and storage layers
- **Type Safety**: TypedDict-based configuration and strong typing throughout
- **Performance**: Singleton pattern for storage instances, pass-through operator execution
- **Extensibility**: New adapters registered via decorators without changing business logic
- **Consistency**: Shared storage layer across flows and document sets

#### Usage Pattern

```json
{
  "flow_name": "ingest-extract-documentset",
  "flow": [
    {
      "type": "document_set",
      "name": "documents",
      "config": {
        "document_set_name": "documents_collection",
        "description": "Persistent storage of extracted document content with metadata tracking",
        "database_path": "./data/document_sets/extracted_docs.duckdb",
        "data_backend": "duckdb",
        "metadata": {
          "pipeline_version": "1.0",
          "extraction_method": "docling",
          "created_by": "docpipe_pipeline",
          "purpose": "demonstration_flow"
        }
      }
    }
  ]
}
```

#### Data Flow

```
Ingest → Extract → [Other Operators] → DocumentSetOperator → [Downstream Operators]
                                              │
                                              ├─> MetadataRepositoryFactory   → DuckDB adapter → KeyValueStorage
                                              ├─> DataStoreFactory            → DuckDB adapter → TableStorage
                                              ├─> AttachmentRepositoryFactory → DuckDB adapter → KeyValueStorage
                                              └─> Original table (pass-through)
```

Storage coordinates (`AttachmentRef`) are persisted separately from the metadata record.
The metadata record and the attachment record have independent lifecycles — deletion removes
the backing data first, then the attachment record, then the metadata record last.

#### Storage Type Configuration

The metadata and attachment storage backend is configured via `docling-pipelines-config.yaml`:

```yaml
assets_management:
  document_set_repository:
    type: duckdb          # "duckdb" is the default
    config:
      database_path: data/duckdb/document_sets.duckdb
```

- **"duckdb"** (default): Metadata and attachment coordinates stored in DuckDB key-value tables alongside the data tables.

**Note**: The `data_backend` parameter in the operator's flow config controls where PyArrow table data is stored, and is independent of the metadata/attachment backend in the YAML.

### OpenLineage Hexagonal Architecture Pattern

Optional data lineage lives in `src/docpipe/core/lineage/` and follows the same ports-and-adapters layout as job management. It is off unless `DOCPIPE_LINEAGE_ENABLED=true`, and it needs the `lineage` extra.

```mermaid
graph TB
    subgraph "Docling-pipelines Layer"
        ORCH[Orchestrator]
        OBS[Execution Observer<br/>when to emit]
        SVC[LineageService<br/>what to emit]
    end

    subgraph "Adapter Layer (Hexagonal)"
        PORT[LineagePublisher Port<br/>Interface]
        OLA[OpenLineage Adapter]
        NOOP[NoOp Adapter<br/>fallback]
    end

    BE[Console / File / HTTP<br/>Marquez]

    ORCH --> OBS
    OBS --> SVC
    SVC --> PORT
    PORT --> OLA
    PORT --> NOOP
    OLA --> BE

    style ORCH fill:#ffe1e1
    style SVC fill:#fff4e1
    style OLA fill:#e1ffe1
    style BE fill:#e1f5ff
```

- **Wiring**: `OrchestratorFactory` calls `lineage_factory.create_lineage_observer()`, which returns `None` when lineage is disabled, so no observer is attached. If `openlineage-python` is missing or fails to initialise, the factory logs a warning and falls back to the no-op publisher.
- **Modes**: `flow` emits one job per run. `operator` also emits a child run per DAG node, linked to the flow run through the `parent` run facet.
- **Dataset identity**: `dataset_naming.get_dataset_info()` maps an adapter config to an OpenLineage `(namespace, name)`. Sources and sinks share the rules, and inter-operator tables use the `inmemory://` namespace, so a node's output matches the next node's input and the backend can draw the edge.
- **Credential safety**: the service strips credential keys from flow definitions and operator metadata before building any facet.
- **Failure isolation**: exceptions raised inside the observer are logged as warnings and the flow continues, unless `DOCPIPE_LINEAGE_STRICT=true`.
- **Distributed runs**: Prefect batch subflows rebuild the observer from environment variables, so the `DOCPIPE_LINEAGE_*` and `OPENLINEAGE__*` variables must be set in the worker environment.

See the [OpenLineage Integration Guide](docs/integrations/openlineage/OPENLINEAGE_GUIDE.md) for configuration, emitted events, custom facets, and adding a custom publisher.

## Deployment Patterns

Docling Pipelines supports multiple deployment patterns to accommodate different operational requirements, from local development to enterprise-scale production deployments.

### 1. Local Development (ThreadPoolAdapter)

**Use Case:** Development, testing, and small-scale processing

**Architecture:**

```mermaid
graph TB
    subgraph "Single Machine"
        FE[FlowExecutor]
        PE[PrefectEngine]
        TPA[ThreadPoolAdapter]
        TP[ThreadPool]
        OP1[Operator 1]
        OP2[Operator 2]
        OP3[Operator 3]
    end

    FE --> PE
    PE --> TPA
    TPA --> TP
    TP --> OP1
    TP --> OP2
    TP --> OP3

    style FE fill:#e1f5ff
    style TPA fill:#e1ffe1
    style TP fill:#fff4e1
```

**Configuration:**

```json
{
  "work_pool": {
    "enabled": false
  }
}
```

**Characteristics:**

- No external infrastructure required
- In-memory batch passing
- Fast startup and iteration
- Limited to single machine resources
- Ideal for I/O-bound operations

**Setup:**

```bash
# No additional setup required
docling-pipelines --flow-file my-flow.json
```

---

### 2. Production Single-Node (ProcessPoolAdapter)

**Use Case:** CPU-intensive workloads on a single powerful machine

**Architecture:**

```mermaid
graph TB
    subgraph "Single Machine"
        FE[FlowExecutor]
        PE[PrefectEngine]
        WPA[WorkPoolAdapter]
        PP[ProcessPool]

        subgraph "Worker Processes"
            P1[Process 1]
            P2[Process 2]
            P3[Process 3]
            P4[Process 4]
        end

        FS[Local Filesystem<br/>Batch Storage]
    end

    FE --> PE
    PE --> WPA
    WPA --> PP
    PP --> P1
    PP --> P2
    PP --> P3
    PP --> P4

    WPA -.->|Write Batches| FS
    P1 -.->|Read/Write| FS
    P2 -.->|Read/Write| FS
    P3 -.->|Read/Write| FS
    P4 -.->|Read/Write| FS

    style FE fill:#e1f5ff
    style WPA fill:#e1ffe1
    style PP fill:#fff4e1
    style FS fill:#ffe1e1
```

**Configuration:**

```json
{
  "work_pool": {
    "enabled": true,
    "type": "process",
    "name": "docpipe-process-pool",
    "max_workers": 4
  }
}
```

**Characteristics:**

- True parallel processing with separate Python processes
- Bypasses GIL limitations
- Disk-based batch storage
- Scales to machine CPU cores
- Better for CPU-bound operations

**Setup:**

```bash
# Process pool is managed automatically
docling-pipelines --flow-file my-flow.json
```

---

### 3. Production Distributed Docker (WorkPoolAdapter + Docker)

**Use Case:** Containerized deployments with horizontal scaling

**Architecture:**

```mermaid
graph TB
    subgraph "Control Node"
        FE[FlowExecutor]
        PE[PrefectEngine]
        WPA[WorkPoolAdapter]
        PS[Prefect Server]
    end

    subgraph "Shared Storage"
        VOL[Docker Volume<br/>Batch Storage]
    end

    subgraph "Worker Nodes"
        W1[Docker Worker 1]
        W2[Docker Worker 2]
        W3[Docker Worker 3]
    end

    FE --> PE
    PE --> WPA
    WPA --> PS
    PS --> W1
    PS --> W2
    PS --> W3

    WPA -.->|Write Batches| VOL
    W1 -.->|Read/Write| VOL
    W2 -.->|Read/Write| VOL
    W3 -.->|Read/Write| VOL

    style FE fill:#e1f5ff
    style WPA fill:#e1ffe1
    style PS fill:#fff4e1
    style VOL fill:#ffe1e1
```

**Configuration:**

```json
{
  "work_pool": {
    "enabled": true,
    "type": "docker",
    "name": "docpipe-docker-pool",
    "image": "docpipe:latest",
    "batch_storage": {
      "type": "local",
      "base_path": "/app/data/batches"
    }
  }
}
```

**Characteristics:**

- Containerized execution environment
- Horizontal scaling across multiple hosts
- Shared volume for batch storage
- Consistent runtime environment
- Easy deployment and rollback

**Setup:**

1. **Build Docker Image:**

```bash
docker build -t docpipe:latest -f docker/Dockerfile .
```

2. **Create Work Pool:**

```bash
prefect work-pool create docpipe-docker-pool --type docker
```

3. **Start Workers:**

```bash
# Using Docker Compose
docker-compose -f docker/docker-compose.worker.yml up -d

# Or manually
docker run -d \
  -v docpipe-batches:/app/data/batches \
  docpipe:latest \
  prefect worker start --pool docpipe-docker-pool
```

4. **Execute Flow:**

```bash
docling-pipelines --flow-file my-flow.json
```

**Docker Compose Example:**

```yaml
version: "3.8"
services:
  worker:
    image: docpipe:latest
    command: prefect worker start --pool docpipe-docker-pool
    volumes:
      - docpipe-batches:/app/data/batches
    environment:
      - PREFECT_API_URL=http://prefect-server:4200/api
    deploy:
      replicas: 3

volumes:
  docpipe-batches:
```

---

### Deployment Pattern Comparison

| Pattern          | Complexity | Scalability    | Cost    | Use Case               |
| ---------------- | ---------- | -------------- | ------- | ---------------------- |
| **Thread Pool**  | Low        | Single machine | Minimal | Development, testing   |
| **Process Pool** | Low        | Single machine | Low     | Single-node production |
| **Docker**       | Medium     | Horizontal     | Medium  | Multi-host deployments |

### Choosing a Deployment Pattern

**Use Thread Pool when:**

- Developing and testing flows
- Processing small datasets (<1000 documents)
- Running on a laptop or workstation
- I/O-bound operations dominate

**Use Process Pool when:**

- Running CPU-intensive operations
- Single powerful machine available
- Simple deployment preferred
- Dataset fits on one machine

**Use Docker when:**

- Need containerized deployments
- Scaling across multiple hosts
- Consistent runtime environment required
- Docker infrastructure already available

---

## Security Architecture

This section documents the security model of Docling-pipelines across its REST API, data pipeline, and external service integration layers.

### 1. REST API Authentication

The FastAPI-based REST API (`src/docpipe/api/`) supports two authentication paths that both produce a short-lived JWT and are enforced on every protected endpoint via the [`get_current_user`](src/docpipe/api/auth/dependencies.py) dependency.

```
                        ┌─────────────────────────────────┐
                        │         REST API Request         │
                        └──────────────┬──────────────────┘
                                       │
               ┌───────────────────────┼───────────────────────┐
               │                       │                       │
               ▼                       ▼                       ▼
    POST /auth/login        GET /auth/oauth2/authorize   Bearer <JWT>
    (LDAP credentials)      (OAuth2 / OIDC flow)         (subsequent calls)
               │                       │                       │
               ▼                       ▼                       │
    LDAPAuthenticator       OAuth2Provider                     │
    (bind + verify DN)      (code exchange                     │
               │             + ID-token validation)            │
               └───────────────────────┘                       │
                           │                                   │
                           ▼                                   ▼
                  create_access_token()              verify_token()
                  (HS256 JWT, 30 min TTL)            (HS256, username claim)
                           │                                   │
                           └─────────────────┬─────────────────┘
                                             ▼
                                    User object injected
                                    into route handler
```

#### LDAP Authentication (`src/docpipe/api/auth/ldap_auth.py`)

- **Standard LDAP/OpenLDAP**: service-account bind to locate the user DN, then re-binds as the user to verify credentials.
- **Active Directory**: authenticates directly with `username@domain` UPN format via `simple_bind_s`.
- **TLS**: optional StartTLS (`ldap_use_ssl: true`) upgrades the connection before any credential exchange.
- Configuration is loaded from environment variables via [`LDAPConfig`](src/docpipe/api/auth/ldap_auth.py) (see `.env.oauth2.example`).

| Config Variable | Description |
|---|---|
| `LDAP_SERVER` | LDAP server URL (e.g. `ldap://localhost:389`) |
| `LDAP_BASE_DN` | Base distinguished name |
| `LDAP_BIND_DN` | Service-account DN for user search |
| `LDAP_BIND_PASSWORD` | Service-account password |
| `LDAP_USE_SSL` | Enable StartTLS |
| `LDAP_USE_ACTIVE_DIRECTORY` | Enable AD-style UPN authentication |
| `LDAP_AD_DOMAIN` | Domain suffix for AD UPN |

#### OAuth2 / OIDC Authentication (`src/docpipe/api/auth/`)

The OAuth2 subsystem follows the Authorization Code flow with PKCE-style state validation for CSRF protection.

**Built-in providers:**

| Provider | Class | Discovery |
|---|---|---|
| Google | `GoogleOAuth2Provider` | `https://accounts.google.com/.well-known/openid-configuration` |
| Azure AD | `AzureADOAuth2Provider` | `https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration` |
| Generic OIDC | `GenericOIDCProvider` | Configurable (Okta, Auth0, Keycloak, GitLab, …) |

**Flow:**
1. `GET /auth/oauth2/authorize` — generates a cryptographically random `state` token (via `secrets.token_urlsafe(32)`) and redirects to the provider.
2. `GET /auth/oauth2/callback` — validates the returned `state`, exchanges the authorization code for tokens, and validates the `id_token` signature against the provider's JWKS.
3. A Docling Pipelines-signed HS256 JWT is issued and returned to the caller.

**ID token validation** (`OAuth2Provider.validate_id_token`):
- Fetches the provider's JWKS and matches the `kid` header.
- Verifies signature (RS256), audience, and issuer.

#### JWT Tokens (`src/docpipe/api/auth/jwt_handler.py`)

| Parameter | Default | Env variable |
|---|---|---|
| Algorithm | HS256 | — |
| Expiry | 30 minutes | `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` |
| Secret | — | `JWT_SECRET_KEY` (must be set in production) |

All tokens carry `username`, `email`, and `full_name` claims. Verification rejects tokens missing the `username` claim.

---

### 2. HTTP Security Headers

`SecurityHeadersMiddleware` (defined in [`src/docpipe/api/main.py`](src/docpipe/api/main.py)) adds the following headers to every response:

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `no-referrer` |
| `Content-Security-Policy` | `default-src 'self'`; scripts/styles limited to self + CDN |

CORS is configurable via the `CORS_ORIGINS` environment variable (comma-separated origins). The default restricts to `http://localhost:3000`.

---

### 3. Request Validation and DoS Protection

`PayloadValidationMiddleware` ([`src/docpipe/api/middleware/payload_validation.py`](src/docpipe/api/middleware/payload_validation.py)) rejects `POST`/`PUT`/`PATCH` requests whose `Content-Length` or streamed body exceeds **5 MB**, returning HTTP 413.

---

### 4. Document-Level Access Control (ACL)

When the REST API serves documents from OpenSearch, the [`ACLQueryBuilder`](src/docpipe/api/services/acl_query_builder.py) enforces row-level access by injecting the authenticated username into every query as a filter on the `allowed_users` field.

**Security model — fail-closed:**

| `allowed_users` field | Access |
|---|---|
| Field absent | Denied |
| Empty array | Denied |
| Contains authenticated username | Granted |

All search, single-document retrieval, and existence queries include the ACL filter as a mandatory `must` clause in the OpenSearch `bool` query, so no code path can accidentally omit the check.

---

### 5. Credential and Secret Management

All sensitive credentials are supplied at runtime via environment variables and are never committed to source control.

| Credential | Mechanism |
|---|---|
| JWT signing secret | `JWT_SECRET_KEY` env var |
| LDAP bind password | `LDAP_BIND_PASSWORD` env var |
| OAuth2 client secret | `OAUTH2_CLIENT_SECRET` env var |
| IBM Cloud / WatsonX API key | `WATSONX_API_KEY` env var |
| OpenAI / Hugging Face API keys | `OPENAI_API_KEY`, `HUGGINGFACE_API_KEY` env vars |
| OpenSearch credentials | `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD` env vars |
| Object storage keys (S3/COS) | `access_key`, `secret_key` in operator config |
| HashiCorp Vault AppRole credentials | `VAULT_ROLE_ID`, `VAULT_SECRET_ID` env vars (or `_FILE` variants for Docker/K8s) |

Configuration files support environment variable substitution (e.g. `${WATSONX_API_KEY}`) so flow definitions remain secret-free. The repository is protected by `detect-secrets` pre-commit hooks to prevent accidental secret commits.

#### HashiCorp Vault Integration

For deployments that centralise secrets in HashiCorp Vault, operator configs can reference secrets using the `vault://` URI scheme:

```json
"property_key": "vault://hashicorp/<path>#<key>"  // pragma: allowlist secret
```

The integration is enabled per-deployment in `docling-pipelines-config.yaml`:

```yaml
secrets:
  vault:
    enabled: true
    provider: hashicorp
```

Vault connection credentials are always read from environment variables — never from the config file:

| Variable | Description |
|---|---|
| `VAULT_ADDR` | Vault server URL (default: `http://127.0.0.1:8200`) |
| `VAULT_ROLE_ID` | AppRole role ID |
| `VAULT_SECRET_ID` | AppRole secret ID |
| `VAULT_MOUNT_POINT` | KV secrets engine mount (default: `secret`) |
| `VAULT_APPROLE_MOUNT` | AppRole auth mount (default: `approle`) |
| `VAULT_NAMESPACE` | Vault Enterprise namespace (optional) |
| `VAULT_CA_CERT` | Path to CA certificate for TLS (optional) |
| `VAULT_CLIENT_CERT` / `VAULT_CLIENT_KEY` | Client cert/key for mTLS (optional) |
| `VAULT_TLS_SKIP_VERIFY` | Skip TLS verification — development only (default: `false`) |

Docker and Kubernetes file-backed secrets are supported via the `_FILE` suffix convention (e.g. `VAULT_ROLE_ID_FILE=/run/secrets/vault_role_id`).

Secret resolution is transparent — values that do not start with `vault://` are passed to operators unchanged, so Vault can be adopted incrementally without modifying existing flows.

---

### 6. IAM Token Management (WatsonX / IBM Cloud)

The [`IAMTokenManager`](src/docpipe/utils/infrastructure/iam_token_manager.py) handles short-lived bearer tokens for IBM Cloud and MCSP environments:

- Tokens are cached per API key in an `LRUCache` with a 1-hour TTL.
- Tokens are refreshed **10 minutes before expiry**, preventing clock-skew failures.
- Cache keys are scoped to the API key, supporting multi-tenant deployments without token bleed.
- Environment is detected automatically from the WatsonX URL pattern.

---

### 7. PII Detection and Data Redaction

Docling-pipelines provides a dedicated pipeline stage for detecting and redacting sensitive data:

- **`PIIAndHAPAnnotator` operator**: detects PII (email, phone, SSN, credit cards, names, addresses, dates of birth, medical records) and HAP content using WatsonX or LiteLLM.
- **`Redaction` operator**: masks or removes spans annotated by the PII detector before data reaches downstream stages such as chunking, embedding, or vector storage.

This enables compliance patterns such as GDPR/CCPA scanning, data-loss prevention, and document sanitization. See [Integration Patterns — PIIAndHAPAnnotator](#10-piinandhapannotator-hexagonal-architecture-pattern) for the detailed architecture.

---

### 8. Security Layers Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                         REST API Layer                          │
│  CORS  │  SecurityHeaders  │  PayloadValidation  │  JWT Bearer  │
├─────────────────────────────────────────────────────────────────┤
│                      Authentication Layer                       │
│         LDAP / Active Directory   │   OAuth2 / OIDC             │
│            LDAPAuthenticator      │   OAuth2Provider            │
│                        JWT issuance (HS256)                     │
├─────────────────────────────────────────────────────────────────┤
│                    Authorization Layer                          │
│       ACLQueryBuilder — OpenSearch allowed_users filter         │
│            (fail-closed: deny if field absent or empty)         │
├─────────────────────────────────────────────────────────────────┤
│                     Data Privacy Layer                          │
│    PIIAndHAPAnnotator  →  Redaction  (pipeline operators)       │
├─────────────────────────────────────────────────────────────────┤
│               External Service Credential Layer                 │
│  IAMTokenManager (WatsonX)  │  API key env vars  │  TLS/LDAPS   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Design Decisions

### 1. Why PyArrow Tables?

**Decision:** Use PyArrow as the primary data interchange format.

**Rationale:**

| Aspect                 | Benefit                                                        |
| ---------------------- | -------------------------------------------------------------- |
| **Memory Efficiency**  | Columnar format reduces memory footprint by 50-70%             |
| **Performance**        | Zero-copy reads, fast serialization (10-100x faster than JSON) |
| **Interoperability**   | Works with Pandas, Polars, DuckDB, Spark                       |
| **Schema Enforcement** | Strong typing prevents data quality issues                     |
| **Scalability**        | Handles datasets from KB to TB efficiently                     |
| **Parquet Support**    | Native integration with Parquet file format                    |

### 2. Why Prefect for Orchestration?

**Decision:** Use Prefect as the workflow orchestration engine.

**Rationale:**

| Feature                | Benefit                                        |
| ---------------------- | ---------------------------------------------- |
| **DAG Support**        | Native directed acyclic graph execution        |
| **Parallel Execution** | Automatic parallelization of independent tasks |
| **Error Handling**     | Built-in retry logic and error recovery        |
| **Monitoring**         | Real-time execution monitoring and logging     |
| **Python-Native**      | Pure Python, no external DSL required          |
| **Local Execution**    | Runs locally without external infrastructure   |

### 3. Why Operator-Based Architecture?

**Decision:** Build the framework around composable operators.

**Rationale:**

| Principle           | Benefit                                         |
| ------------------- | ----------------------------------------------- |
| **Modularity**      | Each operator is self-contained and testable    |
| **Reusability**     | Operators can be reused across different flows  |
| **Extensibility**   | Easy to add new operators without changing core |
| **Composability**   | Complex pipelines built from simple operators   |
| **Maintainability** | Changes isolated to individual operators        |
| **Testability**     | Unit test operators independently               |

**Design Pattern:** Template Method + Strategy Pattern

### 4. Extensibility Considerations

**Design for Extension:**

1. **Abstract Base Classes**: Clear contracts for new operators
2. **Factory Pattern**: Centralized operator instantiation
3. **Configuration-Driven**: Operators configured via JSON
4. **Hexagonal Architecture**: External services via adapters
5. **Plugin Discovery**: Automatic operator registration

**Extension Points:**

```mermaid
graph TD
    EXT[Extension Points]
    EXT --> OP[New Operators]
    EXT --> ADAPT[New Adapters]
    EXT --> ORCH[Custom Orchestrators]
    EXT --> VAL[Custom Validators]

    OP --> IMPL1[Inherit AbstractOperator]
    OP --> IMPL2[Implement transform]
    OP --> IMPL3[Register in factory]

    ADAPT --> IMPL4[Implement adapter interface]
    ADAPT --> IMPL5[Register in VectorDBOperator]

    style EXT fill:#e1f5ff
    style OP fill:#ffe1e1
    style ADAPT fill:#fff4e1
```

**Example: Adding a New Operator**

```python
from core.operators.abstract_operator import AbstractOperator, OperatorCategory

class MyCustomOperator(AbstractOperator):
    short_name = "my_custom"
    category = OperatorCategory.Functional

    def __init__(self, config: dict):
        super().__init__(config)
        self.custom_param = config.get("custom_param")

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        # Implementation
        metadata = self.create_base_metadata(total_docs_count=len(table))
        # Process table
        return [output_table], metadata
    @staticmethod
    def get_required_features() -> list[str]:

        return ["doc_id", "content"]
```

### Schema Evolution

```mermaid
graph LR
    S1[Initial Schema] --> S2[After Extract]
    S2 --> S3[After Chunk]
    S3 --> S4[After Embed]

    S1 -.->|doc_id, doc_name,<br/>file_path| S1
    S2 -.->|+ content, tables,<br/>metadata| S2
    S3 -.->|+ chunks, chunk_ids| S3
    S4 -.->|+ embeddings| S4

    style S1 fill:#ffe1e1
    style S2 fill:#fff4e1
    style S3 fill:#e1ffe1
    style S4 fill:#e1f5ff
```

**Schema Transformation Example:**

**After Ingest:**

```
doc_id: string
doc_name: string
file_path: string
file_size: int64
```

**After Extract:**

```
doc_id: string
doc_name: string
file_path: string
file_size: int64
content: string          # NEW
tables: list<struct>     # NEW
metadata: struct         # NEW
```

**After Chunk:**

```
doc_id: string
doc_name: string
content: string
chunk_id: string         # NEW
chunk_text: string       # NEW
chunk_index: int32       # NEW
```

**After Embed:**

```
doc_id: string
doc_name: string
chunk_id: string
chunk_text: string
embeddings: list<float>  # NEW
```

---

**Why PyArrow?**

- **Memory Efficiency**: Columnar format with zero-copy reads
- **Interoperability**: Standard format across data tools (Pandas, Polars, DuckDB)
- **Performance**: Fast serialization/deserialization
- **Schema Enforcement**: Strong typing with schema validation
- **Scalability**: Handles large datasets efficiently
- **Parquet Integration**: Native support for Parquet file format

**Data Flow Pattern:**

```
Operator Input (PyArrow Table)
    → Processing Logic
    → Operator Output (PyArrow Table)
```

---

- Perform entity extraction, semantic chunking, and embedding generation at scale

## Repository Structure

```
docpipe/
├── src/docpipe_app/          # Main source code
│   ├── backend/                      # Backend components
│   │   ├── app/                      # Backend API application
│   │   │   ├── routes/               # API route handlers
│   │   │   │   ├── flows.py          # Flow management endpoints
│   │   │   │   └── job_runs.py       # Job run management endpoints
│   │   │   ├── dependencies.py       # Dependency injection providers
│   │   │   └── main.py               # FastAPI application
│   │   ├── cli/                      # CLI implementation
│   │   ├── common/                   # Shared utilities and models
│   │   │   ├── clients/              # LLM client abstractions
│   │   │   ├── constants/            # Constants and enums
│   │   │   ├── document_classes/     # 40+ document class schemas
│   │   │   ├── exceptions/           # Exception hierarchy with error codes
│   │   │   ├── models/               # Data models
│   │   │   └── util/                 # Utility functions
│   │   │       ├── core/             # Core utilities (strings, validation, etc.)
│   │   │       ├── data/             # Data handling utilities
│   │   │       ├── infrastructure/   # Infrastructure utilities
│   │   │       ├── job_tracker/      # Legacy job tracking (reference only)
│   │   │       ├── operators/        # Operator utilities
│   │   │       └── orchestration/    # Orchestration utilities
│   │   ├── core/                     # Core orchestration framework
│   │   │   ├── data_access/          # Data access abstractions
│   │   │   ├── job_management/       # Job statistics and management (hexagonal)
│   │   │   │   ├── domain/           # Domain models and ports
│   │   │   │   ├── application/      # Application services
│   │   │   │   └── adapters/         # Infrastructure adapters
│   │   │   ├── operators/            # Operator implementations
│   │   │   │   ├── extract/          # Extract operators
│   │   │   │   ├── functional/       # Functional operators
│   │   │   │   ├── ingest/           # Ingest operators
│   │   │   │   ├── quality/          # Quality/filtering operators
│   │   │   │   └── vectordb/         # Vector database operators
│   │   │   └── orchestrator/         # Orchestration components
│   │   │       ├── cmdline/          # Command-line executor
│   │   │       ├── prefect/          # Prefect orchestration module
│   │   │       │   ├── adapters/     # Batch execution adapters
│   │   │       │   ├── config/       # Work pool configuration
│   │   │       │   ├── domain/       # Domain models
│   │   │       │   └── ports/        # Batch execution port
│   │   │       └── python/           # Python orchestrator
│   │   └── models/                   # ML models (FastText, etc.)
│   └── ui/                           # User interface components
├── tests/                            # Test suites
│   ├── unit/                         # Unit tests
│   ├── integration/                  # Integration tests
│   └── fixtures/                     # Test fixtures
├── docs/                             # Documentation
├── examples/                         # Example flows and configurations
└── pyproject.toml                    # Project configuration
```

## Core Components

### 1. Core Utilities (`src/docpipe/utils/` and `src/docpipe/core/`)

#### Clients (`common/clients/`)

- **LLM Client Abstractions**: Base interfaces for LLM providers
- **Ollama Client**: Integration with Ollama for local LLM operations
- **LiteLLM Client**: Multi-provider LLM support
- **HuggingFace Client**: HuggingFace model integration
- **DoclingServeClient**: REST API client for Docling Serve document processing

#### Exceptions (`common/exceptions/`)

- **Structured Exception Hierarchy**: Comprehensive error handling
- **Error Codes**: Standardized error code system
- **Error Messages**: Centralized error message management

#### Document Classes (`common/document_classes/`)
#### Constants (`core/constants/`)

**File Extension Constants** ([`operator_constants.py`](src/docpipe/core/constants/operator_constants.py))

The `FileExtensions` class provides centralized file format constants used across all operators for consistent file type handling:

**Document Formats:**
- PDF: `.pdf`
- Microsoft Word: `.docx`
- Microsoft PowerPoint: `.pptx`
- Microsoft Excel: `.xlsx`

**Text Formats:**
- Markdown: `.md`
- Plain Text: `.txt`
- HTML: `.html`

**Image Formats:**
- PNG: `.png`
- JPEG: `.jpeg`, `.jpg`
- TIFF: `.tiff`, `.tif`
- BMP: `.bmp`
- WebP: `.webp`
- GIF: `.gif`
- JFIF: `.jfif`

**Audio Formats** (require ASR):
- WAV: `.wav`
- MP3: `.mp3`
- M4A: `.m4a`
- AAC: `.aac`
- OGG: `.ogg`
- FLAC: `.flac`

**Video Formats** (require ASR):
- MP4: `.mp4`
- AVI: `.avi`
- MOV: `.mov`

**Grouped Constants:**
- `BASE_EXTENSIONS`: Core supported formats (documents, text, images)
- `AUDIO_VIDEO_EXTENSIONS`: ASR-dependent formats (audio and video)
- `CLASSIFICATION_FILE_EXTENSIONS`: Document classification formats (BASE_EXTENSIONS excluding .txt and .md)

**Usage in Operators:**
- [`ExtractOperator`](src/docpipe/core/operators/extract/extract_operator.py): Uses `FileExtensions.EXT_TXT` for text file handling
- [`IngestSourceOperator`](src/docpipe/core/operators/ingest/ingest_source.py): Uses `FileExtensions.BASE_EXTENSIONS` for file filtering
- [`DocumentClassifier`](src/docpipe/core/operators/quality/classification/document_classifier.py): Uses `FileExtensions.CLASSIFICATION_FILE_EXTENSIONS` for validation
- [`OperatorUtils`](src/docpipe/core/operators/operator_utils.py): Uses centralized constants in `get_supported_file_extensions()`


### 5. Storage Layer (`src/docpipe/storage/`)

The storage layer provides a clean, interface-based abstraction for data persistence in docpipe. It follows a port-adapter pattern with two primary interfaces for different storage needs.

#### Storage Interfaces

**KeyValueStorage Interface** (`interfaces/key_value_storage.py`)

- Interface for storing JSON-serializable records in logical collections
- Used for asset metadata (flows, document set metadata)
- Operations: save_record, get_record, list_records, delete_record, collection_exists, record_exists
- Implementations:
  - **FileSystemStorage**: JSON files organized by collection directories
  - **DuckDBKeyValueStorage**: DuckDB tables with JSON columns

**TableStorage Interface** (`interfaces/table_storage.py`)

- Interface for PyArrow table storage with SQL query capabilities
- Used for document set data and structured data operations
- Operations: create_table, upsert_data, read_data, delete_table, table_exists, get_row_count, execute_query
- Implementations:
  - **DuckDBTableStorage**: DuckDB-based PyArrow table storage with schema evolution

#### Storage Factory

**StorageFactory** (`factory.py`)

- Factory pattern for creating storage instances
- Methods:
  - `create_key_value_storage(storage_type, **config)`: Creates KeyValueStorage instances
  - `create_table_storage(storage_type, **config)`: Creates TableStorage instances
- Supported types:
  - Key-value: "filesystem", "duckdb"
  - Table: "duckdb"
- Validates storage types and provides clear error messages

#### DuckDB Implementations

**DuckDBKeyValueStorage** (`duck_db/key_value_storage.py`)

- Stores records as JSON in DuckDB tables (one table per collection)
- Schema: `key TEXT PRIMARY KEY, data JSON`
- Singleton pattern per database path for connection reuse
- Features: JSON serialization, SQL-based filtering, atomic operations

**DuckDBTableStorage** (`duck_db/table_storage.py`)

- Stores PyArrow tables directly in DuckDB
- Features:
  - Schema evolution support (automatic column addition)
  - Atomic upsert operations with row count verification
  - SQL query execution with parameterization
  - Metrics computation (row counts, aggregations)
  - Connection pooling and singleton pattern

#### FileSystem Implementation

**FileSystemStorage** (`file_system/key_value_storage.py`)

- Stores records as JSON files in directory structure
- Directory layout: `base_dir/collection/key.json`
- Features: Atomic writes, file locking, directory creation
- Suitable for development and small-scale deployments

#### Storage Exceptions

- **StorageException**: Base exception for storage errors
- **StorageNotFoundError**: Record or table not found
- **StorageValidationError**: Invalid parameters or data
- **StorageConnectionError**: Database connection failures

### 6. Assets Management (`src/docpipe/core/assets/`)

The assets management layer provides hexagonal architecture implementations for managing data assets like flows and document sets. It follows clean architecture principles with clear separation between domain, application, and adapter layers.

#### Flows (`assets/flows/`)

Hexagonal architecture implementation for flow management:

**Domain Layer** (`domain/models/`):

- **Flow**: Core entity representing pipeline definitions
- **FlowMetadata**: Flow metadata and configuration
- **FlowRepository (Port)**: Interface for flow persistence

**Application Layer** (`application/services/`):

- **FlowService**: Business logic for flow operations
  - Flow creation, retrieval, updates, and deletion
  - Flow validation and configuration management

**Adapter Layer** (`adapters/repositories/`):

- **StorageFlowRepository**: Generic repository using KeyValueStorage interface
  - Works with any storage backend (DuckDB, filesystem)
  - Stores flows in 'flows' collection with flow_id as key
  - Exception wrapping with FlowNotFoundException, FlowStorageException

#### Document Sets (`assets/document_sets/`)

Hexagonal architecture implementation for document set management:

**Domain Layer** (`domain/models/`):

- **DocumentSet**: Core entity for named document collections
- **DataCard**: Lineage and provenance tracking

**Common Domain Layer** (`common/domain/`):

- **AttachmentRef**: Backend-agnostic storage coordinate for asset attachments
- **AttachmentRepository**: Port for attachment lifecycle management

**Domain Ports** (`domain/ports/`):

- **DocumentSetMetadataRepository**: Interface for metadata persistence
- **DocumentSetDataStore**: Interface for PyArrow table data operations

**Application Layer** (`application/services/`):

- **DocumentSetService**: Business logic orchestration
  - Idempotent create-or-get operations
  - Metrics computation and updates
  - Data storage coordination
  - Independent of concrete storage implementation

**Adapter Layer** (`adapters/`):

- **DuckDB Adapters** (`adapters/duckdb/`):
  - **DuckDBDocumentSetMetadataRepository**: Metadata persistence using KeyValueStorage
  - **DuckDBDocumentSetDataStore**: Data persistence using TableStorage
  - Registered via factory decorators for automatic discovery

**Factory Layer** (`factories/`):

- **MetadataRepositoryFactory**: Creates metadata repository adapters
- **DataStoreFactory**: Creates data store adapters
- Decorator-based registration system
- Validates adapter configuration before instantiation

**Predefined Schemas**:

- 40+ JSON schemas for common document types
- Insurance forms, bank statements, legal documents, etc.

- **Core Utilities**: String manipulation, validation, patterns
- **Data Utilities**: PyArrow handling, schema management, transformations
- **Infrastructure Utilities**: Logging, caching, retry logic, performance monitoring, IAM token management
- **Job Tracker**: Job statistics and monitoring
- **Orchestration Utilities**: Flow utilities, Prefect configuration, deleted rows tracking

##### IAM Token Manager

**Location**: `src/docpipe/utils/infrastructure/iam_token_manager.py`

The IAM Token Manager handles IBM Cloud and MCSP (Multi-Cloud Service Platform) authentication for WatsonX integrations. It provides automatic token management with caching, refresh, and multi-environment support.

**Key Features**:
- **Multi-Environment Support**: Automatically detects and handles IBM Cloud, MCSP Production, and MCSP Test environments
- **Automatic Environment Detection**: Determines environment from WatsonX URL patterns
- **Token Caching**: Uses LRUCache for efficient token storage with 1-hour TTL
- **Auto-Refresh**: Refreshes tokens 10 minutes before expiration
- **Thread-Safe**: Built on thread-safe LRUCache implementation
- **Multi-Tenant Support**: API key-based cache keys enable multiple tenants

**Environment Detection**:

| Environment | URL Pattern | IAM Endpoint |
|-------------|-------------|--------------|
| MCSP Production | Contains `.aws.` or `platform.saas.ibm.com` | `https://account-iam.platform.saas.ibm.com/api/2.0/apikeys/token` |
| IBM Cloud | All other URLs (default) | `https://iam.cloud.ibm.com/identity/token` |

**Architecture**:
```
WatsonX REST Client
        ↓
IAMTokenManager
  - Environment detection
  - Token caching (LRUCache)
  - Auto-refresh (10 min buffer)
        ↓
IAM Endpoints (IBM Cloud/MCSP)
```

**Usage Example**:
```python
from docpipe.utils.infrastructure.iam_token_manager import IAMTokenManager

# Initialize with API key and WatsonX URL
token_manager = IAMTokenManager(
    api_key="your-api-key",  # pragma: allowlist secret
    watsonx_url="https://us-south.ml.cloud.ibm.com"
)

# Get valid token (automatically cached and refreshed)
token = token_manager.get_token()
```

**Integration with WatsonX**: The WatsonX REST client automatically uses IAM Token Manager for authentication. Users only need to provide their API key and URL - token management is handled transparently.

**IBM Cloud vs MCSP Differences**:
- **IBM Cloud**: Uses form-urlencoded requests, returns `access_token` field
- **MCSP**: Uses JSON requests, returns `token` field
- Both support automatic token refresh with 1-hour expiration

**See Also**: [TROUBLESHOOTING.md](TROUBLESHOOTING.md#iam-authentication-issues) for authentication troubleshooting

### 2. Core Framework (`src/docpipe/core/`)

#### Orchestrator (`core/orchestrator/`)

- **AbstractOrchestrator**: Base interface for all orchestrators
- **PythonOrchestrator**: Programmatic flow execution
- **OrchestratorFactory**: Factory for orchestrator instantiation
- **FlowExecutor**: Flow execution coordination
- **FlowValidator**: Comprehensive flow validation (520+ lines)
- **PrefectEngine**: Prefect-based workflow execution engine
- **BatchManager**: Batch processing coordination
- **AbstractOperatorExecutor**: Base executor interface
- **CommandLineOperatorExecutor**: CLI execution support
- **PythonOperatorExecutor**: Python execution support
- **Event Handling**: `AbstractFlowExecutionEventHandler`, `FlowExecutionEventHandler`
- **NodeLogger**: Node-level logging
- **FuturedList**: Async result handling

**Prefect Module** (`prefect/`):

- **PrefectEngine**: Main Prefect workflow execution engine
- **BatchSubflow**: Standalone batch execution subflow
- **BatchExecutionPort**: Port interface for batch execution strategies
- **ThreadPoolAdapter**: Local thread-based batch execution
- **WorkPoolAdapter**: Distributed batch execution via Prefect work pools
- **WorkPoolConfig**: Configuration for Docker work pools
- **Domain Models**: Batch execution domain models and constants

#### Operators (`core/operators/`)

- **AbstractOperator**: Base operator class with template method pattern
- **OperatorMetadata**: Operator metadata and discovery
- **OperatorUtils**: Operator utility functions

#### Data Access (`core/data_access/`)

- Data access utilities and abstractions
- Storage management interfaces
#### Assets Management (`core/assets_management/`)

The Assets Management module provides metadata management for document collections using hexagonal architecture (ports & adapters pattern). It stores only metadata in DuckDB, not document content.

**Document Libraries** (`document_libraries/`):
- **Domain Layer** (`domain/`):
  - **DocumentLibrary**: Domain model representing a collection of document sets
    - Attributes: library_id, name, description, tags, document_set_ids, aggregate metrics
    - Methods: create(), validate(), add_document_set(), remove_document_set(), update_aggregate_metrics()
    - Validation: Name (3-100 chars), description (max 500 chars), tags (max 20, each 1-50 chars)
  - **DocumentLibraryRepositoryPort**: Repository interface defining persistence contract
  - **Exceptions**: DocumentLibraryNotFoundError, DocumentLibraryAlreadyExistsError, InvalidDocumentLibraryError

- **Adapters Layer** (`adapters/`):
  - **DuckDBDocumentLibraryStorage**: DuckDB storage implementation (metadata only)
    - Tables: `document_libraries` (metadata), `library_documentset_junction` (many-to-many relationships)
    - Schema: library_id (UUID), name, description, tags (JSON), created_at, updated_at, aggregate_metrics (JSON)
  - **DuckDBDocumentLibraryMetadataRepository**: Repository implementation using DuckDB storage (metadata only)
    - CRUD operations: create(), get_by_id(), get_by_name(), list_all(), update(), delete()
    - Relationship management: add_document_set(), remove_document_set(), get_document_sets()
    - Filtering: list_by_tags(), search_by_name()

- **Application Layer** (`application/services/`):
  - **DocumentLibraryService**: Business logic orchestration
    - Library lifecycle: create_library(), get_library(), update_library(), delete_library()
    - Document set management: add_document_set_to_library(), remove_document_set_from_library()
    - Queries: list_libraries(), get_library_document_sets(), search_libraries()
    - Validation: Ensures business rules and constraints

- **API Layer** (`app/api/document_libraries/`):
  - **DTOs**: Pydantic models for request/response (CreateLibraryRequest, LibraryResponse, etc.)
  - **Mapper**: Converts between domain models and DTOs
  - **Routes**: FastAPI endpoints for library operations
    - POST /api/v1/document-libraries - Create library
    - GET /api/v1/document-libraries/{library_id} - Get library
    - PUT /api/v1/document-libraries/{library_id} - Update library
    - DELETE /api/v1/document-libraries/{library_id} - Delete library
    - POST /api/v1/document-libraries/{library_id}/document-sets/{set_id} - Add document set
    - DELETE /api/v1/document-libraries/{library_id}/document-sets/{set_id} - Remove document set
    - GET /api/v1/document-libraries - List all libraries
    - GET /api/v1/document-libraries/search - Search libraries

**Architecture Benefits**:
- **Separation of Concerns**: Domain logic isolated from infrastructure
- **Testability**: Easy to mock repositories and test business logic
- **Flexibility**: Can swap DuckDB for PostgreSQL/MongoDB without changing domain
- **Maintainability**: Clear boundaries between layers

### 3. Operators (`src/docpipe/core/operators/`)

Operators are organized by category (defined in `OperatorCategory` enum). For complete operator API documentation including parameters, configuration options, and usage examples, see [Operator Reference](docs/reference/OPERATORS.md).

**Operator Categories:**
- **Extract**: Document text and entity extraction
- **Ingest**: Data source ingestion (local files, S3, SharePoint, etc.)
- **Functional**: Data transformation (chunking, embeddings, branching, merging)
- **Quality**: Data quality checks (deduplication, classification, PII detection)
- **VectorDB**: Vector storage (OpenSearch, Milvus)
- **Storage**: Persistent storage (DocumentSet with DuckDB) and file export to destinations (StorageOutputOperator — filesystem, S3, IBM COS, SharePoint, OneDrive, Google Drive)

**Architecture Highlights:**
- Hexagonal architecture (ports & adapters) for extensibility
- Multi-provider support (LiteLLM, Watsonx, Ollama, HuggingFace)
- Service layer pattern for complex business logic
- Factory pattern for adapter creation

## Operator Pattern

Each operator follows a consistent pattern:

- Inherits from `AbstractOperator`
- Implements `transform()` method
- Configurable via JSON
- Chainable in flows

### 4. CLI Application (`src/docpipe/cli/`)

- **docpipe_cli.py**: Command-line interface implementation
- Uses `PythonOrchestrator` via `OrchestratorFactory`
- Supports flow execution from JSON files
- Defaults `global_config.enable_micro_batching` to `true` when the flow does not set it explicitly

## Key Features

1. **Lightweight Deployment**: Runs locally
2. **Python-Based Execution**: Pure Python operator implementations
3. **Plugin System**: Extensible with custom operators
4. **Flow Configuration**: JSON-based flow definitions
5. **Local Data Processing**: File system and local storage support
6. **Distributed Execution**: Support for scaling across multiple workers using Prefect work pools (Docker)

## Orchestrator Architecture

```
AbstractOrchestrator (base interface)
└── PythonOrchestrator (single implementation)
    └── Used by CLI via OrchestratorFactory

Supporting Components:
├── FlowExecutor (coordinates flow execution)
├── FlowValidator (validates flow configuration)
├── PrefectEngine (Prefect workflow engine)
│   ├── BatchExecutionPort (strategy interface)
│   │   ├── ThreadPoolAdapter (local execution)
│   │   └── WorkPoolAdapter (distributed execution)
│   └── BatchSubflow (worker-side batch processing)
├── BatchManager (batch processing)
├── OperatorFactory (operator instantiation)
└── Event Handlers (execution monitoring)
```

**Note**: There is no separate `CommandLineOrchestrator` class. The CLI uses `PythonOrchestrator` through the factory pattern.

### 5. REST API (`src/docpipe/api/`)

The FastAPI-based REST API provides programmatic access to flow and job management.
See [REST API Server](docs/api/REST_API_SERVER.md) for the full endpoint reference, startup instructions, and security overview.

The REST job-run path defaults `enable_micro_batching` to `true` at runtime when the submitted flow configuration does not define it. An explicit user value still takes precedence.

#### Flow Management Endpoints (`/api/v1/flows`)

- `POST /api/v1/flows` - Create a new flow
- `GET /api/v1/flows/{flow_id}` - Retrieve flow by ID
- `GET /api/v1/flows` - List flows with pagination and filtering
- `PUT /api/v1/flows/{flow_id}` - Update flow (full replacement)
- `PATCH /api/v1/flows/{flow_id}` - Partial flow update
- `DELETE /api/v1/flows/{flow_id}` - Delete flow
- `DELETE /api/v1/flows` - Bulk delete flows

#### Job Run Management Endpoints (`/api/v1/job_runs`)

- `POST /api/v1/job_runs` - Create and start a job run
- `GET /api/v1/job_runs` - List job runs
- `GET /api/v1/job_runs/{job_run_id}` - Get job run status
- `POST /api/v1/job_runs/{job_run_id}/cancel` - Request job cancellation
- `DELETE /api/v1/job_runs/{job_run_id}` - Delete job run data
- `GET /api/v1/job_runs/{job_run_id}/flow_definition` - Get flow definition snapshot

#### Job Management Architecture

The job management subsystem uses hexagonal architecture (ports and adapters pattern):

- **Domain Layer**: `JobStatsDto`, `NodeStatsDto` models and `JobStatsService` port
- **Application Layer**: `JobManagementService` for orchestrating job operations
- **Adapters Layer**: Multiple storage implementations with pluggable backends
  - `InMemoryJobStatsStore`: Fast in-memory storage for testing/development
  - `JsonJobStatsStore`: JSON file-based storage for restart recovery and inspection
  - `CompositeJobStatsStore`: Write-through composite (memory + persistent) for fast reads with durability
- **Dependency Injection**: Factory pattern via `JobManagementFactory`

This architecture enables:

- Pluggable storage backends (in-memory, JSON, composite, PostgreSQL, Redis, etc.)
- Framework-agnostic job tracking
- Clean separation between business logic and infrastructure
- Restart recovery with JSON persistence
- Write-through caching for optimal performance

## Development Guidelines

1. **Python orchestration**: Entire orchestration using Python and Prefect
2. **Python-Only Operators**: Implement operators in pure Python
3. **Modular Design**: Keep components loosely coupled
4. **Plugin Support**: Design for extensibility
5. **Local Testing**: All features should work locally

## Testing Strategy

- **Unit Tests**: Test individual operators and components
- **Integration Tests**: Test flow execution end-to-end
- **Fixtures**: Reusable test data and configurations
- **Coverage**: Maintain >80% code coverage

## Documentation

- **User Guide**: How to use the CLI and create flows
- **Developer Guide**: How to create custom operators
- **API Reference**: Detailed API documentation
- **Examples**: Sample flows and use cases
