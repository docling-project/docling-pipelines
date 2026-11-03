# docling-pipelines-slim

## Overview

`docling-pipelines-slim` is a lightweight variant of `docling-pipelines` that excludes certain operator dependencies.

## When to Use Slim

Use this variant if:
- Your codebase doesn't need the built-in `extract_operator`
- You want a lighter installation and will add extraction support later via `pip install "docling-pipelines-slim[extract]"`

## Installation

```bash
pip install docling-pipelines-slim
```

### To enable extraction operator support:

```bash
pip install "docling-pipelines-slim[extract]"
```

## Usage

All imports and usage are identical to the standard `docling-pipelines` package:

```python
from docpipe.cli.docpipe_cli import main
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

# Run a flow
manager = DocpipeFlowManager(flow_file="my_flow.json")
result = manager.execute()
```

## Building from Source

### Build slim wheel

> **Note:** The command below is for local builds only. In CI, the slim wheel is built and published to PyPI by the GitHub Actions release workflow alongside the main wheel.

```bash
cd slim/
uv build --wheel
```

Result: `slim/dist/docling_pipelines_slim-<VERSION>-py3-none-any.whl` (version derived from Git tag via hatch-vcs).

### Install from wheel

```bash
# Standard wheel installation
pip install ./dist/docling_pipelines_slim-*.whl

# With support for extraction operator
pip install "./dist/docling_pipelines_slim-*.whl[extract]"
```

## Operator Availability

Core operators are available in slim. Optional operator support requires installing the corresponding optional group.

| Operator | Default | Optional Group |
|----------|---------|-----------------|
| `ingest_source` | ✓ | — |
| `extract_operator` | ✗ | `extract` |
| `extract_operator` decryption of password-protected PDF and Office documents | ✗ | `extract` |
| `chunker` (fixed-size / sentence modes) | ✓ | — |
| `chunker` (hybrid / docling-split modes) | ✗ | `extract` |
| `embeddings` (litellm, watsonx, ollama providers) | ✓ | — |
| `embeddings` (HuggingFace local provider) | ✗ | `extract` |
| `lang_detect`, `redaction` | ✓ | — |
| `vectordb`, `acl_operator` | ✓ | — |
| All quality operators | ✓ | — |

## See Also

- [Parent README](../../README.md)
- [docs/reference/OPERATORS.md](../reference/OPERATORS.md) — Operator reference
- [docs/guides/FLOW_CONFIGURATION_GUIDE.md](FLOW_CONFIGURATION_GUIDE.md) — Flow authoring guide
