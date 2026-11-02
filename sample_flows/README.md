# Sample Flows

This directory contains curated sample flows demonstrating docling-pipelines capabilities, organized by complexity and use case.

## Table of Contents

- [Directory Structure](#directory-structure)
- [Quick Start](#quick-start)
- [Flows by Category](#flows-by-category)
- [Provider Coverage](#provider-coverage)
- [Prerequisites](#prerequisites)
- [How to Run a Flow](#how-to-run-a-flow)
- [Flow Structure](#flow-structure)
- [Customization Guide](#customization-guide)
- [Troubleshooting](#troubleshooting)
- [Next Steps](#next-steps)
- [Additional Resources](#additional-resources)
- [Flow Selection Guide](#flow-selection-guide)
- [Feedback and Support](#feedback-and-support)

---

## Directory Structure

```text
sample_flows/
├── quickstart/          # Start here for beginners
├── operators/           # Individual operator demonstrations
├── use_cases/           # Real-world use case examples
├── advanced/            # Complex workflows and patterns
├── vectordb/            # Vector database integrations
├── storage_output/      # Original and processed content exports
└── custom_operators/    # Custom operator examples
```

---

## Quick Start

### For First-Time Users

1. **Start with the basics:**
   ```bash
   docling-pipelines --flow-file sample_flows/quickstart/basic_ingest_extract.json
   ```

2. **Try a complete local pipeline (zero external services):**
   ```bash
   docling-pipelines --flow-file sample_flows/quickstart/milvus_lite_integration.json
   ```

3. **Try a complete pipeline with Ollama and OpenSearch:**
   ```bash
   docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json
   ```

4. **Explore advanced patterns:**
   ```bash
   docling-pipelines --flow-file sample_flows/advanced/branching_dual_embeddings_with_ingest_report.json
   ```

---

## Flows by Category

### Quickstart

Perfect for beginners - simple, well-documented examples to get started.

| Flow | Description | Prerequisites |
|------|-------------|---------------|
| `basic_ingest_extract.json` | Minimal 2-operator pipeline: ingest → extract | Docling |
| [milvus_lite_integration.json](quickstart/milvus_lite_integration.json) | Container-free local pipeline: ingest → extract → chunk → local HuggingFace embeddings → Milvus Lite (`.db` file) | Docling, Sentence-Transformers, Milvus Lite (all included by default) |
| `complete_pipeline_ollama.json` | Full local pipeline: ingest → extract → chunk → embed → OpenSearch | Ollama, OpenSearch |
| `complete_pipeline_watsonx.json` | Full cloud pipeline with Watsonx provider | Watsonx API, OpenSearch |
| [docker_e2e_ollama_opensearch.json](quickstart/docker_e2e_ollama_opensearch.json) | PDFs to Docling extraction, Ollama embeddings, OpenSearch | Docker stack, `/documents` PDF mount, Ollama embedding model, OpenSearch credentials |

**Start here if:** You're new to docling-pipelines or want to understand basic flow structure.

---

### Operators

Focused examples demonstrating individual operator capabilities.

| Flow | Operator | Description | Provider |
|------|----------|-------------|----------|
| `classification_ollama.json` | document_classifier | Document classification workflow | LiteLLM/Ollama |
| `entity_extraction_litellm.json` | extract_operator | Entity extraction without predefined schema | LiteLLM/Ollama |
| `entity_extraction_watsonx.json` | extract_operator | Entity extraction with cloud provider | Watsonx |
| `entity_curation_ollama.json` | entity_curation | Classification → extraction → entity curation pipeline | LiteLLM/Ollama |
| `pii_hap_detection.json` | pii_and_hap | PII and HAP detection with redaction | LiteLLM/Ollama |

**Start here if:** You want to understand specific operator configurations.

---

### Use Cases

Real-world scenarios showing practical applications.

| Flow | Use Case | Description |
|------|----------|-------------|
| `invoice_processing.json` | Invoice Processing | Complete invoice workflow with entity extraction and OpenSearch storage |
| `s3_to_opensearch.json` | Cloud Integration | Ingest from AWS S3, process, and store in OpenSearch |
| `audio_video_extraction.json` | Audio/Video Transcription | ASR transcription → chunking → embeddings → vector storage |
| `document_set_management.json` | Document Sets | Demonstrates document_set operator for managing document collections |

**Start here if:** You want to see how docling-pipelines solves real problems.

---

### Advanced

Complex workflows demonstrating advanced patterns and operator combinations.

| Flow | Pattern | Description |
|------|---------|-------------|
| `branching_dual_embeddings_with_ingest_report.json` | Branching | Parallel processing with dual embedding models and ingest report |
| [branching_dual_embeddings.json](advanced/branching_dual_embeddings.json) | Dual embeddings | Two LiteLLM embedding branches merge into document set and OpenSearch; requires embedding models and OpenSearch |
| `branching_quality_routing.json` | Quality Routing | Route documents based on quality metrics |
| `quality_branching_merge_pipeline.json` | Branching + Merge | 3-way branching with dedup, quality checks, and row-based merging |
| `multi_stage_enrichment.json` | Multi-Stage | Classification → Entity Extraction → PII Detection → Chunking |
| `hybrid_chunking.json` | Chunking | Semantic + simple chunking strategies |
| `summarization_pipeline.json` | Summarization | Chunking with LLM-based summarization |

**Start here if:** You need complex workflows with conditional routing or parallel processing.

---

### VectorDB

Complete pipelines demonstrating vector database integrations.

| Flow | VectorDB | Description |
|------|----------|-------------|
| `opensearch_integration.json` | OpenSearch | Full pipeline with OpenSearch vector storage |
| `milvus_integration.json` | Milvus | Full pipeline with Milvus vector storage |

**Start here if:** You're setting up vector search or RAG systems.

---

### Storage Output

Export processed text, original documents, and metadata.

| Flow | Description | Prerequisites |
| --- | --- | --- |
| [comprehensive_export_box.json](storage_output/comprehensive_export_box.json) | Archive Box documents, extracted content, and metadata to Box | `BOX_CONFIG_PATH` and Box source/destination folder IDs |
| [comprehensive_export_google_drive.json](storage_output/comprehensive_export_google_drive.json) | Archive local documents, extracted content, and metadata to Google Drive | Local input paths and `GDRIVE_DRIVE_ID`, `GDRIVE_FOLDER_ID`, `GDRIVE_SA_JSON_PATH` |
| [comprehensive_export_sharepoint.json](storage_output/comprehensive_export_sharepoint.json) | Archive local documents, extracted content, and metadata to SharePoint | Local input paths, SharePoint drive ID, tenant/client ID and secret |
| [processed_content_s3.json](storage_output/processed_content_s3.json) | Extract PDFs from S3 and export processed text to S3 | Source and destination S3 buckets and access credentials |
| [refetch_original_filesystem.json](storage_output/refetch_original_filesystem.json) | Archive original files to a local filesystem directory | Existing source and writable destination paths |

**Start here if:** You need processed-content export, document archiving, or compliance handoff.

---

### Custom Operators

Examples showing how to create and use custom operators.

| Flow | Type | Description |
|------|------|-------------|
| `custom_operators_demo.json` | Package-based | Demonstrates package-based custom operators |
| `hello_operator.json` | Simple | Minimal custom operator example |

**Start here if:** You need to extend docling-pipelines with custom functionality.

---

## Provider Coverage

docling-pipelines supports multiple LLM and embedding providers. Our sample flows demonstrate:

### Local Providers
- **Ollama** (via LiteLLM): Most examples use this for easy local setup
  - Models: llama3.2, granite4, nomic-embed-text
  - Setup: `ollama serve` + `ollama pull <model>`

### Cloud Providers
- **Watsonx**: Enterprise cloud provider
  - Examples: `complete_pipeline_watsonx.json`, `entity_extraction_watsonx.json`
  - Requires: API key and project ID

### Flexible Provider
- **LiteLLM**: Adapter supporting 100+ providers
  - Used throughout for flexibility
  - Can switch between Ollama, OpenAI, Anthropic, etc.

---

## Prerequisites

### Required for All Flows
```bash
# Python environment
uv sync --extra dev
source .venv/bin/activate

# Set PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
```

### For Local LLM Flows (Ollama)
```bash
# Start Ollama
ollama serve

# Pull required models
ollama pull llama3.2
ollama pull granite4
ollama pull nomic-embed-text

# Verify
curl http://localhost:11434/api/tags
```

### For OpenSearch Flows
```bash
# Start OpenSearch (from project root)
docker-compose -f docker/docker-compose.opensearch.yml up -d

# Verify
curl -u admin:MyStrongPass123! http://localhost:9200

# Set credentials
export OPENSEARCH_USERNAME=admin
export OPENSEARCH_PASSWORD=<your-opensearch-password>
```

### For Watsonx Flows
```bash
# Set credentials
export WATSONX_API_KEY=your_api_key
export WATSONX_API_BASE=https://us-south.ml.cloud.ibm.com
export WATSONX_CONTAINER_ID=your_project_id
```

## How to Run a Flow

### Basic Execution
```bash
docling-pipelines --flow-file sample_flows/quickstart/basic_ingest_extract.json
```

### With Debug Logging
```bash
DS_LOG_LEVEL=DEBUG docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json
```

### Validate Before Running
```bash
docling-pipelines --flow-file sample_flows/advanced/branching_dual_embeddings_with_ingest_report.json --validate
```

### List Available Operators
```bash
docling-pipelines --list-operators
docling-pipelines --list-operators --verbose
```

---

## Flow Structure

All flows follow this JSON structure:

```json
{
  "flow_name": "Human-readable name",
  "description": "What this flow does",
  "global_config": {
    "doc_column": "content",
    "disable_validation": false,
    "force_ingest": true,
    "storage": "in-memory",
    "execute_type": "local"
  },
  "flow": [
    {
      "name": "unique_operator_name",
      "type": "operator_type",
      "depends_on": ["upstream_operator"],
      "config": {
        // Operator-specific configuration
      }
    }
  ]
}
```

**Key Concepts:**
- **Operators**: Processing units (ingest, extract, chunk, embed, etc.)
- **Dependencies**: `depends_on` defines execution order
- **DAG Structure**: Flows form directed acyclic graphs
- **PyArrow Tables**: Data flows as PyArrow tables between operators

---

## Customization Guide

### Change Input Documents
```json
{
  "name": "ingest",
  "type": "ingest_source",
  "config": {
    "provider": "filesystem",
    "provider_config": {"paths": ["./your/documents/path"]},
    "include_filter": "pdf,txt,docx"
  }
}
```

### Switch LLM Provider
```json
{
  "name": "classify",
  "type": "document_classifier",
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/gpt-4",  // Change model
      "api_key": "${OPENAI_API_KEY}",
      "api_base": "https://api.openai.com/v1"
    }
  }
}
```

### Modify Chunking Strategy
```json
{
  "name": "chunk",
  "type": "chunker",
  "config": {
    "chunk_type": "semantic",  // Options: simple, semantic, hybrid
    "chunk_size": 512,
    "chunk_overlap": 50
  }
}
```

### Change Vector Database
```json
{
  "name": "vectordb",
  "type": "vectordb",
  "config": {
    "provider": "milvus",  // Options: opensearch, milvus
    "index_name": "my_collection",
    // Provider-specific config...
  }
}
```

---

## Troubleshooting

### Common Issues

**1. Ollama not running**
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start if not running
ollama serve
```

**2. OpenSearch connection failed**
```bash
# Check if container is running
docker ps | grep opensearch

# Start if not running
docker-compose -f docker/docker-compose.opensearch.yml up -d
```

**3. Import errors**
```bash
# Ensure PYTHONPATH is set
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
```

**4. Model not found**
```bash
# Pull the required model
ollama pull llama3.2
ollama pull nomic-embed-text
```

**5. No documents found**
- Verify the `paths` in ingest operator
- Check file extensions in `include_filter`
- Ensure files exist in the specified directory

### Debug Mode

Enable detailed logging:
```bash
DS_LOG_LEVEL=DEBUG docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json
```

Log levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

---

## Next Steps

### After Running Sample Flows

1. **Explore Operator Documentation**
   - See `docs/operators/` for detailed operator guides
   - Check `docs/reference/OPERATORS.md` for complete API reference

2. **Build Custom Flows**
   - Start with a sample flow as template
   - Add/remove operators as needed
   - Test with `--validate` flag

3. **Integrate with Your Application**
   - Use Python API: `from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager`
   - See `examples/docpipe_flow_manager/` for programmatic usage

4. **Scale Up**
   - Process larger document collections
   - Use distributed execution with Prefect
   - See [`DISTRIBUTED_EXECUTION_GUIDE.md`](../docs/integrations/prefect/DISTRIBUTED_EXECUTION_GUIDE.md)

---

## Additional Resources

- **User Guide**: `docs/USER_GUIDE_PIPELINE_SETUP.md` - Complete setup instructions
- **Architecture**: `ARCHITECTURE.md` - System design and operator catalog
- **Contributing**: `CONTRIBUTING.md` - Development guidelines
- **Operator Reference**: `docs/reference/OPERATORS.md` - Complete operator API
- **Examples**: `examples/` - Python API usage examples

---

## Flow Selection Guide

**Choose your starting point:**

| If you want to... | Start with... |
|-------------------|---------------|
| Learn the basics | `quickstart/basic_ingest_extract.json` |
| Run a zero-container local RAG pipeline | [quickstart/milvus_lite_integration.json](quickstart/milvus_lite_integration.json) |
| Set up RAG pipeline with Ollama & OpenSearch | `quickstart/complete_pipeline_ollama.json` |
| Run the Docker Ollama/OpenSearch pipeline | [quickstart/docker_e2e_ollama_opensearch.json](quickstart/docker_e2e_ollama_opensearch.json) |
| Use cloud LLMs | `quickstart/complete_pipeline_watsonx.json` |
| Classify documents | `operators/classification_ollama.json` |
| Extract entities | `operators/entity_extraction_litellm.json` |
| Curate entities | `operators/entity_curation_ollama.json` |
| Detect PII/HAP | `operators/pii_hap_detection.json` |
| Transcribe audio/video | `use_cases/audio_video_extraction.json` |
| Process invoices | `use_cases/invoice_processing.json` |
| Ingest from S3 | `use_cases/s3_to_opensearch.json` |
| Route by quality | `advanced/branching_quality_routing.json` |
| Parallel processing | `advanced/branching_dual_embeddings_with_ingest_report.json` |
| Generate and merge dual embeddings | [advanced/branching_dual_embeddings.json](advanced/branching_dual_embeddings.json) |
| Complex pipeline | `advanced/multi_stage_enrichment.json` |
| Use OpenSearch | `vectordb/opensearch_integration.json` |
| Use Milvus | `vectordb/milvus_integration.json` |
| Use serverless Milvus Lite | [quickstart/milvus_lite_integration.json](quickstart/milvus_lite_integration.json) |
| Export original files to Box | [storage_output/comprehensive_export_box.json](storage_output/comprehensive_export_box.json) |
| Export original files to Google Drive | [storage_output/comprehensive_export_google_drive.json](storage_output/comprehensive_export_google_drive.json) |
| Export original files to SharePoint | [storage_output/comprehensive_export_sharepoint.json](storage_output/comprehensive_export_sharepoint.json) |
| Export processed text to S3 | [storage_output/processed_content_s3.json](storage_output/processed_content_s3.json) |
| Archive originals to the filesystem | [storage_output/refetch_original_filesystem.json](storage_output/refetch_original_filesystem.json) |
| Create custom operators | `custom_operators/hello_operator.json` |

---

## Feedback and Support

- **Issues**: Report bugs or request features on GitHub
- **Discussions**: Ask questions in GitHub Discussions
- **Documentation**: Check `docs/` for detailed guides

**Happy building with docling-pipelines!**
