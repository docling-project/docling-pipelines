# Docling Pipelines Quick Start Guide

**Get your first pipeline running in under 5 minutes!**

This guide provides the fastest path from installation to a working document processing pipeline. For detailed setup and advanced features, see [`USER_GUIDE_PIPELINE_SETUP.md`](USER_GUIDE_PIPELINE_SETUP.md).

---

## Prerequisites Check (30 seconds)

Before starting, verify you have:

```bash
# Check Python 3.12
python3.12 --version
# Expected: Python 3.12.x

# Check Node.js 22.15.1 and npm (required to build the bundled frontend)
node --version && npm --version

# Check available disk space (need ~5GB)
df -h .
```

**Don't have Python 3.12?**
- **macOS**: `brew install python@3.12`
- **Ubuntu/Debian**: `sudo apt install python3.12 python3.12-venv`
- **Fedora/RHEL**: `sudo dnf install python3.12`

**Don't have Node.js 22.15.1?**

`uv sync` builds the React frontend as part of the package install, so it fails with `npm not found` if Node.js is missing. The repo pins Node.js 22.15.1 in `frontend/.nvmrc`; a version manager such as [nvm](https://github.com/nvm-sh/nvm) installs the pinned version:

```bash
cd frontend
nvm install   # reads frontend/.nvmrc
nvm use
cd ..
```

On macOS you can install nvm with `brew install nvm`. Run `uv sync` from the same shell so `npm` is on `PATH`.

---

## Setup (1–2 minutes)

Choose the setup mode that fits your needs:
- **Option A — Fast Local Setup (Recommended, Default):** Runs entirely in-process using local HuggingFace `sentence-transformers` embeddings and **Milvus Lite** (`.db` file). Zero Docker/Podman containers or external daemons required.
- **Option B — Full Service Stack (Ollama + OpenSearch):** Installs and starts local Ollama and OpenSearch containers (with OpenSearch Dashboards). See [Option B: Full Service Stack (Ollama + OpenSearch)](#option-b-full-service-stack-ollama--opensearch) below.

### Option A: Fast Local Setup (Zero Containers)

```bash
# Clone the repository
git clone https://github.com/docling-project/docling-pipelines.git
# or, if you forked: git clone https://github.com/<your-username>/docling-pipelines.git
cd docling-pipelines

# Install Python virtual environment and dependencies (includes sentence-transformers & milvus-lite)
uv sync --extra dev
```

> ** Don't have `uv` installed yet?** Run the setup script in Python-only mode to install `uv` and create `.venv` automatically without starting Ollama or OpenSearch:
> ```bash
> chmod +x scripts/setup_docling_pipelines_environment.sh
> ./scripts/setup_docling_pipelines_environment.sh --skip-ollama --skip-opensearch
> ```

---

## Your First Pipeline (1 minute)

Now let's run a complete document processing pipeline (`Ingest → Extract → Chunk → Embed → Store in Milvus Lite`) with zero external services!

### Step 1: Verify Sample Documents

The repository includes sample text files ready to process:

```bash
# View existing sample documents
ls -la sample_documents/
# Output includes: hello.txt, 1kb_file.txt samples
```

**Note:** The sample flow processes these `.txt` files. You can add your own PDF, TXT, or DOCX files to this directory if desired.

### Step 2: Activate Environment

```bash
# Set PYTHONPATH (from project root)
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"

# Activate virtual environment (from project root)
source .venv/bin/activate
```

### Step 3: Run the Pipeline

```bash
# Run the container-free local pipeline (from project root)
docling-pipelines --flow-file sample_flows/quickstart/milvus_lite_integration.json
```

> **Note:** On the first run, `sentence-transformers/all-MiniLM-L6-v2` (~80MB) is downloaded and cached locally by HuggingFace. Notice that `milvus_lite_integration.json` sets `"enable_micro_batching": false` in `global_config` because Milvus Lite uses a single-process file lock on the `.db` file.

### Expected Output

Docling Pipelines provides clean, formatted console output showing pipeline progress in real-time:

```
================================================================================
 FLOW EXECUTION SUMMARY
================================================================================
 Status: Completed
 Total Duration: 11.00s
 Documents: 2 completed, 0 failed, 0 skipped (of 2 total)

 Operator Summary:
 Operator                       Status               Duration     Docs
 ------------------------------------------------------------------------------
 ingest_documents               Completed            < 1s         2/2
 extract_content                Completed            < 1s         2/2
 chunk_documents                Completed            2.00s        2/2
 generate_embeddings            Completed            < 1s         2/2
 store_in_milvus_lite           Completed            1.00s        2/2
================================================================================
```

**Output Features:**
- Real-time operator progress with document counts
- Schema changes showing new columns added by each operator
- Operator-specific metrics (chunk counts, embedding dimensions, etc.)
- Final summary table with per-operator statistics

### Step 4: Verify Success

Check that your documents were processed and persisted to the local Milvus Lite `.db` file:

```bash
python -c '
from pymilvus import MilvusClient

client = MilvusClient("./data/milvus/local_documents.db")
print("Collections:", client.list_collections())
print("Stats:", client.get_collection_stats("local_documents"))
client.close()
'
```

Expected response:

```
Collections: ['local_documents']
Stats: {'row_count': 2}
```

**✅ You succeeded if:**
- Pipeline completes without errors
- `local_documents` collection exists in `./data/milvus/local_documents.db` with `row_count: 2`

**🎉 Congratulations!** You've successfully:
1. ✅ Installed Docling Pipelines and all dependencies
2. ✅ Processed documents through the complete pipeline
3. ✅ Generated local embeddings with Sentence-Transformers and stored them in Milvus Lite

---

## Understanding What Just Happened

Your documents went through this pipeline:

```
📄 Text File → 📥 Ingest → 📝 Extract → ✂️ Chunk → 🧮 Embed → 💾 Store
```

**Each operator did:**

1. **IngestSourceOperator** (filesystem provider): Read sample files (`hello.txt`, `1kb_file.txt`) from disk
2. **ExtractOperator**: Extracted structured content using `docling_library` mode
3. **Chunker**: Split content into chunks using `hybrid` chunking (~512 chars each)
4. **EmbeddingsOperator**: Generated 384-d vector embeddings locally in-process using `sentence-transformers/all-MiniLM-L6-v2`
5. **VectorDBOperator**: Stored vectors and metadata in a local Milvus Lite file (`./data/milvus/local_documents.db`)

---

## Option B: Full Service Stack (Ollama + OpenSearch)

If you want to run pipelines backed by **Ollama** (for local LLM inference/embeddings) and **OpenSearch** (with the OpenSearch Dashboards UI), run the full automated setup:

```bash
# Make setup script executable
chmod +x scripts/setup_docling_pipelines_environment.sh

# Run automated setup (installs uv, Ollama + nomic-embed-text, OpenSearch + Dashboards, and .venv)
./scripts/setup_docling_pipelines_environment.sh --models nomic-embed-text

# Copy environment template
cp .env.example .env
```

**Setup takes 5–10 minutes** depending on your internet connection.

### Verify Services & Run the Ollama + OpenSearch Pipeline

```bash
# 1. Check Ollama (should return list of models)
curl http://localhost:11434/api/tags

# 2. Check OpenSearch (should return cluster info)
curl -u admin:MyStrongPass123! http://localhost:9200

# 3. Run the Ollama + OpenSearch pipeline
docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json

# 4. Query the OpenSearch index to verify
curl -u admin:MyStrongPass123! \
  "http://localhost:9200/sample-documents-index/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{"query": {"match_all": {}}, "size": 1}'
```

---

## What's Next?

### Explore More Examples

```bash
# List all available sample flows
ls -la sample_flows/
```

#### Invoice Processing Example

This flow uses entity extraction (NuExtract) and an LLM-based document classifier. Before running it, install the required dependency and pull the required model:

```bash
# Required for entity extraction with NuExtract
uv pip install qwen-vl-utils

# Required for the document classifier node (openai/llama3.2 via Ollama)
ollama pull llama3.2
```

Then run the flow:

```bash
docling-pipelines --flow-file sample_flows/use_cases/invoice_processing.json
```

### View Your Data in OpenSearch Dashboards

Open your browser to: **http://localhost:5601**
- Username: `admin`
- Password: `MyStrongPass123!` # pragma: allowlist secret

Navigate to **Dev Tools** to run queries against your indexed documents.

### Learn About Operators

```bash
# List all available operators (summary table with Owner, Attributes, Features)
docling-pipelines --list-operators

# Detailed view with full operator parameters
docling-pipelines --list-operators --verbose
```

### Create Your Own Pipeline

1. **Copy the sample flow**: `cp sample_flows/quickstart/milvus_lite_integration.json my_flow.json` (or `complete_pipeline_ollama.json` for Ollama/OpenSearch)
2. **Edit the configuration**: Change `paths`, `chunk_size`, models, etc.
3. **Run your custom flow**: `docling-pipelines --flow-file my_flow.json`

**Flow Format:** Docling Pipelines uses a simplified authoring format where you define operators with `type`, `name`, `config`, and `depends_on` fields. See the **[Flow Authoring Format Guide](docs/guides/FLOW_AUTHORING_FORMAT.md)** for complete examples and best practices.

### Deep Dive Documentation

- **[Flow Authoring Format Guide](docs/guides/FLOW_AUTHORING_FORMAT.md)** - Complete guide to creating flows
- **[Complete Setup Guide](USER_GUIDE_PIPELINE_SETUP.md)** - Detailed installation and configuration
- **[Architecture Overview](ARCHITECTURE.md)** - System design and operator details
- **[README](README.md)** - Full operator reference and examples
- **[Job Stats Metadata Aggregation Guide](docs/internals/NODE_METADATA_AGGREGATION_STRATEGY.md)** - Maintainer rules for micro-batch metadata aggregation
- **[Sample Flows Directory](sample_flows/README.md)** - More pipeline examples by category and use case

---

## Run the Web UI

The frontend source is in `frontend/` and requires Node.js. The Python virtual environment must already be set up (see [Setup](#setup-12-minutes) above).

### Step 1 — Install Node.js 22.15.1

```bash
# With nvm (recommended)
nvm install 22.15.1
nvm use 22.15.1

# Verify
node --version   # v22.15.1
npm --version
```

Don't have nvm? Install it from https://github.com/nvm-sh/nvm, or get Node.js 22 directly:
- **macOS**: `brew install nvm && nvm install && nvm use`
- **Ubuntu/Debian**: use the [NodeSource installer](https://github.com/nodesource/distributions#installation-instructions) — `sudo apt install nodejs npm` alone will install the wrong version
- **Fedora/RHEL**: `sudo dnf module install nodejs:22`
- **Any OS**: download the v22.15.1 installer from https://nodejs.org/en/download

### Step 2 — Start the FastAPI backend

In one terminal, from the project root:

```bash
source .venv/bin/activate
uvicorn docpipe.api.main:app --host 0.0.0.0 --port 8080
```

> **Do not use `python src/docpipe/api/main.py`** when running the UI in dev mode. That invocation automatically starts a BFF sidecar on port 3001, which conflicts with `npm run dev` (which also starts the BFF). Use `uvicorn` as shown above to avoid the port conflict.

### Step 3 — Start the UI

In a second terminal, from the project root:

```bash
cd frontend

# Install dependencies (once)
npm install

# Copy the environment file (once)
cp .env.example .env

# Start the UI
npm run dev
```

Open your browser to **http://localhost:3000/ui/**.

> This starts two processes together: a UI server on port 3000 and a backend proxy (BFF) on port 3001. The BFF forwards all `/api/*` requests to FastAPI on port 8080.

---

## Troubleshooting Quick Fixes

### Setup Script Failed

**Python 3.12 not found:**
```bash
# Install Python 3.12 first, then re-run setup
./scripts/setup_docling_pipelines_environment.sh
```

**Permission denied:**
```bash
chmod +x scripts/setup_docling_pipelines_environment.sh
./scripts/setup_docling_pipelines_environment.sh
```

### Services Not Running

**Ollama not responding:**
```bash
# Check if running
curl http://localhost:11434/api/tags

# If not, start manually
ollama serve &

# Wait 5 seconds, then verify
sleep 5
curl http://localhost:11434/api/tags
```

**OpenSearch not responding:**
```bash
# Check if running
curl -u admin:MyStrongPass123! http://localhost:9200

# If not, start manually
podman-compose -f docker/docker-compose.opensearch.yml up -d

# Wait 30 seconds for startup
sleep 30
curl -u admin:MyStrongPass123! http://localhost:9200
```

### Pipeline Errors

**"ModuleNotFoundError" or import errors:**
```bash
# Ensure PYTHONPATH is set correctly (from project root)
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"

# Verify you're in the right directory
pwd  # Should end with /docling-pipelines
```

**"Connection refused" to Ollama:**
```bash
# Verify Ollama is running
curl http://localhost:11434/api/tags

# Check if models are downloaded
ollama list

# If missing, download required model
ollama pull nomic-embed-text
```

**"Connection refused" to OpenSearch:**
```bash
# Check OpenSearch status
podman-compose -f docker/docker-compose.opensearch.yml ps

# View logs if not running
podman-compose -f docker/docker-compose.opensearch.yml logs

# Restart if needed
podman-compose -f docker/docker-compose.opensearch.yml restart
```

**"File not found" errors:**
```bash
# Ensure sample_documents directory exists
mkdir -p sample_documents

# Verify the flow file path is correct
ls -la sample_flows/quickstart/milvus_lite_integration.json
```

### Still Having Issues?

1. **Check the setup log**: `cat docpipe_setup.log`
2. **View detailed error messages**: Run with debug logging:
   ```bash
   export DS_LOG_LEVEL=DEBUG
   docling-pipelines --flow-file sample_flows/quickstart/milvus_lite_integration.json
   ```
3. **Start fresh**: Clean up and re-run setup:
   ```bash
   # Stop services
   podman-compose -f docker/docker-compose.opensearch.yml down
   pkill -f "ollama serve"

   # Remove config
   rm .docpipe_setup_config docpipe_setup.log

   # Re-run setup
   ./scripts/setup_docling_pipelines_environment.sh
   ```

---

## Quick Reference Commands

```bash
# Activate environment (from project root)
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
source .venv/bin/activate

# Run a flow
docling-pipelines --flow-file path/to/flow.json

# List operators (summary table)
docling-pipelines --list-operators

# List operators (detailed view)
docling-pipelines --list-operators --verbose

# Check services
curl http://localhost:11434/api/tags  # Ollama
curl -u admin:MyStrongPass123! http://localhost:9200  # OpenSearch

# Stop services
podman-compose -f docker/docker-compose.opensearch.yml down
pkill -f "ollama serve"
```

---

## Need Help?

- 📖 **Full Documentation**: [`USER_GUIDE_PIPELINE_SETUP.md`](USER_GUIDE_PIPELINE_SETUP.md)
- 🏗️ **Architecture**: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- 💡 **Examples**: [`sample_flows/README.md`](sample_flows/README.md)
- 🐛 **Issues**: Check existing issues or create a new one

**Happy data processing! 🚀**
