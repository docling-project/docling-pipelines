# Docling pipelines

[![PyPI version](https://img.shields.io/pypi/v/docling-pipelines)](https://pypi.org/project/docling-pipelines/)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![License MIT](https://img.shields.io/github/license/docling-project/docling-pipelines)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/docling-project/docling-pipelines/actions/workflows/ci.yml/badge.svg)](https://github.com/docling-project/docling-pipelines/actions/workflows/ci.yml)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![DCO](https://img.shields.io/badge/DCO-required-brightgreen)](https://developercertificate.org/)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/15122/badge)](https://www.bestpractices.dev/projects/15122)

## What is Docling pipelines?

Docling pipelines is an enterprise-grade document curation pipeline for Retrieval Augmented Generation (RAG) applications. It ingests data from unstructured sources, curates documents, and writes entities and vector embeddings to targets — enabling AI-ready pipelines at scale.

It connects to cloud document sources (S3, OneDrive, SharePoint, Google Drive, Box, and more) and extracts content and entities from PDF, DOCX, HTML, images, and other formats using [Docling](https://github.com/docling-project/docling). Extracted content is curated for LLMs, converted into chunks and embeddings, and stored in a vector database such as Milvus or OpenSearch.

## Features

- 📥 **[Multi-source ingestion](docs/operators/ingest/ingest_source_readme.md)** — local filesystem, Amazon S3, IBM COS, SharePoint, OneDrive, Google Drive, Box, Dropbox, and web pages
- 📄 **[Document extraction](docs/operators/extract/extract_operator_readme.md)** — PDF, DOCX, HTML, images, and more via Docling, with configurable OCR engines, GPU acceleration, and optional VLM and ASR pipelines
- 🧠 **[Entity extraction](docs/guides/UNIFIED_LLM_ARCHITECTURE_GUIDE.md)** — LLM-based extraction via LiteLLM (100+ providers), IBM watsonx.ai, or Docling templates
- ✂️ **[Chunking](docs/operators/functional/chunker_readme.md)** — Docling-native and semantic chunking strategies
- 🔢 **[Embeddings](docs/operators/functional/embeddings_readme.md)** — vector embedding generation for any downstream vector store
- 🔍 **[Quality operators](docs/reference/OPERATORS.md)** — language detection, readability scoring, PII/HAP detection, deduplication, redaction, SQL filtering, document classification, and ML enrichment
- 🗄️ **[Vector](docs/operators/vectordb/vectordb_readme.md) & [cloud storage](docs/operators/storage/storage_output_readme.md)** — write vectors to OpenSearch or Milvus (including container-free Milvus Lite), or export curated documents to filesystem, S3, IBM COS, SharePoint, OneDrive, and Google Drive
- 🔀 **[DAG-based flows](docs/guides/FLOW_AUTHORING_FORMAT.md) & [micro-batching](docs/integrations/prefect/DISTRIBUTED_EXECUTION_GUIDE.md)** — define pipelines as JSON with automatic dependency resolution, parallel micro-batching, and distributed execution via Prefect (thread pools, process pools, or Docker work pools)
- 🔄 **[Incremental processing](docs/reference/GLOBAL_CONFIG.md#incremental-processing)** — stateful delta runs (backed by Parquet or PostgreSQL) that track document changes, skip unchanged files, and optionally synchronize source deletions
- ⚡ **[Event-driven streaming](docs/guides/EVENT_STREAMING_GUIDE.md)** — real-time Kafka event consumption with Schema Registry support and routing-key-to-flow mappings for automated create/update/delete triggers
- 🔐 **[Enterprise security & governance](docs/guides/SECURITY_BEST_PRACTICES.md)** — [HashiCorp Vault](docs/guides/VAULT_INTEGRATION_GUIDE.md) (`vault://`) secret resolution, document [ACL extraction](docs/operators/extract/acl_readme.md) and [query-time enforcement](docs/api/ACL_DOCUMENT_RETRIEVAL.md), and [OAuth2/OIDC](docs/api/OAUTH2_AUTHENTICATION.md) + LDAP/JWT REST API authentication
- 📊 **Observability, lineage & reporting** — [OpenLineage](docs/integrations/openlineage/OPENLINEAGE_GUIDE.md) event emission, [OpenTelemetry](docs/guides/TELEMETRY_SETUP.md) distributed tracing and metrics, and automated per-run [CSV job reports](docs/guides/JOB_REPORT_GENERATION.md)
- 🗂️ **Asset management** — organize pipelines and data with Projects, [Document Libraries](docs/guides/USER_GUIDE_DOCUMENT_LIBRARIES.md), [Document Sets](docs/operators/storage/document_set_readme.md), and custom [Document Class schemas](docs/reference/DOCUMENT_SCHEMAS.md) (backed by DuckDB or PostgreSQL)
- 🔌 **[Extensible](docs/guides/CUSTOM_OPERATORS_GUIDE.md)** — load custom operators from Python packages, local paths, or S3 without modifying core code
- 🖥️ **Multiple interfaces** — CLI (`docling-pipelines`, `docling-pipelines-api`), [Python API](docs/guides/PYTHON_API_GUIDE.md) (`DocpipeFlowManager`), [REST API](docs/api/REST_API_SERVER.md) (FastAPI), and a built-in [Documentation MCP server](docs_mcp/README.md) (`docling-pipelines-docs-mcp`) for AI coding agents
- 🌐 **[Web UI](docs/guides/UI_USER_GUIDE.md)** *(beta)* — browser-based pipeline builder and run monitor; experimental and not yet recommended for production workloads

## Installation

```bash
pip install docling-pipelines
```

Requires Python 3.12. Works on macOS and Linux (x86_64 and arm64).

### Optional extras

Install optional capabilities as needed:

```bash
pip install "docling-pipelines[event-streaming]"  # Kafka event consumer & Schema Registry
pip install "docling-pipelines[lineage]"          # OpenLineage data lineage tracking
pip install "docling-pipelines[telemetry]"        # OpenTelemetry tracing & metrics
pip install "docling-pipelines[presidio]"         # Local Presidio PII detection provider
pip install "docling-pipelines[vlm_asr]"          # Docling VLM and ASR pipelines
```

### OCR Installation

RapidOCR is included in the default PyPI installation and works out of the box. Additional OCR extras (`easyocr`, `tesserocr`, `ocrmac`) are also available. For advanced setups, platform-specific extras, or other OCR backends, see the [Extract Operator Guide](docs/operators/extract/extract_operator_readme.md).

### Lightweight variant

For a lightweight version of docling-pipelines that excludes certain operator dependencies, see [docs/guides/SLIM_VARIANT.md](docs/guides/SLIM_VARIANT.md).

## Quickstart

### 1. Run a flow (CLI)

```bash
docling-pipelines --flow-file path/to/flow.json
```

Validate without executing:

```bash
docling-pipelines --flow-file flow.json --validate
```

List all available operators or global configuration parameters:

```bash
docling-pipelines --list-operators
docling-pipelines --list-global-config
```

### 2. Python API

```python
from docpipe import DocpipeFlowManager

manager = DocpipeFlowManager(flow_file="path/to/flow.json")
result = manager.execute()
```

Log verbosity is controlled via `DS_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`).

### 3. REST API

Start the FastAPI server (and bundled UI at `/ui`):

```bash
docling-pipelines-api
# or with custom host/port:
uvicorn docpipe.api.main:app --host 0.0.0.0 --port 8080
```

Interactive OpenAPI documentation is available at `http://localhost:8080/api/v1/docs`.

### 4. Documentation MCP Server

Give AI coding assistants searchable access to the documentation corpus:

```bash
docling-pipelines-docs-mcp
```

## UI *(beta)*

> **⚠️ Beta notice:** The web UI is experimental and **not production-ready**. It is under active development and may change significantly between releases. For production workloads, use the CLI, Python API, or REST API.

A browser-based UI for building flows and monitoring runs is included in this repository under [`frontend/`](frontend/).

Docling pipelines includes a React + TypeScript frontend (IBM Carbon Design System) served by the FastAPI backend at `/ui`.

### Development setup

**Prerequisites:** Node.js 22.15.1 (use `nvm use` in the `frontend/` directory), npm.

**1. Start the backend:**
```bash
uvicorn docpipe.api.main:app --reload --host 0.0.0.0 --port 8080
```

**2. Start the frontend dev server (separate terminal):**
```bash
cd frontend
nvm use
npm install
npm run dev
# UI available at http://localhost:3000
```

### Production (bundled with the wheel)

The frontend is automatically built and bundled into the wheel during `uv build`. When `node` is available on `PATH`, the bundled Node.js BFF sidecar starts automatically alongside FastAPI. After installing:
```bash
uvicorn docpipe.api.main:app --host 0.0.0.0 --port 8080
# UI available at http://localhost:8080/ui
```

For full details see [FRONTEND_BUILD_INTEGRATION.md](FRONTEND_BUILD_INTEGRATION.md) and the [Frontend README](frontend/README.md).

## Documentation

Check out the full [documentation](docs/README.md) for installation, flow authoring, operator reference, and more:

- [Quick Start Guide](QUICKSTART.md) — first pipeline in under 5 minutes
- [Pipeline Setup Guide](USER_GUIDE_PIPELINE_SETUP.md) — complete setup with Ollama, OpenSearch, and flow examples
- [Flow Authoring Format](docs/guides/FLOW_AUTHORING_FORMAT.md) — declarative flow authoring
- [Operator Reference](docs/reference/OPERATORS.md) — full parameter specs for all operators
- [Global Configuration Reference](docs/reference/GLOBAL_CONFIG.md) — micro-batching, incremental processing, and Prefect settings
- [REST API Server](docs/api/REST_API_SERVER.md) — endpoints, OAuth2/LDAP authentication, and ACL document retrieval
- [Event Streaming Guide](docs/guides/EVENT_STREAMING_GUIDE.md) — Kafka event-driven execution and routing-key mappings
- [Observability & Lineage](docs/guides/TELEMETRY_SETUP.md) — OpenTelemetry tracing, [OpenLineage](docs/integrations/openlineage/OPENLINEAGE_GUIDE.md), and [CSV Job Reports](docs/guides/JOB_REPORT_GENERATION.md)
- [Vault Integration](docs/guides/VAULT_INTEGRATION_GUIDE.md) — HashiCorp Vault `vault://` secret resolution
- [Deployment Guides](docs/deployment/DOCKER_COMPOSE.md) — Docker Compose and [OpenShift](docs/deployment/OPENSHIFT.md) deployment
- [Architecture](ARCHITECTURE.md) — system design and distributed execution patterns
- [Troubleshooting](TROUBLESHOOTING.md) — common issues and solutions

## Available Operators

| Category | Operators |
|---|---|
| **Ingest** | Local Filesystem & Remote Source Ingest (`ingest_source`) — [filesystem, S3, IBM COS, SharePoint, OneDrive, Google Drive, Box, Dropbox, web](docs/operators/ingest/ingest_source_readme.md) |
| **Extract** | Document Extractor (`extract_operator`), ACL Extraction (`acl_operator`) |
| **Functional** | Chunking (`chunker`), Embeddings (`embeddings`), Branching Operator (`branching`), Merge Operator (`merge`), Document ID Hash (`doc_id_hash`), Entity Curation (`entity_curation`), No-op (`noop`) |
| **Quality** | Language Annotator (`lang_detect`), Readability Operator (`readability`), PII and HAP Annotator (`pii_and_hap`), Document Classifier (`document_classifier`), Annotation Filter (`sql_filter`), Redaction (`redaction`), De-duplicator (`ededup`), ML Text Enrichment (`ml_enrichment`), Document Quality (`doc_quality`) |
| **VectorDB** | Vector Database (`vectordb`) — OpenSearch, Milvus, and Milvus Lite |
| **Storage** | Document Set (`document_set`) — DuckDB/PostgreSQL-backed document collections, Storage Output (`storage_output`) — write pipeline output to filesystem, S3, IBM COS, SharePoint, OneDrive, and Google Drive |

For per-operator configuration guides, see [Operator Configuration Guides](docs/reference/OPERATORS.md).

## Examples

Explore [sample flows](examples/) and [DocpipeFlowManager examples](examples/docpipe_flow_manager/) for common pipeline patterns.

For interactive, hands-on tutorials, see the [Jupyter notebook examples](examples/notebooks/README.md).

## Contributing

Please read [Contributing to Docling pipelines](CONTRIBUTING.md) for development setup, code standards, testing requirements, and the pull request process.

## License

The Docling pipelines codebase is under the [MIT License](LICENSE).
