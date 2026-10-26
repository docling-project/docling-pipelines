# Docling Pipelines Troubleshooting Guide

This comprehensive guide helps you diagnose and resolve common issues when working with Docling Pipelines pipelines.

## Table of Contents

1. [Quick Diagnostics](#quick-diagnostics)
2. [Common Issues by Category](#common-issues-by-category)
   - [Installation & Setup](#installation--setup)
   - [Ollama Issues](#ollama-issues)
   - [OpenSearch Issues](#opensearch-issues)
   - [Pipeline Execution](#pipeline-execution)
   - [Import/Path Errors](#importpath-errors)
   - [Job Stats and Execution Tracking](#job-stats-and-execution-tracking)
   - [Operator-Specific Issues](#operator-specific-issues)
3. [Error Code Reference](#error-code-reference)
4. [Debugging Guide](#debugging-guide)
5. [Service-Specific Troubleshooting](#service-specific-troubleshooting)
6. [Environment Issues](#environment-issues)
7. [FAQ](#faq)
8. [Getting Help](#getting-help)

---

## Quick Diagnostics

Run these commands to quickly check your Docling Pipelines environment:

```bash
# 1. Check Python version (must be 3.12)
python3.12 --version

# 2. Check if virtual environment is activated
which python  # Should point to .venv/bin/python

# 3. Verify PYTHONPATH is set correctly
echo $PYTHONPATH  # Should include src

# 4. Check Ollama service
curl http://localhost:11434/api/tags

# 5. Check OpenSearch service
curl -u admin:${OPENSEARCH_PASSWORD} http://localhost:9200

# 6. Check Milvus service
python3 -c "from pymilvus import connections; connections.connect(host='localhost', port=19530); print('Milvus: Connected')"

# 7. Verify you're in the project root
pwd  # Should end with /docling-pipelines

# 8. List available Ollama models
ollama list

# 9. Check OpenSearch cluster health
curl -u admin:MyStrongPass123! "http://localhost:9200/_cluster/health?pretty"
```

**Health Check Script:**

```bash
#!/bin/bash
echo "=== Docling Pipelines Environment Health Check ==="
echo ""
echo "1. Python Version:"
python3.12 --version || echo "❌ Python 3.12 not found"
echo ""
echo "2. Virtual Environment:"
which python | grep -q ".venv" && echo "✅ Virtual environment active" || echo "❌ Virtual environment not active"
echo ""
echo "3. PYTHONPATH:"
[[ -n "$PYTHONPATH" ]] && echo "✅ PYTHONPATH set: $PYTHONPATH" || echo "❌ PYTHONPATH not set"
echo ""
echo "4. Ollama Service:"
curl -s http://localhost:11434/api/tags > /dev/null && echo "✅ Ollama running" || echo "❌ Ollama not responding"
echo ""
echo "5. OpenSearch Service:"
curl -s -u admin:MyStrongPass123! http://localhost:9200 > /dev/null && echo "✅ OpenSearch running" || echo "❌ OpenSearch not responding"
echo ""
echo "6. Milvus Service:"
python3 -c "from pymilvus import connections; connections.connect(host='localhost', port=19530)" 2>/dev/null && echo "✅ Milvus running" || echo "❌ Milvus not responding"
```

---

## Common Issues by Category

### Installation & Setup

#### Issue: Python 3.12 Not Found

**Symptoms:**

```
bash: python3.12: command not found
```

**Solutions:**

**macOS:**

```bash
brew install python@3.12
```

**Ubuntu/Debian:**

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-dev
```

**Fedora/RHEL:**

```bash
sudo dnf install python3.12 python3.12-devel
```

**Verify installation:**

```bash
python3.12 --version
```

---

#### Issue: uv Package Manager Not Found

**Symptoms:**

```
bash: uv: command not found
```

**Solution:**

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Add to PATH (add to ~/.bashrc or ~/.zshrc)
export PATH="$HOME/.cargo/bin:$PATH"

# Reload shell
source ~/.bashrc  # or source ~/.zshrc

# Verify installation
uv --version
```

---

#### Issue: Virtual Environment Creation Failed

**Symptoms:**

```
Error: Failed to create virtual environment
```

**Solutions:**

1. **Ensure Python 3.12 is installed:**

```bash
python3.12 --version
```

2. **Remove existing .venv and recreate:**

```bash
# From project root
rm -rf .venv
uv venv --python python3.12
```

3. **Install dependencies:**

```bash
# From project root
uv sync --extra dev
```

---

#### Issue: `fasttext-numpy2` Build Failure on macOS 15+ (Sequoia / Tahoe)

**Symptoms:**

```
× Failed to build `fasttext-numpy2==0.10.4`
...
fatal error: 'istream' file not found
error: command '/usr/bin/c++' failed with exit code 1
```

**Cause:**

`fasttext-numpy2` 0.10.4 compiles a C++ extension from source on macOS because no pre-built
macOS or arm64 wheel is published on PyPI (only Linux `manylinux` wheels are available). On
macOS 15+ with clang 17, the compiler no longer resolves C++ standard library headers at the
deployment target hardcoded in the build (`-mmacosx-version-min=11.0`).

**Solution:**

Set these environment variables before running `uv sync`:

```bash
CPLUS_INCLUDE_PATH=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/c++/v1:/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include \
CXXFLAGS="-isysroot $(xcrun --show-sdk-path) -mmacosx-version-min=14.0" \
uv sync --extra dev
```

To avoid setting these every time, add them to a `.envrc` in the project root (if you use
[direnv](https://direnv.net/)) or to your `~/.zshrc`:

```bash
export CPLUS_INCLUDE_PATH=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/c++/v1:/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include
export CXXFLAGS="-isysroot $(xcrun --show-sdk-path) -mmacosx-version-min=14.0"
```

**Verify Xcode CLT is installed:**

```bash
xcode-select --print-path
# Expected: /Library/Developer/CommandLineTools

xcrun --show-sdk-path
# Expected: /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk
```

If `xcode-select` prints nothing, install the tools first:

```bash
xcode-select --install
```

---

#### Issue: Permission Denied During Setup

**Symptoms:**

```
Permission denied: './scripts/setup_docling_pipelines_environment.sh'
```

**Solution:**

```bash
chmod +x scripts/setup_docling_pipelines_environment.sh
./scripts/setup_docling_pipelines_environment.sh
```

---

#### Issue: Distributed workers show inconsistent or missing job status

**Symptoms:**
```text
Job run exists on the submitter but worker updates do not appear in job status APIs
```

**Likely cause:**
- Filesystem job stats storage is configured with a local path that workers cannot access
- submitter and workers resolve different filesystem paths
- worker environment does not receive the same job stats backend configuration

**Solutions:**
1. Check job management configuration via environment variables and confirm the selected backend matches your deployment model.
2. For distributed execution, prefer PostgreSQL job stats storage.
3. If using filesystem storage, configure a shared filesystem path visible to both submitter and workers.
4. Ensure worker environments inherit the same effective backend configuration and connection settings.
5. If needed, override config explicitly with `DOCPIPE_STORAGE_BACKEND`, `DOCPIPE_FRAMEWORK_TYPE`, `DOCPIPE_JOB_STATS_BASE_DIR`, and PostgreSQL env variables.
6. Review [`docs/integrations/prefect/DISTRIBUTED_EXECUTION_GUIDE.md`](docs/integrations/prefect/DISTRIBUTED_EXECUTION_GUIDE.md) for distributed storage guidance.

---

#### Issue: Job status is stored, but aggregated node metadata looks wrong

**Symptoms:**
```text
Counters are too low or too high
Lists are overwritten instead of combined
Batch progress looks incorrect in aggregated results
```

**Likely cause:**
- a new operator metadata field was added without reviewing aggregation behavior
- the field was left on the default `LAST` strategy when it should use `SUM`, `UNION`, `WEIGHTED_AVERAGE`, or another explicit strategy

**Solutions:**
1. Review [`DEFAULT_STRATEGIES`](src/docpipe/core/job_management/application/aggregation/strategies.py) in [`strategies.py`](src/docpipe/core/job_management/application/aggregation/strategies.py).
2. Add explicit mappings for newly introduced metadata fields when needed.
3. Add or update tests covering multi-batch aggregation behavior.
4. See [`docs/internals/NODE_METADATA_AGGREGATION_STRATEGY.md`](docs/internals/NODE_METADATA_AGGREGATION_STRATEGY.md) for maintainer guidance.

---

#### Issue: Job run ends in crashed or canceled state during batch execution

**Symptoms:**
```text
Batch work starts, but the final job state becomes CRASHED or CANCELED unexpectedly
```

**Likely cause:**
- the outer Prefect flow finished before submitted batch futures completed
- task-runner shutdown canceled in-flight batch work before final job state was recorded cleanly

**Solutions:**
1. Confirm the execution path waits for submitted batch work before the outer flow exits.
2. Check [`PrefectEngine`](src/docpipe/core/orchestration/prefect/prefect_engine.py) behavior when debugging batch failures.
3. Validate that job-management terminal-state updates are still reached on failure paths.
4. Prefer PostgreSQL storage in concurrent/distributed environments to reduce ambiguity in final state updates.

---

### Ollama Issues

#### Issue: Ollama Connection Refused

**Error Code:** `OLLAMA_CONNECTION_FAILED`

**Symptoms:**

```
ConnectionError: Failed to connect to Ollama at http://localhost:11434
Error code: ollama_connection_failed
```

**Diagnosis:**

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags
```

**Solutions:**

1. **Start Ollama server:**

```bash
ollama serve
```

2. **Run in background:**

```bash
ollama serve > /dev/null 2>&1 &
```

3. **Check if port 11434 is in use:**

```bash
lsof -i :11434
# If another process is using it, kill it or change Ollama port
```

4. **Verify Ollama installation:**

```bash
which ollama
ollama --version
```

---

#### Issue: Ollama Model Not Found

**Error Code:** `OLLAMA_MODEL_NOT_FOUND`

**Symptoms:**

```
Error: Model 'granite4' not found
Error code: ollama_model_not_found
```

**Diagnosis:**

```bash
# List installed models
ollama list
```

**Solutions:**

1. **Pull the required model:**

```bash
# For LLM operations
ollama pull granite4

# For embeddings
ollama pull nomic-embed-text

# For entity extraction
ollama pull llama3.2
```

2. **Verify model is available:**

```bash
ollama list | grep granite4
```

3. **Check model size before pulling:**

```bash
# granite4: ~2.5GB
# llama3.2: ~2GB
# nomic-embed-text: ~274MB
```

---

#### Issue: Ollama Using Too Much Memory

**Symptoms:**

- System slowdown
- Out of memory errors
- Ollama process consuming >8GB RAM

**Solutions:**

1. **Use smaller models:**

```bash
# Instead of granite4 (2.5GB), use smaller variants
ollama pull granite4:3b  # Smaller version

# For embeddings, nomic-embed-text is already small (274MB)
ollama pull nomic-embed-text
```

2. **Limit Ollama memory usage:**

```bash
# Set environment variable before starting Ollama
export OLLAMA_MAX_LOADED_MODELS=1
ollama serve
```

3. **Stop unused models:**

```bash
# Ollama automatically unloads models after 5 minutes of inactivity
# To force unload, restart Ollama
pkill -f "ollama serve"
ollama serve
```

---

#### Issue: Slow Ollama Model Downloads

**Symptoms:**

- Model download taking >30 minutes
- Download speed <1MB/s

**Solutions:**

1. **Download smaller models first:**

```bash
# Start with the smallest model
ollama pull nomic-embed-text  # Only 274MB, ~30 seconds

# Then larger models
ollama pull granite4  # 2.5GB, ~5 minutes
```

2. **Check internet connection:**

```bash
# Test download speed
curl -o /dev/null http://speedtest.wdc01.softlayer.com/downloads/test10.zip
```

3. **Use a different mirror (if available):**

```bash
# Check Ollama documentation for mirror options
```

---
### WatsonX Issues

#### Issue: WatsonX Authentication Failed

**Error Code:** `WATSONX_AUTH_FAILED`

**Symptoms:**

```
AuthenticationError: Failed to authenticate with WatsonX
Error: Invalid API key or credentials
```

**Diagnosis:**

```bash
# Check if environment variables are set
echo $WATSONX_API_KEY
echo $WATSONX_CONTAINER_ID
```

**Solutions:**

1. **Set required environment variables:**

```bash
export WATSONX_API_KEY="your-api-key"   #pragma: allowlist secret
export WATSONX_CONTAINER_ID="your-project-or-space-id"
```

2. **Verify API key is valid:**

```bash
# Test authentication with curl
curl -X POST "https://us-south.ml.cloud.ibm.com/ml/v1/text/generation?version=2023-05-29" \
  -H "Authorization: Bearer ${WATSONX_API_KEY}" \
  -H "Content-Type: application/json"
```

3. **Check container ID format:**

```bash
# Project ID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# Space ID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

4. **Verify container kind:**

```bash
# Set container kind if using space instead of project
export WATSONX_CONTAINER_KIND="space"  # or "project" (default)
```

---

#### Issue: WatsonX Model Not Found

**Error Code:** `WATSONX_MODEL_NOT_FOUND`

**Symptoms:**

```
Error: Model 'ibm/granite-13b-chat-v2' not found or not accessible
```

**Solutions:**

1. **Verify model is available in your WatsonX instance:**

Check WatsonX.ai console for available models in your project/space.

2. **Use correct model identifier:**

```json
{
  "entity_extraction": {
    "provider": "watsonx",
    "provider_config": {
      "model_id": "ibm/granite-13b-chat-v2",
      "api_key": "${WATSONX_API_KEY}",
      "container_id": "${WATSONX_CONTAINER_ID}"
    }
  }
}
```

3. **Check model access permissions:**

Ensure your API key has access to the specified model in the project/space.

---

#### Issue: WatsonX Connection Timeout

**Symptoms:**

```
TimeoutError: Request to WatsonX timed out after 120 seconds
```

**Solutions:**

1. **Increase timeout in provider config:**

```json
{
  "entity_extraction": {
    "provider": "watsonx",
    "provider_config": {
      "api_key": "${WATSONX_API_KEY}",
      "container_id": "${WATSONX_CONTAINER_ID}",
      "timeout": 300
    }
  }
}
```

2. **Check network connectivity:**

```bash
# Test connection to WatsonX endpoint
curl -I https://us-south.ml.cloud.ibm.com
```

3. **Verify API base URL:**

```bash
# Set correct region endpoint
export WATSONX_API_BASE_URL="https://us-south.ml.cloud.ibm.com"
# Or use eu-de, eu-gb, jp-tok, etc.
```

---

#### Issue: WatsonX Rate Limiting

**Symptoms:**

```
Error: Rate limit exceeded (429 Too Many Requests)
```

**Solutions:**

1. **Reduce parallel workers:**

```json
{
  "max_workers": 1,
  "entity_extraction": {"provider": "watsonx"}
}
```

2. **Add retry logic in provider config:**

```json
{
  "entity_extraction": {
    "provider": "watsonx",
    "provider_config": {
      "max_retries": 3,
      "retry_delay": 2
    }
  }
}
```

3. **Check WatsonX quota limits:**

Review your WatsonX plan limits and usage in the IBM Cloud console.

---


### OpenSearch Issues

#### Issue: OpenSearch Connection Refused

**Error Code:** `OPENSEARCH_CONNECTION_FAILED`

**Symptoms:**

```
ConnectionError: Failed to connect to OpenSearch at http://localhost:9200
Error code: opensearch_connection_failed
```

**Diagnosis:**

```bash
# Check if OpenSearch is running
curl -u admin:${OPENSEARCH_PASSWORD} http://localhost:9200
```

**Solutions:**

1. **Start OpenSearch using podman-compose:**

```bash
podman-compose -f docker/docker-compose.opensearch.yml up -d
```

2. **Or using docker-compose:**

```bash
docker-compose -f docker/docker-compose.opensearch.yml up -d
```

3. **Wait for startup (30-60 seconds):**

```bash
# Check logs
podman-compose -f docker/docker-compose.opensearch.yml logs -f opensearch-node

# Wait for "Node started" message
```

4. **Verify cluster health:**

```bash
curl -u admin:MyStrongPass123! "http://localhost:9200/_cluster/health?pretty"
```

---

#### Issue: OpenSearch Index Creation Failed

**Error Code:** `OPENSEARCH_INDEX_ERROR`

**Symptoms:**

```
Error: Failed to create index 'my-index'
Error code: opensearch_index_error
```

**Diagnosis:**

```bash
# Check if index already exists
curl -u admin:MyStrongPass123! "http://localhost:9200/_cat/indices?v"
```

**Solutions:**

1. **Delete existing index and recreate:**

```bash
# Delete index
curl -X DELETE -u admin:MyStrongPass123! "http://localhost:9200/my-index"

# Verify deletion
curl -u admin:MyStrongPass123! "http://localhost:9200/_cat/indices?v"
```

2. **Check index settings in flow configuration:**

```json
{
  "type": "vectordb",
  "name": "opensearch_store",
  "config": {
    "provider": "opensearch",
    "index_name": "my-index",  // Must be lowercase, no spaces
    "vector_dimension": 768,  // Must match embedding model dimension
    "provider_config": {
        "host": "localhost",
        "port": 9200,
        "engine": "nmslib",  // Valid: nmslib, faiss, lucene
        "algorithm": "hnsw",
        "space_type": "l2"
    }
  }
}
```

3. **Verify dimension matches embedding model:**

```bash
# nomic-embed-text: 768 dimensions
# Check your model's documentation for correct dimension
```

---

#### Issue: OpenSearch Cluster Status Red

**Symptoms:**

```json
{
  "status": "red",
  "unassigned_shards": 5
}
```

**Diagnosis:**

```bash
# Check cluster health
curl -u admin:MyStrongPass123! "http://localhost:9200/_cluster/health?pretty"

# Check shard allocation
curl -u admin:MyStrongPass123! "http://localhost:9200/_cat/shards?v"
```

**Solutions:**

1. **Restart OpenSearch:**

```bash
podman-compose -f docker/docker-compose.opensearch.yml restart
```

2. **Check disk space:**

```bash
df -h
# OpenSearch requires at least 10% free disk space
```

3. **Reset cluster (WARNING: deletes all data):**

```bash
podman-compose -f docker/docker-compose.opensearch.yml down -v
podman-compose -f docker/docker-compose.opensearch.yml up -d
```

---

#### Issue: OpenSearch Authentication Failed

**Symptoms:**

```
401 Unauthorized
```

**Solutions:**

1. **Verify credentials:**

```bash
# Default credentials from docker/docker-compose.opensearch.yml
# Username: admin
# Password: <your-opensearch-password>

curl -u admin:${OPENSEARCH_PASSWORD} http://localhost:9200
```

2. **Check if credentials were changed:**

```bash
# View docker/docker-compose.opensearch.yml
cat docker/docker-compose.opensearch.yml | grep -A 5 "OPENSEARCH_INITIAL_ADMIN_PASSWORD"
```

3. **Reset admin password:**

```bash
# Stop OpenSearch
podman-compose -f docker/docker-compose.opensearch.yml down

# Edit docker/docker-compose.opensearch.yml and change password
# Restart
podman-compose -f docker/docker-compose.opensearch.yml up -d
```

---

### Milvus Issues

#### Issue: Milvus Connection Refused

**Symptoms:**
- Error: `Connection refused` or `Failed to connect to Milvus`
- Pipeline fails at VectorDB operator with Milvus adapter

**Causes:**
1. Milvus server not running
2. Wrong host/port configuration
3. Firewall blocking connection

**Solutions:**

1. **Check if Milvus is running:**
   ```bash
   # Docker
   docker ps | grep milvus

   # Podman
   podman ps | grep milvus
   ```

2. **Start Milvus if not running:**
   ```bash
   docker-compose -f docker-compose.milvus.yml up -d
   ```

3. **Verify connection:**
   ```bash
   python3 -c "from pymilvus import connections; connections.connect(host='localhost', port=19530); print('Connected successfully')"
   ```

4. **Check configuration in flow:**
   ```json
   {
     "type": "vectordb",
     "name": "milvus_store",
     "config": {
       "provider": "milvus",
       "index_name": "my_collection",
       "provider_config": {
         "host": "localhost",
         "port": 19530
       }
     }
   }
   ```

#### Issue: Milvus Collection Creation Failed

**Symptoms:**
- Error: `Collection already exists` or `Invalid collection name`
- VectorDB operator fails during initialization

**Causes:**
1. Collection name conflicts
2. Invalid collection name format
3. Dimension mismatch with existing collection

**Solutions:**

1. **Drop existing collection:**
   ```bash
   python3 -c "from pymilvus import connections, utility; connections.connect(host='localhost', port=19530); utility.drop_collection('your_collection_name')"
   ```

2. **Use unique collection names:**
   - Avoid special characters
   - Use alphanumeric and underscores only
   - Keep names under 255 characters

3. **Verify dimension matches embeddings:**
   ```json
   {
     "type": "vectordb",
     "name": "milvus_collection",
     "config": {
       "provider": "milvus",
       "index_name": "my_collection",
       "vector_dimension": 768,
       "provider_config": {
         "index_type": "HNSW"
       }
     }
   }
   ```

#### Issue: Milvus Dimension Mismatch

**Symptoms:**
- Error: `Dimension mismatch` or `Invalid vector dimension`
- Insertion fails with dimension error

**Causes:**
1. Configured dimension doesn't match embedding dimension
2. Chunked embeddings not properly detected
3. Wrong embedding model used

**Solutions:**

1. **Verify embedding dimension:**
   ```python
   # Check your embedding model's output dimension
   # For Ollama nomic-embed-text: 768
   # For sentence-transformers: varies by model
   ```

2. **Let auto-detection work:**
   - Remove `vector_dimension` from config to enable auto-detection
   - System will detect dimension from first batch

3. **Match embedding model:**
   ```json
   {
     "type": "embeddings",
     "name": "generate_embeddings",
     "config": {
       "provider": "litellm",
       "provider_config": {
         "model_id": "openai/nomic-embed-text",
         "api_base": "http://localhost:11434/v1"
       },
       "embeddings_column": "embeddings"
     }
   },
   {
     "type": "vectordb",
     "name": "store_in_milvus",
     "config": {
       "provider": "milvus",
       "index_name": "my_collection",
       "vector_dimension": 768,
       "provider_config": {
         "index_type": "HNSW"
       }
     }
   }
   ```

#### Issue: Milvus Index Build Failed

**Symptoms:**
- Error: `Index build failed` or `Invalid index parameters`
- Collection created but index not built

**Causes:**
1. Invalid index type for metric type
2. Insufficient memory for index building
3. Invalid index parameters

**Solutions:**

1. **Use compatible index and metric combinations:**
   ```json
   {
     "type": "vectordb",
     "name": "milvus_hnsw",
     "config": {
       "provider": "milvus",
       "index_name": "my_collection",
       "provider_config": {
         "index_type": "HNSW",
         "metric_type": "L2"
       }
     }
   }
   ```

2. **Adjust index parameters:**
   ```json
   {
     "type": "vectordb",
     "name": "milvus_tuned",
     "config": {
       "provider": "milvus",
       "index_name": "my_collection",
       "provider_config": {
         "index_type": "HNSW",
         "index_parameters": {
           "M": 16,
           "efConstruction": 256
         }
       }
     }
   }
   ```

3. **Check Milvus memory:**
   ```bash
   docker stats milvus-standalone
   ```
#### Issue: Unable to Access Watsonx.data Milvus from macOS

**Symptoms:**
- Error: `MilvusException: (code=2, message=Fail connecting to server on <host>:<port>)`
- Connection fails when accessing watsonx.data Milvus from non-VM macOS system
- Works fine from Linux or VM environments

**Cause:**
- gRPC DNS resolution issue on macOS when connecting to watsonx.data Milvus
- The default DNS resolver doesn't work properly with GRPC certificates on macOS

**Solution:**

Set the `GRPC_DNS_RESOLVER` environment variable to `"native"` before running your Python script:

```python
import os
os.environ["GRPC_DNS_RESOLVER"] = "native"

from pymilvus import connections
connections.connect(
    alias="<db_name>",
    host="<host>",
    port=443,
    secure=True,
    server_name="<host>",
    user="<username>",
    password="<password>"
)
```

**Alternative: Set environment variable before execution:**

```bash
export GRPC_DNS_RESOLVER="native"
docling-pipelines --flow-file sample_flows/vectordb/milvus_integration.json
```

**Verification Steps:**

1. Check if Milvus instance was deleted and recreated (GRPC server/host URL might have changed)
2. Verify the certificate is a GRPC certificate (not an https certificate)
3. Add the environment variable setting to your script or shell

**Reference:**
- [IBM watsonx.data Documentation](https://www.ibm.com/docs/en/watsonxdata/standard/2.3.x?topic=milvus-unable-access-from-non-vm-macos-system)

---


### Pipeline Execution

#### Issue: Flow Validation Failed

**Error Code:** `FLOW_VALIDATION_FAILED`

**Symptoms:**

```
FlowValidationException: Invalid Flow definition
Error code: flow_validation_failed
```

**Common Validation Errors:**

1. **Missing Required Operator:**

```
Error: The first operator in the flow must be an "Ingest data" operator
Message code: INGEST_OPERATOR_MISPLACED
```

**Solution:** Ensure your flow starts with an ingest operator:

```json
{
  "flow": [
    {
      "type": "ingest_source",
      "name": "ingest_1",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["sample_documents"]}
      }
    }
  ]
}
```

2. **Disconnected Operators:**

```
Error: Flow contains disconnected operators
Message code: DISJOINT_OPERATORS_DETECTED
```

**Solution:** Ensure all operators are connected via edges:

```json
{
  "edges": [
    { "source": "ingest_1", "target": "extract_1" },
    { "source": "extract_1", "target": "chunk_1" }
  ]
}
```

3. **Duplicate Operator Names:**

```
Error: Same operator name(s) are used for multiple operators
Message code: OPERATOR_NAME_REPEATED
```

**Solution:** Use unique IDs for each operator node.

---

#### Issue: Flow Execution Failed

**Error Code:** `FLOW_EXECUTION_FAILED`

**Symptoms:**

```
FlowExecutionFailedException: Pipeline execution failed
Error code: flow_execution_failed
```

**Diagnosis:**

```bash
# Enable debug logging
export DS_LOG_LEVEL=DEBUG
docling-pipelines --flow-file my_flow.json
```

**Common Causes:**

1. **Input files not found:**

```bash
# Verify input folder exists
ls -la sample_documents/

# Check file paths in flow configuration
```

2. **Operator configuration invalid:**

```bash
# Check operator parameters match requirements
# See operator documentation in README.md
```

3. **Service unavailable (Ollama/OpenSearch):**

```bash
# Verify services are running
curl http://localhost:11434/api/tags
curl -u admin:${OPENSEARCH_PASSWORD} http://localhost:9200
```

---

#### Issue: Prefect Flow Task Failed

**Error Code:** `PREFECT_FLOW_TASK_FAILED`

**Symptoms:**

```
PrefectFlowFailed: Task execution failed
Error code: prefect_flow_failed
```

**Solutions:**

1. **Check Prefect logs:**

```bash
# Logs are in the terminal output
# Look for the specific task that failed
```

2. **Run with verbose logging:**

```bash
export DS_LOG_LEVEL=DEBUG
docling-pipelines --flow-file my_flow.json
```

3. **Check operator-specific errors:**

```bash
# Each operator logs its own errors
# Look for the operator name in the error message
```

---
#### Issue: Documents Being Skipped (Already Ingested) - CLI Execution

**Applies To:** `docling-pipelines` CLI execution only

**Symptoms:**

```
Documents are being skipped during ingestion with "already ingested" messages, even though they should be processed
```

**Cause:**

When using `docling-pipelines`, multiple flows with the same `flow_name` will generate the same `job_id`, causing incremental metadata conflicts. Documents processed in one pipeline may be incorrectly marked as processed in another pipeline with the same flow_name.

**Diagnosis:**

```bash
# Check if multiple flows use the same flow_name
grep -r "flow_name" sample_flows/*.json

# Example: Both flows below would generate the same job_id (UUID v5)
# Flow 1: flow_name "my-pipeline" → job_id "5f543fcf-ccf4-5537-a2a5-e6bdca4f6060"
# Flow 2: flow_name "my-pipeline" → job_id "5f543fcf-ccf4-5537-a2a5-e6bdca4f6060" (conflict!)
```

**Solution:**

1. **Use unique flow_name for each logically different pipeline:**

**Before (Problematic):**
```json
// flow1.json
{
  "flow_name": "document-pipeline",
  "description": "PDF processing pipeline",
  "flow": [...]
}

// flow2.json  
{
  "flow_name": "document-pipeline",
  "description": "Word document processing pipeline",
  "flow": [...]
}
```

**After (Fixed):**
```json
// flow1.json
{
  "flow_name": "pdf-document-pipeline",
  "description": "PDF processing pipeline",
  "flow": [...]
}

// flow2.json
{
  "flow_name": "word-document-pipeline",
  "description": "Word document processing pipeline",
  "flow": [...]
}
```

2. **Force re-ingestion if you need to reprocess documents:**

```json
{
  "flow_name": "my-pipeline",
  "global_config": {
    "force_ingest": true
  },
  "flow": [...]
}
```

**Prevention:**

- Use descriptive, unique flow_name values for each logically different pipeline
- Document your flow_name conventions in your project
- The job_id is automatically generated from flow_name as a deterministic UUID v5 (36-character format)

**Note:** This issue does not apply when using `DocpipeFlowManager` programmatically with custom job_id parameters.

**Related Documentation:**
- See [`docs/guides/FLOW_CONFIGURATION_GUIDE.md`](docs/guides/FLOW_CONFIGURATION_GUIDE.md#flow-identification-flow_name-and-job_id) section "Flow Identification: flow_name and job_id"

---


### Import/Path Errors

#### Issue: ModuleNotFoundError

**Symptoms:**

```
ModuleNotFoundError: No module named 'docpipe_app'
ModuleNotFoundError: No module named 'common'
ModuleNotFoundError: No module named 'core'
```

**Root Cause:** PYTHONPATH not set correctly or running from wrong directory.

**Solutions:**

1. **Set PYTHONPATH correctly (from project root):**

```bash
# Navigate to project root
cd /path/to/docling-pipelines

# Set PYTHONPATH
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"

# Verify
echo $PYTHONPATH
```

2. **Ensure you're in the project root:**

```bash
pwd  # Should end with /docling-pipelines

# If not, navigate to project root
cd /path/to/docling-pipelines
```

3. **Activate virtual environment:**

```bash
# From project root
source .venv/bin/activate
```

4. **Add to shell profile for persistence:**

```bash
# Add to ~/.bashrc or ~/.zshrc
echo 'export PYTHONPATH="/path/to/docling-pipelines/src:${PYTHONPATH}"' >> ~/.bashrc
source ~/.bashrc
```

---

#### Issue: Running from Wrong Directory

**Symptoms:**

```
FileNotFoundError: [Errno 2] No such file or directory: 'sample_flows/...'
```

**Solution:**

**Always run docling-pipelines from the project root:**

```bash
# ✅ CORRECT: From project root
cd /path/to/docling-pipelines
docling-pipelines --flow-file sample_flows/use_cases/invoice_processing.json

# ❌ INCORRECT: From subdirectory - will cause path resolution issues
cd some/subdirectory
docling-pipelines --flow-file ...  # WILL FAIL
```

---

#### Issue: File Paths in Flow Configuration

**Symptoms:**

```
FileNotFoundError: Input folder not found: ~/documents
```

**Solutions:**

1. **Use absolute paths:**

```json
{
  "config": {
    "paths": "/Users/username/docling-pipelines/sample_documents"
  }
}
```

2. **Use relative paths from project root:**

```json
{
  "config": {
    "paths": "sample_documents"
  }
}
```

3. **Avoid using ~ or $HOME:**

```bash
# ❌ Don't use
"paths": "~/documents"

# ✅ Use instead
"paths": "/Users/username/documents"
```

---

### Operator-Specific Issues

#### Issue: Chunker Invalid Chunk Type

**Error Message:**

```
Invalid chunk_type: invalid_type
Message code: CHUNKER_INVALID_CHUNK_TYPE
```

**Valid chunk types:**

- `simple`: Fixed-size chunking
- `semantic`: Semantic similarity-based chunking
- `hybrid`: Docling-based chunking (requires ExtractOperator)

**Solution:**

```json
{
  "type": "chunker",
  "name": "semantic_chunker",
  "config": {
    "chunk_type": "semantic", // Must be: simple, semantic, or hybrid
    "chunk_size": 512,
    "chunk_overlap": 50
  }
}
```
#### Issue: Semantic Chunking Requires Embeddings Support

**Error Message:**

```
This server does not support embeddings
```

or chunking operation fails when using `chunk_type: "semantic"`.

**Root Cause:**

Semantic chunking requires Ollama embeddings support to calculate semantic similarity between text segments. This error occurs when:
- Ollama doesn't have an embeddings model installed
- Ollama version is outdated and lacks embeddings support
- The embeddings endpoint is not accessible

**Solutions:**

1. **Install an embeddings model:**

```bash
ollama pull granite4
```

2. **Update Ollama to the latest version:**

```bash
# macOS
brew upgrade ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

3. **Switch to simple chunking in your flow JSON:**

```json
{
  "type": "chunker",
  "name": "chunker_node",
  "config": {
    "chunk_type": "simple",  // Changed from "semantic"
    "chunk_size": 512,
    "chunk_overlap": 50
  }
}
```

**Verification:**

Test embeddings support:

```bash
curl http://localhost:11434/api/embeddings -d '{
  "model": "granite4",
  "prompt": "test"
}'
```

**See Also:**
- [QUICKSTART.md](QUICKSTART.md) for Ollama setup instructions
- [Chunker documentation](docs/operators/functional/chunker_readme.md) for chunking strategies


#### Issue: Audio/Video Processing Fails with ffmpeg Error

**Error Message:**

```
ffmpeg not found or codec error during audio/video processing
```

**Symptoms:**

- Audio files (M4A, AAC, OGG, FLAC) fail to process
- Video files (MP4, AVI, MOV) fail to process
- Error mentions "ffmpeg" or "codec"

**Diagnosis:**

```bash
# Check if ffmpeg is installed
ffmpeg -version

# Check if ffmpeg is in PATH
which ffmpeg  # macOS/Linux
where ffmpeg  # Windows
```

**Solutions:**

1. **Install ffmpeg:**

**macOS:**
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

2. **Verify installation:**
```bash
ffmpeg -version
```

3. **Add ffmpeg to PATH (if installed but not found):**

**macOS:**
```bash
export PATH="/opt/homebrew/bin:$PATH"
# Add to ~/.zshrc or ~/.bash_profile for persistence
```

**Linux:**
```bash
export PATH="/usr/local/bin:$PATH"
# Add to ~/.bashrc for persistence
```

4. **Restart terminal after installation**

**Note:** WAV and MP3 audio files do not require ffmpeg and should work without it.

**Supported Formats:**
- **Requires ffmpeg**: M4A, AAC, OGG, FLAC (audio), MP4, AVI, MOV (video)
- **No ffmpeg needed**: WAV, MP3 (audio)

---

#### Issue: Embeddings Invalid Type

**Error Message:**

```
Invalid embeddings type: invalid_type
Message code: EMBEDDINGS_INVALID_TYPE
```

**Valid embeddings types:**

- `huggingface`: Native HuggingFace local or API embeddings
- `litellm`: LiteLLM-managed embedding providers (100+ including Ollama, HuggingFace API, OpenAI, etc.)
- `watsonx`: Native IBM watsonx.ai adapter

**Solution:**

```json
{
  "operator_type": "EmbeddingsOperator",
  "operator_params": {
    "provider": "watsonx",
    "model_id": "ibm/slate-125m-english-rtrvr",
    "provider_config": {
      "api_key": "${WATSONX_API_KEY}",
      "api_base": "${WATSONX_API_BASE}",
      "container_id": "${WATSONX_CONTAINER_ID}",
      "container_kind": "project"
    }
  }
}
```

**Important distinction:**

- Native watsonx uses `api_base` and `container_id`
- LiteLLM watsonx uses LiteLLM-specific parameter names such as `api_base` and provider-specific IDs

---

#### Issue: SQL Filter Dropping Mandatory Columns

**Error Message:**

```
Mandatory features drop attempted: ['id', 'content']
Message code: DROPPING_MANDATORY_FEATURES
```

**Mandatory columns that cannot be dropped:**

- `id`: Document identifier
- `content`: Document content
- `pages_processed`: Processing metadata

**Solution:**

```json
{
  "type": "sql_filter",
  "name": "filter_documents",
  "config": {
    "filter_criteria": "SELECT * FROM table WHERE length > 100"
    // Don't use: SELECT column1, column2 (missing id, content)
  }
}
```

---

#### Issue: Extract Operator Missing

**Error Message:**

```
Extract operator is either missing or not connected in the flow
Message code: EXTRACT_OPERATOR_MISSING
```

**Solution:** Add an extract operator before chunking:

```json
{
  "flow": [
    {
      "type": "ingest_source",
      "name": "ingest_1",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["./sample_documents"]}
      }
    },
    {
      "type": "extract_operator",
      "name": "extract_1",
      "config": {
        "text_extraction": {
          "provider": "docling_library"
        }
      },
      "depends_on": ["ingest_1"]
    },
    {
      "type": "chunker",
      "name": "chunk_1",
      "config": {
        "chunk_type": "simple",
        "chunk_size": 512
      },
      "depends_on": ["extract_1"]
    }
  ]
}

### Document Set Storage Issues

**Problem:** Database file not created or cannot be found

**Symptoms:**
```text
FileNotFoundError: Database file not found at data/duckdb/document_sets.db
```

**Solutions:**
1. Verify workspace directory is correct:
   ```bash
   pwd  # Should be at project root
   ```

2. Check database path configuration:

   ```python
   # Default path is relative to workspace
   data/duckdb/document_sets.db
   ```

3. Ensure directory exists:

   ```bash
   mkdir -p data/duckdb
   ```

4. Check file permissions:
   ```bash
   ls -la data/duckdb/
   chmod 755 data/duckdb
   ```

---

**Problem:** Document set name validation errors

**Symptoms:**

```
ValueError: Invalid document_set_name: must be alphanumeric with underscores/hyphens
```

**Solutions:**

1. Use valid characters only (alphanumeric, underscore, hyphen):

   ```json
   "document_set_name": "my_documents_2024"  // Valid
   "document_set_name": "my documents!"      // Invalid
   ```

2. Avoid special characters and spaces
3. Keep names under 255 characters

---

**Problem:** Schema evolution errors when adding new columns

**Symptoms:**

```
DuckDBError: Column 'new_field' does not exist in table
```

**Solutions:**

1. Schema evolution is automatic - verify the operator is receiving the new column
2. Check PyArrow table schema before storage:

   ```python
   print(table.schema)
   ```

3. Ensure column names are valid SQL identifiers
4. Restart pipeline if schema changes are not detected

---

**Problem:** Row count mismatch after storage

**Symptoms:**

```
AssertionError: Row count mismatch: expected 100, got 95
```

**Solutions:**

1. Check for data corruption in upstream operators
2. Verify no filtering is happening before storage
3. Enable debug logging to see detailed row counts:

   ```bash
   DS_LOG_LEVEL=DEBUG docling-pipelines --flow-file your_flow.json
   ```

4. Inspect the PyArrow table before storage:
   ```python
   print(f"Table has {len(table)} rows")
   ```

---

**Problem:** Database locked or in use

**Symptoms:**

```
sqlite3.OperationalError: database is locked
```

**Solutions:**

1. Close other connections to the database
2. Check for running processes:

   ```bash
   lsof data/duckdb/document_sets.db
   ```

3. Wait for concurrent operations to complete
4. Use connection pooling for concurrent access

---

**Problem:** Metadata not being stored correctly

**Symptoms:**

- Custom metadata fields missing from document set
- Metadata appears as empty dictionary

**Solutions:**

1. Verify metadata is valid JSON:

   ```json
   "metadata": {
     "key": "value",
     "number": 123,
     "boolean": true
   }
   ```

2. Check metadata is not null or undefined
3. Ensure metadata values are JSON-serializable
4. Avoid nested objects deeper than 2-3 levels

---

**Problem:** Cannot query stored documents

**Symptoms:**

```
DuckDBError: Table 'document_set_name' does not exist
```

**Solutions:**

1. Verify document set was created successfully:

   ```python
   from storage.duckdb_storage import DuckDBStorage
   storage = DuckDBStorage(db_path="data/duckdb/document_sets.db")
   tables = storage.list_tables()
   print(tables)
   ```

2. Check table name matches exactly (case-sensitive)
3. Ensure database file path is correct
4. Verify flow completed without errors

---

**Problem:** Performance issues with large document sets

**Symptoms:**

- Slow write operations
- High memory usage
- Database file growing very large

**Solutions:**

1. Use batch processing for large datasets
2. Consider partitioning large document sets
3. Monitor database file size:

   ```bash
   du -h data/duckdb/document_sets.db
   ```

4. Optimize queries with proper indexing
5. Use `retain_deleted_docs: false` to avoid storing deleted documents

---

**Problem:** REST API document set operations failing

**Symptoms:**

```
HTTP 500: Internal server error when creating document set
```

**Solutions:**

1. Check API server logs for detailed errors
2. Verify database path is accessible by API server
3. Ensure proper permissions on database directory
4. Check API authentication if enabled
5. Verify request payload matches expected schema

---

## Error Code Reference

### Flow Validation and Execution Errors

| Error Code | Description | Common Causes | Solutions |
|------------|-------------|---------------|-----------|
| `FLOW_VALIDATION_FAILED` | Flow configuration is invalid | Missing operators, invalid connections, malformed JSON | Check flow structure, validate JSON syntax, ensure all required operators present |
| `FLOW_EXECUTION_FAILED` | Pipeline execution failed | Operator errors, service unavailable, invalid data | Check logs, verify services running, validate input data |
| `PREFECT_FLOW_TASK_FAILED` | Prefect task execution failed | Task timeout, resource exhaustion, operator error | Check Prefect logs, increase resources, fix operator configuration |

### Flow CRUD Operation Errors

| Error Code | Description | Common Causes | Solutions |
|------------|-------------|---------------|-----------|
| `FLOW_NOT_FOUND` | Flow file not found | Incorrect path, file deleted | Verify file path, check file exists |
| `FLOW_ALREADY_EXISTS` | Flow with same name exists | Duplicate flow name | Use unique flow name or delete existing flow |
| `FLOW_INVALID_DATA` | Flow data is invalid | Malformed JSON, missing fields | Validate JSON, check required fields |
| `FLOW_STORAGE_ERROR` | File system error | Permission denied, disk full | Check permissions, free disk space |

### Operator Errors

| Error Code | Description | Common Causes | Solutions |
|------------|-------------|---------------|-----------|
| `OPERATOR_CONFIGURATION_INVALID` | Operator config invalid | Missing parameters, invalid values | Check operator documentation, validate parameters |
| `OPERATOR_EXECUTION_FAILED` | Operator execution failed | Runtime error, invalid input | Check operator logs, validate input data |
| `SQL_FILTER_ERROR` | SQL filter error | Invalid SQL syntax, column not found | Validate SQL syntax, check column names |

### Integration Errors

| Error Code | Description | Common Causes | Solutions |
|------------|-------------|---------------|-----------|
| `OLLAMA_CONNECTION_FAILED` | Cannot connect to Ollama | Ollama not running, wrong port | Start Ollama server, check port 11434 |
| `OLLAMA_MODEL_NOT_FOUND` | Model not available | Model not pulled | Pull model: `ollama pull model-name` |
| `OPENSEARCH_CONNECTION_FAILED` | Cannot connect to OpenSearch | OpenSearch not running, wrong credentials | Start OpenSearch, verify credentials |
| `OPENSEARCH_INDEX_ERROR` | Index operation failed | Index exists, invalid settings | Delete index or use different name |

### Configuration and Service Errors

| Error Code | Description | Common Causes | Solutions |
|------------|-------------|---------------|-----------|
| `INVALID_CONFIGURATION` | Configuration error | Missing settings, invalid values | Check configuration file, validate settings |
| `EXTERNAL_SERVICE_ERROR` | External service error | API error, network failure | Check service status, verify connectivity |
| `HTTP_ERROR` | HTTP request failed | Invalid URL, server error | Check URL, verify server status |
| `CONNECTION_ERROR` | Network connection error | Network down, firewall blocking | Check network, verify firewall rules |
| `INVALID_RESPONSE` | Invalid response from service | Malformed response, wrong format | Check service logs, verify API version |

---

## Debugging Guide

### Enable Debug Logging

**Set log level to DEBUG:**
```bash
DS_LOG_LEVEL=DEBUG docling-pipelines --flow-file my_flow.json
```

Or set as environment variable:
```bash
export DS_LOG_LEVEL=DEBUG
docling-pipelines --flow-file my_flow.json
```

**Log levels:**

- `DEBUG`: Detailed diagnostic information
- `INFO`: General informational messages (default)
- `WARNING`: Warning messages
- `ERROR`: Error messages
- `CRITICAL`: Critical errors

---

### Log File Locations

**Prefect logs:**

```bash
# Logs are output to terminal by default
# To save to file:
docling-pipelines --flow-file my_flow.json > pipeline.log 2>&1
```

**Operator logs:**

```bash
# Each operator logs to the same output stream
# Look for operator name in log messages:
# [INFO] Operator: ingest_source_filesystem - Processing...
```

**Service logs:**

**Ollama:**

```bash
# If running in background
tail -f /tmp/ollama.log  # Or wherever you redirected output
```

**OpenSearch:**

```bash
podman-compose -f docker/docker-compose.opensearch.yml logs -f opensearch-node
```

---

### Reading Log Output

**Typical log format:**

```
[2024-01-15 10:30:45] [INFO] [ingest_source_filesystem] Processing folder: sample_documents
[2024-01-15 10:30:46] [INFO] [ingest_source_filesystem] Found 5 files
[2024-01-15 10:30:47] [INFO] [extract_operator] Extracting content from file1.pdf
[2024-01-15 10:30:50] [ERROR] [extract_operator] Failed to extract: Connection refused
```

**Key information:**

- **Timestamp**: When the event occurred
- **Level**: Severity (INFO, WARNING, ERROR)
- **Operator**: Which operator generated the log
- **Message**: What happened

---

### Common Log Patterns

**Pattern 1: Connection Refused**

```
[ERROR] Failed to connect to http://localhost:11434
```

**Meaning:** Service (Ollama/OpenSearch) not running  
**Action:** Start the service

---

**Pattern 2: File Not Found**

```
[ERROR] FileNotFoundError: [Errno 2] No such file or directory: 'sample_documents'
```

**Meaning:** Input path doesn't exist  
**Action:** Verify path, create directory if needed

---

**Pattern 3: Model Not Found**

```
[ERROR] Model 'granite4' not found in Ollama
```

**Meaning:** Ollama model not pulled  
**Action:** Run `ollama pull granite4`

---

**Pattern 4: Import Error**

```
[ERROR] ModuleNotFoundError: No module named 'docpipe_app'
```

**Meaning:** PYTHONPATH not set correctly  
**Action:** Set PYTHONPATH from project root

---

### Using Python Debugger

**Add breakpoints in code:**

```python
import pdb; pdb.set_trace()
```

**Run with debugger:**

```bash
python -m pdb -m docpipe.cli.docpipe_cli --flow-file my_flow.json
```

---

### Verbose Operator Output

**Enable verbose output using environment variable:**

```bash
# Set debug level for detailed operator output
DS_LOG_LEVEL=DEBUG docling-pipelines --flow-file my_flow.json
```

**Note:** Individual operator verbosity settings (if supported) are separate from the global log level.

---

## Service-Specific Troubleshooting

### Ollama Troubleshooting

#### Check Ollama Status

```bash
# Check if running
curl http://localhost:11434/api/tags

# Check process
ps aux | grep ollama

# Check port
lsof -i :11434
```

#### Ollama Performance Issues

**Slow inference:**

```bash
# Use smaller models
ollama pull granite4:3b  # Instead of granite4:7b

# Check system resources
top  # Look for ollama process
```

**High memory usage:**

```bash
# Limit loaded models
export OLLAMA_MAX_LOADED_MODELS=1
ollama serve
```

#### Ollama Model Issues

**List all models:**

```bash
ollama list
```

**Remove unused models:**

```bash
ollama rm model-name
```

**Update model:**

```bash
ollama pull model-name  # Re-pulls latest version
```

---

### OpenSearch Troubleshooting

#### Check OpenSearch Status

```bash
# Cluster health
curl -u admin:MyStrongPass123! "http://localhost:9200/_cluster/health?pretty"

# Node info
curl -u admin:MyStrongPass123! "http://localhost:9200/_nodes?pretty"

# Indices
curl -u admin:MyStrongPass123! "http://localhost:9200/_cat/indices?v"
```

#### OpenSearch Performance Issues

**Slow indexing:**

```bash
# Check cluster stats
curl -u admin:MyStrongPass123! "http://localhost:9200/_cluster/stats?pretty"

# Increase refresh interval
curl -X PUT -u admin:MyStrongPass123! "http://localhost:9200/my-index/_settings" \
  -H 'Content-Type: application/json' \
  -d '{"index": {"refresh_interval": "30s"}}'
```

**High memory usage:**

```bash
# Check heap usage
curl -u admin:MyStrongPass123! "http://localhost:9200/_cat/nodes?v&h=heap.percent,heap.current,heap.max"

# Adjust heap size in docker/docker-compose.opensearch.yml
# OPENSEARCH_JAVA_OPTS: "-Xms512m -Xmx512m"
```

#### OpenSearch Index Issues

**Delete index:**

```bash
curl -X DELETE -u admin:MyStrongPass123! "http://localhost:9200/my-index"
```

**Reindex data:**

```bash
curl -X POST -u admin:MyStrongPass123! "http://localhost:9200/_reindex" \
  -H 'Content-Type: application/json' \
  -d '{
    "source": {"index": "old-index"},
    "dest": {"index": "new-index"}
  }'
```

**Check index mapping:**

```bash
curl -u admin:MyStrongPass123! "http://localhost:9200/my-index/_mapping?pretty"
```

---

### Milvus Troubleshooting

#### Check Milvus Status
```bash
# Check if running
docker ps | grep milvus

# Test connection
python3 -c "from pymilvus import connections; connections.connect(host='localhost', port=19530); print('Connected')"

# Check collections
python3 -c "from pymilvus import connections, utility; connections.connect(host='localhost', port=19530); print(utility.list_collections())"
```

#### Milvus Performance Issues

**Slow search:**
```bash
# Check collection stats
python3 -c "
from pymilvus import connections, Collection
connections.connect(host='localhost', port=19530)
collection = Collection('your_collection')
print(f'Entities: {collection.num_entities}')
print(f'Index: {collection.index().params}')
"

# Use faster index type
# HNSW is generally faster than IVF_FLAT for most use cases
```

**High memory usage:**
```bash
# Check Milvus container stats
docker stats milvus-standalone

# Reduce index parameters in flow config:
# "M": 8,  # Lower value = less memory
# "efConstruction": 128  # Lower value = less memory
```

#### Milvus Collection Issues

**List collections:**
```bash
python3 -c "from pymilvus import connections, utility; connections.connect(host='localhost', port=19530); print(utility.list_collections())"
```

**Drop collection:**
```bash
python3 -c "from pymilvus import connections, utility; connections.connect(host='localhost', port=19530); utility.drop_collection('collection_name')"
```

**Check collection schema:**
```bash
python3 -c "
from pymilvus import connections, Collection
connections.connect(host='localhost', port=19530)
collection = Collection('your_collection')
print(collection.schema)
"
```

**Query collection:**
```bash
python3 -c "
from pymilvus import connections, Collection
connections.connect(host='localhost', port=19530)
collection = Collection('your_collection')
collection.load()
results = collection.query(expr='pk >= \"\"', output_fields=['pk'], limit=5)
print(results)
"
```

---

### Docling Troubleshooting

#### Docling Extraction Failures

**Symptoms:**

```
[ERROR] Failed to extract content from document.pdf
```

**Solutions:**

1. **Check document format:**

```bash
# Supported formats: PDF, DOCX, PPTX, HTML
file document.pdf  # Verify file type
```

2. **Check document size:**

```bash
# Large documents may timeout
ls -lh document.pdf

# Split large documents if needed
```

3. **Verify Docling dependencies:**

```bash
# From project root
uv sync --extra dev
```

#### Docling Timeout Issues

**Increase timeout in operator configuration:**

```json
{
  "type": "extract_operator",
  "name": "extract_with_timeout",
  "config": {
    "text_extraction": {
      "provider": "docling_library"
    },
    "entity_extraction": {
      "provider": "none"
    },
    "timeout": 300  // Increase from default 60 seconds
  }
}
```

---
### Watsonx Troubleshooting

#### Authentication Issues

**Symptoms:**
- `401 Unauthorized` errors
- "Failed to fetch IAM access token"
- Token refresh failures

**Solutions:**

1. **Verify API key:**
   ```bash
   echo $WATSONX_API_KEY
   ```

2. **Check environment variables:**
   ```bash
   echo $WATSONX_API_BASE
   echo $WATSONX_CONTAINER_ID
   ```

3. **Test connectivity:**
   ```bash
   curl -X GET "${WATSONX_API_BASE}/ml/v1/foundation_model_specs?version=2023-05-29"
   ```

4. **Enable debug logging:**
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

#### Rate Limit Errors

**Symptoms:**
- `429 Too Many Requests` errors
- "Exceeded limit of calls to endpoint"

**Solutions:**
- Reduce batch size in operator configuration
- Add delays between requests
- Request higher rate limits from IBM Cloud

#### Configuration Issues

**Common Mistakes:**
- Using `api_base` instead of `url`
- Using `project_id` instead of `container_id`
- Missing required parameters

**Correct Configuration:**
```json
{
  "provider": "watsonx",
  "model_name": "ibm/slate-125m-english-rtrvr",
  "provider_config": {
    "api_key": "${WATSONX_API_KEY}",
    "api_base": "${WATSONX_API_BASE}",
    "container_id": "${WATSONX_CONTAINER_ID}"
  }
}
```

## Environment Issues

### Python Version Problems

**Issue: Wrong Python version**

```bash
# Check version
python --version  # Should be 3.12.x

# If wrong version, use python3.12 explicitly
python3.12 --version
```

**Solution: Use correct Python version**

```bash
# Recreate virtual environment with Python 3.12 (from project root)
rm -rf .venv
uv venv --python python3.12
source .venv/bin/activate
uv sync --extra dev
```

---

### Virtual Environment Issues

**Issue: Virtual environment not activated**

```bash
# Check if activated
which python  # Should point to .venv/bin/python
```

**Solution: Activate virtual environment**

```bash
# From project root
source .venv/bin/activate
```

**Issue: Virtual environment corrupted**

```bash
# Remove and recreate (from project root)
rm -rf .venv
uv venv --python python3.12
source .venv/bin/activate
uv sync --extra dev
```

---

### Dependency Conflicts

**Issue: Package version conflicts**

```
ERROR: Cannot install package-a and package-b because these package versions have conflicting dependencies
```

**Solution: Update dependencies**

```bash
# From project root
uv sync --extra dev --upgrade
```

**Issue: Missing dependencies**

```
ModuleNotFoundError: No module named 'package_name'
```

**Solution: Install dependencies**

```bash
# From project root
uv sync --extra dev
```

---

### PYTHONPATH Issues

**Issue: PYTHONPATH not set**

```
ModuleNotFoundError: No module named 'docpipe_app'
```

**Solution: Set PYTHONPATH**

```bash
# From project root
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
```

**Verify PYTHONPATH is set correctly:**

```bash
echo $PYTHONPATH
```

**Expected output:**
```
/Users/username/codebase/docling-pipelines/src:...
```

The output should show your project's `src` directory as the first entry. The actual path will match your project location.

**Make permanent:**

```bash
# Add to ~/.bashrc or ~/.zshrc
echo 'export PYTHONPATH="/path/to/docling-pipelines/src:${PYTHONPATH}"' >> ~/.bashrc
source ~/.bashrc
```

---

## FAQ

### General Questions

**Q: What Python version is required?**  
A: Python 3.12 is required. Earlier or later versions are not supported.

**Q: Can I use Docker instead of Podman?**  
A: Yes, Docker and Podman are interchangeable. Use `docker-compose` instead of `podman-compose`.

**Q: Where are the log files stored?**  
A: Logs are output to the terminal by default. Redirect to a file: `docling-pipelines --flow-file my_flow.json > pipeline.log 2>&1`

**Q: How do I stop all services?**  
A:

```bash
# Stop OpenSearch
podman-compose -f docker/docker-compose.opensearch.yml down

# Stop Ollama
pkill -f "ollama serve"
```

**Q: Can I run multiple pipelines simultaneously?**  
A: Yes, but be aware of resource constraints (CPU, memory, GPU if using Ollama).

---

### Installation Questions

**Q: Do I need GPU for Ollama?**  
A: No, Ollama works on CPU. GPU acceleration is optional and improves performance.

**Q: How much disk space is needed?**  
A: Minimum 5GB for models and data. Recommended 10GB+ for production use.

**Q: Can I install on Windows?**  
A: Yes, but use WSL2 (Windows Subsystem for Linux) for best compatibility.

**Q: What if I don't have admin/sudo access?**  
A: You can install in user space using `uv` and run services in containers without root.

---

### Configuration Questions

**Q: How do I change the OpenSearch password?**  
A: Edit `docker/docker-compose.opensearch.yml` and change `OPENSEARCH_INITIAL_ADMIN_PASSWORD`, then restart.

**Q: Can I use a different port for Ollama?**  
A: Yes, set `OLLAMA_HOST` environment variable: `export OLLAMA_HOST=0.0.0.0:11435`

**Q: How do I use a remote OpenSearch cluster?**  
A: Update the `opensearch_url` in your flow configuration to point to the remote cluster.

**Q: Can I use different embedding models?**  
A: Yes, any Ollama model that supports embeddings. Update `model_name` in EmbeddingsOperator configuration.

---

### Pipeline Questions

**Q: How do I process multiple folders?**  
A: Use `IngestSourceOperator` with multiple paths in `connection_params.paths` (e.g. `["./folder1", "./folder2"]`).

**Q: Can I skip the chunking step?**  
A: Yes, but embeddings will be generated for entire documents, which may not be optimal for large documents.

**Q: How do I handle different document types?**  
A: Use BranchingOperator to route different document types to different processing paths.

**Q: What's the maximum document size?**  
A: Depends on available memory. Large documents (>100MB) should be split or processed with increased timeouts.

---

### Performance Questions

**Q: Why is my pipeline slow?**  
A: Common causes:

- Large documents
- Slow embedding generation (use smaller models)
- Network latency to OpenSearch
- Insufficient CPU/memory

**Q: How can I speed up processing?**  
A:

- Use smaller embedding models
- Increase batch sizes
- Use GPU for Ollama (if available)
- Optimize chunk sizes

**Q: How many documents can I process?**  
A: No hard limit, but performance depends on:

- Document size
- Available memory
- OpenSearch cluster capacity

---

### Error Questions

**Q: What does "Connection refused" mean?**  
A: The service (Ollama or OpenSearch) is not running. Start the service and try again.

**Q: What does "Model not found" mean?**  
A: The Ollama model hasn't been pulled. Run `ollama pull model-name`.

**Q: What does "Flow validation failed" mean?**  
A: Your flow configuration has errors. Check the error message for specific issues.

**Q: What does "PYTHONPATH not set" mean?**  
A: The Python import path is not configured. Set PYTHONPATH from the project root.

---

## Getting Help

### Before Reporting Issues

1. **Check this troubleshooting guide**
2. **Review the documentation:**
   - [`README.md`](README.md) - Overview and operator reference
   - [`USER_GUIDE_PIPELINE_SETUP.md`](USER_GUIDE_PIPELINE_SETUP.md) - Complete setup guide
   - [`QUICKSTART.md`](QUICKSTART.md) - Quick start guide
   - [`ARCHITECTURE.md`](ARCHITECTURE.md) - System architecture

3. **Run diagnostics:**

```bash
# Health check
curl http://localhost:11434/api/tags
curl -u admin:${OPENSEARCH_PASSWORD} http://localhost:9200

# Check logs
docling-pipelines --flow-file my_flow.json 2>&1 | tee debug.log
```

4. **Try with debug logging:**

```bash
export DS_LOG_LEVEL=DEBUG
docling-pipelines --flow-file my_flow.json
```

---

### Reporting Bugs

When reporting issues, include:

1. **Environment information:**

```bash
# Python version
python3.12 --version

# OS information
uname -a

# Package versions (from project root)
uv pip list
```

2. **Error message:**

```bash
# Full error output
docling-pipelines --flow-file my_flow.json 2>&1 | tee error.log
```

3. **Flow configuration:**

```bash
# Sanitized flow.json (remove sensitive data)
cat my_flow.json
```

4. **Steps to reproduce:**

- What you were trying to do
- Commands you ran
- Expected vs actual behavior

5. **Service status:**

```bash
# Ollama
curl http://localhost:11434/api/tags

# OpenSearch
curl -u admin:MyStrongPass123! "http://localhost:9200/_cluster/health?pretty"
```

---

### Community Resources

**GitHub Issues:**

- Search existing issues: https://github.com/your-org/docling-pipelines/issues
- Create new issue: https://github.com/your-org/docling-pipelines/issues/new

**Documentation:**

- Main README: [`README.md`](README.md)
- User Guide: [`USER_GUIDE_PIPELINE_SETUP.md`](USER_GUIDE_PIPELINE_SETUP.md)
- Quick Start: [`QUICKSTART.md`](QUICKSTART.md)
- Architecture: [`ARCHITECTURE.md`](ARCHITECTURE.md)

**Examples:**

- Sample flows: [`sample_flows/`](sample_flows/)
- Test flows: [`sample_flows/`](sample_flows/)

---

### Support Channels

**For bugs and feature requests:**

- GitHub Issues: https://github.com/your-org/docling-pipelines/issues

**For questions and discussions:**

- GitHub Discussions: https://github.com/your-org/docling-pipelines/discussions

**For security issues:**

- Email: security@your-org.com
- Do not post security issues publicly

---

## Additional Resources

### Useful Commands Reference

```bash
# Environment setup (from project root)
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
source .venv/bin/activate

# Service management
ollama serve &
podman-compose -f docker/docker-compose.opensearch.yml up -d

# Pipeline execution
docling-pipelines --flow-file my_flow.json

# Debugging
export DS_LOG_LEVEL=DEBUG
docling-pipelines --flow-file my_flow.json 2>&1 | tee debug.log

# Service health checks
curl http://localhost:11434/api/tags
curl -u admin:${OPENSEARCH_PASSWORD} http://localhost:9200

# Cleanup
podman-compose -f docker/docker-compose.opensearch.yml down -v
pkill -f "ollama serve"
```

---

### Quick Links

- **Installation Guide**: [`USER_GUIDE_PIPELINE_SETUP.md#2-prerequisites-and-installation`](USER_GUIDE_PIPELINE_SETUP.md#2-prerequisites-and-installation)
- **Ollama Setup**: [`USER_GUIDE_PIPELINE_SETUP.md#3-ollama-setup`](USER_GUIDE_PIPELINE_SETUP.md#3-ollama-setup)
- **OpenSearch Setup**: [`USER_GUIDE_PIPELINE_SETUP.md#4-opensearch-setup-with-podman`](USER_GUIDE_PIPELINE_SETUP.md#4-opensearch-setup-with-podman)
- **Flow Configuration**: [`USER_GUIDE_PIPELINE_SETUP.md#5-understanding-flow-configuration`](USER_GUIDE_PIPELINE_SETUP.md#5-understanding-flow-configuration)
- **Operator Reference**: [`README.md#operators`](README.md#operators)

---

**Last Updated:** 2024-01-15  
**Version:** 1.0.0
