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

### To enable local PII detection with Presidio:

```bash
pip install "docling-pipelines-slim[presidio]"
```

Presidio also needs a spaCy model. Install the model wheel that matches your installed spaCy minor version, for example `en_core_web_sm==3.8.0` for spaCy 3.8, from spaCy's model releases (or your internal mirror of them):

```bash
pip install "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
```

`presidio-analyzer` declares `numpy<2.5.0` and `preshed<3.0.14`, so installing this extra can downgrade those packages in an existing environment.

### To enable the local Hugging Face provider (HAP detection and local embeddings):

The `huggingface` extra installs `torch`, `transformers` and `sentence-transformers`. It serves both `hap_provider: "huggingface"` in `pii_and_hap` and the local `huggingface` provider of `embeddings`. On Linux, `torch` from PyPI is the CUDA build, which pulls several GB of NVIDIA libraries. If you do not need a GPU, install the CPU-only build first:

```bash
pip install "torch==2.15.0" --index-url https://download.pytorch.org/whl/cpu
```

```bash
pip install "docling-pipelines-slim[huggingface]"
```

- The `torch` pin is exact: any `2.15.0` build, CPU-only (`2.15.0+cpu`) or CUDA (for example `2.15.0+cu128`), satisfies it. A different `torch` version needs your installer's override feature, for example uv's `override-dependencies`.
- Through `sentence-transformers`, the extra also brings `scipy` and `scikit-learn`.

The same extra names exist on the full distribution (`docling-pipelines[presidio]`, `docling-pipelines[huggingface]`), so one install command works for both. On the full distribution, `huggingface` installs nothing extra, because its packages are core dependencies.

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
| `chunker` (fixed-size / sentence modes) | ✓ | — |
| `chunker` (hybrid / docling-split modes) | ✗ | `extract` |
| `embeddings` (litellm, watsonx, ollama providers) | ✓ | — |
| `embeddings` (HuggingFace local provider) | ✗ | `huggingface` (also included in `extract`) |
| `lang_detect`, `redaction` | ✓ | — |
| `vectordb`, `acl_operator` | ✓ | — |
| `pii_and_hap` (litellm, watsonx providers) | ✓ | — |
| `pii_and_hap` (`presidio` PII provider) | ✗ | `presidio`, plus a spaCy model wheel you install |
| `pii_and_hap` (`huggingface` HAP provider) | ✗ | `huggingface` |
| Other quality operators | ✓ | — |

## See Also

- [Parent README](../../README.md)
- [docs/reference/OPERATORS.md](../reference/OPERATORS.md) — Operator reference
- [docs/guides/FLOW_CONFIGURATION_GUIDE.md](FLOW_CONFIGURATION_GUIDE.md) — Flow authoring guide
