<!-- sonar.exclusions=**/*.md -->
# Unified LLM Architecture

This document describes the current LLM adapter architecture used across all operators in docpipe.

---

# Overview

All LLM integrations in Docling Pipelines share a common set of provider adapters, ports, and a single factory.
The goals are:

* Standardize all LLM integrations across operators
* Eliminate duplicated provider-specific logic
* Reuse common interfaces and factories
* Support multiple providers consistently
* Simplify future provider onboarding

---

# Core Architecture

## Two Patterns

Most operators follow the **direct port** pattern. Entity extraction is the one exception and uses an
**operator-specific adapter layer** on top of the shared infrastructure — see
[Section 2: Entity Extraction](#2-entity-extraction-operator) for the rationale.

### Pattern A — Direct Port (Classification, PII/HAP, Summarization, Embeddings)

```text
Operator
   ↓
Service Layer (business logic, optional for simple operators)
   ↓ calls
LLMAdapterFactory
   ↓ returns
Common Port Interface  (LLMInferencePort / LLMEmbeddingPort / TextDetectionPort)
   ↑ implemented by
Consolidated Provider Adapters (WatsonXAdapter, LiteLLMAdapter)
```

`provider_config` from the flow JSON is passed **directly and unchanged** to `LLMAdapterFactory`.
It only ever contains connection-level fields (`api_key`, `api_base`, `url`, `container_kind`, etc.).

### Pattern B — Operator-Specific Adapter Layer (Entity Extraction only)

```text
ExtractOperator
   ↓
EntityExtractionAdapterFactory  (operator-specific factory)
   ↓ creates via registry
LiteLLMEntityAdapter / WatsonxEntityAdapter  (thin registered subclasses)
   ↓ extends
LLMEntityAdapter  (shared base: parallelism, schema building, response normalisation)
   ↓ calls
LLMAdapterFactory.create_inference_adapter()
   ↓ returns
LLMInferencePort  (LiteLLMAdapter or WatsonXAdapter)
```

This extra layer exists because entity extraction's `transform()` contract operates on a full
`pa.Table` with per-document parallelism — it cannot be expressed as a plain `chat()` call.
See [Section 2](#2-entity-extraction-operator) for full details.

---

# Key Decisions

## 1. Ollama via LiteLLM

Ollama is accessed through LiteLLM using the OpenAI-compatible API:

```yaml
api_base: http://localhost:11434/v1
model_id: openai/<model_name>
```

### Benefits

* Removes duplicate Ollama implementations
* Reuses LiteLLM infrastructure
* Consistent provider handling
* Easier maintenance

---

## 2. Common Ports

Three shared interfaces cover all LLM capabilities:

| Port                | Purpose                       | Used by |
| ------------------- | ----------------------------- | ------- |
| `LLMInferencePort`  | Chat/generation APIs          | Classification, Entity Extraction, Summarization, PII/HAP (LLM mode) |
| `LLMEmbeddingPort`  | Embedding generation          | Embeddings Operator |
| `TextDetectionPort` | Specialized detection APIs    | PII/HAP (WatsonX mode) |

---

## 3. Unified Factory

A single factory handles all adapter creation:

| Factory             | Responsibility                                  |
| ------------------- | ----------------------------------------------- |
| `LLMAdapterFactory` | Inference, Embeddings, and Text Detection APIs  |

---

# Common Infrastructure (Foundation Layer)

## Port Interfaces

### 1. LLM Inference Port

**File**

```text
src/docpipe/core/ports/llm_inference_port.py
```

**Purpose**: Common interface for `chat()` and `generate()` calls.

**Used by**: Classification, Entity Extraction, Summarization, PII/HAP (LLM mode)

---

### 2. LLM Embedding Port

**File**

```text
src/docpipe/core/ports/llm_embedding_port.py
```

**Purpose**: Common interface for `generate_embeddings()`, `generate_embeddings_batch()`, `get_embedding_dimension()`.

**Used by**: Embeddings Operator

---

### 3. Text Detection Port

**File**

```text
src/docpipe/core/ports/text_detection_port.py
```

**Purpose**: Specialized interface for PII/HAP detection via WatsonX detection APIs.

**Used by**: PII/HAP Operator (WatsonX path only)

---

# Provider Adapters (Consolidated Architecture)

Each provider has a **single consolidated adapter** that implements one or more port interfaces.

---

## WatsonX Adapter

**File**

```text
src/docpipe/core/adapters/watsonx/watsonx_adapter.py
```

### Implements Three Ports

```text
LLMInferencePort      (chat, generate)
LLMEmbeddingPort      (generate_embeddings, generate_embeddings_batch, get_embedding_dimension)
TextDetectionPort     (detect, detect_entities, detect_entities_batch)
```

### Key Features

* **Single adapter** for all WatsonX capabilities
* **Model override**: All methods accept optional `model_name` parameter
* **Flexible response format**: `response_format` passed as method parameter, not in `__init__`
* **Specialized detection**: Uses WatsonX `/ml/v1/text/detection` API for PII/HAP

### Usage Example

```python
from docpipe.core.adapters import WatsonXAdapter

adapter = WatsonXAdapter(
    api_key="<your-watsonx-api-key>",  # pragma: allowlist secret
    container_id="<your-project-id>",
    api_base="https://us-south.ml.cloud.ibm.com",
    model_name="ibm/granite-13b-chat-v2"
)

# Inference with JSON response
response = adapter.chat(
    messages=[{"role": "user", "content": "Classify this"}],
    response_format={"type": "json_object"}
)

# Embeddings (model override)
embeddings = adapter.generate_embeddings(
    model_name="ibm/slate-125m-english-rtrvr",
    text="Sample text"
)

# Text detection
result = adapter.detect(text="Check for PII")
```

---

## LiteLLM Adapter

**File**

```text
src/docpipe/core/adapters/litellm/litellm_adapter.py
```

### Implements Two Ports

```text
LLMInferencePort      (chat, generate)
LLMEmbeddingPort      (generate_embeddings, generate_embeddings_batch, get_embedding_dimension)
```

### Supports 100+ Providers

* **OpenAI**: `gpt-4`, `text-embedding-3-small`
* **Anthropic**: `claude-3-opus-20240229`
* **Ollama**: `openai/llama2`, `openai/nomic-embed-text` (via OpenAI-compatible API)
* **HuggingFace**: `huggingface/sentence-transformers/all-MiniLM-L6-v2`
* **And 90+ more providers**

### Key Features

* **Single adapter** for all LiteLLM capabilities
* **Model override**: All methods accept optional `model_name` parameter
* **Flexible response format**: `response_format` passed as method parameter (not hardcoded)
* **No default JSON format**: Callers explicitly specify when needed

### Usage Example

```python
from docpipe.core.adapters import LiteLLMAdapter

adapter = LiteLLMAdapter(
    model_name="openai/llama2",
    api_key="ollama",  # pragma: allowlist secret
    api_base="http://localhost:11434/v1"
)

response = adapter.chat(
    messages=[{"role": "user", "content": "Classify this"}],
    response_format={"type": "json_object"}
)

embeddings = adapter.generate_embeddings(
    model_name="openai/nomic-embed-text",
    text="Sample text"
)
```

---

# LLM Adapter Factory

**File**

```text
src/docpipe/core/adapters/llm_adapter_factory.py
```

Single unified factory for creating all types of LLM adapters across all providers.

### Methods

```python
# Create inference adapter (LLMInferencePort)
create_inference_adapter(provider, model_id, provider_config)

# Create embedding adapter (LLMEmbeddingPort)
create_embedding_adapter(provider, model_id, provider_config)

# Create text detection adapter (TextDetectionPort)
create_text_detection_adapter(provider, model_id, provider_config)

# Query supported providers for a capability
get_supported_providers(capability="inference")
```

### Provider Support Matrix

| Provider      | Inference | Embeddings | Text Detection | Notes |
| ------------- | --------- | ---------- | -------------- | ----- |
| `watsonx`     | ✅         | ✅          | ✅              | IBM watsonx.ai — single consolidated adapter |
| `litellm`     | ✅         | ✅          | ❌              | 100+ providers (Ollama, OpenAI, Anthropic, etc.) |
| `huggingface` | ❌         | ✅          | ❌              | Local or API-based HuggingFace models |

### Usage Examples

```python
from docpipe.core.adapters import LLMAdapterFactory

# WatsonX inference
adapter = LLMAdapterFactory.create_inference_adapter(
    provider="watsonx",
    model_id="ibm/granite-13b-chat-v2",
    provider_config={
        "api_key": "<your-watsonx-api-key>",  # pragma: allowlist secret
        "url": "https://us-south.ml.cloud.ibm.com",
        "container_id": "<your-project-id>",
        "container_kind": "project"
    }
)

# LiteLLM embedding (Ollama)
adapter = LLMAdapterFactory.create_embedding_adapter(
    provider="litellm",
    model_id="openai/nomic-embed-text",
    provider_config={
        "api_base": "http://localhost:11434/v1",
        "api_key": "ollama"  # pragma: allowlist secret
    }
)

# HuggingFace embedding (local)
adapter = LLMAdapterFactory.create_embedding_adapter(
    provider="huggingface",
    model_id="sentence-transformers/all-MiniLM-L6-v2",
    provider_config={"use_local": True, "device": "cpu"}
)

# WatsonX text detection
adapter = LLMAdapterFactory.create_text_detection_adapter(
    provider="watsonx",
    model_id="ibm/granite-13b-chat-v2",
    provider_config={
        "api_key": "<your-watsonx-api-key>",  # pragma: allowlist secret
        "url": "https://us-south.ml.cloud.ibm.com",
        "container_id": "<your-project-id>",
        "container_kind": "project"
    }
)
```

### LiteLLM Provider Examples

LiteLLM provides unified access to multiple providers via model ID prefixes:

- **Ollama**: `openai/<model>` with `api_base: http://localhost:11434/v1`
- **HuggingFace API**: `huggingface/<model>` with HuggingFace API key
- **OpenAI**: `gpt-4`, `text-embedding-3-small`, etc.
- **Anthropic**: `claude-3-opus-20240229`, etc.
- **And 90+ more providers**

---

# `provider_config` Reference

`provider_config` fields are **scoped by operator**, not global. Operators that pass `provider_config`
directly to `LLMAdapterFactory` (classification, PII/HAP, summarization, embeddings) only need
connection-level fields. Entity extraction is the exception — see the note below.

## Shared config models (connection-level fields)

Used by: **Classification**, **PII/HAP**, **Summarization**, **Embeddings**

These operators pass `provider_config` unchanged to `LLMAdapterFactory`.
The Pydantic models live in `src/docpipe/core/operators/shared/llm_provider_config.py`.

| Provider | Model | Key fields |
| -------- | ----- | ---------- |
| `litellm` | `LLMProviderConfig` | `model_id`, `api_base`, `api_key` |
| `watsonx` | `WatsonxProviderConfig` | `model_id`, `url`, `api_key`, `container_kind`, `container_id` |

## Entity extraction config models

Used by: **ExtractOperator** (`entity_extraction` block only)

Entity extraction puts `temperature` and `max_tokens` **inside** `provider_config` rather than as
separate operator-level fields. The Pydantic models live in
`src/docpipe/core/operators/extract/adapters/outbound/entity_extraction/llm_entity_config.py`.

| Provider | Model | Key fields |
| -------- | ----- | ---------- |
| `litellm` | `LLMEntityConfig` | `model_id`, `api_base`, `api_key`, `temperature`, `max_tokens` |
| `watsonx` | `WatsonxEntityConfig` | above + `url`, `container_kind`, `project_id` |

---

# Operator Reference

---

# 1. Classification Operator

**File**

```text
src/docpipe/core/operators/quality/classification/document_classifier.py
```

## Architecture

```text
DocumentClassifierOperator
    ↓ depends on
ClassificationPort  (src/docpipe/core/operators/quality/classification/ports/outbound/classification_port.py)
    ↑ resolved by
ClassificationAdapterFactory  (registry + provider aliases)
    ↓ from_config()
StandardLLMClassificationAdapter  (src/docpipe/core/operators/quality/classification/adapters/outbound/standard_llm_adapter.py)
    ↓ calls LLMAdapterFactory.create_inference_adapter()
    ↓ holds
LLMInferencePort
    ↑ implemented by
WatsonXAdapter / LiteLLMAdapter
```

## StandardLLMClassificationAdapter

**File**

```text
src/docpipe/core/operators/quality/classification/adapters/outbound/standard_llm_adapter.py
```

**Responsibilities**: config validation, `LLMInferencePort` construction (in `from_config()`),
prompt building, LLM call, response parsing.

`provider_config` is passed directly to `LLMAdapterFactory`. It is required for `litellm` and
optional for `watsonx` (which falls back to `WATSONX_*` environment variables). `temperature` and
`max_tokens` are read from `provider_config`, defaulting to
`OperatorConstants.Classification.DEFAULT_TEMPERATURE` / `DEFAULT_MAX_TOKENS`.

## Flow JSON example

```json
{
  "type": "document_classifier",
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/granite4:latest",
      "api_base": "http://localhost:11434/v1",
      "api_key": "${OLLAMA_API_KEY}"
    },
    "confidence_threshold": 7.0,
    "doc_column": "content",
    "output_column": "document_type"
  }
}
```

---

# 2. Entity Extraction Operator

**File**

```text
src/docpipe/core/operators/extract/extract_operator.py
```

## Why entity extraction has its own adapter layer

Entity extraction cannot follow Pattern A (direct port) for two reasons:

1. **Unit of work**: The `EntityExtractionPort.transform()` contract takes a full `pa.Table` and
   returns `tuple[list[pa.Table], dict]`. This is the operator contract — it involves per-document
   parallelism, `expand_extracted_data` flag handling, and `output_column` routing. None of that
   can be expressed as a plain `LLMInferencePort.chat()` call.

2. **Per-provider config schemas**: The `EntityExtractionAdapterFactory` advertises a different
   Pydantic config schema per provider for UI/metadata generation (`get_metadata()`). Each
   registered adapter class owns its `get_config_schema()` method. A single adapter class cannot
   own two different schemas simultaneously.

## Architecture

```text
ExtractOperator
    ↓
EntityExtractionAdapterFactory
    ↓ routes through registry (@register_entity_extraction_adapter)
LiteLLMEntityAdapter / WatsonxEntityAdapter  (thin subclasses — own ADAPTER_NAME + get_config_schema())
    ↓ extends
LLMEntityAdapter  (shared base — parallelism, schema building, JSON normalisation, truncation)
    ↓ calls
LLMAdapterFactory.create_inference_adapter()
    ↓ returns
LLMInferencePort  (LiteLLMAdapter or WatsonXAdapter)
```

For the `docling` mode, `DoclingEntityAdapter` is registered directly without going through
`LLMAdapterFactory` — it uses Docling's own template extraction pipeline.

## Adding a new LLM-based entity extraction provider

1. Create a subclass of `LLMEntityAdapter` with `ADAPTER_NAME`, `get_config_schema()`, and the
   `@register_entity_extraction_adapter` decorator.
2. Create a Pydantic config model for the new provider's `provider_config` fields.
3. Import the subclass in `entity_extraction/__init__.py` so the decorator fires on package import.
4. Ensure the new provider string is also in `LLMAdapterFactory.INFERENCE_PROVIDERS` — the
   two registries are independent and both must know about the provider.

## `provider_config` convention note

Entity extraction puts `temperature` and `max_tokens` **inside** `provider_config`. This differs
from classification and summarization, where these are top-level operator config fields. This is
a historical inconsistency, not an intentional design difference.

## Flow JSON example

```json
{
  "type": "extract_operator",
  "config": {
    "entity_extraction": {
      "provider": "litellm",
      "provider_config": {
        "model_id": "openai/granite4:latest",
        "api_base": "http://localhost:11434/v1",
        "api_key": "${OLLAMA_API_KEY}",
        "temperature": 0.0,
        "max_tokens": 2000
      },
      "max_doc_chars": 8000,
      "expand_extracted_data": false
    }
  }
}
```

---

# 3. PII/HAP Operator

**File**

```text
src/docpipe/core/operators/quality/pii_and_hap/pii_and_hap_annotator.py
```

## Architecture — Decorator-Based Adapter Registry

Detection is split by capability into two ports, so single-capability providers fit:
`PIIDetectionPort.detect_pii()` and `HAPDetectionPort.detect_hap()`, both with `validate()`.
`PIIAndHAPDetectionPort` inherits both and derives them from one `detect(payload=...)` call.
Each adapter declares `SUPPORTS_PII` / `SUPPORTS_HAP`, self-registers with
`PIIAndHAPDetectionFactory` via `@register_pii_and_hap_detection_adapter`, and the factory
rejects flags that do not match the implemented ports:

```text
PIIAndHAPAnnotator.__init__()
    ↓ resolve pii_provider / hap_provider (legacy "provider" sets both)
PIIAndHAPDetectionFactory.validate_selection()   (fail-fast capability check)
    ↓
PIIAndHAPDetectionFactory.create_adapters(pii=..., hap=...)
    ↓
WatsonxPIIAndHAPAdapter | LiteLLMPIIAndHAPAdapter   (PII + HAP)
PresidioPIIAdapter                                 (PII only)
    ↓ injected independently
PIIHAPService(pii_adapter=..., hap_adapter=...)
```

The WatsonX and LiteLLM adapters use different underlying ports because of provider API differences:
- **`WatsonxPIIAndHAPAdapter`**: WatsonX exposes a specialized `/ml/v1/text/detection` API
  (not a standard chat API), so it wraps `TextDetectionPort`.
- **`LiteLLMPIIAndHAPAdapter`**: LiteLLM uses standard prompt-based inference, so it wraps
  `LLMInferencePort`.

## PIIHAPService

**File**

```text
src/docpipe/core/operators/quality/pii_and_hap/services/pii_hap_service.py
```

**Actual constructor signature**:

```python
PIIHAPService(*, pii_adapter: PIIDetectionPort | None = None, hap_adapter: HAPDetectionPort | None = None)
```

Receives pre-built adapters via constructor injection and calls `validate()` once per distinct
adapter at construction time (fail-fast). Per request it invokes only the capabilities present in
the payload's `detectors` (derived from `expected_redactions`); when one dual-capability adapter
serves both, it makes a single combined `detect()` call. Contains no provider branching.

## Flow JSON example

```json
{
  "type": "pii_and_hap",
  "config": {
    "provider": "watsonx",
    "provider_config": {
      "model_id": "ibm/granite-13b-chat-v2",
      "url": "https://us-south.ml.cloud.ibm.com",
      "api_key": "${WATSONX_API_KEY}",
      "container_kind": "project",
      "container_id": "${WATSONX_CONTAINER_ID}"
    }
  }
}
```

---

# 4. Embeddings Operator

**File**

```text
src/docpipe/core/operators/functional/embeddings/embeddings_operator.py
```

## Architecture

```text
EmbeddingsOperator
    ↓ calls LLMAdapterFactory.create_embedding_adapter()
    ↓ holds
LLMEmbeddingPort
    ↑ implemented by
WatsonXAdapter / LiteLLMAdapter / HuggingFaceAdapter
```

No service layer — the operator calls the port directly. This is appropriate because embeddings
generation has no business logic beyond calling `generate_embeddings_batch()`.

## Flow JSON example

```json
{
  "type": "embeddings",
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/nomic-embed-text",
      "api_base": "http://localhost:11434/v1",
      "api_key": "${OLLAMA_API_KEY}"
    }
  }
}
```

---

# 5. Chunker / Summarization

**File**

```text
src/docpipe/core/operators/functional/chunker.py
src/docpipe/core/operators/functional/summarization_service.py
```

## Architecture

```text
ChunkerOperator
    ↓ (when summarization is enabled)
SummarizationService  (src/docpipe/core/operators/functional/summarization_service.py)
    ↓ calls LLMAdapterFactory.create_inference_adapter()
    ↓ holds
LLMInferencePort
    ↑ implemented by
WatsonXAdapter / LiteLLMAdapter
```

Summarization is opt-in. When the `summarization` config block is absent, no LLM adapter is
created and the operator runs as a pure text chunker.

## SummarizationService

**Actual constructor signature**:

```python
SummarizationService(
    *,
    llm_adapter: LLMInferencePort,
    summary_sentences: int = 3,
    summary_max_words: int = 100,
    overlap_ratio: float = 0.1,
    max_length: int = 8192,
)
```

## Flow JSON example

Summarization config lives inside the `summarization` sub-key, not at the operator root:

```json
{
  "type": "chunker",
  "config": {
    "chunk_size": 512,
    "summarization": {
      "provider": "litellm",
      "provider_config": {
        "model_id": "openai/granite4:latest",
        "api_base": "http://localhost:11434/v1",
        "api_key": "${OLLAMA_API_KEY}"
      }
    }
  }
}
```

---

# Benefits of the Architecture

## Reduced Duplication

One consolidated adapter per provider instead of provider-specific adapters in every operator.

## Better Separation of Concerns

| Layer    | Responsibility                          |
| -------- | --------------------------------------- |
| Operator | Workflow orchestration                  |
| Service  | Business logic (prompts, parsing, etc.) |
| Adapter  | Provider protocol translation           |
| Port     | Interface contract                      |

## Easier Testing

* Mock common ports (`LLMInferencePort`, `LLMEmbeddingPort`) to test services in isolation
* No need to mock HTTP calls in operator-level tests

## Provider Expansion

Adding a new provider for **classification, PII/HAP, summarization, or embeddings** requires:

1. Implement the relevant port interface (`LLMInferencePort` or `LLMEmbeddingPort`)
2. Register the new adapter in `LLMAdapterFactory`

No operator changes needed for these operators.

Adding a new LLM-based provider for **entity extraction** additionally requires a thin subclass
in the entity extraction adapter package. See
[Section 2 — Adding a new LLM-based entity extraction provider](#adding-a-new-llm-based-entity-extraction-provider).
