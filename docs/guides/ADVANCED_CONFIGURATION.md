# Docling Pipelines Advanced Configuration Guide

This guide covers advanced configuration topics for production deployments, distributed execution, and performance optimization.

## Table of Contents

1. [Job Stats Storage Configuration](#job-stats-storage-configuration)
2. [Incremental Metadata Configuration](#incremental-metadata-configuration)
3. [Ededup Shared Storage Guidance](#ededup-shared-storage-guidance)
4. [Execution Models](#execution-models)

---

## Job Stats Storage Configuration

Docling Pipelines supports pluggable job stats storage for job runs, node execution state, and micro-batch progress tracking.

### Available Backends

- **In-memory** - test and development scenarios
- **Filesystem storage** - local file-backed persistence
- **DuckDB** - embedded database for local development (no server required)
- **PostgreSQL** - durable storage for concurrent and distributed execution

### Backend Selection

Job-management components are wired through [`JobManagementFactory`](../../src/docpipe/core/job_management/adapters/config/job_management_factory.py). Backend selection is controlled by environment variables and defaults.

The main user-facing configuration is controlled via environment variables:

```yaml
job_management:
  framework:
    type: default
    config: {}
  store:
    type: filesystem
    config:
      base_dir: ./data/job_stats_store_data
```

This allows users to configure:

- the job framework type via `DOCPIPE_FRAMEWORK_TYPE` environment variable
- the job stats store backend via `DOCPIPE_STORAGE_BACKEND` environment variable
- the job stats store runtime config via backend-specific environment variables
- the flow repository via `LOCAL_FLOWS_DIR` environment variable

Common overrides include:

- `DOCPIPE_CONFIG_PATH`
- `DOCPIPE_STORAGE_BACKEND`
- `DOCPIPE_FRAMEWORK_TYPE`
- `DOCPIPE_JOB_STATS_BASE_DIR`
- `DOCPIPE_POSTGRES_HOST`
- `DOCPIPE_POSTGRES_PORT`
- `DOCPIPE_POSTGRES_DB`
- `DOCPIPE_POSTGRES_USER`
- `DOCPIPE_POSTGRES_PASSWORD`

Effective precedence for job-management runtime selection is:

1. explicit environment variables
2. built-in defaults in [`JobManagementFactory`](../../src/docpipe/core/job_management/adapters/config/job_management_factory.py)

### Filesystem Storage Guidance

Filesystem storage is useful for single-host execution and simple local testing.

Important requirements:

- the job stats base directory must be writable
- for distributed Prefect workers, the configured path must resolve to the same shared filesystem location for the submitter and workers
- local-only paths on the submitter machine are not sufficient for distributed workers
- when JSON storage is selected from config, worker propagation resolves `base_dir` to an absolute path before injecting it into the worker environment

### DuckDB Guidance

DuckDB is an embedded analytical database that provides persistent storage without requiring a server. It's ideal for local development and testing.

Use DuckDB when:

- you want persistent storage without running a database server
- you need SQL query capabilities for analyzing job statistics
- you're working in a single-host environment
- you want faster queries than JSON storage

Configuration example:

```yaml
job_management:
  store:
    type: duckdb
    config:
      database_path: ./data/duckdb/job_stats.duckdb
```

DuckDB defaults to `<DOCPIPE_DATA_PATH>/duckdb`, or `<project-root>/data/duckdb` when unset, resolved at startup.
Job stats use `job_stats.duckdb`; document sets and libraries share the default `document_sets.duckdb` file.
Explicit `database_path` settings take precedence over `DOCPIPE_DATA_PATH`, including the YAML example above.

The shipped root [`docling-pipelines-config.yaml`](../../docling-pipelines-config.yaml) explicitly sets the document-set
`database_path` to `data/duckdb/document_sets.duckdb`. Setting `DOCPIPE_DATA_PATH` alone does not move the document-set
database used by the API. The environment-based default applies only when no `database_path` is configured.

**Compatibility limitation:** With the shipped YAML and `DOCPIPE_DATA_PATH` pointing to a different data root, a flow
with a `document_set` node that has no explicit `database_path` uses the environment-based default, while the API keeps
the YAML path. These consumers previously used the same file when launched from the project root. To share a database,
set the same absolute `database_path` in the API's document-set repository configuration and the operator's configuration.

Important notes:

- DuckDB stores all data in a single file
- Not recommended for distributed execution (use PostgreSQL instead)
- Provides SQL interface for querying job statistics
- See [`examples/duckdb_job_stats/`](../../examples/duckdb_job_stats/) for usage examples

### PostgreSQL Guidance

PostgreSQL is the recommended backend for multi-process and distributed execution because it provides durable shared storage and stronger concurrency behavior than file-backed JSON storage.

Use PostgreSQL when:

- multiple workers need to update job stats concurrently
- workers do not share a reliable filesystem path
- you need a single durable backend for job status APIs
- you want workers on different containers, pods, or machines to share a single backend without filesystem coupling

### Metadata Aggregation Maintenance

Node stats are aggregated on the read path, not in the storage adapter. When operators add new metadata fields, maintainers must review [`DEFAULT_STRATEGIES`](../../src/docpipe/core/job_management/application/aggregation/strategies.py) and update it if the field should not use the default `LAST` aggregation behavior.

See [`docs/internals/NODE_METADATA_AGGREGATION_STRATEGY.md`](../internals/NODE_METADATA_AGGREGATION_STRATEGY.md) for the maintainer workflow.

### Distributed Execution and Work Pool Environment Inheritance

For distributed Prefect execution, work pool runtime configuration is modeled in [`work_pool_config.py`](../../src/docpipe/core/orchestration/prefect/config/work_pool_config.py) and applied by [`WorkPoolAdapter`](../../src/docpipe/core/orchestration/prefect/adapters/work_pool_adapter.py).

Important behavior:

- worker `env` values configured directly in the work pool take highest precedence
- if job-management env values are omitted from the work pool config, workers inherit the submitter's effective job-management configuration
- the inherited effective configuration is resolved from:
  - submitter environment variables
  - code defaults

This makes it possible to configure job management via environment variables per environment or per deployment.

For full distributed execution examples and work-pool-specific configuration, see [`DISTRIBUTED_EXECUTION_GUIDE.md`](../integrations/prefect/DISTRIBUTED_EXECUTION_GUIDE.md).

---

## Incremental Metadata Configuration

Docling Pipelines supports incremental processing to avoid reprocessing unchanged input data. Incremental metadata stores processing state such as file identity and modification information so ingest operators can determine whether an item is new, changed, or already processed.

### Configuration

Use the `incremental_metadata` section in `docling-pipelines-config.yaml`:

```yaml
incremental_metadata:
  storage:
    type: "filesystem"  # Options: filesystem, postgresql
    config:
      base_dir: "./data"
      lock_timeout: 30.0
```

This configuration is the single source of truth for incremental metadata backend selection and runtime settings.

### Storage Backends

#### JSON

JSON storage is the default backend. It is file-based, easy to inspect, and suitable for development or smaller single-host deployments.

```yaml
incremental_metadata:
  storage:
    type: "json"
    config:
      base_dir: "./data/incremental_metadata"
      lock_timeout: 30.0
```

Use JSON when:

- you want a simple file-based backend
- you are running locally or on a single host
- you want metadata files that are easy to inspect during debugging

#### Parquet

Parquet storage uses a columnar file format and is better suited to larger datasets or analytics-oriented workflows.

```yaml
incremental_metadata:
  storage:
    type: "parquet"
    config:
      base_dir: "./data/incremental_metadata"
      lock_timeout: 30.0
```

Use Parquet when:

- you need more efficient columnar storage than JSON
- you want better compression for larger metadata volumes
- you are operating on a shared filesystem but do not need a database backend

#### PostgreSQL

PostgreSQL is the recommended backend for production deployments that require stronger concurrency behavior and durable centralized storage.

```yaml
incremental_metadata:
  storage:
    type: "postgresql"
    config:
      base_dir: "./data"
      lock_timeout: 30.0
  postgres:
    host: "${POSTGRES_HOST:-localhost}"
    port: 5432
    database: "${POSTGRES_DB:-docpipe}"
    user: "${POSTGRES_USER:-docpipe_user}"
    password: "${POSTGRES_PASSWORD}"
    schema: "incremental_metadata"
```

Use PostgreSQL when:

- multiple workers need to access incremental metadata concurrently
- submitters and workers do not share a reliable local filesystem path
- you need durable centralized state for distributed or production execution

### Environment Variables for Sensitive Data

Use environment variable substitution in `docling-pipelines-config.yaml` for credentials and deployment-specific values.

```yaml
incremental_metadata:
  storage:
    type: "postgresql"
    config:
      base_dir: "${DATA_DIR:-./data}"
      lock_timeout: "${LOCK_TIMEOUT:-30.0}"
  postgres:
    host: "${INCR_META_DB_HOST:-localhost}"
    port: "${INCR_META_DB_PORT:-5432}"
    database: "${INCR_META_DB_NAME:-docpipe}"
    user: "${INCR_META_DB_USER:-docpipe_user}"
    password: "${INCR_META_DB_PASSWORD}"
    schema: "${INCR_META_DB_SCHEMA:-incremental_metadata}"
```

Guidance:

- use `${VAR_NAME}` for required secrets
- use `${VAR_NAME:-default}` for optional values with safe defaults
- do not commit real credentials into version control

See [`docling-pipelines-config.yaml.example`](../../docling-pipelines-config.yaml.example) for complete backend examples and environment variable patterns.

---

## Ededup Shared Storage Guidance

`EdedupOperator` records admitted hashes persistently by job, flow node, and run. Configure its registry under
`ededup.storage` in `docling-pipelines-config.yaml`; this is separate from `incremental_metadata.storage` and the
flow's `global_config`.

For workers on separate hosts or pods, use a shared PostgreSQL database and schema. Configure the same connection
settings and schema for every worker, and grant the database role permission to create the schema and `hashes` table
or provision those objects ahead of time. The default schema is `ededup_registry`.

```yaml
ededup:
  storage:
    type: postgresql
    config:
      postgres:
        schema: ededup_registry
```

Connection settings can use the common `DOCPIPE_POSTGRES_HOST`, `DOCPIPE_POSTGRES_PORT`, `DOCPIPE_POSTGRES_DB`,
`DOCPIPE_POSTGRES_USER`, and `DOCPIPE_POSTGRES_PASSWORD` environment variables. If using filesystem storage instead,
every worker must see the same shared filesystem path and support reliable file locking and atomic replacement. A
pod-local directory does not coordinate admissions between pods; use PostgreSQL when workers cannot share a reliable
filesystem. See [Global Configuration](../reference/GLOBAL_CONFIG.md#ededup-registry-storage) and the
[operator reference](../reference/OPERATORS.md#ededupoperator) for precedence and path details.

## Execution Models

Docling Pipelines uses Prefect as its orchestration engine and supports two Prefect execution modes:

### Ephemeral Mode (Default)

By default, Docling Pipelines runs Prefect in **ephemeral mode** with a temporary in-memory server. This mode is ideal for:

- Development and testing
- Small to medium workloads (< 1000 documents)
- Single-machine processing
- Quick prototyping and learning

**How it works:**

- Prefect server runs temporarily in-memory
- No external Prefect server setup required
- Automatic cleanup after execution
- Zero configuration needed

**Usage:**

```bash
# Simply run your flow - Prefect ephemeral mode is automatic
docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json
```

### Distributed Execution with Prefect Work Pools (Optional)

For production workloads and large-scale processing, Docling Pipelines supports **Prefect's distributed execution** using work pools and workers.

**When to use:**

- Processing large document collections (1000+ documents)
- Horizontal scaling across multiple machines
- Production deployments with high availability
- Resource-intensive operations requiring distributed processing

**Deployment options:**

1. **Local POC**: Test distributed patterns with Prefect server and workers on a single machine
2. **Docker Compose**: Multi-worker setup with containerized Prefect infrastructure

For complete setup instructions, work pool configuration, and deployment guides, see:

**[Prefect Distributed Execution Guide](../integrations/prefect/DISTRIBUTED_EXECUTION_GUIDE.md)**

This guide covers:

- Prefect server and work pool setup
- Worker deployment for different environments
- Batch storage strategies (inline and local filesystem)
- Docker deployment configurations
- Troubleshooting and performance tuning

---

## Related Documentation

- **[User Guide: Pipeline Setup](../../USER_GUIDE_PIPELINE_SETUP.md)** - Basic setup and first pipeline
- **[Prefect Distributed Execution Guide](../integrations/prefect/DISTRIBUTED_EXECUTION_GUIDE.md)** - Detailed distributed execution setup
- **[Job Stats Management](../internals/NODE_METADATA_AGGREGATION_STRATEGY.md)** - Maintainer guide for metadata aggregation
