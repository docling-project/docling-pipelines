# Docling Pipelines Pipeline User Guide: Complete Setup and Execution

This comprehensive guide walks you through setting up and executing a complete Docling Pipelines pipeline from document ingestion to vector storage in OpenSearch.

## Table of Contents

1. [Introduction](#1-introduction)
2. [Prerequisites and Installation](#2-prerequisites-and-installation)
3. [Ollama Setup](#3-ollama-setup)
4. [OpenSearch Setup with Podman](#4-opensearch-setup-with-podman)
5. [Creating Your First Flow](#5-creating-your-first-flow)
6. [Running the Pipeline](#6-running-the-pipeline)
7. [Verification and Testing](#7-verification-and-testing)
8. [Troubleshooting](#8-troubleshooting)
9. [Next Steps](#9-next-steps)

---

## Quick Reference

> **⚠️ CRITICAL: Working Directory Requirements**
>
> All `docling-pipelines` commands **MUST** be run from the **project root directory** (`docling-pipelines/`).
>
> **Correct:**
>
> ```bash
> # From project root (docling-pipelines/)
> docling-pipelines --flow-file sample_flows/use_cases/invoice_processing.json
> ```
>
> **Incorrect:**
>
> ```bash
> # From docpipe directory - WILL FAIL with ModuleNotFoundError
> cd src/docpipe
> docling-pipelines --flow-file ...  # ERROR: No module named 'docpipe'
> ```
>
> **Why:** The PYTHONPATH must point to `src` as the source root. Running from subdirectories breaks Python imports.

---

## 1. Introduction

### Quick Start

**For fast setup (5 minutes), see [QUICKSTART.md](QUICKSTART.md)** which provides automated installation and your first pipeline execution.

This guide provides comprehensive details for:
- Manual installation and configuration
- Understanding each component
- Troubleshooting and debugging

### Prerequisites

Before proceeding, ensure you have:
- Python 3.12 installed
- Node.js 22.15.1 and npm installed (the package install builds the bundled frontend; see [QUICKSTART.md](QUICKSTART.md#prerequisites-check-30-seconds))
- 5GB+ available disk space
- Internet connection for downloading dependencies

**Quick setup:** Use the automated script from [QUICKSTART.md](QUICKSTART.md):
```bash
./scripts/setup_docling_pipelines_environment.sh

# Combine options
./scripts/setup_docling_pipelines_environment.sh --interactive --models granite4
```

#### Available Options

| Option                   | Description                                                                          |
| ------------------------ | ------------------------------------------------------------------------------------ |
| `--interactive`          | Enable interactive mode with prompts for each step                                   |
| `--models MODEL1,MODEL2` | Specify Ollama models (comma-separated). Default: granite4,llama3.2,nomic-embed-text |
| `--skip-ollama`          | Skip Ollama installation and setup                                                   |
| `--skip-opensearch`      | Skip OpenSearch installation and setup                                               |
| `--skip-python`          | Skip Python environment setup                                                        |
| `--help`                 | Show help message with all options                                                   |

#### What the Script Installs

**Python Environment:**

- Verifies Python 3.12 is installed
- Installs uv package manager
- Creates virtual environment in `.venv`
- Installs all project dependencies

**Ollama (for LLM operations):**

- Installs Ollama server
- Starts Ollama service on `http://localhost:11434`
- Downloads specified models (default: granite4, llama3.2, nomic-embed-text)

**OpenSearch (for vector storage):**

- Installs Podman or uses existing Docker
- Installs podman-compose
- Starts OpenSearch on `http://localhost:9200`
- Starts OpenSearch Dashboards on `http://localhost:5601`
- Default credentials: admin / `<YOUR_OPENSEARCH_PASSWORD>` (configured in `docker/docker-compose.opensearch.yml`)

#### After Setup Completes

The script creates two files:

- `.docpipe_setup_config` - Configuration settings
- `docpipe_setup.log` - Detailed setup log

**Next steps:**

1. Set PYTHONPATH from project root:

   ```bash
   export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
   ```

   > **Warning:** This must be run from the project root directory (`docling-pipelines`), not from subdirectories. The PYTHONPATH must point to `src` as the source root for Python imports to work correctly.

2. Activate the virtual environment:

   ```bash
   # From project root
   source .venv/bin/activate
   ```

3. Verify installation:

   ```bash
   docling-pipelines --help
   ```

4. Run your first flow:
   ```bash
   docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json
   ```

#### Troubleshooting the Setup Script

**Script fails with "Python 3.12 not found":**

- Install Python 3.12 manually (see [Prerequisites](#2-prerequisites-and-installation))
- Run the script again

**Ollama fails to start:**

- Check if port 11434 is already in use: `lsof -i :11434`
- Start manually: `ollama serve`

**OpenSearch fails to start:**

- Check if ports 9200 or 5601 are in use
- View logs: `podman-compose -f docker/docker-compose.opensearch.yml logs`
- Ensure you're in the project root directory

**Permission denied errors:**

- Make script executable: `chmod +x scripts/setup_docling_pipelines_environment.sh`
- Some operations may require sudo (script will prompt)

**Want to start fresh?**

```bash
# Stop services
podman-compose -f docker/docker-compose.opensearch.yml down
pkill -f "ollama serve"

# Remove configuration
rm .docpipe_setup_config docpipe_setup.log

# Run setup again
./scripts/setup_docling_pipelines_environment.sh
```

---

### Manual Setup

If you prefer manual control or the automated script doesn't work for your environment, follow the detailed manual setup instructions below.

---

### What is Docling Pipelines?

Docling Pipelines is a modular, operator-based data processing framework designed for building flexible data pipelines. It enables you to:

- Ingest documents from various sources
- Extract structured content using AI-powered tools
- Chunk documents for optimal processing
- Generate embeddings for semantic search
- Store vectors in OpenSearch for similarity search

### What This Guide Covers

This guide demonstrates the complete **Ingest → Extract → Chunk → Embeddings → OpenSearch** pipeline, which is the foundation for building Retrieval-Augmented Generation (RAG) systems and semantic search applications.

### Pipeline Overview

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Ingest    │───▶│   Extract   │───▶│    Chunk    │───▶│ Embeddings  │───▶│ OpenSearch  │
│   Local     │    │   Docling   │    │   Hybrid    │    │   Ollama    │    │   Vector    │
│   Folder    │    │             │    │             │    │             │    │   Storage   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

### Prerequisites Overview

Before starting, you'll need:

- **Python 3.12** - Required for Docling Pipelines
- **uv package manager** - Fast Python package management
- **Ollama** - Local LLM server for embeddings
- **Podman or Docker** - For running OpenSearch
- **Basic command-line knowledge** - For running commands
- **ffmpeg** - Required for audio/video processing (M4A, AAC, OGG, FLAC, MP4, AVI, MOV formats)

---

## 2. Prerequisites and Installation

### Python 3.12 Requirement

Docling Pipelines requires Python 3.12. Check your version:

```bash
python --version
# Should output: Python 3.12.x
```

If you need to install Python 3.12:

**macOS (using Homebrew):**

```bash
brew install python@3.12
```

**Linux (Ubuntu/Debian):**

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv
```

### Installing uv Package Manager

uv is a fast Python package manager that Docling Pipelines uses for dependency management.

**Install uv:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Verify installation:**

```bash
uv --version
```

### Installing ffmpeg (Required for Audio/Video Processing)

ffmpeg is required for processing audio formats (M4A, AAC, OGG, FLAC) and all video formats (MP4, AVI, MOV) with Docling ASR.

**macOS (using Homebrew):**

```bash
brew install ffmpeg
```

**Linux (Ubuntu/Debian):**

```bash
sudo apt update
sudo apt install ffmpeg
```

**Linux (RHEL/CentOS/Fedora):**

```bash
sudo dnf install ffmpeg
```

**Verify installation:**

```bash
ffmpeg -version
```

**Note:** If you only process WAV or MP3 audio files, ffmpeg is not required. However, for M4A, AAC, OGG, FLAC audio formats and all video formats, ffmpeg must be installed and available on your PATH.

### Cloning and Setting Up the Project

**1. Clone the repository:**

```bash
git clone https://github.com/docling-project/docling-pipelines.git
cd docling-pipelines
```

> **Note:** If you already have the repository cloned, simply navigate to it:
>
> ```bash
> cd docling-pipelines
> ```

**2. Create virtual environment and install dependencies:**

```bash
# From project root
uv sync --extra dev
```

This command:

- Installs CPython 3.12.13 in a virtual environment (`.venv/` at project root)
- Installs all project dependencies
- Installs development dependencies

> **Note: VLM, ASR, and Docling entity extraction require an additional install step.**
>
> If you intend to use VLM-based text extraction (`text_extraction.provider_config.vlm_pipeline`),
> ASR transcription (`text_extraction.provider_config.asr_pipeline`), or Docling template-based
> entity extraction (`entity_extraction.provider: "docling"`), install the `vlm_asr` optional
> dependency group which provides `docling[vlm,asr]`:
>
> ```bash
> uv sync --extra vlm_asr
> ```

**3. Activate the virtual environment:**

**macOS/Linux:**

```bash
# From project root
source .venv/bin/activate
pre-commit install
```

**Windows:**

```bash
.venv\Scripts\activate
pre-commit install
```

**4. Configure environment variables:**

```bash
# Copy environment template
cp .env.example .env

# The default values work for local development
# Edit .env if you need to customize settings
```

> **HashiCorp Vault (optional):** If your organisation uses Vault for secret management, set `secrets.vault.enabled: true` in `docling-pipelines-config.yaml` and supply `VAULT_ROLE_ID` and `VAULT_SECRET_ID` as environment variables. See the [Architecture Guide — HashiCorp Vault Integration](ARCHITECTURE.md) for full details.

### Verify Installation

```bash
# Check Docling Pipelines CLI is available
docling-pipelines --help

# List available operators
docling-pipelines --list-operators
```

---

## 3. Ollama Setup

### Installing Ollama

Ollama provides local LLM inference for embeddings and entity extraction.

**macOS:**

```bash
brew install ollama
```

**Linux:**

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Verify installation:**

```bash
ollama --version
```

### Starting the Ollama Server

```bash
# Start Ollama server (runs in background)
ollama serve
```

The server will start on `http://localhost:11434`.

### Downloading Models

Download the models you'll use for embeddings and extraction:

```bash
# Embedding model (required for embeddings operator)
ollama pull nomic-embed-text

# Alternative embedding models
ollama pull granite4
ollama pull mxbai-embed-large

# LLM models for entity extraction (optional)
ollama pull llama3.2
ollama pull llama3.1
```

**Verify models are downloaded:**

```bash
ollama list
```

### Verifying Ollama is Running

```bash
# Check server status
curl http://localhost:11434/api/tags

# Should return JSON with list of available models
```

**Expected response:**
```json
{
  "models": [
    {
      "name": "nomic-embed-text:latest",
      ...
    }
  ]
}
```

### Troubleshooting Common Ollama Issues

**Issue: Port 11434 already in use**

```bash
# Find process using port 11434
lsof -i :11434

# Kill the process if needed
kill -9 <PID>

# Restart Ollama
ollama serve
```

**Issue: Model download fails**

```bash
# Check internet connection
# Try downloading again
ollama pull nomic-embed-text

# If still fails, check Ollama logs
ollama logs
```

---

## 4. OpenSearch Setup with Podman

### Installing Podman

Podman is a container engine similar to Docker, used to run OpenSearch.

**macOS:**

```bash
brew install podman
```

**Linux (Ubuntu/Debian):**

```bash
sudo apt update
sudo apt install podman
```

**Linux (Fedora/RHEL):**

```bash
sudo dnf install podman
```

**Verify installation:**

```bash
podman --version
```

**Initialize Podman machine (macOS only):**

```bash
podman machine init
podman machine start
```

### Starting OpenSearch Using podman-compose

**1. Install podman-compose:**

```bash
pip install podman-compose
```

**2. Start OpenSearch:**

```bash
# From project root
podman-compose -f docker/docker-compose.opensearch.yml up -d
```

This starts:
- OpenSearch on `http://localhost:9200`
- OpenSearch Dashboards on `http://localhost:5601`

**3. Wait for OpenSearch to start (30-60 seconds):**

```bash
# Check if OpenSearch is ready
curl -u admin:<YOUR_OPENSEARCH_PASSWORD> http://localhost:9200

# Should return cluster information
```

> **Note:** Replace `<YOUR_OPENSEARCH_PASSWORD>` with the password from `docker/docker-compose.opensearch.yml`.

### Verifying OpenSearch is Running

```bash
# Check cluster health
curl -u admin:<YOUR_OPENSEARCH_PASSWORD> http://localhost:9200/_cluster/health?pretty

# Expected: "status": "green" or "yellow"
```

**Check container status:**

```bash
podman-compose -f docker/docker-compose.opensearch.yml ps
```

### Accessing OpenSearch Dashboards

Open your browser to: **http://localhost:5601**

**Login credentials:**
- Username: `admin`
- Password: `<YOUR_OPENSEARCH_PASSWORD>`

> **Note:** Use the password configured in `docker/docker-compose.opensearch.yml`.

Navigate to **Dev Tools** to run queries against your indexed documents.

### Default Credentials and Security

**Default credentials (for development only):**
- Username: `admin`
- Password: `<YOUR_OPENSEARCH_PASSWORD>`

> **⚠️ Security Warning**: The default password in the docker-compose file is for development only. For production:
> - Change the `OPENSEARCH_INITIAL_ADMIN_PASSWORD` in docker-compose or use environment variables
> - Enable SSL/TLS
> - Configure proper authentication
> - See [Advanced Configuration Guide](docs/guides/ADVANCED_CONFIGURATION.md) for production setup

### Stopping and Cleaning Up OpenSearch

**Stop OpenSearch:**

```bash
podman-compose -f docker/docker-compose.opensearch.yml down
```

**Remove volumes (deletes all data):**

```bash
podman-compose -f docker/docker-compose.opensearch.yml down -v
```

**View logs:**

```bash
podman-compose -f docker/docker-compose.opensearch.yml logs
```

---

## 5. Creating Your First Flow

### Testing with the Sample Flow

**Before creating your own flow**, test your setup using the provided sample flow.

The repository includes a complete, ready-to-run pipeline in `sample_flows/quickstart/complete_pipeline_ollama.json` that demonstrates the full document processing workflow:

- **Ingest** → Reads documents from `./sample_documents`
- **Extract** → Extracts content using Docling
- **Chunk** → Splits documents using hybrid chunking (512 tokens, 128 overlap)
- **Embed** → Generates embeddings using Ollama
- **Store** → Saves vectors to OpenSearch index `sample-documents-index`

**To test your setup:**

> **⚠️ Important:** Commands must be run from the **project root directory** (`docling-pipelines/`), not from subdirectories.

1. Ensure you have sample documents in `./sample_documents/` directory (create it if needed)
2. Run the sample flow:
   ```bash
   # From project root
   docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json
   ```

### Understanding Pipeline Output

Docling Pipelines provides clean, formatted console output showing pipeline progress in real-time.

**Example output:**

```
================================================================================
 FLOW: complete-document-pipeline
 Operators: 5
 Started: 2024-01-15 10:30:00
================================================================================

[ingest] Starting ingest_source...

================================================================================
 ingest (COMPLETED)
================================================================================
 Duration: 0.50s | Documents: 1 processed, 0 failed, 0 skipped

 Data Columns: 8 total (8 added by this operator)
   Added (8): id, name, path, size, created_time, modified_time, content, extension
================================================================================

[extract] Starting extract_operator...
[chunk] Starting chunker...
[embeddings] Starting embeddings...
[vectordb] Starting vectordb...

================================================================================
 FLOW EXECUTION SUMMARY
================================================================================
 Status: COMPLETED
 Total Duration: 15.30s
 Documents: 1 completed, 0 failed, 0 skipped (of 1 total)

 Operator Summary:
 Operator                       Status               Duration     Docs
 ------------------------------------------------------------------------------
 ingest                         COMPLETED            0.50s        1/1
 extract                        COMPLETED            3.20s        1/1
 chunk                          COMPLETED            1.10s        1/1
 embeddings                     COMPLETED            8.50s        1/1
 vectordb                       COMPLETED            2.00s        1/1
================================================================================
```

**Output Features:**
- Real-time operator progress with document counts
- Schema changes showing new columns added by each operator
- Operator-specific metrics (chunk counts, embedding dimensions, etc.)
- Final summary table with per-operator statistics

#### Controlling Log Verbosity

Control log output using the `DS_LOG_LEVEL` environment variable:

```bash
# Debug: Detailed information
export DS_LOG_LEVEL=DEBUG
docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json

# Info: Standard output (default)
export DS_LOG_LEVEL=INFO
docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json

# Warning: Only warnings and errors
export DS_LOG_LEVEL=WARNING
docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json

# Error: Only errors
export DS_LOG_LEVEL=ERROR
docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json
```

### Creating a Custom Flow

For detailed information on creating and configuring flows, see:

**[Flow Configuration Guide](docs/guides/FLOW_CONFIGURATION_GUIDE.md)**

This comprehensive guide covers:
- Flow structure and required fields
- Global configuration options
- Complete operator configuration examples
- Connecting operators
- Schema templates and best practices

---

## 6. Running the Pipeline

### Setting PYTHONPATH

**Critical:** Set PYTHONPATH before running any Docling Pipelines commands:

```bash
# From project root
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
```

> **⚠️ Important:** This must be run from the project root directory, not from subdirectories.

### Activating the Virtual Environment

```bash
# From project root
source .venv/bin/activate
```

### Executing the Flow

```bash
# From project root
docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json
```

**Common CLI options:**

```bash
# List available operators
docling-pipelines --list-operators

# List operators with detailed information
docling-pipelines --list-operators --verbose

# Validate flow without executing
docling-pipelines --flow-file my_flow.json --validate

# Run with debug logging
DS_LOG_LEVEL=DEBUG docling-pipelines --flow-file my_flow.json
```

### Understanding the Output

The pipeline will:
1. Load and validate the flow configuration
2. Execute operators in dependency order
3. Display real-time progress for each operator
4. Show final execution summary with statistics

**Success indicators:**
- All operators show `COMPLETED` status
- No errors in the output
- Final summary shows all documents processed

---

## 7. Verification and Testing

### Verify Ollama Setup

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# List downloaded models
ollama list

# Test embedding generation
curl http://localhost:11434/api/embeddings -d '{
  "model": "nomic-embed-text",
  "prompt": "test"
}'
```

### Verify OpenSearch Setup

```bash
# Check cluster health
curl -u admin:<YOUR_OPENSEARCH_PASSWORD> http://localhost:9200/_cluster/health?pretty

# List indices
curl -u admin:<YOUR_OPENSEARCH_PASSWORD> http://localhost:9200/_cat/indices?v

# Query sample index
curl -u admin:<YOUR_OPENSEARCH_PASSWORD> \
  "http://localhost:9200/sample-documents-index/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{"query": {"match_all": {}}, "size": 1}'
```

### Using OpenSearch Dashboards

1. Open browser to: **http://localhost:5601**
2. Login with credentials: `admin` / `<YOUR_OPENSEARCH_PASSWORD>`
3. Navigate to **Dev Tools**
4. Run queries:

```json
GET sample-documents-index/_search
{
  "query": {
    "match_all": {}
  }
}
```

---

## 8. Troubleshooting

### Common Issues

**Issue: ModuleNotFoundError**

```bash
# Solution: Set PYTHONPATH from project root
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"

# Verify you're in project root
pwd  # Should end with /docling-pipelines
```

**Issue: Ollama connection refused**

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# If not running, start it
ollama serve

# Verify models are downloaded
ollama list
```

**Issue: OpenSearch connection refused**

```bash
# Check OpenSearch status
podman-compose -f docker/docker-compose.opensearch.yml ps

# View logs
podman-compose -f docker/docker-compose.opensearch.yml logs

# Restart if needed
podman-compose -f docker/docker-compose.opensearch.yml restart
```

**Issue: Flow validation failed**

```bash
# Validate flow to see specific errors
docling-pipelines --flow-file my_flow.json --validate

# Check flow syntax and operator configurations
# See Flow Configuration Guide for correct format
```

### Debug Logging

Enable debug logging for detailed troubleshooting:

```bash
export DS_LOG_LEVEL=DEBUG
docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json
```

For comprehensive troubleshooting, see **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)**.

---

## 9. Next Steps

### Explore More Operators

```bash
# List all available operators
docling-pipelines --list-operators

# Get detailed operator information
docling-pipelines --list-operators --verbose
```

**Available operator categories:**
- **Ingest**: IngestSourceOperator (filesystem, S3, IBM COS, SharePoint, OneDrive, Google Drive, Box, CSV, web)
- **Extract**: ExtractOperator (with multiple extraction providers)
- **Quality**: DocumentClassifier, LanguageDetect, Redaction, Dedup
- **Functional**: Chunker, Embeddings, Branching, Merge, NOOP
- **VectorDB**: VectorDBOperator (OpenSearch, Milvus)
- **Storage**: DocumentSetOperator

See **[Operator Reference](docs/reference/OPERATORS.md)** for complete specifications.

### Customize Your Pipeline

1. **Copy the sample flow**: `cp sample_flows/quickstart/complete_pipeline_ollama.json my_flow.json`
2. **Edit the configuration**: Change paths, chunk sizes, models, etc.
3. **Run your custom flow**: `docling-pipelines --flow-file my_flow.json`

**For detailed flow configuration**, see **[Flow Configuration Guide](docs/guides/FLOW_CONFIGURATION_GUIDE.md)**.

### Performance Tuning

For production deployments and performance optimization, see **[Advanced Configuration Guide](docs/guides/ADVANCED_CONFIGURATION.md)** which covers:
- Job stats storage backends (DuckDB, PostgreSQL)
- Incremental metadata for avoiding reprocessing
- Distributed execution with Prefect work pools
- Production deployment patterns

### Programmatic Usage

Use Docling Pipelines as a Python library in your applications:

```python
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

manager = DocpipeFlowManager(flow_file="my_flow.json")
result = manager.execute()
```

**For complete Python API documentation**, see **[Python API Guide](docs/guides/PYTHON_API_GUIDE.md)**.

---

## Additional Resources

### Documentation

- **[QUICKSTART.md](QUICKSTART.md)** - Fast 5-minute setup
- **[Flow Configuration Guide](docs/guides/FLOW_CONFIGURATION_GUIDE.md)** - Creating and configuring flows
- **[Python API Guide](docs/guides/PYTHON_API_GUIDE.md)** - Programmatic usage
- **[Advanced Configuration](docs/guides/ADVANCED_CONFIGURATION.md)** - Production deployment
- **[Operator Reference](docs/reference/OPERATORS.md)** - Complete operator specifications
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Comprehensive troubleshooting
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System design and architecture
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Contributing guidelines

### Examples

- **[Sample Flows](sample_flows/)** - Example flow configurations
- **[Examples Directory](examples/)** - Code examples and patterns
- **[Operator Examples](docs/operators/)** - Detailed operator guides

### Community

- **Issues**: Report bugs and request features
- **Discussions**: Ask questions and share ideas
- **Contributing**: See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines
