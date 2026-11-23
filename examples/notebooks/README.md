# Jupyter Notebook Examples

Interactive notebook examples for learning docling-pipelines through hands-on experimentation.

## Quick Start

```bash
# From repository root
source .venv/bin/activate
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"

# Install notebook dependencies
uv sync --extra notebooks

# Start Jupyter
jupyter notebook examples/notebooks/
```

## Validation

Validate notebook Python code cells locally with the same nbQA/Ruff hook used by CI:

```bash
pre-commit run nbqa-ruff-check --all-files
```

## Prerequisites

### Required Services

1. **Ollama** (for LLM operations and embeddings)
   ```bash
   # Install Ollama
   brew install ollama  # macOS

   # Start Ollama server
   ollama serve

   # Pull required models
   ollama pull nomic-embed-text
   ollama pull granite4
   ```

2. **OpenSearch** (optional, for vector storage examples)
   ```bash
   # Start OpenSearch with Docker
   docker-compose -f docker/docker-compose.opensearch.yml up -d

   # Verify it's running
   curl http://localhost:9200
   ```

### Python Environment

```bash
# Create and activate virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
uv sync --extra notebooks

# Set PYTHONPATH
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
```

## Available Notebooks

### Priority 1: Essential Notebooks

#### 1. [01_quickstart.ipynb](01_quickstart.ipynb)
**Complete pipeline in 10-15 minutes**

- Self-contained example with auto-generated test data
- Full pipeline: Ingest → Extract → Chunk → Embeddings
- Visual outputs and metrics
- Perfect for first-time users

**What you'll learn:**
- Basic DocpipeFlowManager usage
- Flow execution and monitoring
- Result inspection and visualization

#### 2. [02_operator_showcase.ipynb](02_operator_showcase.ipynb)
**Demonstrate all operator categories**

- Ingest operators (local, S3, CSV)
- Extract operators (Docling, VLM, entities)
- Chunking operators (simple, semantic, hybrid)
- Quality operators (language, PII, readability)
- Functional operators (embeddings, branching)
- Storage operators (VectorDB, DocumentSet)

**What you'll learn:**
- Available operators and their capabilities
- Parameter configuration
- Visual comparison of operator outputs

#### 3. [03_document_extraction.ipynb](03_document_extraction.ipynb)
**Deep dive into document extraction strategies**

- Basic text extraction with Docling
- VLM-enhanced extraction for complex layouts
- Entity extraction with and without schemas
- Multi-format output options (HTML, JSON, text, doctags, doclang)
- Configuration quick reference for all ExtractOperator parameters

**What you'll learn:**
- Choosing the right extraction mode for your documents
- Configuring VLM pipelines for better quality
- Extracting structured entities with LLMs
- Performance tuning and advanced configurations
- When to use different providers (docling_library, docling_serve, docling entity extraction)

**Prerequisites:**
- Ollama with `granite4` model (for entity extraction)
- Ollama with `ibm/granite-docling:258m` model (for VLM examples)
- Sample PDFs in `tests/fixtures/invoices/`

#### 4. [04_embeddings_vectordb.ipynb](04_embeddings_vectordb.ipynb)
**Complete workflow for embeddings and vector search**

- Generate embeddings with Ollama (nomic-embed-text)
- Store vectors in OpenSearch with FAISS indexing
- Perform semantic similarity search on stored documents
- Understand embedding models and trade-offs
- Learn vector search concepts (similarity metrics, algorithms)
- VectorDB operator configuration and best practices

**What you'll learn:**
- Embedding generation pipeline (Ingest → Extract → Chunk → Embeddings)
- OpenSearch vector storage with KNN search
- Similarity search on ingested documents
- Choosing embedding models for different use cases
- Vector search algorithms (HNSW, IVF, Flat)
- VectorDB operator `available_features` configuration

**Prerequisites:**
- Ollama with `nomic-embed-text` model: `ollama pull nomic-embed-text`
- OpenSearch running on `localhost:9200` (optional but recommended)
- Sample documents in `sample_documents/`

#### 5. [05_quality_operators.ipynb](05_quality_operators.ipynb)
**Data quality assessment and enrichment**

- Language detection with FastText (176 languages)
- Readability scoring (Flesch Reading Ease, Grade Level, etc.)
- Document deduplication based on content similarity
- ML-based quality enrichment (29 features)
- PII and HAP detection with LLMs
- Complete quality pipeline combining multiple operators

**What you'll learn:**
- Assessing document quality with multiple metrics
- Configuring quality operators for different use cases
- Filtering and cleaning data based on quality scores
- Enriching documents with metadata and quality indicators
- Detecting sensitive content (PII) and harmful content (HAP)
- Building multi-stage quality assessment pipelines

**Prerequisites:**
- Ollama with `granite4` model (for PII/HAP detection): `ollama pull granite4`
- Sample documents in `sample_documents/`
- Customer support documents in `tests/fixtures/customer_support_docs/`

#### 6. [06_rag_pipeline.ipynb](06_rag_pipeline.ipynb)
**End-to-end retrieval-augmented question answering with intermediate inspection**

- Builds a single indexing flow: Ingest → Extract → Chunk → Embeddings → VectorDB
- Uses customer support fixtures as a deterministic RAG corpus
- Inspects intermediate parquet outputs after each major stage
- Verifies what was stored in OpenSearch before querying
- Runs real retrieval and grounded generation in notebook cells
- Includes lightweight answer evaluation against expected terms
- Cleans up local parquet artifacts at the end

**What you'll learn:**
- How to structure a simple RAG workflow with docling-pipelines
- The difference between indexing-time flow execution and query-time retrieval/generation
- How to inspect intermediate operator outputs in a notebook
- How retrieved chunks are turned into grounded prompts
- How to sanity-check generated answers with lightweight evaluation

**Prerequisites:**
- Ollama with `nomic-embed-text` model: `ollama pull nomic-embed-text`
- Ollama with `granite4` model: `ollama pull granite4`
- OpenSearch running on `localhost:9200`
- Customer support documents in `tests/fixtures/customer_support_docs/`

#### 7. [07_flow_authoring.ipynb](07_flow_authoring.ipynb)
**Interactive workshop for programmatic flow authoring**

- Build flows programmatically with DocpipeFlowManager
- Understand global configuration (execution, micro-batching, storage, incremental processing)
- Learn flow validation and error handling with hands-on examples
- Master dynamic pipeline generation based on parameters
- Implement advanced patterns (branching, composition helpers)

**What you'll learn:**
- Global config fundamentals (force_ingest, micro-batching, storage types)
- Incremental processing for efficient re-runs
- Flow validation before execution (4 common error types)
- Dynamic flow generation with `build_pipeline()` function
- Quality-based branching workflows
- Composition helpers for reusable pipeline components

**Prerequisites:**
- Ollama with `nomic-embed-text` model: `ollama pull nomic-embed-text`
- Understanding of basic flow structure (see 01_quickstart.ipynb first)
- Sample documents auto-generated by notebook

#### 8. [08_chunking_strategies.ipynb](08_chunking_strategies.ipynb)
**Compare `simple`, `semantic` and `hybrid` chunking on real documents**

- Runs one flow (Ingest → Extract → Branching → three chunker nodes) on three repository docs
- Chunks the same documents with all three `ChunkerOperator` strategies
- Structural metrics: chunk count, mean size, size spread, overlap ratio
- Semantic coherence metrics: intra-chunk and inter-chunk cosine similarity
- Retrieval: top-3 chunks per strategy for five queries (four with an answer phrase, one negative control)
- Strategy decision guide and per-strategy config quick reference

**What you'll learn:**
- How each chunking strategy places its boundaries on tables, code and prose
- How to measure chunking quality without labeled data
- How to check a chunking choice with answer phrases and a no-answer control query
- How to pick a strategy and starting parameters for your documents

**Prerequisites:**
- Ollama with `nomic-embed-text` is required (`semantic` chunking, coherence scores and retrieval): `ollama pull nomic-embed-text`. The notebook stops with instructions if it is missing.
- Writes flow output to `./data/chunking-strategies-nb/` (git-ignored; each run overwrites it)


## Sample Data

Notebooks use existing sample data from the repository:

- **Documents**: `sample_documents/` - Text files for testing
- **Invoices**: `tests/fixtures/invoices/` - PDF invoices for extraction
- **Purchase Orders**: `tests/fixtures/purchase_orders/` - Sample POs
- **Customer Support**: `tests/fixtures/customer_support_docs/` - Support documents

## Troubleshooting

### Import Errors

```
ImportError: No module named 'docpipe'
```

**Solution**: Set PYTHONPATH correctly
```bash
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
```

### Connection Errors

```
ConnectionError: Failed to connect to Ollama
```

**Solution**: Start Ollama and pull models
```bash
ollama serve
ollama pull nomic-embed-text
```

### Kernel Issues

```
Kernel not found
```

**Solution**: Install ipykernel in your environment
```bash
uv sync --extra notebooks
python -m ipykernel install --user --name=docpipe
```

## Tips for Using Notebooks

1. **Run cells sequentially** - Notebooks are designed to be executed top-to-bottom
2. **Check prerequisites** - Each notebook has a prerequisites check cell
3. **Restart kernel if needed** - Use "Kernel → Restart & Run All" to start fresh
4. **Save outputs** - Notebooks with outputs are useful for reference
5. **Experiment** - Modify parameters and re-run cells to learn

## Additional Resources

- **Main Documentation**: [README.md](../../README.md)
- **Python API Guide**: [docs/guides/PYTHON_API_GUIDE.md](../../docs/guides/PYTHON_API_GUIDE.md)
- **Operator Reference**: [docs/reference/OPERATORS.md](../../docs/reference/OPERATORS.md)
- **Python Examples**: [examples/docpipe_flow_manager/](../docpipe_flow_manager/)
- **Troubleshooting**: [TROUBLESHOOTING.md](../../TROUBLESHOOTING.md)

## Contributing

Have a useful notebook example? Contributions are welcome!

1. Create your notebook in `examples/notebooks/`
2. Ensure it runs without errors
3. Add clear markdown explanations
4. Include visual outputs
5. Submit a pull request

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for guidelines.
