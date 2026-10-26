
# Prefect Distributed Execution Guide

Complete guide for running Docling Pipelines pipelines with distributed execution using Prefect work pools and workers.

## Table of Contents

1. [Introduction and Overview](#1-introduction-and-overview)
2. [Quick Start Guides](#2-quick-start-guides)
3. [Work Pool Configuration](#3-work-pool-configuration)
4. [Deployment Scenarios](#4-deployment-scenarios)
5. [Troubleshooting](#5-troubleshooting)
6. [Migration Path](#6-migration-path)
7. [Reference](#7-reference)

---

## 1. Introduction and Overview

### What is Distributed Execution in Docling Pipelines?

Distributed execution allows Docling Pipelines pipelines to process data across multiple machines or containers, enabling horizontal scaling and improved throughput. Instead of processing all batches on a single machine, work is distributed to multiple workers that execute batches in parallel.

### When to Use Distributed Execution

**Use distributed execution when:**
- Processing large datasets (>1000 documents)
- Requiring horizontal scalability
- Needing fault tolerance and retry mechanisms
- Running production workloads
- Deploying on Docker

**Use default local execution when:**
- Developing and testing
- Processing small datasets (<1000 documents)
- Running quick prototypes
- Learning Docling Pipelines

### Architecture Overview

```
┌─────────────────┐
│ Your Machine    │
│ (Submitter)     │──┐
└─────────────────┘  │
        │            │  Submit Flow
        │            ↓
        │     ┌──────────────────────────────────────┐
        │     │         Prefect Server               │
        │     │      (Central Coordinator)           │
        │     └──────────────────────────────────────┘
        │                  │
        │     ┌────────────┼────────────┐
        │     ↓            ↓            ↓
        │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
        │  │  Worker 1   │ │  Worker 2   │ │  Worker 3   │
        │  └─────────────┘ └─────────────┘ └─────────────┘
        │         ▲            ▲            ▲
        │         │            │            │
        │         └────────────┼────────────┘
        │                      │
        │              ┌─────────────┐
        └─────────────▶│   Storage   │
                       │ (Local)     │
                       └─────────────┘
```

**Components:**

1. **Prefect Server**: Central coordinator that queues flow runs and manages work pools
2. **Work Pool**: Named queue where flow runs wait for execution
3. **Workers**: Processes that poll the work pool and execute batches
4. **Submitter**: Your machine that submits flow runs to the work pool
5. **Batch Storage**: Shared local filesystem storage for transferring data between submitter and workers
6. **Job Stats Store**: Persistent storage for job and node execution statistics

### Prerequisites

- Docling Pipelines installed and configured
- Python 3.12+ with virtual environment activated
- PYTHONPATH set correctly (see [`USER_GUIDE_PIPELINE_SETUP.md`](../../../USER_GUIDE_PIPELINE_SETUP.md))
- Ollama and OpenSearch running (for operators that require them)

---

## 2. Quick Start Guides

### 2.1 Default Execution (Zero Setup)

By default, Docling Pipelines runs in **ephemeral mode** with zero infrastructure setup.

**When to use:**
- Development and testing
- Small workloads (<1000 documents)
- Quick prototyping

**How to run:**

```bash
# Just run - no setup needed
docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json
```

**Under the hood:**
- Uses Prefect ephemeral mode (temporary in-memory server)
- Thread pool for parallel execution
- All data stays in memory or local filesystem
- No external dependencies

**Environment variables:**
- `PREFECT_MODE`: Defaults to `ephemeral` (no need to set)
- No `PREFECT_API_URL` required

### 2.2 Local POC Setup (Single-Machine Distributed)

Run distributed execution on a single machine to understand work pools before moving to Docker.

**When to use:**
- Testing distributed execution locally
- Understanding work pools and workers (see [Work Pools](https://docs.prefect.io/latest/concepts/work-pools/) and [Workers](https://docs.prefect.io/latest/concepts/workers/))
- Validating flow configurations (see [Deployments](https://docs.prefect.io/latest/concepts/deployments/))

#### Step 1: Start Prefect Server

```bash
# Terminal 1: Start Prefect server
prefect server start
```

Server starts at `http://localhost:4200`. Open in browser to access Prefect UI.

#### Step 2: Create Work Pool

```bash
# Terminal 2: Create a process work pool
prefect work-pool create docpipe-pool --type process
```

Verify:
```bash
prefect work-pool ls
```

#### Step 3: Start Worker

```bash
# Terminal 2: Start worker
prefect worker start --pool docpipe-pool
```

#### Step 4: Configure Environment

```bash
# Terminal 3: Set environment variables
export PREFECT_MODE=server
export PREFECT_API_URL=http://localhost:4200/api
```

**Critical**: Without `PREFECT_MODE=server`, Docling Pipelines uses ephemeral mode and ignores work pool configuration.

**Job stats store guidance for this setup:**
- The worker selects its job stats backend from `docling-pipelines-config.yaml` (the submitter forwards `DOCPIPE_CONFIG_PATH` when the file exists). `DOCPIPE_STORAGE_BACKEND` and `DOCPIPE_FRAMEWORK_TYPE` are still forwarded to workers, but `JobManagementFactory` no longer reads them, so the worker must be able to read the same config file. `DOCPIPE_JOB_STATS_BASE_DIR` and the `DOCPIPE_POSTGRES_*` variables are still honoured
- [`JsonJobStatsStore`](../../../src/docpipe/core/job_management/adapters/stores/json/json_job_stats_store.py) can work for `work-pool-process` only when the submitter and worker share the same filesystem semantics
- Requirement: the submitter and worker must share the same filesystem and the same absolute path namespace for the job stats directory
- Relative filesystem `base_dir` paths depend on where the submitter and worker processes are started
- If filesystem storage is effective for the submitter, `DOCPIPE_JOB_STATS_BASE_DIR` is propagated to workers as a resolved absolute path so workers do not reinterpret relative `base_dir` values differently
- For reliable distributed execution across different containers or machines, use [`PostgresJobStatsStore`](../../../src/docpipe/core/job_management/adapters/stores/postgres/postgres_job_stats_store.py)
- If PostgreSQL storage is effective for the submitter, the worker inherits `DOCPIPE_POSTGRES_HOST`, `DOCPIPE_POSTGRES_PORT`, `DOCPIPE_POSTGRES_DB`, `DOCPIPE_POSTGRES_USER`, and `DOCPIPE_POSTGRES_PASSWORD` unless explicitly overridden in work-pool env

#### Step 5: Configure Flow

Add work pool configuration to your flow JSON:

```json
{
  "flow_name": "distributed-local-pipeline",
  "description": "Distributed execution using Prefect work pools",
  "global_config": {
    "doc_column": "content",
    "storage": "in-memory",
    "execute_type": "local",
    "prefect": {
      "batch_execution": {
        "strategy": "work-pool-process",
        "work_pool_name": "docpipe-pool",
        "batch_storage": {
          "type": "local",
          "path": "/tmp/docpipe-batches"
        }
      }
    }
  },
  "flow": [...]
}
```

#### Step 6: Run Flow

```bash
# Terminal 3: Run the flow
docling-pipelines --flow-file your-flow.json
```

#### Step 7: Verify Execution

1. Check Prefect UI at `http://localhost:4200`
2. Navigate to "Flow Runs" to see execution
3. Check "Work Pools" → "docpipe-pool" for worker activity
4. Monitor worker logs in Terminal 2

---

## 3. Work Pool Configuration

### 3.1 Configuration Location

Work pool configuration is added to your flow JSON under `global_config.prefect.batch_execution`:

```json
{
  "global_config": {
    "prefect": {
      "batch_execution": {
        "strategy": "work-pool-docker",
        "work_pool_name": "docpipe-pool",
        "batch_storage": {
          "type": "s3",
          "bucket": "my-docpipe-batches"
        }
      }
    }
  }
}
```

### 3.2 Work Pool Types

#### Process Work Pool (`work-pool-process`)

**Description**: Executes batches as local processes without containerization.

**Use cases:**
- Docker Compose deployments with shared filesystem
- Single-machine distributed execution
- Development and testing

**Configuration:**

```json
{
  "prefect": {
    "batch_execution": {
      "strategy": "work-pool-process",
      "work_pool_name": "docpipe-pool",
      "batch_storage": {
        "type": "local",
        "path": "/data/batches"
      }
    }
  }
}
```

**Requirements:**
- Prefect Server accessible from submitter and workers
- Shared filesystem between submitter and workers
- Same Python environment on all machines

**Work Pool Path Resolution:**

The `deployment_path` configuration controls where Prefect workers look for your code. This is critical because the submitter (where you run `docling-pipelines`) and the worker (where batches execute) may have different filesystem layouts.

| Scenario | Submitter | Worker | Paths Same? | `os.getcwd()` Works? |
|---|---|---|---|---|
| **Local dev** (Steps 1-4 above) | Your machine | Same machine (subprocess) | ✅ Yes | ✅ Yes |
| **Docker** (docker-compose) | Your machine | Docker container | ❌ No | ❌ No |

*Local Development Flow* (`os.getcwd()` works):
- Submitter creates deployment with `path = os.getcwd()` (e.g., `/Users/.../docling-pipelines`)
- Worker runs on same machine as subprocess
- Worker sets working directory to `/Users/.../docling-pipelines`
- ✅ Path exists! Flow executes successfully

*Docker Flow* (`os.getcwd()` breaks):
- Submitter creates deployment with `path = os.getcwd()` (e.g., `/Users/.../docling-pipelines`)
- Worker runs in Docker container
- Worker tries to set working directory to `/Users/.../docling-pipelines`
- ❌ Path doesn't exist! Code is at `/app/src/docpipe`

**Solution:**

The `deployment_path` parameter is **optional**:
- `None` (default) → falls back to `os.getcwd()` → **local dev works**
- Explicitly set → uses that path → **Docker works**

*Local Development* (no change needed):
```json
{
  "prefect": {
    "batch_execution": {
      "strategy": "work-pool-process",
      "work_pool_name": "docpipe-pool"
    }
  }
}
```

*Docker Compose* (set `deployment_path` explicitly):
```json
{
  "prefect": {
    "batch_execution": {
      "strategy": "work-pool-process",
      "work_pool_name": "docpipe-pool",
      "deployment_path": "/app/src/docpipe"
    }
  }
}
```

This matches:
- **Dockerfile** line 43: `ENV PYTHONPATH=/app/src`
- **docker-compose** line 67: `PYTHONPATH: /app/src`


**Job stats store guidance:**
- The worker selects its backend from the config file at `DOCPIPE_CONFIG_PATH`; mount or bake that file into the worker image. `DOCPIPE_STORAGE_BACKEND` and `DOCPIPE_FRAMEWORK_TYPE` are forwarded but not read by `JobManagementFactory`. Backend-specific settings (`DOCPIPE_JOB_STATS_BASE_DIR`, `DOCPIPE_POSTGRES_*`) are still honoured
- Filesystem job stats storage is acceptable only when submitter and worker processes read/write the same filesystem path namespace
- Requirement: submitter and workers must share the same filesystem and must see the same absolute job stats path
- If using [`JsonJobStatsStore`](../../../src/docpipe/core/job_management/adapters/stores/json/json_job_stats_store.py), `DOCPIPE_JOB_STATS_BASE_DIR` should resolve to the same absolute shared path for submitter and workers instead of relying on cwd-relative resolution
- Example shared path choices:
  - local machine process pool: `DOCPIPE_JOB_STATS_BASE_DIR=/absolute/path/to/data/job_stats`
  - Docker shared volume/process pool: `DOCPIPE_JOB_STATS_BASE_DIR=/app/data/job_stats`
- If workers run on different machines or in isolated runtimes, use [`PostgresJobStatsStore`](../../../src/docpipe/core/job_management/adapters/stores/postgres/postgres_job_stats_store.py)
- For PostgreSQL-backed job stats, workers must resolve the same database connection, typically via inherited or explicit `DOCPIPE_POSTGRES_HOST`, `DOCPIPE_POSTGRES_PORT`, `DOCPIPE_POSTGRES_DB`, `DOCPIPE_POSTGRES_USER`, and `DOCPIPE_POSTGRES_PASSWORD` environment variables

#### Docker Work Pool (`work-pool-docker`)

**Description**: Executes batches in Docker containers.

**Use cases:**
- Docker Compose deployments
- Environments requiring dependency isolation
- Reproducible execution environments

##### Understanding Container Images

**Worker Image vs Batch Execution Image:**
- **Worker image**: Runs the Prefect worker process (infrastructure concern, configured in docker-compose.yml or worker startup)
- **Batch execution image**: Executes individual batch subflows (application concern, configured in flow JSON `image` field)
- These can be the same image but serve different purposes
- Worker image is pulled when starting worker infrastructure; batch image is pulled per job execution

**Configuration options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `image` | string | `"docling-pipelines:latest"` | Docker image for batch execution (can include registry) |
| `image_pull_policy` | string | `"Never"` | When to pull: `"Never"` (POC), `"IfNotPresent"` (prod), `"Always"` (latest) |
| `networks` | list[string] | `[]` | Docker networks to connect to |
| `env` | dict | `{}` | Environment variables for container |

##### Using Container Registries

**Public Registries:**

Public registries work by embedding the registry URL in the image name. No authentication required.

**Image name format examples (replace with your actual registry and image):**
- Docker Hub: `docker.io/your-username/your-image:tag` or `your-username/your-image:tag`
- GitHub Container Registry: `ghcr.io/your-org/your-image:tag`
- Harbor: `your-harbor.example.com/project/your-image:tag`
- Any public registry: `your-registry.example.com/path/your-image:tag`

**Example with Docker Hub:**
```json
{
  "prefect": {
    "batch_execution": {
      "strategy": "work-pool-docker",
      "work_pool_name": "docpipe-docker-pool",
      "image": "myusername/docling-pipelines:v1.0.0",
      "image_pull_policy": "IfNotPresent"
    }
  }
}
```

**Example with GHCR:**
```json
{
  "prefect": {
    "batch_execution": {
      "strategy": "work-pool-docker",
      "image": "ghcr.io/myorg/docling-pipelines:v1.0.0",
      "image_pull_policy": "Always"
    }
  }
}
```

**Private Docker Registries:**

Private registries require authentication configured on the worker host machine.

**Setup steps:**
1. Authenticate Docker on worker host:
   ```bash
   docker login registry.example.com
   # Enter username and password
   ```

2. Configure flow with fully-qualified image name:
   ```json
   {
     "prefect": {
       "batch_execution": {
         "image": "registry.example.com/docpipe/runtime:v1.0.0",
         "image_pull_policy": "IfNotPresent"
       }
     }
   }
   ```

3. Credentials are stored in `~/.docker/config.json` on worker host

**Important notes:**
- Authentication is NOT configured in Docling Pipelines flow JSON
- Each worker host must authenticate separately
- Use `image_pull_policy: "IfNotPresent"` to reduce registry load
- POC setups use `"Never"` with locally built images

**Image Pull Policy Guidance:**

| Policy | Use Case | Behavior |
|--------|----------|----------|
| `"Never"` | POC/local development | Never pulls, uses local image only. Fails if image not present. |
| `"IfNotPresent"` | Production (recommended) | Pulls only if image not cached locally. Efficient for stable versions. |
| `"Always"` | Latest/development | Always pulls from registry. Use for `:latest` tag or rapid iteration. |

**Example with local storage:**

```json
{
  "prefect": {
    "batch_execution": {
      "strategy": "work-pool-docker",
      "work_pool_name": "docpipe-docker-pool",
      "image": "docling-pipelines:v1.0.0",
      "image_pull_policy": "IfNotPresent",
      "networks": ["docpipe-network"],
      "env": {
        "PYTHONPATH": "/app/src",
        "LOG_LEVEL": "INFO",
        "OLLAMA_HOST": "http://ollama:11434",
        "OPENSEARCH_HOST": "opensearch",
        "OPENSEARCH_PORT": "9200",
        "OPENSEARCH_USERNAME": "admin",
        "OPENSEARCH_PASSWORD": "<your-opensearch-password>",
        "OPENSEARCH_USE_SSL": "false",
        "OPENSEARCH_VERIFY_CERTS": "false",
        "PREFECT_API_URL": "http://prefect-server:4200/api",
        "PREFECT_MODE": "server"
      },
      "batch_storage": {
        "type": "local",
        "path": "/data/batches"
      }
    }
  }
}
```

**Requirements:**
- Docker daemon accessible from workers
- Docker image built and available (locally or in registry)
- Shared volume for batch storage (if using `local` type)
- Private registry authentication configured on worker host (if applicable)

**Job stats store guidance:**
- Do not rely on [`JsonJobStatsStore`](../../../src/docpipe/core/job_management/adapters/stores/json/json_job_stats_store.py) for Docker work pools unless submitter and all worker containers share the same mounted filesystem path for job stats
- Requirement: submitter and worker containers must share the same filesystem mount and must use the same in-container absolute path for job stats
- If you switch Docker worker infrastructure to Prefect `process` execution on a shared volume, set `DOCPIPE_JOB_STATS_BASE_DIR` to the mounted absolute path seen inside that runtime, for example `/app/data/job_stats`
- For actual distributed Docker execution, use [`PostgresJobStatsStore`](../../../src/docpipe/core/job_management/adapters/stores/postgres/postgres_job_stats_store.py)

### 3.3 Batch Storage Configuration

Batch storage determines how PyArrow table data is transferred between submitter and workers.

#### Storage Type Comparison

| Type | Use Case | Size Limit | Network Required | Shared Storage |
|------|----------|------------|------------------|----------------|
| `inline` | Small batches, testing | ~512KB | No | No |
| `local` | Docker Compose, same machine, shared volumes | Unlimited | No | Yes (filesystem) |

#### Inline Storage

**Description**: Serializes batch data as JSON in Prefect parameters.

**Configuration:**

```json
{
  "batch_storage": {
    "type": "inline"
  }
}
```

**Limitations:**
- Maximum batch size: ~512KB (controlled by `PREFECT_SERVER_API_MAX_PARAMETER_SIZE`)
- Warning threshold: 400KB
- Not suitable for production

**Overriding size limits:**

Set on Prefect Server (not workers or submitter):

```bash
# Increase to 2MB
export PREFECT_SERVER_API_MAX_PARAMETER_SIZE=2097152

# Restart Prefect Server
```

**Use cases:**
- Development and testing
- Very small datasets
- Quick prototyping

#### Local Filesystem Storage

**Description**: Writes batch data to shared filesystem.

**Configuration:**

```json
{
  "batch_storage": {
    "type": "local",
    "path": "/data/batches"
  }
}
```

**Requirements:**
- Shared filesystem mounted at same path on all machines
- Read/write permissions
- Sufficient disk space

**Use cases:**
- Docker Compose with shared volumes
- Single-machine deployments
- Development environments

**Example Docker Compose volume:**

```yaml
services:
  docpipe-submitter:
    volumes:
      - batch-data:/data/batches

  docpipe-worker:
    volumes:
      - batch-data:/data/batches

volumes:
  batch-data:
```

    "bucket": "docpipe-batches",
    "prefix": "tmp/batches/",
    "access_key": "minioadmin",
    "secret_key": "minioadmin",  <!-- pragma: allowlist secret -->
    "endpoint_url": "http://minio:9000"
  }
}
```

### 3.4 Complete Flow Examples

#### Example 1: Docker Work Pool with Local Storage

```json
{
  "name": "docker-compose-pipeline",
  "flow_id": "docker-example-001",
  "description": "Pipeline using Docker work pool with local storage",
  "storage": "in-memory",
  "execute_type": "local",
  "global_config": {
    "doc_column": "content",
    "prefect": {
      "batch_execution": {
        "strategy": "work-pool-docker",
        "work_pool_name": "docpipe-docker-pool",
        "image": "docling-pipelines:latest",
        "image_pull_policy": "Never",
        "networks": ["docpipe-network"],
        "env": {
          "PYTHONPATH": "/app/src",
          "LOG_LEVEL": "INFO",
          "OLLAMA_HOST": "http://ollama:11434",
          "OPENSEARCH_HOST": "opensearch",
          "OPENSEARCH_PORT": "9200",
          "OPENSEARCH_USERNAME": "admin",
          "OPENSEARCH_PASSWORD": "<your-opensearch-password>",
          "OPENSEARCH_USE_SSL": "false",
          "OPENSEARCH_VERIFY_CERTS": "false",
          "PREFECT_API_URL": "http://prefect-server:4200/api",
          "PREFECT_MODE": "server"
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
      "name": "ingest_documents",
      "type": "ingest_source",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["/data/input"]},
        "include_filter": "pdf,txt,docx"
      }
    },
    {
      "name": "extract_content",
      "type": "extract_operator",
      "depends_on": ["ingest_documents"],
      "config": {
        "text_extraction": {
          "provider": "docling_serve",
          "provider_config": {
            "base_url": "http://docling:5000"
          }
        },
        "entity_extraction": {"provider": "none"}
      }
    }
  ]
}
```

---

## 4. Deployment Scenarios

### 4.1 Docker Deployment

#### Overview

Docker-based distributed execution uses `docker/docker-compose.distributed.yml` to run:

**Core Services (Required):**
- Prefect server (central coordinator)
- Prefect workers (4 replicas for distributed batch processing)

**Optional Services:**
- Ollama (LLM operations) - *Optional: Skip if you provide `OLLAMA_HOST` pointing to existing instance*
- Docling Serve (document processing) - *Optional: Skip if you provide `DOCLING_SERVE_URL` pointing to existing instance*
- OpenSearch (vector storage) - *Optional: Skip if you provide `OPENSEARCH_HOST` pointing to existing instance*

**Note:** The optional services are included for convenience in local/POC setups. In production:
- Use existing Ollama, Docling, and OpenSearch deployments by configuring environment variables
- Use local storage (shared filesystem/PVC) for batch data exchange between submitter and workers

#### Architecture

```
┌─────────────────┐
│ Your Machine    │
│ (Submitter)     │──┐
└─────────────────┘  │
                     │  Submit Flow
                     ↓
┌──────────────────────────────────────┐
│         Prefect Server               │
│      (Central Coordinator)           │
└──────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        ↓            ↓            ↓
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│  Worker 1   │ │  Worker 2   │ │  Worker 3   │
│  (Docker)   │ │  (Docker)   │ │  (Docker)   │
└─────────────┘ └─────────────┘ └─────────────┘
        │            │            │
        └────────────┼────────────┘
                     ↓
              ┌─────────────┐
              │   MinIO     │
              │ (S3 Storage)│
              └─────────────┘
```

#### Prerequisites

1. Docker or Podman installed
2. Docker Compose or podman-compose installed
3. Docling Pipelines repository cloned

#### Step-by-Step Setup

**1. Build the Docling Pipelines Image**

```bash
# From project root
docker build -t docling-pipelines:latest .
```

Or with Podman:
```bash
podman build -t docling-pipelines:latest .
```

**2. Start the Distributed Stack**

```bash
# Start all services
docker-compose -f docker/docker-compose.distributed.yml up -d
```

Or with Podman:
```bash
podman-compose -f docker/docker-compose.distributed.yml up -d
```

This starts:
- `prefect-postgres`: Database for Prefect server
- `prefect-server`: Prefect orchestration server
- `prefect-worker`: 4 worker replicas
- `minio`: S3-compatible storage
- `ollama`: LLM service with models
- `docling-serve`: Document processing
- `opensearch`: Vector database
- `opensearch-dashboards`: OpenSearch UI

**3. Verify Services**

```bash
# Check containers
docker-compose -f docker/docker-compose.distributed.yml ps

# Check Prefect server
curl http://localhost:4200/api/health

# Check MinIO
curl http://localhost:9000/minio/health/live

# Check Ollama
curl http://localhost:11434/api/tags
```

**4. Create Work Pool**

Workers automatically create the work pool on startup. Verify:

```bash
export PREFECT_API_URL=http://localhost:4200/api
prefect work-pool ls
```

**5. Set Environment Variables**

```bash
export PREFECT_MODE=server
export PREFECT_API_URL=http://localhost:4200/api
```

**Critical**: Without `PREFECT_MODE=server`, Docling Pipelines uses ephemeral mode and ignores work pool configuration.

**6. Configure Flow**

See [Example 1: Docker Work Pool with Local Storage](#example-1-docker-work-pool-with-local-storage) above.

**7. Run Flow**

```bash
# Place documents in data/input
mkdir -p data/input
cp your-documents/* data/input/

# Run flow
docling-pipelines --flow-file your-flow.json
```

**8. Monitor Execution**

- **Prefect UI**: http://localhost:4200
- **MinIO Console**: http://localhost:9001 (minioadmin/minioadmin)
- **OpenSearch Dashboards**: http://localhost:5601 (admin/&lt;your-opensearch-password&gt;)

#### Key Configuration Points

**Shared Storage:**

Batch data must be accessible to both the submitter and all workers. The compose file uses shared volumes for:
1. Batch tables
2. Input/output data

```yaml
volumes:
  - ./data:/app/data  # Shared data directory
  - ./logs:/app/logs  # Shared logs directory
```

**Docker Network:**

All services must be on the same network (`docpipe-net`).

**Scaling Workers:**

```bash
# Scale to 8 workers
docker-compose -f docker/docker-compose.distributed.yml up -d --scale prefect-worker=8
```

#### Stopping the Stack

```bash
# Stop services
docker-compose -f docker/docker-compose.distributed.yml down

# Stop and remove volumes (WARNING: deletes data)
docker-compose -f docker/docker-compose.distributed.yml down -v
```

---

## 5. Troubleshooting

### 5.1 Common Pitfalls

#### PREFECT_MODE Not Set

**Symptom**: Work pool configuration ignored, jobs run locally

**Cause**: `PREFECT_MODE` not set to `server`

**Solution**:
```bash
export PREFECT_MODE=server
export PREFECT_API_URL=http://your-prefect-server:4200/api
```

**Verification**:
```bash
echo $PREFECT_MODE  # Should output: server
echo $PREFECT_API_URL
```

#### Worker Not Picking Up Jobs

**Symptom**: Flow runs stay in "Scheduled" state

**Solutions**:
```bash
# Verify work pool exists
prefect work-pool ls

# Check worker is connected
prefect worker ls

# Verify work pool name matches flow JSON
```

#### Batch Storage Errors

**For local storage:**
```bash
# Ensure path exists and is writable
mkdir -p /data/batches
chmod 777 /data/batches
```

#### Cannot Connect to External Services

**Docker:**
```bash
# Verify services on same network
docker network inspect docpipe-net

# Test connectivity
docker-compose exec prefect-worker ping -c 1 ollama
```

### 5.2 Configuration Errors

#### Missing Work Pool Name

**Error:**
```
ValueError: work_pool_name is required for WorkPool strategy
```

**Solution**: Add `work_pool_name` to configuration:
```json
{
  "prefect": {
    "batch_execution": {
      "work_pool_name": "docpipe-pool"
    }
  }
}
```

#### Work Pool Does Not Exist

**Error:**
```
WorkPoolNotFound: Work pool 'docpipe-pool' not found
```

**Solution**: Create the work pool:
```bash
# For process work pool
prefect work-pool create docpipe-pool --type process

# For Docker work pool
prefect work-pool create docpipe-pool --type docker
```

#### Missing Batch Storage Configuration

**Error:**
```
ValueError: batch_storage.path is required when batch_storage.type is 'local'
```

**Solution**: Add required configuration:
```json
{
  "batch_storage": {
    "type": "local",
    "path": "/data/batches"
  }
}
```

#### S3 Credentials Missing

**Error:**
```
ValueError: S3 credentials are required when batch_storage.type is 's3'
```

**Solution**: Provide credentials:
```json
{
  "batch_storage": {
    "type": "s3",
    "bucket": "my-bucket",
    "access_key": "your-access-key-id",
    "secret_key": "<your-secret-access-key>"  <!-- pragma: allowlist secret -->
  }
}
```

#### Prefect Server Not Accessible

**Error:**
```
Could not connect to Prefect Server at http://localhost:4200
```

**Solution**: Ensure Prefect Server is running:
```bash
# Check server health
curl http://localhost:4200/api/health

# Start server (Docker Compose)
docker-compose up -d prefect-server

# Or start locally
prefect server start
```

### 5.3 Verification Steps

#### Check Work Pool Exists

```bash
prefect work-pool ls
```

#### Check Deployment Creation

```bash
prefect deployment ls
```

Look for `docpipe-batch-subflow/<your-deployment-name>`.

#### Test Worker Connection

```bash
# Start worker (separate terminal)
prefect worker start --pool docpipe-pool
```

Worker should show "Worker started" message.

#### Verify Batch Storage Access

**For local:**
```bash
ls -la /data/batches
```

### 5.4 Performance Troubleshooting

#### Slow Batch Execution

**Symptoms**: Batches take longer than expected

**Possible causes:**
1. Insufficient worker resources (CPU/memory)
2. Network latency between submitter and workers
3. Slow shared storage I/O
4. Too many batches for available workers

**Solutions:**
- Increase worker resources (Docker: adjust container resources)
- Add more workers to work pool
- Use local storage for same-machine deployments
- Optimize batch size

#### Workers Not Picking Up Jobs

**Symptoms**: Flow runs stay in "Scheduled" state

**Possible causes:**
1. No workers running for work pool
2. Workers can't connect to Prefect Server
3. Work pool name mismatch

**Solutions:**
```bash
# Check workers running
prefect worker ls

# Start worker
prefect worker start --pool docpipe-pool

# Check work pool configuration
prefect work-pool inspect docpipe-pool
```

### 5.5 Debug Mode

Enable debug logging for detailed troubleshooting:

```bash
DS_LOG_LEVEL=DEBUG docling-pipelines --flow-file your-flow.json
```

---

## 6. Migration Path

### 6.1 Configuration Evolution

#### Ephemeral (Default)

**Flow JSON:**
```json
{
  "global_config": {
    "doc_column": "content"
  }
}
```

**Environment:**
```bash
# PREFECT_MODE=ephemeral (or not set - this is default)
```

**When to use:**
- Development and testing
- Small workloads
- Quick prototyping

---

#### Local Distributed

**Flow JSON:**
```json
{
  "global_config": {
    "prefect": {
      "batch_execution": {
        "strategy": "work-pool-process",
        "work_pool_name": "docpipe-pool",
        "batch_storage": {
          "type": "local",
          "path": "/tmp/docpipe-batches"
        }
      }
    }
  }
}
```

**Environment:**
```bash
export PREFECT_MODE=server
export PREFECT_API_URL=http://localhost:4200/api
```

**When to use:**
- Testing distributed execution locally
- Understanding work pools
- Validating configurations

---

#### Docker

**Flow JSON:**
```json
{
  "global_config": {
    "prefect": {
      "batch_execution": {
        "strategy": "work-pool-docker",
        "work_pool_name": "docpipe-pool",
        "image": "docling-pipelines:latest",
        "env": {
          "PREFECT_MODE": "server",
          "PREFECT_API_URL": "http://prefect-server:4200/api"
        },
        "batch_storage": {
          "type": "s3",
          "bucket": "docpipe-batches",
          "endpoint_url": "http://minio:9000"
        }
      }
    }
  }
}
```

**Environment (submitter):**
```bash
export PREFECT_MODE=server
export PREFECT_API_URL=http://localhost:4200/api
```

**When to use:**
- Docker Compose deployments
- Multi-container environments
- Dependency isolation

---

### 6.2 Side-by-Side Comparison

| Feature | Ephemeral | Local Distributed | Docker |
|---------|-----------|-------------------|--------|
| Setup Complexity | ⭐ Simple | ⭐⭐ Medium | ⭐⭐⭐ Complex |
| Scalability | ❌ Single machine | ✅ Single machine | ✅✅ Multi-container |
| Isolation | ❌ None | ❌ Process-level | ✅ Container |
| Resource Limits | ❌ No | ❌ No | ✅ Yes |
| Production Ready | ❌ No | ❌ No | ✅ Yes |
| Fault Tolerance | ❌ No | ✅ Basic | ✅✅ Good |

### 6.3 Upgrade Guidance

**From Ephemeral to Local Distributed:**
1. Start Prefect server
2. Create work pool
3. Start worker
4. Add work pool configuration to flow JSON
5. Set `PREFECT_MODE=server`

**From Local Distributed to Docker:**
1. Build Docker image
2. Start docker-compose stack
3. Update flow JSON with Docker configuration
4. Configure shared local filesystem storage

---

## 7. Reference

### 7.1 Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `PREFECT_MODE` | Yes (for distributed) | Execution mode | `server` or `ephemeral` |
| `PREFECT_API_URL` | Yes (for distributed) | Prefect server URL | `http://localhost:4200/api` |
| `DOCPIPE_STORAGE_BACKEND` | Optional | Forwarded from the submitter. Not read by `JobManagementFactory`; the backend comes from the config file at `DOCPIPE_CONFIG_PATH` | `filesystem`, `postgresql`, `inmemory` |
| `DOCPIPE_FRAMEWORK_TYPE` | Optional | Forwarded from the submitter. Not read by `JobManagementFactory`; the framework comes from the config file | `default` |
| `DOCPIPE_JOB_STATS_BASE_DIR` | Optional for filesystem store | Absolute shared job stats path for filesystem-backed job stats; inherited from submitter if omitted | `/app/data/job_stats` |
| `DOCPIPE_POSTGRES_HOST` | Optional for PostgreSQL store | PostgreSQL host for job stats store; inherited from submitter if omitted | `postgres` |
| `DOCPIPE_POSTGRES_PORT` | Optional for PostgreSQL store | PostgreSQL port for job stats store; inherited from submitter if omitted | `5432` |
| `DOCPIPE_POSTGRES_DB` | Optional for PostgreSQL store | PostgreSQL database name for job stats store; inherited from submitter if omitted | `docpipe` |
| `DOCPIPE_POSTGRES_USER` | Optional for PostgreSQL store | PostgreSQL user for job stats store; inherited from submitter if omitted | `docpipe_user` |
| `DOCPIPE_POSTGRES_PASSWORD` | Required for PostgreSQL store unless supplied in config | PostgreSQL password for job stats store | `secret` |
| `OLLAMA_HOST` | For Ollama operators | Ollama server URL | `http://ollama:11434` |
| `OPENSEARCH_HOST` | For OpenSearch | OpenSearch host | `localhost` |
| `OPENSEARCH_PORT` | For OpenSearch | OpenSearch port | `9200` |
| `OPENSEARCH_USERNAME` | For OpenSearch | Username | `admin` |
| `OPENSEARCH_PASSWORD` | For OpenSearch | Password | `<your-opensearch-password>` |
| `OPENSEARCH_USE_SSL` | For OpenSearch | Use SSL | `false` |
| `OPENSEARCH_VERIFY_CERTS` | For OpenSearch | Verify certificates | `false` |

**Notes**:
- Batch storage for distributed execution is configured in the flow JSON `batch_storage` section.
- Job-management env values are applied with precedence: explicit work-pool env, then submitter process env, then code defaults.

### 7.2 Configuration Schema

**Note**: The `deployment_name` field is optional and defaults to `"docpipe-batch-subflow"`. You only need to specify it if you want to create multiple deployments of the same flow in the same work pool (advanced use case).

**Minimal configuration:**

```json
{
  "global_config": {
    "prefect": {
      "batch_execution": {
        "strategy": "work-pool-process",
        "work_pool_name": "docpipe-pool",
        "batch_storage": {
          "type": "local",
          "path": "/tmp/batches"
        }
      }
    }
  }
}
```

**Inline storage (for small batches):**

```json
{
  "global_config": {
    "prefect": {
      "batch_execution": {
        "strategy": "work-pool-docker",
        "work_pool_name": "docpipe-docker-pool",
        "batch_storage": {
          "type": "inline"
        }
      }
    }
  }
}
```

> **Note**: Inline storage passes batch data directly through Prefect's API. Only suitable for small batches due to `PREFECT_SERVER_API_MAX_PARAMETER_SIZE` limitations. For production workloads with larger batches, use `local` or `s3` storage.

### 7.3 Links to Examples

- **Sample Flow**: [`sample_flows/quickstart/complete_pipeline_ollama.json`](../../../sample_flows/quickstart/complete_pipeline_ollama.json)
- **Docker Compose**: [`docker/docker-compose.distributed.yml`](../../../docker/docker-compose.distributed.yml)
### 7.4 Related Documentation

- **User Guide**: [`USER_GUIDE_PIPELINE_SETUP.md`](../../../USER_GUIDE_PIPELINE_SETUP.md)
- **Architecture**: [ARCHITECTURE.md](../../../ARCHITECTURE.md)
- **Prefect Documentation**: https://docs.prefect.io/concepts/work-pools/
- **Docker Documentation**: https://docs.docker.com/

---

## 8. Future Enhancements

The following features are planned for future releases to enhance distributed execution capabilities:

### 8.1 Pluggable Job Stats Store

**Current State**: Job statistics are stored locally using pickle files, which limits visibility in distributed environments where multiple workers operate independently.

**Planned Enhancement**: Add pluggable storage backends for job statistics, enabling distributed workers to share job metrics in a common database.

**Supported Backends** (planned):
- PostgreSQL
- MySQL
- Redis
- Other relational/NoSQL databases

**Benefits**:
- Centralized job statistics across all workers
- Real-time visibility into pipeline execution metrics
- Better monitoring and debugging in distributed deployments
- Historical analysis of job performance

### 8.2 Pluggable Incremental Metadata Storage

**Current State**: Incremental metadata tables (tracking processed files, checksums, etc.) are stored locally, preventing workers from sharing state about which data has been processed.

**Planned Enhancement**: Add external storage support for incremental metadata, allowing all workers to access and update shared incremental processing state.

**Supported Backends** (planned):
- PostgreSQL
- MySQL
- Shared filesystem-backed storage
- Other persistent storage solutions

**Benefits**:
- Consistent incremental processing across distributed workers
- Prevents duplicate processing when multiple workers handle the same data sources
- Enables true stateful distributed pipelines
- Supports failover and worker replacement without losing processing state

**Use Cases**:
- Multi-worker ingestion from shared data sources
- Distributed incremental updates to vector databases
- Coordinated processing of large datasets across worker pools

---

### 7.5 Best Practices

#### Work Pool Naming

Use descriptive names indicating environment and type:
- `docpipe-dev-docker` - Development Docker pool
- `docpipe-prod-process` - Production process pool
- `docpipe-staging-process` - Staging process pool

#### Resource Allocation

**Docker:**
- Use `--cpus` and `--memory` flags when starting workers
- Monitor with `docker stats`

#### Missing Batch Storage Configuration

**Error:**
```
ValueError: batch_storage.path is required when batch_storage.type is 'local'
```

**Solution**: Add required configuration:
```json
{
  "batch_storage": {
    "type": "local",
    "path": "/data/batches"
  }
}
```

    "bucket": "my-bucket",
    "access_key": "your-access-key-id",
    "secret_key": "<your-secret-access-key>"
  }
}
```

#### Prefect Server Not Accessible

**Error:**
```
Could not connect to Prefect Server at http://localhost:4200
```

**Solution**: Ensure Prefect Server is running:
```bash
# Check server health
curl http://localhost:4200/api/health

# Start server (Docker Compose)
docker-compose up -d prefect-server

# Or start locally
prefect server start
```

### 5.3 Verification Steps

#### Check Work Pool Exists

```bash
prefect work-pool ls
```

#### Check Deployment Creation

```bash
prefect deployment ls
```

Look for `docpipe-batch-subflow/<your-deployment-name>`.

#### Test Worker Connection

```bash
# Start worker (separate terminal)
prefect worker start --pool docpipe-pool
```

Worker should show "Worker started" message.

#### Verify Batch Storage Access

```bash
ls -la /data/batches
```

### 5.4 Performance Troubleshooting

#### Slow Batch Execution

**Symptoms**: Batches take longer than expected

**Possible causes:**
1. Insufficient worker resources (CPU/memory)
2. Network latency between submitter and workers
3. Slow shared storage I/O
4. Too many batches for available workers

**Solutions:**
- Increase worker resources (Docker: adjust container resources)
- Add more workers to work pool
- Use local storage for same-machine deployments
- Optimize batch size

#### Workers Not Picking Up Jobs

**Symptoms**: Flow runs stay in "Scheduled" state

**Possible causes:**
1. No workers running for work pool
2. Workers can't connect to Prefect Server
3. Work pool name mismatch

**Solutions:**
```bash
# Check workers running
prefect worker ls

# Start worker
prefect worker start --pool docpipe-pool

# Check work pool configuration
prefect work-pool inspect docpipe-pool
```

### 5.5 Debug Mode

Enable debug logging for detailed troubleshooting:

```bash
DS_LOG_LEVEL=DEBUG docling-pipelines --flow-file your-flow.json
```

---

## 6. Migration Path

### 6.1 Configuration Evolution

#### Ephemeral (Default)

**Flow JSON:**
```json
{
  "global_config": {
    "doc_column": "content"
  }
}
```

**Environment:**
```bash
# PREFECT_MODE=ephemeral (or not set - this is default)
```

**When to use:**
- Development and testing
- Small workloads
- Quick prototyping

---

#### Local Distributed

**Flow JSON:**
```json
{
  "global_config": {
    "prefect": {
      "batch_execution": {
        "strategy": "work-pool-process",
        "work_pool_name": "docpipe-pool",
        "batch_storage": {
          "type": "local",
          "path": "/tmp/docpipe-batches"
        }
      }
    }
  }
}
```

**Environment:**
```bash
export PREFECT_MODE=server
export PREFECT_API_URL=http://localhost:4200/api
```

**When to use:**
- Testing distributed execution locally
- Understanding work pools
- Validating configurations

---

#### Docker

**Flow JSON:**
```json
{
  "global_config": {
    "prefect": {
      "batch_execution": {
        "strategy": "work-pool-docker",
        "work_pool_name": "docpipe-pool",
        "image": "docling-pipelines:latest",
        "env": {
          "PREFECT_MODE": "server",
          "PREFECT_API_URL": "http://prefect-server:4200/api"
        },
        "batch_storage": {
          "type": "s3",
          "bucket": "docpipe-batches",
          "endpoint_url": "http://minio:9000"
        }
      }
    }
  }
}
```

**Environment (submitter):**
```bash
export PREFECT_MODE=server
export PREFECT_API_URL=http://localhost:4200/api
```

**When to use:**
- Docker Compose deployments
- Multi-container environments
- Dependency isolation

---

---

### 6.2 Side-by-Side Comparison

| Feature | Ephemeral | Local Distributed | Docker |
|---------|-----------|-------------------|--------|
| Setup Complexity | ⭐ Simple | ⭐⭐ Medium | ⭐⭐⭐ Complex |
| Scalability | ❌ Single machine | ✅ Single machine | ✅✅ Multi-container |
| Isolation | ❌ None | ❌ Process-level | ✅ Container |
| Resource Limits | ❌ No | ❌ No | ✅ Yes |
| Production Ready | ❌ No | ❌ No | ✅ Yes |
| Fault Tolerance | ❌ No | ✅ Basic | ✅✅ Good |

### 6.3 Upgrade Guidance

**From Ephemeral to Local Distributed:**
1. Start Prefect server
2. Create work pool
3. Start worker
4. Add work pool configuration to flow JSON
5. Set `PREFECT_MODE=server`

**From Local Distributed to Docker:**
1. Build Docker image
2. Start docker-compose stack
3. Update flow JSON with Docker configuration
4. Configure shared local filesystem storage

---

## 7. Reference

### 7.1 Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `PREFECT_MODE` | Yes (for distributed) | Execution mode | `server` or `ephemeral` |
| `PREFECT_API_URL` | Yes (for distributed) | Prefect server URL | `http://localhost:4200/api` |
| `OLLAMA_HOST` | For Ollama operators | Ollama server URL | `http://ollama:11434` |
| `OPENSEARCH_HOST` | For OpenSearch | OpenSearch host | `localhost` |
| `OPENSEARCH_PORT` | For OpenSearch | OpenSearch port | `9200` |
| `OPENSEARCH_USERNAME` | For OpenSearch | Username | `admin` |
| `OPENSEARCH_PASSWORD` | For OpenSearch | Password | `<your-opensearch-password>` |
| `OPENSEARCH_USE_SSL` | For OpenSearch | Use SSL | `false` |
| `OPENSEARCH_VERIFY_CERTS` | For OpenSearch | Verify certificates | `false` |

**Note**: Batch storage for distributed execution is configured in the flow JSON `batch_storage` section.

### 7.2 Configuration Schema

**Minimal configuration:**

```json
{
  "global_config": {
    "prefect": {
      "batch_execution": {
        "strategy": "work-pool-process",
        "work_pool_name": "docpipe-pool",
        "batch_storage": {
          "type": "local",
          "path": "/tmp/batches"
        }
      }
    }
  }
}
```

### 7.3 Links to Examples

- **Sample Flow**: [`sample_flows/quickstart/complete_pipeline_ollama.json`](../../../sample_flows/quickstart/complete_pipeline_ollama.json)
- **Docker Compose**: [`docker/docker-compose.distributed.yml`](../../../docker/docker-compose.distributed.yml)
### 7.4 Related Documentation

- **User Guide**: [USER_GUIDE_PIPELINE_SETUP.md](../../../USER_GUIDE_PIPELINE_SETUP.md)
- **Architecture**: [ARCHITECTURE.md](../../../ARCHITECTURE.md)
- **Prefect Documentation**: https://docs.prefect.io/concepts/work-pools/
- **Docker Documentation**: https://docs.docker.com/

### 7.5 Best Practices

#### Work Pool Naming

Use descriptive names indicating environment and type:
- `docpipe-dev-docker` - Development Docker pool
- `docpipe-prod-process` - Production process pool
- `docpipe-staging-process` - Staging process pool

#### Resource Allocation

**Docker:**
- Use `--cpus` and `--memory` flags when starting workers
- Monitor with `docker stats`

#### Batch Storage Selection

| Scenario | Recommended Storage |
|----------|-------------------|
| Development/testing | `inline` (if batches <400KB) or `local` |
| Docker Compose | `local` with shared volumes |
| Production | `s3` with proper IAM/credentials |

#### Security

- Never commit credentials to version control
- Store credentials securely (environment variables, secret managers)
- Rotate credentials regularly

#### Monitoring

Monitor these metrics:
- Worker utilization (busy workers)
- Batch execution time (average and p95)
- Batch storage transfer time
- Failed batch rate
- Queue depth (pending flow runs)

---

## Summary

Distributed execution in Docling Pipelines enables horizontal scaling and improved throughput through Prefect work pools and workers. Key takeaways:

1. **Start Simple**: Begin with ephemeral mode, progress to local POC, then Docker
2. **PREFECT_MODE is Critical**: Always set `PREFECT_MODE=server` for distributed execution
3. **Choose Right Storage**: Use inline for testing and local shared filesystem storage for distributed execution
4. **Monitor and Scale**: Add workers as needed, monitor performance metrics
5. **Follow Best Practices**: Use descriptive names, set resource limits, secure credentials

For additional help, consult:
- [`USER_GUIDE_PIPELINE_SETUP.md`](../../../USER_GUIDE_PIPELINE_SETUP.md) - Complete setup guide
- [Prefect Documentation](https://docs.prefect.io/concepts/work-pools/) - Official Prefect docs
