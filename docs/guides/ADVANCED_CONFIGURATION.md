# Docling Pipelines Advanced Configuration Guide

This guide covers advanced configuration topics for production deployments, distributed execution, and performance optimization.

## Table of Contents

1. [Job Stats Storage Configuration](#job-stats-storage-configuration)
2. [Incremental Metadata Configuration](#incremental-metadata-configuration)
3. [Docling Converter Pool Configuration](#docling-converter-pool-configuration)
4. [Asset Metadata Storage Configuration](#asset-metadata-storage-configuration)
5. [Ededup Shared Storage Guidance](#ededup-shared-storage-guidance)
6. [Execution Models](#execution-models)
5. [Breaking Changes from the Central Config Loader](#breaking-changes-from-the-central-config-loader)

---

## Job Stats Storage Configuration

Docling Pipelines supports pluggable job stats storage for job runs, node execution state, and micro-batch progress tracking.

### Available Backends

- **In-memory** - test and development scenarios
- **Filesystem storage** - local file-backed persistence
- **DuckDB** - embedded database for local development (no server required)
- **PostgreSQL** - durable storage for concurrent and distributed execution

### Backend Selection

Job-management components are wired through [`JobManagementFactory`](../../src/docpipe/core/job_management/adapters/config/job_management_factory.py). The backend is selected from the central config file (`docling-pipelines-config.yaml`, or the path in `DOCPIPE_CONFIG_PATH`), which is read by `DocpipeConfigLoader`.

```yaml
job_management:
  framework:
    type: default
    config: {}
  storage:
    type: filesystem
    config:
      base_dir: ./data/job_stats_store_data
```

This allows users to configure:

- the job framework type via `job_management.framework.type`
- the job stats storage backend and its settings via `job_management.storage`
- the flow repository via the `LOCAL_FLOWS_DIR` environment variable

Environment variables that still apply on the submitter:

- `DOCPIPE_CONFIG_PATH` (location of the config file)
- `DOCPIPE_JOB_STATS_BASE_DIR` (honoured by the filesystem store)
- `DOCPIPE_POSTGRES_HOST`, `DOCPIPE_POSTGRES_PORT`, `DOCPIPE_POSTGRES_DB`, `DOCPIPE_POSTGRES_USER`, `DOCPIPE_POSTGRES_PASSWORD`, `DOCPIPE_POSTGRES_SCHEMA`

`DOCPIPE_STORAGE_BACKEND` and `DOCPIPE_FRAMEWORK_TYPE` **no longer override the config file** when the submitter selects a backend. They are still written into worker environments by `JobManagementFactory.resolve_worker_env()` so that distributed workers use the same backend as the submitter. See [Breaking changes](#breaking-changes-from-the-central-config-loader).

Effective precedence for job-management runtime selection is:

1. `job_management.storage` in the config file
2. `global_storage` in the config file
3. built-in default (see [Default backend](#default-backend))

The config file is read once per process and cached. Changes to `DOCPIPE_CONFIG_PATH` or to the file made after the first read are ignored until the process restarts (or `DocpipeConfigLoader.reset()` is called, which is intended for tests).

#### Default backend

When the config file is absent, or neither `job_management.storage` nor `global_storage` sets a type, job stats use the **in-memory** backend. Nothing is written to disk, and run history is lost when the process exits. This differs from the other storage-backed services (incremental metadata, job run reports, flow definition snapshots), which default to **filesystem**.

To persist job stats, configure a backend explicitly:

```yaml
job_management:
  storage:
    type: filesystem
    config:
      base_dir: ./data/job_stats_store_data
```

Alternatively, set `global_storage.type`; job management uses it when it has no `job_management.storage` block. A type configured in either place always takes precedence over the in-memory default.

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
  storage:
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

## Asset Metadata Storage Configuration

Document sets and document libraries store their metadata (name, description, statistics, library membership) and the document set attachment references through a pluggable asset repository. The backend is selected per asset type under `assets_management` in `docling-pipelines-config.yaml`.

### Available Backends

| `type` | Repository | Use when |
|---|---|---|
| `duckdb` (default in the shipped config) | `DuckDBAssetRepository` | Single process, local development. DuckDB is an embedded single-writer file, so only one process can write to it at a time. |
| `postgres` | `PostgresAssetRepository` | More than one API replica or worker reads and writes the same document sets and libraries. |

The repositories are created by [`AssetRepositoryFactory`](../../src/docpipe/core/assets/common/factories/repository_factory.py). Both the REST API and the `document_set` operator resolve the backend from the same configuration, so flow runs and API requests always see the same records.

### PostgreSQL Configuration

```yaml
assets_management:
  documentset_repository:
    type: postgres
    config:
      database_path: data/duckdb/document_sets.duckdb  # document set data tables (DuckDB)
      postgres:
        host: localhost
        port: 5432
        database: docpipe
        user: docpipe_user
        # password: prefer the DOCPIPE_POSTGRES_PASSWORD environment variable
        schema: docpipe_assets
        pool_size: 5
        max_overflow: 10
        pool_timeout: 30

  documentlibrary_repository:
    type: postgres
    config:
      postgres:
        host: localhost
        database: docpipe
        user: docpipe_user
```

Configuration rules:

- Connection keys use the same names as the PostgreSQL job stats store. Any key that is not set falls back to `DOCPIPE_POSTGRES_HOST`, `DOCPIPE_POSTGRES_PORT`, `DOCPIPE_POSTGRES_DB`, `DOCPIPE_POSTGRES_USER` and `DOCPIPE_POSTGRES_PASSWORD`, so one set of environment variables can serve job stats and asset metadata.
- A password is required (YAML or `DOCPIPE_POSTGRES_PASSWORD`). Without one, startup fails with a `RepositoryConfigurationException` that names the missing setting.
- The backend type can be overridden per asset type with `DOCUMENTSET_REPOSITORY_TYPE=postgres` and `DOCUMENTLIBRARY_REPOSITORY_TYPE=postgres`.
- `schema` is optional (default `docpipe_assets`) and must be a lowercase PostgreSQL identifier.

### Schema and Concurrency

- The tables `<schema>.asset_records` and `<schema>.asset_attachments` are created automatically on first use. Creation runs inside one transaction guarded by a PostgreSQL advisory lock, so several replicas can start at the same time.
- Each asset is stored as one JSONB row keyed by collection (`document_sets`, `document_libraries`, `document_set_attachments`) and asset ID.
- Asset names are unique per collection, enforced by a database constraint. When two replicas create the same document set at the same moment, one insert wins and the other receives a `409` conflict, which the document set service resolves by returning the existing set.
- Every write runs in its own transaction. Updates lock the target row (`SELECT ... FOR UPDATE`).
- The asset tables live in their own schema, separate from the job stats tables and their Alembic migrations.

### Scope

The `postgres` backend covers asset metadata and attachment references. The document set data tables (the stored PyArrow rows) are still written by the data store selected with the `document_set` operator option `data_backend` (DuckDB by default) at `database_path`. DuckDB lets only one process open a database file for writing, so in multi-replica deployments plan which process writes each data store file.

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

---

## Docling Converter Pool Configuration

The `extract_operator` reuses Docling converters through a pool that is shared by every flow and job in the process, so its limits are process-wide settings in `docling-pipelines-config.yaml` rather than flow or operator parameters:

```yaml
docling:
  converter_pool:
    size: 8                 # default: min(2 x CPU count, 16)
    idle_ttl_seconds: 600   # 0 = keep idle converters until the process exits
```

The environment variables `DOCPIPE_DOCLING_CONVERTER_POOL_SIZE` and `DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS` take precedence over the file. See [Converter Reuse and Pool Sizing](../operators/extract/extract_operator_readme.md#converter-reuse-and-pool-sizing) for sizing guidance.

---

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

## Breaking Changes from the Central Config Loader

Reading `docling-pipelines-config.yaml` is now centralised in `DocpipeConfigLoader` ([`config_utils.py`](../../src/docpipe/utils/infrastructure/config_utils.py)), and every storage factory resolves its backend through it. The change is intentional and alters the behavior below. Review it before upgrading an existing deployment.

### Configuration behavior

| Area | Before | Now | Migration |
|---|---|---|---|
| `DOCPIPE_STORAGE_BACKEND`, `DOCPIPE_FRAMEWORK_TYPE` | Overrode `job_management` in the YAML on the submitter | Ignored when selecting a backend. Still written to workers by `resolve_worker_env()` | Set `job_management.storage.type` and `job_management.framework.type` in the config file |
| `global_storage.config` and `global_storage.postgres` | Merged into job management, incremental metadata, job run reports and flow definition snapshots | Used only when the service has **no** `storage` block, and never merged with a service block | Copy the needed `config` and `postgres` values into each service's `storage` block |
| Legacy job-management keys `storage_backend`, `storage_config` | Selected the backend and merged config | Ignored | Use `job_management.storage.type` and `job_management.storage.config` |
| `store:` key under `job_management` | Documented form | `storage:` is the documented form. `store:` is still accepted when `storage:` is absent | Rename `store:` to `storage:` |
| `DOCPIPE_INCREMENTAL_BASE_DIR` | Set the filesystem incremental store directory | Removed | Set `incremental_metadata.storage.config.base_dir` |
| Config file lifetime | Re-read by each factory call | Read once per process and cached | Restart the process, or call `DocpipeConfigLoader.reset()` in tests |

The default job-stats backend with no configuration is unchanged: **in-memory**.

A service `storage` block that sets only `config` and no `type` takes its type from `global_storage.type`, and otherwise from the built-in default.

#### Global storage is no longer merged

Before, `global_storage.config` and `global_storage.postgres` were merged into the settings of job management, incremental metadata, job run reports and flow definition snapshots. Now the storage **type** is resolved from the service block, then `global_storage`, but the `config` and `postgres` values are never copied across.

```yaml
global_storage:
  type: postgresql
  config:
    postgres:
      host: db.internal      # Before: reached job management and incremental metadata
      database: docpipe      # Now: ignored for connection settings, see below
```

Put the connection settings where each service reads them:

```yaml
job_management:
  storage:
    type: postgresql
    config:
      postgres:                # sibling of "storage"
        host: db.internal
        database: docpipe

incremental_metadata:
  storage:
    type: postgresql
    config:
      postgres:            # inside "config"
        host: db.internal
        database: docpipe
```

Connection settings can still come from `DOCPIPE_POSTGRES_HOST`, `DOCPIPE_POSTGRES_PORT`, `DOCPIPE_POSTGRES_DB`, `DOCPIPE_POSTGRES_USER` and `DOCPIPE_POSTGRES_PASSWORD`, which apply to every service and need no per-service copy. The password should always come from `DOCPIPE_POSTGRES_PASSWORD` or a `${...}` substitution, not a literal value in the file.

### Python API changes

| Removed or renamed                                                                                                                                                                            | Replacement |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---|
| `from_config_file()`, `from_default_sources()`, `from_environment()` on `JobManagementFactory`, `IncrementalMetadataFactory`, `ContentStorageFactory`, `FlowDefinitionSnapshotStorageFactory` | `create_default_factory()` |
| Constructor keyword `backend=`                                                                                                                                                                | `storage_type=` |
| `list_backends()` on the job run report and flow definition snapshot factories                                                                                                                | `list_storage_types()` |
| `AssetRepositoryFactory` (`common/factories/asset_repository_factory.py`)                                                                                                                     | `AssetRepositoryFactory` (`common/factories/asset_repository_factory.py`) |
| Module constants `DEFAULT_CONFIG_PATH`, `ENV_CONFIG_PATH_KEY`, `ENV_INCREMENTAL_BASE_DIR_KEY` in the factory modules                                                                          | `docpipe.utils.infrastructure.config_utils` (`ENV_INCREMENTAL_BASE_DIR_KEY` is removed) |

---

## Related Documentation

- **[User Guide: Pipeline Setup](../../USER_GUIDE_PIPELINE_SETUP.md)** - Basic setup and first pipeline
- **[Prefect Distributed Execution Guide](../integrations/prefect/DISTRIBUTED_EXECUTION_GUIDE.md)** - Detailed distributed execution setup
- **[Job Stats Management](../internals/NODE_METADATA_AGGREGATION_STRATEGY.md)** - Maintainer guide for metadata aggregation
