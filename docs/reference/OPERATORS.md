---
title: Operator Reference
---

# Operator Reference

## Table of Contents

- [Operator Reference](#operator-reference)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
    - [How to use this reference](#how-to-use-this-reference)
  - [Operator API Reference](#operator-api-reference)
    - [Common Operator Contract](#common-operator-contract)
      - [Operator Ownership Attribute](#operator-ownership-attribute)
    - [Ingest Operators](#ingest-operators)
      - [IngestSourceOperator](#ingestsourceoperator)
    - [Extract Operators](#extract-operators)
      - [ExtractOperator](#extractoperator)
    - [Quality Operators](#quality-operators)
      - [DocumentClassifierOperator](#documentclassifieroperator)
      - [LanguageDetect](#languagedetect)
      - [ReadabilityOperator](#readabilityoperator)
      - [RedactionOperator](#redactionoperator)
      - [PIIAndHAPAnnotator](#piiandhapannotator)
      - [EdedupOperator](#ededupoperator)
      - [MLEnrichmentOperator](#mlenrichmentoperator)
      - [SQLFilterOperator](#sqlfilteroperator)
    - [Functional Operators](#functional-operators)
      - [ChunkerOperator](#chunkeroperator)
      - [EntityCurationOperator](#entitycurationoperator)
      - [EmbeddingsOperator](#embeddingsoperator)
      - [BranchingOperator](#branchingoperator)
      - [MergeOperator](#mergeoperator)
      - [NOOPOperator](#noopoperator)
      - [DocIdHashOperator](#docidhashoperator)
    - [VectorDB Operators](#vectordb-operators)
      - [VectorDBOperator](#vectordboperator)
    - [Storage Operators](#storage-operators)
      - [DocumentSetOperator](#documentsetoperator)
      - [StorageOutputOperator](#storageoutputoperator)
  - [DocpipeFlowManager API](#docpipeflowmanager-api)
    - [Constructor](#constructor)
    - [`validate()`](#validate)
    - [`execute()`](#execute)
    - [`get_execution_metadata()`](#get_execution_metadata)
    - [`get_execution_logs()`](#get_execution_logs)
    - [`list_operators(verbose=False)`](#list_operatorsverbosefalse)
    - [Method name note](#method-name-note)
  - [CLI API Reference](#cli-api-reference)
    - [Command forms](#command-forms)
    - [Global arguments](#global-arguments)
    - [Exit codes](#exit-codes)
  - [Flow Configuration API](#flow-configuration-api)
    - [Root structure](#root-structure)
    - [Flow fields](#flow-fields)
    - [Operator structure](#operator-structure)
    - [Operator fields](#operator-fields)
    - [Dependency declaration](#dependency-declaration)
    - [Validation rules](#validation-rules)
  - [Exception Reference](#exception-reference)
    - [`DocpipeException`](#docpipeexception)
    - [`FlowExecutionFailedException`](#flowexecutionfailedexception)
    - [`FlowValidationException`](#flowvalidationexception)
    - [`PrefectFlowFailed`](#prefectflowfailed)
    - [`ValidationException`](#validationexception)
    - [`ConfigurationError`](#configurationerror)
    - [`DependencyError`](#dependencyerror)
    - [`ExternalServiceError`](#externalserviceerror)
    - [`FlowNotFoundException`](#flownotfoundexception)
    - [`FlowAlreadyExistsException`](#flowalreadyexistsexception)
    - [`FlowInvalidDataException`](#flowinvaliddataexception)
    - [`FlowStorageException`](#flowstorageexception)
    - [`RepositoryConfigurationException`](#repositoryconfigurationexception)
    - [`ValidationAlert`](#validationalert)
    - [`ValidationAlertEncoder`](#validationalertencoder)
  - [Utilities API](#utilities-api)
    - [PyArrow handler utilities](#pyarrow-handler-utilities)
      - [`BaseParquetTableHandler`](#baseparquettablehandler)
      - [`CpdParquetTableHandler`](#cpdparquettablehandler)
      - [`get_parquet_table_handler()`](#get_parquet_table_handler)
    - [Schema utilities](#schema-utilities)
      - [`align_table_schema(table, all_cols)`](#align_table_schematable-all_cols)
      - [`_combine_tables(tables, table_type)`](#_combine_tablestables-table_type)
      - [`_total_rows(tables)`](#_total_rowstables)
    - [Document class utilities](#document-class-utilities)
      - [`DocumentClassUtils.normalize_filename(name)`](#documentclassutilsnormalize_filenamename)
      - [`DocumentClassUtils.load_document_class(doc_class_path)`](#documentclassutilsload_document_classdoc_class_path)
      - [`DocumentClassUtils.generate_docling_template(doc_class_path, include_nested=True, max_fields=None)`](#documentclassutilsgenerate_docling_templatedoc_class_path-include_nestedtrue-max_fieldsnone)
    - [Operator display utility](#operator-display-utility)
      - [`list_operators(verbose=False)`](#list_operatorsverbosefalse-1)

## Overview

[`OPERATOR_REFERENCE.md`](../reference/OPERATORS.md) centralizes the public APIs that are visible to pipeline authors, application integrators, and operator users.

This reference is organized around four entry points:

- **Operators**: flow node implementations under [`src/docpipe/core/operators`](../../src/docpipe/core/operators)
- **Programmatic execution**: [`DocpipeFlowManager`](../../src/docpipe/lib/docpipe_flow_manager.py#L24)
- **CLI execution**: [`docling-pipelines`](../../src/docpipe/cli/docpipe_cli.py#L147)
- **Flow JSON definitions**: DAG configuration consumed by the orchestrator

### How to use this reference

- Use the operator sections when authoring flow JSON.
- Use the flow manager section when embedding Docling Pipelines in Python code.
- Use the CLI section when running or validating flows from the shell.
- For classification-specific architecture details, see [`docs/operators/quality/document_classifier_readme.md`](../operators/quality/document_classifier_readme.md), which documents the simplified service-based architecture used by `DocumentClassifierOperator`.

---

## Operator API Reference

### Common Operator Contract

All operators ultimately inherit from [`AbstractOperator`](../../src/docpipe/core/operators/abstract_operator.py#L28).

**Shared behavior**

- Operators receive a `config` dictionary during initialization.
- Operators expose metadata through the static method [`get_metadata()`](../../src/docpipe/core/operators/abstract_operator.py#L59), which can be called on the class without instantiation (e.g., `OperatorClass.get_metadata()`).
- Input column requirements are expressed with [`get_required_features()`](../../src/docpipe/core/operators/abstract_operator.py#L55).
- Validation hooks are implemented via [`validate()`](../../src/docpipe/core/operators/abstract_operator.py#L51).
- Runtime work is usually performed by `transform()` or `runner()` methods depending on the operator.

**Common input shape**

Most operators consume a `pyarrow.Table` with some subset of these columns:

| Column            | Type                                    | Meaning                                       |
| ----------------- | --------------------------------------- | --------------------------------------------- |
| `id`              | string                                  | Document identifier                           |
| `name`            | string                                  | Source path or display name                   |
| `content`         | string                                  | Extracted text or serialized document content |
| `doc_id_hash`     | string                                  | Stable hashed identifier                      |
| `chunked_content` | list or JSON string                     | Chunk payloads generated by chunking          |
| `embeddings`      | vector/list[float] or list[list[float]] | Dense vector output                           |

#### Operator Ownership Attribute

All operators must declare an `owner` class variable to support priority-based resolution when multiple operators share the same `short_name`.

```python
# Built-in docpipe operators
from docpipe.core.constants.constants import DocpipeConstants
owner: str = DocpipeConstants.OWNER_DOCPIPE  # MUST be set for all built-in operators

# Custom operators
owner: str = "custom"  # MUST be set for all custom operators
```

For full details on the priority system, override behaviour, and registering custom tiers, see [CONTRIBUTING.md — Custom Operator Requirements](../../CONTRIBUTING.md#custom-operator-requirements) and [External Operator Integration — Operator Priority](../guides/EXTERNAL_OPERATOR_INTEGRATION.md#operator-priority-and-override).

### Ingest Operators

#### IngestSourceOperator

**Purpose:** Multi-provider ingest abstraction for sources such as object storage, SharePoint, OneDrive, Google Drive, Box, Dropbox, web pages, and filesystem adapters.

**Category:** Ingest

**Class:** `core.operators.ingest.ingest_source.IngestSourceOperator`

| Parameter          | Type   | Required | Default | Description                                                                  |
| ------------------ | ------ | -------: | ------- | ---------------------------------------------------------------------------- |
| `provider`         | string |      Yes | -       | Source provider: `filesystem`, `s3`, `ibm_cos`, `sharepoint`, `onedrive`, `google_drive`, `box_driver`, `dropbox`, `web` |
| `provider_config`  | object |      Yes | -       | All provider-specific parameters including credentials in a single dict      |
| `connection_params`| object |       No | -       | **Deprecated.** Use `provider_config` instead                                |
| `credentials`      | object |       No | -       | **Deprecated.** Use `provider_config` instead                                |
| `include_filter`   | string |       No | -       | Extension include list (comma-separated, e.g. `"pdf,docx"`)                  |
| `exclude_filter`   | string |       No | -       | Extension exclude list (comma-separated)                                     |
| `max_files`        | int    |       No | `100`   | Maximum number of files to ingest                                            |
| `force_ingest`     | bool   |       No | `false` | Reprocess prior docs                                                         |

**Input Schema**

- No input table required

**Output Schema**

| Column            | Type   | Description                                       |
| ----------------- | ------ | ------------------------------------------------- |
| `id`              | string | MD5 hash of the source path                       |
| `name`            | string | Source identifier (file path, URL, etc.)          |
| `document_format` | string | File extension (e.g., `.pdf`, `.xlsx`, `.docx`)   |
| `metadata`        | string | JSON-serialized metadata from the source document |
| `source_id`       | string | The source identifier                             |
| `path`            | string | Source path/URL for on-demand binary loading      |
| `modified_time`   | int64  | Document modification timestamp (Unix timestamp)  |

**Exceptions**

- `ImportError`
- `ValueError`
- authentication and network failures

**Example**

**Folder Ingestion:**

```json
{
  "name": "ingest-s3",
  "type": "ingest_source",
  "config": {
    "provider": "s3",
    "provider_config": {
      "bucket": "example-bucket",
      "prefix": "incoming/",
      "access_key": "${S3_ACCESS_KEY}",
      "secret_key": "${S3_SECRET_KEY}"
    },
    "include_filter": "pdf,docx",
    "max_files": 200
  }
}
```

**Filesystem Ingestion:**

```json
{
  "name": "ingest-local",
  "type": "ingest_source",
  "config": {
    "provider": "filesystem",
    "provider_config": {
      "paths": ["/data/documents"],
      "recursive": true
    },
    "include_filter": "pdf,docx,txt"
  }
}
```

**Note:** S3 supports file-level ingestion by specifying a full key as the `prefix` (e.g., `"incoming/report.pdf"`). For other providers, use folder-level configuration.

---

### Extract Operators

#### ExtractOperator

**Purpose:** Unified extraction operator using hexagonal architecture with multiple adapters for text extraction (docling_library, docling_serve) and entity extraction (litellm, watsonx, docling, none).

**Category:** Extract

**Class:** `core.operators.extract.extract_operator.ExtractOperator`

> **Streaming execution:** When `entity_extraction` is enabled, text and entity extraction run concurrently. Each document is submitted for entity extraction as soon as its text extraction finishes, without waiting for the full batch. When entity extraction is disabled the operator behaves as before.

| Parameter                                                     | Type   |    Required | Default                 | Supported Providers             | Description                                                                                        |
|---------------------------------------------------------------|--------|------------:|-------------------------|---------------------------------|----------------------------------------------------------------------------------------------------|
| `text_extraction`                                             | object |          No | `{"provider": "docling_library", "doc_column": "content"}` | All | Text extraction configuration (see below)                                                          |
| `text_extraction.provider`                                    | string |          No | `docling_library`       | All                             | Text extraction provider: `docling_library` (local with optional VLM) or `docling_serve` (remote API)  |
| `text_extraction.doc_column`                                  | string |          No | `content`               | All                             | Column name for storing extracted text content                                                     |
| `doc_format`                                                  | string |          No | `markdown`              | All                             | Primary content format: `"markdown"` (default) or `"doclang"`. When `"doclang"`, the `content` column contains DocLang XML instead of Markdown. Use `"doclang"` for pipelines that must preserve DocLang's structured element hierarchy through redaction and vector indexing. |
| `text_extraction.provider_config.additional_formats`          | array  |          No | `[]`                    | All                             | Additional output formats beyond the primary format: `html`, `json`, `text`, `doctags`, `doclang`, `markdown`. When `doc_format=doclang`, add `"markdown"` here to also produce a `content_markdown` column. |
| `text_extraction.provider_config.vlm_pipeline`                | object |          No | `null`                  | `docling_library`               | VLM (Vision-Language Model) pipeline configuration. When present, VLM processing is enabled. |
| `text_extraction.provider_config.vlm_pipeline.preset`         | string |          No | `granite_docling`       | `docling_library`               | VLM preset name. Valid presets: `smoldocling`, `granite_docling`, `deepseek_ocr`, `granite_vision`, `pixtral`, `got_ocr`, `phi4`, `qwen`, `nanonets_ocr2`, `gemma_12b`, `gemma_27b`, `dolphin`, `glm_ocr`, `lightonocr`, `falcon_ocr` |
| `text_extraction.provider_config.vlm_pipeline.engine`         | string |          No | `api_ollama`            | `docling_library`               | VLM engine type. Valid engines: `api_ollama`, `api_openai`, `api_watsonx`, `api_lmstudio`, `api` (generic), `transformers` (local), `mlx` (macOS) |
| `text_extraction.provider_config.vlm_pipeline.engine_options` | object |          No | `{}`                    | `docling_library`               | Engine-specific options (api_base, model_id, etc.)                                                 |
| `text_extraction.provider_config.asr_pipeline`                | object |          No | `null`                  | `docling_library`               | ASR (Automatic Speech Recognition) pipeline configuration. When present, ASR processing is enabled. |
| `text_extraction.provider_config.asr_pipeline.model_id`       | string |          No | `whisper_turbo`         | `docling_library`               | ASR model name. Valid values: `whisper_tiny`, `whisper_small`, `whisper_medium`, `whisper_base`, `whisper_large`, `whisper_turbo`, and their `_mlx`/`_native` variants (e.g., `whisper_tiny_mlx`, `whisper_tiny_native`) |
| `text_extraction.provider_config.standard_pipeline`           | object |          No | `null`                  | `docling_library`               | Standard pipeline acceleration configuration. Omit entirely for default behaviour. |
| `text_extraction.provider_config.standard_pipeline.accelerator` | object |         No | `null`                  | `docling_library`               | GPU accelerator options for PDF and image processing. When present, the GPU `DocumentConverter` is pooled process-wide and reused across documents and micro-batches. **Requires `max_workers: 1` and `use_processes: false`.** Cannot be combined with `vlm_pipeline`. |
| `text_extraction.provider_config.standard_pipeline.accelerator.device` | string | No | auto-detected | `docling_library` | GPU device to use. Accepted values: `mps` (Apple Silicon), `cuda` (NVIDIA, any device), `cuda:<index>` (e.g. `cuda:0`), `xpu` (Intel). When omitted, the best available device is auto-detected via torch (CUDA → MPS → XPU). Device availability is checked at runtime via torch backends. |
| `text_extraction.provider_config.standard_pipeline.accelerator.num_threads` | int | No | `4` | `docling_library` | Number of CPU-side threads for the Docling pipeline. Must be a positive integer. Booleans are rejected. |
| `text_extraction.provider_config`                             | object |          No | `{}`                    | All                             | Provider-specific configuration                                               |
| `text_extraction.provider_config.base_url`                    | string |         Yes | None                     | Docling Serve API endpoint (docling_serve mode). Required when using docling_serve provider.                                                                                                                                                                                                         |
| `text_extraction.provider_config.api_key`                     | string |          No | `null`                  | `docling_serve`                 | Optional API key for authentication                                           |
| `text_extraction.provider_config.timeout`                     | int    |          No | `300`                   | `docling_serve`                 | Request timeout in seconds                                                    |
| `text_extraction.provider_config.ocr`                         | object |          No | `null`                  | Both                            | OCR configuration block. Omit to use the default OCR configuration (OCR on, RapidOCR engine, default mode). |
| `text_extraction.provider_config.ocr.enabled`                 | bool   |          No | `true`                  | Both                            | Enable OCR processing.                                                        |
| `text_extraction.provider_config.ocr.engine`                  | string |          No | `"rapidocr"`            | Both                            | OCR engine: `auto`, `easyocr`, `tesserocr`, `tesseract`, `rapidocr`, `ocrmac`, `kserve_v2_ocr`, `nemotron-ocr`. `rapidocr` is the default. |
| `text_extraction.provider_config.ocr.mode`                    | string |          No | `"default"`             | Both                            | OCR scanning mode: `default`, `full_page`, `layout_regions`, `pdf_aware_layout_regions` |
| `text_extraction.provider_config.ocr.engine_options`          | object |          No | `null`                  | Both                            | Engine-specific parameters (see engine options reference in extract_operator_readme.md) |
| `text_extraction.provider_config.pdf_backend`                 | string |          No | `dlparse_v2`            | `docling_serve`                 | PDF backend: `dlparse_v4`, `dlparse_v3`, `pypdfium2`                          |
| `entity_extraction`                                           | object |          No | `{"provider": "none"}`  | All                             | Entity extraction configuration (see below)                                                        |
| `entity_extraction.provider`                                  | string |          No | `none`                  | All                             | Entity extraction provider: `litellm` (includes Ollama via openai/ prefix), `watsonx`, `docling`, or `none`. **Note:** When using any entity extraction provider (not `none`), either `custom_schema` must be provided OR a `document_type` column must be present from an upstream classification operator. |
| `entity_extraction.output_column`                             | string |          No | `entities`              | All                             | Column name for storing extracted entities                                                         |
| `entity_extraction.max_doc_chars`                             | int    |          No | `8000`                  | All                             | Maximum document characters to process for entity extraction                                       |
| `entity_extraction.expand_extracted_data`                     | bool   |          No | `false`                 | All                             | Expand entity JSON into individual columns                                                         |
| `entity_extraction.custom_schema`                             | object |          No | `{}`                    | `litellm`, `watsonx`, `docling` | Schema dictionary for structured extraction. **Required** when using entity extraction providers unless a `document_type` column is present. |
| `entity_extraction.provider_config`                           | object |          No | `{}`                    | `litellm`, `watsonx`, `docling` | Provider-specific configuration including `model_id` (see below)                                   |
| `entity_extraction.provider_config.model_id`                  | string | Conditional | varies by provider      | `litellm`, `watsonx`            | LLM model identifier (required for litellm/watsonx providers). **Must include provider prefix when using LiteLLM** (e.g., `openai/gpt-4`, `openai/llama3.2` for Ollama, `anthropic/claude-3-opus`) |
| `entity_extraction.provider_config.temperature`               | float  |          No | `0.0`                   | `litellm`, `watsonx`            | Sampling temperature                                                                               |
| `entity_extraction.provider_config.max_tokens`                | int    |          No | `2000`                  | `litellm`, `watsonx`            | Maximum response tokens                                                                            |
| `entity_extraction.provider_config.api_key`                   | string | Conditional | -                       | `litellm`, `watsonx`            | Provider API key (required for most providers)                                                     |
| `entity_extraction.provider_config.api_base`                  | string |          No | -                       | `litellm`, `watsonx`            | API endpoint URL (e.g., `http://localhost:11434/v1` for Ollama)                                    |
| `entity_extraction.provider_config.container_id`              | string | Conditional | -                       | `watsonx`                       | WatsonX container ID (required for watsonx provider)                                                   |
| `entity_extraction.provider_config.container_kind`            | string |          No | `project`               | `watsonx`                       | WatsonX container kind                                                              |
| `entity_extraction.provider_config.stream`                    | bool   |          No | `false`                 | `litellm`                       | Enable HTTP chunked transfer encoding for streaming responses. Recommended for remote vLLM clusters processing large documents to prevent connection drops. |
| `entity_extraction.provider_config.timeout`                   | int    |          No | `600`                   | `litellm`, `watsonx`            | HTTP client read timeout in seconds. Set to 1800 (30 minutes) for large documents requiring extended generation time. |
| `entity_extraction.provider_config.vlm_pipeline`              | object |          No | `{}`                    | `docling`                       | Custom VLM model configuration for Docling entity extraction                   |
| `max_workers`                                                 | int    |          No | auto                    | All                             | Maximum parallel workers (auto-detected based on CPU)                                              |
| `use_processes`                                               | bool   |          No | `false`                 | All                             | Use ProcessPoolExecutor vs ThreadPoolExecutor                                                      |

**Input Schema**

- `name` (`string`)
- binary payload column from an ingest operator
- optional existing content column

**Output Schema**

- `content` (or configured via `doc_column` parameter) - Primary extracted content: Markdown when `doc_format=markdown` (default), DocLang XML when `doc_format=doclang`
- `content_html` - HTML format (if `additional_formats` includes "html")
- `content_json` - JSON structured format (if `additional_formats` includes "json")
- `content_text` - Plain text format (if `additional_formats` includes "text")
- `content_doctags` - Docling's native DocTags format (if `additional_formats` includes "doctags")
- `content_doclang` - DocLang format (if `additional_formats` includes "doclang" and `doc_format=markdown`)
- `content_markdown` - Markdown format (if `additional_formats` includes "markdown" and `doc_format=doclang`)
- `entities` (or configured `output_column`) - Extracted entities as JSON string (if entity extraction enabled)
- `doc_id_hash` - Document hash identifier
- `pages_processed` - Number of pages in the document. Obtained from Docling extraction metadata when available; otherwise estimated using 3000 characters = 1 page
- Individual entity columns (if `expand_extracted_data=true`)

**Execution Metadata**

The operator provides the following metadata after execution:

- `page_type_stats` (dict): Aggregate estimated pages grouped by source document format (e.g., `{"pdf": 120, "docx": 45}`)
- `total_pages_converted` (int): Total estimated pages across all successfully processed documents

**Exceptions**

- `FlowExecutionFailedException`
- `ValueError` for invalid configuration
- Provider-specific exceptions (Ollama, LiteLLM, Docling)

**Example: Basic Text Extraction**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content",
      "provider_config": {}
    },
    "entity_extraction": {
      "provider": "none"
    }
  }
}
```

**Example: VLM Text Extraction**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "provider_config": {
        "vlm_pipeline": {
          "preset": "granite_docling",
          "engine": "api_ollama",
          "engine_options": {
            "api_base": "http://localhost:11434",
            "model_id": "ibm/granite-docling:258m"
          }
        }
      }
    },
    "entity_extraction": {
      "provider": "none"
    },
    "max_workers": 1
  }
}
```

**Example: GPU-Accelerated Text Extraction**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content",
      "provider_config": {
        "standard_pipeline": {
          "accelerator": {
            "device": "mps",
            "num_threads": 6
          }
        }
      }
    },
    "entity_extraction": {
      "provider": "none"
    },
    "max_workers": 1,
    "use_processes": false
  }
}
```

**Example: Docling Serve with OCR**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_serve",
      "provider_config": {
        "base_url": "http://localhost:5001",
        "ocr": {
          "enabled": true,
          "engine": "easyocr"
        },
        "pdf_backend": "dlparse_v4"
      }
    },
    "entity_extraction": {
      "provider": "none"
    }
  }
}
```

**Example: Text + LiteLLM Entity Extraction (with Ollama)**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library"
    },
    "entity_extraction": {
      "provider": "litellm",
      "provider_config": {
        "model_id": "openai/granite4:latest",
        "temperature": 0.0,
        "max_tokens": 4096,
        "api_base": "http://localhost:11434/v1",
        "api_key": "<ollama_key>"
      },
      "custom_schema": {
        "invoice_number": "string",
        "total_amount": "float"
      }
    }
  }
}
```

**Example: Text + LiteLLM Entity Extraction (with OpenAI)**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library"
    },
    "entity_extraction": {
      "provider": "litellm",
      "provider_config": {
        "model_id": "openai/gpt-3.5-turbo",
        "temperature": 0.0,
        "max_tokens": 2000,
        "api_key": "${OPENAI_API_KEY}",
        "api_base": "https://api.openai.com/v1"
      }
    }
  }
}
```

**Example: Multi-Format Output**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "provider_config": {
        "additional_formats": ["html", "json", "text", "doclang"]
      }
    },
    "entity_extraction": {
      "provider": "none"
    }
  }
}
```

**Example: Text + WatsonX Entity Extraction**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library"
    },
    "entity_extraction": {
      "provider": "watsonx",
      "provider_config": {
        "model_id": "ibm/granite-13b-chat-v2",
        "temperature": 0.0,
        "max_tokens": 2000,
        "api_key": "${WATSONX_API_KEY}",
        "container_id": "${WATSONX_CONTAINER_ID}",
        "api_base": "https://us-south.ml.cloud.ibm.com",
        "container_kind": "project"
      },
      "custom_schema": {
        "invoice_number": "string",
        "total_amount": "float"
      }
    }
  }
}
```

**Example: Docling Template-Based Entity Extraction**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library"
    },
    "entity_extraction": {
      "provider": "docling",
      "custom_schema": {
        "type": "object",
        "properties": {
          "invoice_number": { "type": "string" },
          "total_amount": { "type": "number" }
        }
      }
    }
  }
}
```

**Example: Docling Entity Extraction with Custom Inline Model**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library"
    },
    "entity_extraction": {
      "provider": "docling",
      "provider_config": {
        "vlm_pipeline": {
          "model_type": "inline",
          "inline_model": {
            "repo_id": "numind/NuExtract-2.0-2B",
            "inference_framework": "transformers",
            "scale": 2.0,
            "temperature": 0.0,
            "max_new_tokens": 4096,
            "load_in_8bit": true,
            "torch_dtype": "bfloat16"
          }
        }
      },
      "custom_schema": {
        "type": "object",
        "properties": {
          "invoice_number": { "type": "string" },
          "total_amount": { "type": "number" }
        }
      }
    }
  }
}
```

**Custom VLM Configuration for Docling Entity Extraction**

The `vlm_pipeline` parameter enables custom VLM model configuration for the Docling entity extraction adapter. Only inline models (HuggingFace) are supported as DocumentExtractor does not support remote API endpoints.

**Note:** For API-based entity extraction, use `entity_extraction.provider: "litellm"` or `"watsonx"` instead of Docling.

**Configuration Structure:**

| Parameter                                       | Type   | Required | Description                                                                     |
| ----------------------------------------------- | ------ | -------- | ------------------------------------------------------------------------------- |
| `vlm_pipeline`                                  | object | No       | Custom VLM model configuration for Docling entity extraction                    |
| `vlm_pipeline.model_type`                       | string | Yes\*    | Model type: must be `inline` (\*required if `vlm_pipeline` provided)            |
| `vlm_pipeline.inline_model`                     | object | Yes\*    | Inline model configuration (\*required if `vlm_pipeline` provided)              |
| `vlm_pipeline.inline_model.repo_id`             | string | Yes      | HuggingFace model repository ID (e.g., `numind/NuExtract-2.0-2B`)               |
| `vlm_pipeline.inline_model.inference_framework` | string | No       | Inference framework: `transformers`, `vllm`, or `mlx` (default: `transformers`) |
| `vlm_pipeline.inline_model.scale`               | float  | No       | Image scaling factor (default: `2.0`)                                           |
| `vlm_pipeline.inline_model.temperature`         | float  | No       | Sampling temperature (default: `0.0`)                                           |
| `vlm_pipeline.inline_model.max_new_tokens`      | int    | No       | Maximum generation length (default: `4096`)                                     |
| `vlm_pipeline.inline_model.load_in_8bit`        | bool   | No       | Enable 8-bit quantization (default: `true`)                                     |
| `vlm_pipeline.inline_model.torch_dtype`         | string | No       | Precision type: `bfloat16`, `float16`, `float32` (default: `bfloat16`)          |
| `vlm_pipeline.inline_model.prompt`              | string | No       | Custom prompt template (default: `""`)                                          |
| `vlm_pipeline.inline_model.response_format`     | string | No       | Response format: `markdown`, `doctags`, `html`, etc. (default: `markdown`)      |

**Usage Notes:**

- **Inline Models Only**: Only HuggingFace models loaded directly into memory are supported. DocumentExtractor does not support remote API endpoints.
- **API-Based Extraction**: For API-based entity extraction (Ollama via LiteLLM, OpenAI, etc.), use `entity_extraction.provider: "litellm"` or `"watsonx"` instead.
- **Default Behavior**: If `vlm_pipeline` is not provided, Docling uses its default model configuration.
- **Performance**: Inline models require sufficient GPU memory and are suitable for local deployment with GPU resources.
- **Compatibility**: Ensure the chosen model supports the inference framework and hardware configuration.

**Architecture**

The ExtractOperator uses hexagonal architecture (ports and adapters pattern) with clear separation of concerns:

**Layers:**

- **Domain Layer**: `EntityExtractionService` handles business logic (prompt building, schema validation, response parsing)
- **Port Layer**: `TextExtractionPort` and `EntityExtractionPort` define extraction interfaces
- **Adapter Layer**: Concrete implementations for different extraction strategies
  - Text: `DoclingAdapter` (docling_library), `DoclingServeAdapter` (docling_serve)
  - Entity: `LLMEntityAdapter` (unified for litellm/watsonx), `DoclingEntityAdapter` (docling)
- **Factory Layer**: `TextExtractionAdapterFactory` and `EntityExtractionAdapterFactory` create adapters based on provider

**Key Benefits:**

- Easy addition of new extraction strategies by implementing ports
- Clear separation between business logic, interfaces, and implementations
- Independent text and entity extraction provider selection
- Unified LLM support: Both `litellm` and `watsonx` providers use the same `LLMEntityAdapter`
- Parallel processing with auto-optimized worker counts

**Integration Requirements**

- **Ollama** (for litellm entity provider with Ollama): Server at `http://localhost:11434`, model pulled (e.g., `ollama pull llama3.2`). Access via litellm provider with `openai/` model prefix
- **Docling Serve** (for docling_serve text provider): Service at configured URL (default `http://localhost:5001`)
- **LiteLLM** (for litellm entity provider): API keys for chosen provider (OpenAI, Anthropic, etc.)
- **WatsonX** (for watsonx entity provider): Environment variables `WATSONX_API_KEY`, `WATSONX_CONTAINER_ID`, optional `WATSONX_API_BASE_URL`, `WATSONX_CONTAINER_KIND`
- **ffmpeg** (for audio/video processing): Required for M4A, AAC, OGG, FLAC audio formats and all video formats (MP4, AVI, MOV). Not required for WAV/MP3. Install: `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Linux)

**Usage Notes**

- Dual-provider operation: text and entity extraction in single operator
- Text providers: `docling_library` (local, optional VLM/ASR) or `docling_serve` (remote API with OCR)
- Entity providers: `litellm` (100+ providers including Ollama via openai/ prefix), `watsonx` (IBM WatsonX.ai), `docling` (template-based), `none` (default)
- **Entity Extraction Validation**: When using any entity extraction provider (not `none`), you must provide either:
  - A `custom_schema` in the operator configuration, OR
  - A `document_type` column from an upstream classification operator (e.g., DocumentClassifierOperator)
  - If neither is provided, a `ConfigurationError` will be thrown with message: "Entity extraction requires either a custom_schema in operator config OR a document_type column from upstream classification operator"
- **VLM Pipeline**: Configure via nested `text_extraction.provider_config.vlm_pipeline` object with `preset`, `engine`, and `engine_options` for enhanced extraction of complex documents
- **ASR Pipeline**: Configure via nested `text_extraction.provider_config.asr_pipeline` object with `model_id` for audio/video transcription
- Docling Serve provider supports OCR for scanned documents and multi-language processing
- **Text File Handling**: `.txt` files are automatically processed locally using UTF-8/latin-1 decoding, bypassing Docling Serve even when `docling_serve` provider is configured
- **Extension Detection**: Files without extensions are automatically detected using magic byte analysis (supports PDF, DOCX, XLSX, PPTX, images, HTML, and text formats)
- Audio/Video Support: Processes audio (WAV, MP3, M4A, AAC, OGG, FLAC) and video (MP4, AVI, MOV) files using ASR. Requires ffmpeg for M4A, AAC, OGG, FLAC, and all video formats
- **Extension Validation**: Files with unsupported extensions are automatically skipped and logged. Supported extensions vary by provider:
  - `docling_library`: PDF, DOCX, PPTX, XLSX, images, HTML, Markdown, AsciiDoc, TXT, and audio/video (with ASR)
  - `docling_serve`: Same as docling_library except NO audio/video support
  - `docling` entity extraction: PDF, DOCX, PPTX, HTML, images (excludes XLSX, TXT, MD, WEBP)
- See [ExtractOperator](../operators/extract/extract_operator_readme.md) for complete documentation including detailed extension support

---

### Quality Operators

#### DocumentClassifierOperator

**Purpose:** Classifies documents into predefined types using LLM-based classification with confidence scoring and reasoning. Uses a port/adapter architecture (`ClassificationPort`) with shared LLM infrastructure supporting multiple providers (LiteLLM, Watsonx).

**Category:** Quality

**Class:** `core.operators.quality.classification.document_classifier.DocumentClassifierOperator`

| Parameter                  | Type      | Required | Default                        | Description                                                                                                                                                                     |
| -------------------------- | --------- | -------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `provider`                 | string    | No       | `"litellm"`                    | LLM provider: `"litellm"` or `"watsonx"`                                                                                                                                        |
| `provider_config`          | object    | No       | `{}`                           | Provider-specific configuration (api_key, api_base, etc.)                                                                                                                       |
| `provider_config.model_id` | string    | No       | `"openai/granite3.1-dense:8b"` | Model identifier in `<provider>/<model_id>` format (e.g., `"openai/granite3.1-dense:8b"` for Ollama, `"openai/gpt-4o-mini"`, `"huggingface/meta-llama/Llama-3.3-70B-Instruct"`) |
| `document_types`           | list/dict | No       | Auto-loaded                    | Document types to classify into (list or dict with descriptions)                                                                                                                |
| `confidence_threshold`     | float     | No       | `7.0`                          | Minimum confidence for classification (1-10 scale)                                                                                                                              |
| `doc_column`               | string    | No       | `"content"`                    | Column containing document text                                                                                                                                                 |
| `output_column`            | string    | No       | `"document_type"`              | Column name for classification result                                                                                                                                           |
| `include_confidence`       | boolean   | No       | `true`                         | Include confidence score in output                                                                                                                                              |
| `include_reasoning`        | boolean   | No       | `false`                        | Include reasoning explanation in output                                                                                                                                         |
| `max_content_length`       | integer   | No       | `2000`                         | Maximum content length to send to LLM                                                                                                                                           |
| `strict_label_matching`    | boolean   | No       | `false`                        | Write the configured spelling of the matched document type and reject labels that match none (output `None`). When `false`, any label is accepted and normalised to lower-case with underscores |
| `max_workers`              | integer   | No       | Auto                           | Number of parallel workers                                                                                                                                                      |
| `use_processes`            | boolean   | No       | `false`                        | Use processes instead of threads                                                                                                                                                |

**Provider-Specific Configuration**

**LiteLLM (100+ providers):**

```json
{
  "provider": "litellm",
  "provider_config": {
    "model_id": "openai/gpt-4o-mini",
    "api_key": "${OPENAI_API_KEY}",
    "timeout": 120
  }
}
```

Supported LiteLLM providers:

- OpenAI: `openai/gpt-4o-mini`, `openai/gpt-4`, `openai/gpt-3.5-turbo`
- Anthropic: `anthropic/claude-3-opus`, `anthropic/claude-3-sonnet`, `anthropic/claude-3-haiku`
- Azure OpenAI: `azure/gpt-4`
- AWS Bedrock: `bedrock/anthropic.claude-3-sonnet`
- Google Vertex AI: `vertex_ai/gemini-pro`
- HuggingFace: `huggingface/meta-llama/Llama-3.3-70B-Instruct`, `huggingface/mistralai/Mistral-7B-Instruct-v0.2`
- Ollama via OpenAI-compatible endpoint: `openai/llama3.2:latest`, `openai/granite3.1-dense:8b` with `api_base: "http://localhost:11434/v1"`

**Watsonx:**

```json
{
  "provider": "watsonx",
  "provider_config": {
    "model_id": "ibm/granite-13b-chat-v2",
    "api_base": "https://us-south.ml.cloud.ibm.com",
    "api_key": "${WATSONX_API_KEY}",
    "container_kind": "project",
    "container_id": "${WATSONX_CONTAINER_ID}",
    "timeout": 120
  }
}
```

**Input Schema**

- PyArrow Table with document content (text column or binary content for extraction)
- Optional `content` column (if not present, will be fetched from binary content)
- **File Extension Validation**: Only documents with supported file extensions are processed: `.pdf`, `.docx`, `.pptx`, `.doc`, `.ppt`
  - Unsupported file types are **skipped** (not classified) but remain in the output table with `None` classification values

**Output Schema**

Adds the following columns:

- `document_type` (string): Classified document type
- `document_type_confidence` (float): Confidence score 1-10 (if `include_confidence=true`)
- `document_type_reasoning` (string): Classification explanation (if `include_reasoning=true`)
- `content` (string): Document content (if fetched and not already present)

**Metadata**

The operator tracks document processing statistics in metadata:

- `processed_docs`: Number of successfully classified documents
- `failed_docs`: List of failed document paths with reasons (errors during processing)
- `failed_docs_count`: Total number of failed documents
- `skipped_docs`: List of skipped document paths with reasons (includes unsupported file extensions)
- `skipped_docs_count`: Total number of skipped documents

**Document Types Configuration**

Simple list format:

```json
{
  "document_types": ["invoice", "receipt", "contract", "report", "letter"]
}
```

Detailed dictionary format (recommended):

```json
{
  "document_types": {
    "invoice": "Business invoice with line items, totals, and payment terms",
    "receipt": "Payment receipt or transaction confirmation",
    "contract": "Legal contract or agreement document",
    "report": "Business or technical report with analysis and findings",
    "other": "Other document types not fitting above categories"
  }
}
```

**Exceptions**

- `DocpipeException`: Adapter initialization failures, invalid provider configuration
- `ValueError`: Invalid response format from LLM
- `json.JSONDecodeError`: Failed to parse LLM response

**Example - LiteLLM with OpenAI**

```json
{
  "id": "classify-node",
  "name": "classify",
  "operator": "classification_operator",
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/gpt-4o-mini",
      "api_key": "${OPENAI_API_KEY}"
    },
    "document_types": {
      "invoice": "Business invoice with line items and totals",
      "receipt": "Payment receipt or confirmation",
      "contract": "Legal contract or agreement",
      "report": "Business or technical report"
    },
    "confidence_threshold": 8.0,
    "include_confidence": true,
    "include_reasoning": true,
    "max_content_length": 4000
  }
}
```

**Example - LiteLLM with Ollama OpenAI-Compatible Endpoint**

```json
{
  "id": "classify-node",
  "name": "classify",
  "operator": "document_classifier",
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/llama3.2:latest",
      "api_key": "${api-key}",
      "api_base": "http://localhost:11434/v1"
    },
    "document_types": {
      "invoice": "Business invoice with line items, totals, and payment terms",
      "receipt": "Payment receipt or transaction confirmation",
      "contract": "Legal contract or agreement document",
      "other": "Other document types"
    },
    "confidence_threshold": 7.0,
    "include_confidence": true,
    "include_reasoning": true
  }
}
```

**Architecture**

Uses a hexagonal (ports and adapters) architecture:

- **Operator Layer**: `DocumentClassifierOperator` handles PyArrow table processing and orchestration, and depends only on `ClassificationPort`
- **Port**: `ClassificationPort` defines `classify_document()`; `ClassificationAdapterFactory` resolves the `provider` to a concrete adapter
- **Adapter**: `StandardLLMClassificationAdapter` performs prompt building, the LLM call and response parsing. It also extracts text with Docling when only binary content is available, and reports it back for reuse by the Extract operator
- **Domain Layer**: Pure domain models (`ClassificationRequest`, `ClassificationResponse`) and prompt building
- **Infrastructure Layer**: Leverages shared `LLMAdapterFactory` for multi-provider LLM support (LiteLLM, Watsonx)

See the [Classification Operator Guide](../operators/quality/document_classifier_readme.md#architecture) for details.

**Related Documentation**

- [Classification Operator Guide](../operators/quality/document_classifier_readme.md)
- [Extract Operator](../operators/extract/extract_operator_readme.md)

---

#### LanguageDetect

**Purpose:** Detect document language and confidence scores using a pluggable adapter.

**Category:** Quality

**Class:** `core.operators.quality.language_detection.lang_id.LanguageDetect`

| Parameter                 | Type   | Required | Default      | Description                              |
| ------------------------- | ------ | -------: | ------------ | ---------------------------------------- |
| `doc_column`              | string |       No | `content`    | Text input column                        |
| `filter_unknown_language` | bool   |       No | `false`      | Drop documents that cannot be classified |
| `language_provider`       | string |       No | `langdetect` | Detection provider                       |

**Output Schema**

- `content` (or configured via `doc_column` parameter) - Extracted markdown text (always generated)
- `content_html` - HTML format (if `additional_formats` includes "html")
- `content_json` - JSON structured format (if `additional_formats` includes "json")
- `content_text` - Plain text format (if `additional_formats` includes "text")
- `content_doctags` - Docling's native DocTags format (if `additional_formats` includes "doctags")
- `content_doclang` - DocLang format (if `additional_formats` includes "doclang")
- `entities` (or configured `output_column`) - Extracted entities as JSON string (if entity extraction enabled)
- `doc_id_hash` - Document hash identifier
- `pages_processed` - Number of pages in the document. Obtained from Docling extraction metadata when available; otherwise estimated using 3000 characters = 1 page
- Individual entity columns (if `expand_extracted_data=true`)

**Execution Metadata**

The operator provides the following metadata after execution:

- `page_type_stats` (dict): Aggregate estimated pages grouped by source document format (e.g., `{"pdf": 120, "docx": 45}`)
- `total_pages_converted` (int): Total estimated pages across all successfully processed documents

**Exceptions**

- [`FlowExecutionFailedException`](../../src/docpipe/exceptions/docpipe_exceptions.py)
- `ValueError` for invalid configuration
- Provider-specific exceptions (Ollama, LiteLLM, Docling)

**Example: Basic Text Extraction**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content",
      "provider_config": {
      }
    },
    "entity_extraction": {
      "provider": "none"
    }
  }
}
```

**Example: VLM Text Extraction**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "provider_config": {
        "vlm_pipeline": {
          "preset": "granite_docling",
          "engine": "api_ollama",
          "engine_options": {
            "api_base": "http://localhost:11434",
            "model_id": "ibm/granite-docling:258m"
          }
        }
      }
    },
    "entity_extraction": {
      "provider": "none"
    },
    "max_workers": 1
  }
}
```

**Example: Docling Serve with OCR**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_serve",
      "provider_config": {
        "base_url": "http://localhost:5001",
        "ocr": {
          "enabled": true,
          "engine": "easyocr"
        },
        "pdf_backend": "dlparse_v4"
      }
    },
    "entity_extraction": {
      "provider": "none"
    }
  }
}
```

**Example: Text + LiteLLM Entity Extraction (with Ollama)**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library"
    },
    "entity_extraction": {
      "provider": "litellm",
      "provider_config": {
        "model_id": "openai/granite4:latest",
        "temperature": 0.0,
        "max_tokens": 4096,
        "api_base": "http://localhost:11434/v1",
        "api_key": "<ollama_key>"
      },
      "custom_schema": {
        "invoice_number": "string",
        "total_amount": "float"
      }
    }
  }
}
```

**Example: Text + LiteLLM Entity Extraction (with OpenAI)**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library"
    },
    "entity_extraction": {
      "provider": "litellm",
      "provider_config": {
        "model_id": "openai/gpt-3.5-turbo",
        "temperature": 0.0,
        "max_tokens": 2000,
        "api_key": "${OPENAI_API_KEY}",
        "api_base": "https://api.openai.com/v1"
      }
    }
  }
}
```

**Example: Multi-Format Output**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "provider_config": {
        "additional_formats": ["html", "json", "text", "doclang"],
      }
    },
    "entity_extraction": {
      "provider": "none"
    }
  }
}
```

**Example: Text + WatsonX Entity Extraction**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library"
    },
    "entity_extraction": {
      "provider": "watsonx",
      "provider_config": {
        "model_id": "ibm/granite-13b-chat-v2",
        "temperature": 0.0,
        "max_tokens": 2000,
        "api_key": "${WATSONX_API_KEY}",
        "container_id": "${WATSONX_CONTAINER_ID}",
        "api_base": "https://us-south.ml.cloud.ibm.com",
        "container_kind": "project"
      },
      "custom_schema": {
        "invoice_number": "string",
        "total_amount": "float"
      }
    }
  }
}
```

**Example: Docling Template-Based Entity Extraction**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library"
    },
    "entity_extraction": {
      "provider": "docling",
      "custom_schema": {
        "type": "object",
        "properties": {
          "invoice_number": { "type": "string" },
          "total_amount": { "type": "number" }
        }
      }
    }
  }
}
```

**Example: Docling Entity Extraction with Custom Inline Model**

```json
{
  "id": "extract-node",
  "name": "extract",
  "operator": "extract_operator",
  "config": {
    "text_extraction": {
      "provider": "docling_library"
    },
    "entity_extraction": {
      "provider": "docling",
      "provider_config": {
        "vlm_pipeline": {
          "model_type": "inline",
          "inline_model": {
            "repo_id": "numind/NuExtract-2.0-2B",
            "inference_framework": "transformers",
            "scale": 2.0,
            "temperature": 0.0,
            "max_new_tokens": 4096,
            "load_in_8bit": true,
            "torch_dtype": "bfloat16"
          }
        }
      },
      "custom_schema": {
        "type": "object",
        "properties": {
          "invoice_number": { "type": "string" },
          "total_amount": { "type": "number" }
        }
      }
    }
  }
}
```

**Custom VLM Configuration for Docling Entity Extraction**

The `vlm_pipeline` parameter enables custom VLM model configuration for the Docling entity extraction adapter. Only inline models (HuggingFace) are supported as DocumentExtractor does not support remote API endpoints.

**Note:** For API-based entity extraction, use `entity_extraction.provider: "litellm"` or `"watsonx"` instead of Docling.

**Configuration Structure:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `vlm_pipeline` | object | No | Custom VLM model configuration for Docling entity extraction |
| `vlm_pipeline.model_type` | string | Yes* | Model type: must be `inline` (*required if `vlm_pipeline` provided) |
| `vlm_pipeline.inline_model` | object | Yes* | Inline model configuration (*required if `vlm_pipeline` provided) |
| `vlm_pipeline.inline_model.repo_id` | string | Yes | HuggingFace model repository ID (e.g., `numind/NuExtract-2.0-2B`) |
| `vlm_pipeline.inline_model.inference_framework` | string | No | Inference framework: `transformers`, `vllm`, or `mlx` (default: `transformers`) |
| `vlm_pipeline.inline_model.scale` | float | No | Image scaling factor (default: `2.0`) |
| `vlm_pipeline.inline_model.temperature` | float | No | Sampling temperature (default: `0.0`) |
| `vlm_pipeline.inline_model.max_new_tokens` | int | No | Maximum generation length (default: `4096`) |
| `vlm_pipeline.inline_model.load_in_8bit` | bool | No | Enable 8-bit quantization (default: `true`) |
| `vlm_pipeline.inline_model.torch_dtype` | string | No | Precision type: `bfloat16`, `float16`, `float32` (default: `bfloat16`) |
| `vlm_pipeline.inline_model.prompt` | string | No | Custom prompt template (default: `""`) |
| `vlm_pipeline.inline_model.response_format` | string | No | Response format: `markdown`, `doctags`, `html`, etc. (default: `markdown`) |

**Usage Notes:**

- **Inline Models Only**: Only HuggingFace models loaded directly into memory are supported. DocumentExtractor does not support remote API endpoints.
- **API-Based Extraction**: For API-based entity extraction (Ollama via LiteLLM, OpenAI, etc.), use `entity_extraction.provider: "litellm"` or `"watsonx"` instead.
- **Default Behavior**: If `vlm_pipeline` is not provided, Docling uses its default model configuration.
- **Performance**: Inline models require sufficient GPU memory and are suitable for local deployment with GPU resources.
- **Compatibility**: Ensure the chosen model supports the inference framework and hardware configuration.

**Architecture**

The ExtractOperator uses hexagonal architecture (ports and adapters pattern) with clear separation of concerns:

**Layers:**
- **Domain Layer**: `EntityExtractionService` handles business logic (prompt building, schema validation, response parsing)
- **Port Layer**: `TextExtractionPort` and `EntityExtractionPort` define extraction interfaces
- **Adapter Layer**: Concrete implementations for different extraction strategies
  - Text: `DoclingAdapter` (docling_library), `DoclingServeAdapter` (docling_serve)
  - Entity: `LLMEntityAdapter` (unified for litellm/watsonx), `DoclingEntityAdapter` (docling)
- **Factory Layer**: `TextExtractionAdapterFactory` and `EntityExtractionAdapterFactory` create adapters based on provider

**Key Benefits:**
- Easy addition of new extraction strategies by implementing ports
- Clear separation between business logic, interfaces, and implementations
- Independent text and entity extraction provider selection
- Unified LLM support: Both `litellm` and `watsonx` providers use the same `LLMEntityAdapter`
- Parallel processing with auto-optimized worker counts

**Integration Requirements**

- **Ollama** (for litellm entity provider with Ollama): Server at `http://localhost:11434`, model pulled (e.g., `ollama pull llama3.2`). Access via litellm provider with `openai/` model prefix
- **Docling Serve** (for docling_serve text provider): Service at configured URL (default `http://localhost:5001`)
- **LiteLLM** (for litellm entity provider): API keys for chosen provider (OpenAI, Anthropic, etc.)
- **WatsonX** (for watsonx entity provider): Environment variables `WATSONX_API_KEY`, `WATSONX_CONTAINER_ID`, optional `WATSONX_API_BASE_URL`, `WATSONX_CONTAINER_KIND`
- **ffmpeg** (for audio/video processing): Required for M4A, AAC, OGG, FLAC audio formats and all video formats (MP4, AVI, MOV). Not required for WAV/MP3. Install: `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Linux)

**Usage Notes**

- Dual-provider operation: text and entity extraction in single operator
- Text providers: `docling_library` (local, optional VLM/ASR) or `docling_serve` (remote API with OCR)
- Entity providers: `litellm` (100+ providers including Ollama via openai/ prefix), `watsonx` (IBM WatsonX.ai), `docling` (template-based), `none` (default)
- **Entity Extraction Validation**: When using any entity extraction provider (not `none`), you must provide either:
  - A `custom_schema` in the operator configuration, OR
  - A `document_type` column from an upstream classification operator (e.g., DocumentClassifierOperator)
  - If neither is provided, a `ConfigurationError` will be thrown with message: "Entity extraction requires either a custom_schema in operator config OR a document_type column from upstream classification operator"
- **VLM Pipeline**: Configure via nested `text_extraction.provider_config.vlm_pipeline` object with `preset`, `engine`, and `engine_options` for enhanced extraction of complex documents
- **ASR Pipeline**: Configure via nested `text_extraction.provider_config.asr_pipeline` object with `model_id` for audio/video transcription
- Docling Serve provider supports OCR for scanned documents and multi-language processing
- **Text File Handling**: `.txt` files are automatically processed locally using UTF-8/latin-1 decoding, bypassing Docling Serve even when `docling_serve` provider is configured
- **Extension Detection**: Files without extensions are automatically detected using magic byte analysis (supports PDF, DOCX, XLSX, PPTX, images, HTML, and text formats)
- Audio/Video Support: Processes audio (WAV, MP3, M4A, AAC, OGG, FLAC) and video (MP4, AVI, MOV) files using ASR. Requires ffmpeg for M4A, AAC, OGG, FLAC, and all video formats
- **Extension Validation**: Files with unsupported extensions are automatically skipped and logged. Supported extensions vary by provider:
  - `docling_library`: PDF, DOCX, PPTX, XLSX, images, HTML, Markdown, AsciiDoc, TXT, and audio/video (with ASR)
  - `docling_serve`: Same as docling_library except NO audio/video support
  - `docling` entity extraction: PDF, DOCX, PPTX, HTML, images (excludes XLSX, TXT, MD, WEBP)
- See [ExtractOperator](../operators/extract/extract_operator_readme.md) for complete documentation including detailed extension support

---

#### ReadabilityOperator

**Purpose:** Compute readability metrics using `dpk_readability`.

**Category:** Quality

**Class:** `core.operators.quality.readability.ReadabilityOperator`

| Parameter                | Type         | Required | Default           | Description        |
| ------------------------ | ------------ | -------: | ----------------- | ------------------ |
| `doc_column`             | string       |       No | `content`         | Input text column  |
| `readability_score_list` | list[string] |      Yes | default score set | Metrics to compute |

**Output Schema**

- selected readability columns

---

#### RedactionOperator

**Purpose:** Mask words or regex matches in document content.

**Category:** Quality

**Class:** `core.operators.quality.redaction.RedactionOperator`

| Parameter           | Type   | Required | Default           | Description                  |
| ------------------- | ------ | -------: | ----------------- | ---------------------------- |
| `doc_column`        | string |       No | `content`         | Input text column            |
| `regex`             | string |      Yes | -                 | Pattern or literal to redact |
| `masking_character` | string |       No | `*`               | Replacement character        |
| `stats_column`      | string |       No | `redaction_stats` | Per-row redaction count      |
| `doc_format`        | string |       No | `markdown`        | Content format of the input column: `"markdown"` (default) or `"doclang"`. When `"doclang"`, redaction is applied per DOM node using `defusedxml` — XML tags, attributes, and element hierarchy are preserved. Falls back to plain-text redaction if the XML is malformed. |

**Output Schema**

- updated `content`
- redaction stats column

---

#### PIIAndHAPAnnotator

**Purpose:** Detect Personally Identifiable Information (PII) and Hate, Abuse, and Profanity (HAP) content, with optional redaction. PII and HAP can use different providers: `litellm` and `watsonx` support both, `presidio` supports PII only.

**Category:** Quality

**Short Name:** `pii_and_hap`

**Class:** `core.operators.quality.pii_and_hap.pii_and_hap_annotator.PIIAndHAPAnnotator`

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `provider` | string | No | `litellm` | Provider for every expected redaction without its own `pii_provider` / `hap_provider`: `litellm`, `watsonx`, `presidio` (PII only) |
| `provider_config` | object | No | `{}` | Provider-specific configuration (see below); shared with `pii_provider` / `hap_provider` when they name the same provider or `provider` is unset |
| `pii_provider` | string | No | — | Provider for PII only: `litellm`, `watsonx`, `presidio` |
| `pii_provider_config` | object | No | `{}` | Configuration for `pii_provider` (falls back to `provider_config` as above) |
| `hap_provider` | string | No | — | Provider for HAP only: `litellm`, `watsonx` |
| `hap_provider_config` | object | No | `{}` | Configuration for `hap_provider` (falls back to `provider_config` as above) |
| `doc_column` | string | No | `content` | Input text column |
| `expected_redactions` | list | No | `["pii","hap"]` | Detection types to run: any subset of `["pii","hap"]` |
| `pii_list` | list | No | all 13 types | PII types to detect |
| `redaction` | boolean | No | `false` | Replace detected PII spans with `redaction_character` |
| `redaction_character` | string | No | `*` | Masking character for PII redaction |
| `hap_redaction` | boolean | No | `false` | Replace detected HAP spans with `hap_redaction_character` |
| `hap_redaction_character` | string | No | `*` | Masking character for HAP redaction |
| `pii_threshold` | float | No | `0.5` | Confidence threshold for PII detection (0.0–1.0) |
| `hap_threshold` | float | No | `0.8` | Confidence threshold for HAP detection (0.0–1.0) |
| `display_pii` | boolean | No | `false` | Add extra columns with detected PII values (**testing only**) |

**`provider_config` — LiteLLM:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `model_id` | string | Yes | Model ID with provider prefix (e.g. `openai/granite4` for Ollama) |
| `api_base` | string | No | API endpoint URL (e.g. `http://localhost:11434/v1` for Ollama) |
| `api_key` | string | No | Authentication key |

**`provider_config` — WatsonX:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `model_id` | string | Yes | WatsonX model identifier |
| `api_key` | string | Yes | IBM Cloud API key |
| `url` | string | Yes | WatsonX endpoint URL |
| `container_kind` | string | Yes | `"project"` or `"space"` |
| `container_id` | string | Yes | Project or space UUID |
| `timeout` | integer | No | Request timeout in seconds (default: `300`) |

**`provider_config` — Presidio (PII only; requires `pip install "docling-pipelines[presidio]"` and a spaCy model):**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `language` | string | No | Document language code (default: `en`) |
| `spacy_model` | string | No | spaCy NER model (default: `en_core_web_lg`) |
| `entity_mapping` | object | No | Presidio entity type to PII type overrides (e.g. `{"DATE_TIME": "DateOfBirth"}`) |

A provider selected for a capability it does not support (e.g. `hap_provider: "presidio"`) fails validation before any document is processed.

**Output Schema:**

| Column | Type | Description |
| --- | --- | --- |
| `pii_bank_account` | int64 | Count of bank account numbers detected |
| `pii_credit_card` | int64 | Count of credit card numbers detected |
| `pii_email_address` | int64 | Count of email addresses detected |
| `pii_ip_address` | int64 | Count of IP addresses detected |
| `pii_phone_number` | int64 | Count of phone numbers detected |
| `pii_ssn_details` | int64 | Count of Social Security Numbers detected |
| `pii_person_name` | int64 | Count of person names detected |
| `pii_date_of_birth` | int64 | Count of dates of birth detected |
| `pii_address` | int64 | Count of physical addresses detected |
| `pii_passport_number` | int64 | Count of passport numbers detected |
| `pii_driver_license` | int64 | Count of driver's license numbers detected |
| `pii_national_id` | int64 | Count of national identity numbers detected |
| `pii_medical_record` | int64 | Count of medical record numbers detected |
| `hap` | int64 | Count of HAP instances detected |

When `display_pii: true`, additional `*_info` columns are appended for each PII type. **Never enable in production.**

**See Also:** [PII and HAP Documentation](../operators/quality/pii_and_hap_readme.md)

---

#### EdedupOperator

**Purpose:** Remove repeated normalized content using atomic shared hash registration.

**Category:** Quality

**Class:** `core.operators.quality.ededup.EdedupOperator`

| Parameter | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `doc_column` | string | No | `content` | Content column to normalize and hash |
| `doc_id_hash_column` | string | No | `doc_id_hash` | Required document hash/ID input column; content is hashed independently |

The legacy `filter` argument is unsupported. It was a backend-only argument and was not exposed as a user-configurable
field in the UI. The operator uses its dedicated `ededup.storage` backend configured in
`docling-pipelines-config.yaml`. PostgreSQL coordinates separate pods; filesystem coordinates callers sharing one local
storage directory. The orchestrator supplies job, run, and node IDs. Direct callers supplying job/run context must also
supply the node ID; partial execution context is rejected.
Call `transform(table)` when invoking the operator directly; the former `transform(table, file_name=...)` form is
unsupported. Context-free standalone instances retain an in-memory registry across calls on that instance only.

Configuration precedence is `ededup.storage` over `global_storage` over filesystem defaults; nested ededup config values
override shared values. `incremental_metadata` settings and `DOCPIPE_INCREMENTAL_BASE_DIR` are not consulted. Invalid
ededup backend settings fail explicitly. PostgreSQL uses common `DOCPIPE_POSTGRES_*` connection settings and creates
only `hashes`, defaulting to the `ededup_registry` schema when no schema is configured. Filesystem uses
`<base_dir>/ededup_registry/hashes_<scope_hash>.parquet` and matching `.lock` files, where `base_dir` is
`ededup.storage.config.base_dir` or the common data root. The scope hash is SHA-256 of the JSON-encoded
`[job_id, node_id, job_run_id]`. Registry records persist across runs and source deletion.
When moving from the earlier coupled configuration, copy service-specific storage settings into `ededup.storage`
before running. Data under the previous `dedup_registry` namespace and legacy `ededup_hashes` tables/folders are not automatically migrated or read. To keep using PostgreSQL data from the previous default, set the schema to `dedup_registry`; move previous filesystem registry files into the new `ededup_registry` directory under the same base directory.

Registration is isolated by `(job_id, node_id, job_run_id, hash_value)`. Within each input table, the first occurrence wins;
across concurrent batches the winner depends on registration order. Hashes use the existing normalization: remove spaces,
newlines and ASCII punctuation, lowercase, then SHA-256. This is not a byte-for-byte comparison.

The five stored fields are `job_id`, `node_id`, `job_run_id`, `hash_value`, and `doc_id`; document ID is not part of
uniqueness. Each branch's ededup node admits independently, while all workers for one node share its stable ID. Merging
branch outputs adds no automatic cross-branch deduplication. PostgreSQL uses bounded bulk inserts with conflict-ignore
and returns only newly inserted hashes after the whole call commits; an error rolls back every chunk.

A renamed document with unchanged content is skipped if the same node/run already admitted its hash; the original
record is unchanged. A new run, or another branch's node without that hash, can admit the new document ID independently.
Reopening an existing registry preserves these memberships. A downstream failure does not remove admissions: retrying
at the same node/run skips the hash, while a new run can accept it.

Records retain the accepted source `doc_id` and are not removed when source documents disappear. Historical runs never
suppress a new run, including overlapping runs. These records are admissions, not completed-processing history; they are
retained and require an operational retention policy at scale. No automatic run cleanup is performed.

Deduplication does not perform rename detection, downstream filename updates, or reuse of previously generated outputs.

---

#### MLEnrichmentOperator

**Purpose:** Compute text quality features using `dpk_enrichment`.

**Category:** Quality

**Class:** `core.operators.quality.ml_enrichment.MLEnrichmentOperator`

| Parameter                        | Type   | Required | Default           | Description                          |
| -------------------------------- | ------ | -------: | ----------------- | ------------------------------------ |
| `doc_column`                     | string |       No | `content`         | Input text column                    |
| `lang_column`                    | string |       No | language constant | Language column                      |
| `output_column_prefix`           | string |       No | `""`              | Prefix for generated feature columns |
| `newline_normalized_column_name` | string |       No | `""`              | Optional normalized text output      |
| `error_column_name`              | string |       No | `""`              | Optional per-row error column        |

---

#### SQLFilterOperator

**Purpose:** Filter rows with SQL-like expressions or structured criteria and optionally drop selected columns.

**Category:** Quality

**Class:** `core.operators.quality.sql_filter.SQLFilterOperator`

| Parameter                 | Type         | Required | Default | Description                       |
| ------------------------- | ------------ | -------: | ------- | --------------------------------- |
| `filter_criteria_list`    | list[string] |       No | `[]`    | SQL-style predicates              |
| `filter_logical_operator` | string       |       No | `AND`   | Join operator for criteria        |
| `features_to_drop`        | list[string] |       No | `[]`    | Columns to remove after filtering |
| `filter_criteria_json`    | object       |       No | -       | Structured criteria format        |

---


### Functional Operators

#### ChunkerOperator

**Purpose:** Split extracted text into chunks using simple, semantic, or hybrid/docling strategies with optional multi-provider LLM summarization.

**Category:** Functional

**Class:** `core.operators.functional.chunker.ChunkerOperator`

| Parameter                                | Type   | Required | Default                                  | Description                                                                                                              |
| ---------------------------------------- | ------ | -------: | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `doc_column`                             | string |      Yes | `content`                                | Input content column                                                                                                     |
| `chunk_type`                             | string |      Yes | `simple`                                 | `simple`, `semantic`, or `hybrid`                                                                                        |
| `chunk_size`                             | int    |       No | project default                          | Character or token size depending on chunker                                                                             |
| `chunk_overlap`                          | int    |       No | `200`                                    | Overlap between chunks                                                                                                   |
| `chunk_overlap_percentage`               | int    |       No | `20`                                     | Overlap as a percentage of `chunk_size` (0–40). Validated for `simple` and `hybrid` only. Values above 20 produce a warning. |
| `semantic_embeddings_model`              | string |       No | None                                     | Ollama model for semantic chunking (required if chunk_type is semantic)                                                  |
| `breakpoint_threshold_type`              | string |       No | `percentile`                             | Semantic split threshold method                                                                                          |
| `breakpoint_threshold_amount`            | float  |       No | `null`                                   | Threshold amount                                                                                                         |
| `docling_tokenizer`                      | string |       No | `sentence-transformers/all-MiniLM-L6-v2` | Tokenizer for hybrid chunking (only used when chunk_type is hybrid)                                                      |
| `retain_original_content`                | bool   |       No | `false`                                  | Keep original content                                                                                                    |
| `summarization`                          | object |       No | `{}`                                     | **Nested config object** for all summarization settings. When present with provider specified, summarization is enabled. |
| `summarization.provider`                 | string |       No | `litellm`                                | LLM provider: `litellm` or `watsonx`                                                                                     |
| `summarization.provider_config`          | object |       No | `{}`                                     | Provider-specific configuration including `model_id`                                                                     |
| `summarization.provider_config.model_id` | string |       No | `granite4`                               | Model ID (auto-prefixed with `openai/` for LiteLLM)                                                                      |
| `summarization.max_input_tokens`         | int    |       No | `8000`                                   | Maximum tokens per LLM request (range: 1000-32000)                                                                       |
| `summarization.overlap_ratio`            | float  |       No | `0.2`                                    | Overlap ratio for sliding window summarization                                                                           |
| `summarization.summary_sentences`        | int    |       No | `2`                                      | Target sentences per summary (range: 1-5)                                                                                |
| `summarization.summary_max_words`        | int    |       No | `20`                                     | Maximum words per summary (range: 10-100)                                                                                |

**Note:** Flat configuration (top-level `summarization_provider`, `summarization_provider_config`, etc.) is still supported for backward compatibility but the nested `summarization` object is recommended.

**Summarization Providers:**

When `summarization` object is present with a `provider` specified, the operator uses the common LLM infrastructure to generate summaries for each chunk:

- **LiteLLM** (default): Unified API for 100+ providers (OpenAI, Azure, Anthropic, Cohere, AWS Bedrock, GCP Vertex AI, etc.)
- **Watsonx**: IBM watsonx.ai cloud service (enterprise AI)

**Provider-Specific Configuration (`summarization.provider_config`):**

| Provider    | Parameter        | Type   | Default                             | Description                           |
| ----------- | ---------------- | ------ | ----------------------------------- | ------------------------------------- |
| **LiteLLM** | `api_base`       | string | `http://localhost:11434/v1`         | API endpoint URL (defaults to Ollama) |
|             | `api_key`        | string | `ollama`                            | Provider API key                      |
| **Watsonx** | `api_key`        | string | -                                   | IBM Cloud API key                     |
|             | `container_id`   | string | -                                   | watsonx.ai project/space ID           |
|             | `container_kind` | string | -                                   | Container type (`project` or `space`) |
|             | `api_base`       | string | `https://us-south.ml.cloud.ibm.com` | watsonx.ai service URL                |

**Configuration Structure:**

The **recommended approach** is to use the nested `summarization` object:

```json
{
  "summarization": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/llama3.2:3b",
      "api_base": "http://localhost:11434/v1",
      "api_key": "<ollama>"
    },
    "summary_sentences": 3,
    "summary_max_words": 50
  }
}
```

**Backward Compatibility:**

The flat configuration structure is still supported:

```json
{
  "summarization": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/llama3.2:3b",
      "api_base": "http://localhost:11434/v1",
      "api_key": "<ollama>"
    },
    "summary_sentences": 3
  },
  "summary_max_words": 50
}
```

**Input Schema**

- configured `doc_column`, usually `content`

**Output Schema**

- `chunk_sequence_number`
- `start_index`
- `chunked_content` (array of objects with `chunk`, `start_index`, and optional `summary` fields when summarization is configured)

**Exceptions**

- [`DocpipeException`](../../src/docpipe/exceptions/docpipe_exceptions.py)
- validation messages
- Ollama errors for semantic chunking
- LLM provider errors for summarization (handled gracefully)

**Examples**

Basic chunking without summarization:

```json
{
  "id": "chunk-node",
  "name": "chunk",
  "operator": "chunker",
  "config": {
    "chunk_type": "hybrid",
    "doc_column": "content",
    "chunk_size": 512,
    "chunk_overlap": 128
  }
}
```

Chunking with LiteLLM summarization (Ollama) - Nested Structure:

```json
{
  "id": "chunk-with-summary",
  "name": "chunk",
  "operator": "chunker",
  "config": {
    "chunk_type": "simple",
    "doc_column": "content",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "summarization": {
      "provider": "litellm",
      "provider_config": {
        "model_id": "openai/llama3.2:3b",
        "api_base": "http://localhost:11434/v1",
        "api_key": "<ollama>"
      },
      "summary_sentences": 2,
      "summary_max_words": 20
    }
  }
}
```

Chunking with Watsonx summarization - Nested Structure:

```json
{
  "id": "chunk-watsonx",
  "name": "chunk",
  "operator": "chunker",
  "config": {
    "chunk_type": "simple",
    "doc_column": "content",
    "chunk_size": 1000,
    "summarization": {
      "provider": "watsonx",
      "provider_config": {
        "model_id": "ibm/granite-13b-chat-v2",
        "api_key": "${WATSONX_API_KEY}",
        "api_base": "${WATSONX_API_BASE}",
        "container_id": "${WATSONX_PROJECT_ID}",
        "container_kind": "project"
      }
    }
  }
}
```

#### EntityCurationOperator

**Purpose:** Transform extracted entities into structured, curated data using document class schemas with 4 core transformation functions for currency, date, number, and weight parsing.

**Category:** Functional

**Class:** `docpipe.core.operators.functional.entity_curation.entity_curation_operator.EntityCurationOperator`

| Parameter              | Type   | Required | Default         | Description                                 |
| ---------------------- | ------ | -------: | --------------- | ------------------------------------------- |
| `entities_column`      | string |       No | `entities`      | Column containing extracted entities (dict) |
| `document_type_column` | string |       No | `document_type` | Column containing document type identifier  |

**Input Schema**

- `entities` (dict): Extracted entity key-value pairs from ExtractOperator
- `document_type` (string): Document class identifier (e.g., "invoice", "purchase_order")
- Other columns are preserved

**Output Schema**

- All input columns preserved
- `transformed_entities` column: JSON string containing nested structure of curated entities organized by target tables

**Transformation Functions**

The operator includes 4 core transformations:

| Function              | Purpose                               | Example                               |
| --------------------- | ------------------------------------- | ------------------------------------- |
| `currency_to_numeric` | Locale-aware currency parsing (Babel) | `"1.234,56 €"` (de_DE) → `1234.56`    |
| `make_date_uniform`   | Date normalization to YYYY-MM-DD      | `"January 15, 2024"` → `"2024-01-15"` |
| `to_number`           | Multi-language number parsing         | `"一千二百三十四"` (Chinese) → `1234` |
| `weight_to_numeric`   | Locale-aware weight conversion to kg  | `"5斤"` (zh_CN) → `2.5`               |

**Document Class Schemas**

Schemas are defined with `target_tables` specifying field mappings and transformations. Supports 40+ document classes including invoice, purchase_order, receipt, insurance_claim, passport, and more.

**Exceptions**

- [`ValidationError`](../../src/docpipe/exceptions/docpipe_exceptions.py) - Missing required columns
- Transformation errors are logged but don't stop processing (graceful degradation)

**Example**

```json
{
  "id": "curate-node",
  "name": "entity_curation",
  "operator": "entity_curation",
  "config": {
    "entities_column": "entities",
    "document_type_column": "document_type"
  }
}
```

**Usage Notes**

- Should be placed after `ExtractOperator` in the pipeline when entity extraction is enabled
- Requires document class schemas for transformation (returns empty dict for unknown document types)
- Output is always in JSON format with nested structure matching schema's target tables
- See [Entity Curation README](../operators/functional/entity_curation_readme.md) for detailed documentation

---

---

#### EmbeddingsOperator

**Purpose:** Generate dense embeddings using pluggable providers such as Ollama, HuggingFace, LiteLLM-backed vendors, and IBM watsonx.ai.

**Category:** Functional

**Class:** `core.operators.functional.embeddings.embeddings_operator.EmbeddingsOperator`

| Parameter           | Type    | Required | Default       | Description                                                                                      |
| ------------------- | ------- | -------: | ------------- | ------------------------------------------------------------------------------------------------ |
| `provider`          | string  |      Yes | `litellm`     | Provider type: `litellm`, `watsonx`, `huggingface`                                               |
| `provider_config`   | object  |      Yes | -             | Provider-specific configuration (see table below)                                                |
| `embeddings_column` | string  |       No | `embeddings`  | Output vector column                                                                             |
| `doc_column`        | string  |       No | `content`     | Input content column                                                                             |
| `doc_id_hash`       | string  |       No | `doc_id_hash` | Hash column name                                                                                 |
| `overlap_ratio`     | float   |       No | `0.2`         | Long-text chunk overlap ratio                                                                    |
| `token_limit`       | integer |       No | `8192`        | Maximum token limit for text chunking. Adjust based on model's context window (512-8192 tokens). |

**Supported Providers:**

- **LiteLLM**: Unified API for 100+ providers (OpenAI, Azure, Cohere, AWS, GCP, Ollama, HuggingFace API)
- **Watsonx**: IBM watsonx.ai cloud service (enterprise AI)
- **HuggingFace**: Native local or API-based inference with sentence-transformers models

**Provider-Specific Configuration (`provider_config`):**

| Provider        | Parameter                 | Type   | Required | Default | Description                                                                                                                   |
| --------------- | ------------------------- | ------ | -------- | ------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **LiteLLM**     | `model_id`                | string | Yes      | -       | Model identifier with provider prefix (e.g., `openai/nomic-embed-text`, `huggingface/sentence-transformers/all-MiniLM-L6-v2`) |
|                 | `api_base`                | string | No       | -       | Custom API endpoint URL (e.g., `http://localhost:11434` for Ollama)                                                           |
|                 | `api_key`                 | string | No       | -       | Provider API key (required for most providers, not needed for Ollama)                                                         |
|                 | `batch_size`              | int    | No       | `32`    | Texts per embedding request; texts from several documents are packed into the same request                                    |
|                 | `max_concurrent_requests` | int    | No       | `4`     | Embedding requests kept in flight at once; lower it if the provider returns rate-limit (429) errors                           |
|                 | `timeout`                 | int    | No       | `120`   | Request timeout in seconds                                                                                                    |
| **Watsonx**     | `model_id`                | string | Yes      | -       | Model identifier (e.g., `ibm/slate-125m-english-rtrvr`)                                                                       |
|                 | `api_key`                 | string | Yes      | -       | IBM Cloud API key                                                                                                             |
|                 | `api_base`                | string | Yes      | -       | WatsonX API URL (e.g., `https://us-south.ml.cloud.ibm.com`)                                                                   |
|                 | `container_id`            | string | Yes      | -       | WatsonX project or space ID                                                                                                   |
|                 | `container_kind`          | string | Yes      | -       | Container type: `project` or `space`                                                                                          |
|                 | `batch_size`              | int    | No       | `800`   | Texts per embedding request; texts from several documents are packed into the same request                                    |
|                 | `max_concurrent_requests` | int    | No       | `1`     | Embedding requests kept in flight at once (watsonx.ai allows 8 req/s per instance)                                            |
|                 | `timeout`                 | int    | No       | `120`   | Request timeout in seconds                                                                                                    |
|                 | `enable_rate_limiting`    | bool   | No       | `false` | Enable rate limiting for API calls                                                                                            |
| **HuggingFace** | `model_id`                | string | Yes      | -       | Model identifier (e.g., `sentence-transformers/all-MiniLM-L6-v2`)                                                             |
|                 | `use_local`               | bool   | No       | `true`  | Use local model inference (true) or HuggingFace API (false)                                                                   |
|                 | `device`                  | string | No       | `cpu`   | Device for local inference: `cpu`, `cuda`, `mps`                                                                              |
|                 | `api_token`               | string | No       | -       | HuggingFace API token (required for API mode)                                                                                 |
|                 | `batch_size`              | int    | No       | `32`    | Texts per encode call; texts from several documents are encoded together (requests run one at a time)                         |

**Request batching:** The operator collects the texts of all input documents (chunks for `chunked_content`, or one text per document for `content`; processed internally in slices of 2,000 rows), sends them in requests of `batch_size` texts with up to `max_concurrent_requests` requests in flight, and maps the vectors back to their documents in order. Provider retries (LiteLLM, watsonx) apply to each request on its own. If a request still fails with an error that can depend on its input (HTTP 400, 413 or 422, including context-window and content-policy errors, or a context-length error) and it carried texts of several documents, each of those documents is re-embedded on its own (only its texts from the failed request, in requests of `batch_size`), so a bad text fails only its own document; this fallback adds at most (failed shared requests + affected documents) requests. Any other failure (rate limit 429, timeouts, connection errors, 5xx, authentication or permission errors, unexpected responses) is provider-wide: every document of the failed request is marked as failed with that error and nothing is re-sent, so a full outage causes no extra requests beyond the provider client's own per-request retries (for example, 100 one-text documents with `batch_size` 32 cause 4 requests). A failed request that carried a single document fails that document directly. The `max_concurrent_requests` limit applies to each operator run: when micro-batching runs several batches at the same time, up to `max_concurrent_batches` x `max_concurrent_requests` requests can be in flight.

**Note:** For Ollama models via LiteLLM, use `openai/` prefix (e.g., `openai/nomic-embed-text`). For HuggingFace API via LiteLLM, use `huggingface/` prefix (e.g., `huggingface/sentence-transformers/all-MiniLM-L6-v2`). For native HuggingFace local inference, use `provider: "huggingface"` with the model name directly.

**Input Schema**

- `content` or `chunked_content`

**Output Schema**

- `embeddings`

**Exceptions**

- [`DocpipeException`](../../src/docpipe/exceptions/docpipe_exceptions.py)
- provider authentication/network failures

**Example 1: LiteLLM with Ollama (local)**

```json
{
  "id": "embedding-node",
  "name": "embeddings",
  "operator": "embeddings",
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/nomic-embed-text",
      "api_base": "http://localhost:11434",
      "batch_size": 32,
      "timeout": 120
    },
    "embeddings_column": "embeddings",
    "text_column": "content"
  }
}
```

**Example 2: LiteLLM with HuggingFace API**

```json
{
  "id": "embedding-node",
  "name": "embeddings",
  "operator": "embeddings",
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "huggingface/sentence-transformers/all-MiniLM-L6-v2",
      "api_key": "${HUGGINGFACE_API_KEY}",
      "batch_size": 16
    },
    "embeddings_column": "embeddings",
    "text_column": "content"
  }
}
```

**Example 2b: Native HuggingFace (Local Inference)**

```json
{
  "id": "embedding-node",
  "name": "embeddings",
  "operator": "embeddings",
  "config": {
    "provider": "huggingface",
    "provider_config": {
      "model_id": "sentence-transformers/all-MiniLM-L6-v2",
      "use_local": true,
      "device": "cpu",
      "batch_size": 16
    },
    "embeddings_column": "embeddings",
    "text_column": "content"
  }
}
```

**Example 3: WatsonX embeddings**

```json
{
  "id": "embedding-node",
  "name": "embeddings",
  "operator": "embeddings",
  "config": {
    "provider": "watsonx",
    "provider_config": {
      "model_id": "ibm/slate-125m-english-rtrvr",
      "api_key": "${WATSONX_API_KEY}",
      "api_base": "https://us-south.ml.cloud.ibm.com",
      "container_id": "${WATSONX_PROJECT_ID}",
      "container_kind": "project",
      "batch_size": 32
    },
    "embeddings_column": "embeddings",
    "text_column": "content"
  }
}
```

**Example 4: LiteLLM with OpenAI**

```json
{
  "id": "embedding-node",
  "name": "embeddings",
  "operator": "embeddings",
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/text-embedding-3-small",
      "api_key": "${OPENAI_API_KEY}",
      "batch_size": 32
    },
    "embeddings_column": "embeddings",
    "text_column": "content"
  }
}
```

---

#### BranchingOperator

**Purpose:** Split a table into multiple output tables using SQL-like filter conditions.

**Category:** Functional

**Class:** `core.operators.functional.branching_operator.BranchingOperator`

| Parameter                         | Type         | Required | Default          | Description                   |
| --------------------------------- | ------------ | -------: | ---------------- | ----------------------------- |
| `branches`                        | list[object] |      Yes | `[]`             | Branch definitions            |
| `branches[].link_id`              | string       |      Yes | -                | Output edge identifier        |
| `branches[].link_name`            | string       |       No | -                | Human-friendly branch name    |
| `branches[].logical_operator`     | string       |       No | `AND`/per-branch | Logical join between criteria |
| `branches[].filter_criteria_list` | list[string] |       No | `[]`             | SQL-like filters              |
| `branches[].filter_criteria_json` | object       |       No | -                | Structured filter criteria    |

**Input Schema**

- Any table with columns referenced by branch criteria

**Output Schema**

- Multiple output tables, one per branch

**Exceptions**

- validation errors
- propagated SQL filter errors

---

#### MergeOperator

**Purpose:** Combine multiple PyArrow tables from different branches using row concatenation or column joins.

**Category:** Functional

**Class:** `core.operators.functional.merge.MergeOperator`

| Parameter                 | Type         |    Required | Default | Description                                                       |
| ------------------------- | ------------ | ----------: | ------- | ----------------------------------------------------------------- |
| `merge_type`              | string       |         Yes | `rows`  | Merge strategy: `rows` (concatenate) or `columns` (join)          |
| `column_option`           | string       | Conditional | -       | Join type when `merge_type=columns`: `inner_join` or `full_outer` |
| `input_links`             | list[object] |         Yes | `[]`    | Input link configurations                                         |
| `input_links[].link_name` | string       |         Yes | -       | Unique identifier for each input branch                           |

**Input Schema**

- Multiple PyArrow tables from different branches, each identified by `link_name`
- All tables must contain an `id` column for row merge duplicate detection and column merge joins

**Output Schema**

- **Row Merge (`merge_type=rows`)**: Single table with all rows concatenated vertically
  - Preserves all columns from all input tables
  - Validates no duplicate IDs across tables
- **Column Merge (`merge_type=columns`)**: Single table with columns joined horizontally
  - `inner_join`: Only rows with matching IDs across all tables
  - `full_outer`: All rows from all tables, with nulls for missing values
  - Non-ID columns from subsequent tables get `_<link_name>` suffix
  - Complex types (lists, structs) are remapped without suffix

**Exceptions**

- `FlowExecutionFailedException`: Fewer than 2 input links provided
- `DocpipeException`: Duplicate IDs detected in row merge
- Validation errors for missing or invalid configuration

**Usage Notes**

- Typically used after [`BranchingOperator`](#branchingoperator) to recombine split data flows
- The order of `input_links` determines column suffix application in column merge
- Row merge requires unique IDs across all input tables
- Column merge performs ID-based joins, similar to SQL JOIN operations

**Example Flow Configuration**

```json
{
  "id": "merge-node",
  "name": "merge_branches",
  "operator": "merge",
  "config": {
    "merge_type": "columns",
    "column_option": "inner_join",
    "input_links": [{ "link_name": "branch1" }, { "link_name": "branch2" }]
  },
  "input_edges": [
    { "node_id_ref": "branch1-node", "link_name": "branch1" },
    { "node_id_ref": "branch2-node", "link_name": "branch2" }
  ]
}
```

---

#### NOOPOperator

**Purpose:** Pass input rows through unchanged, optionally sleeping for a configured interval.

**Category:** Functional

**Class:** `core.operators.functional.noop.NOOPOperator`

| Parameter   | Type | Required | Default | Description                          |
| ----------- | ---- | -------: | ------- | ------------------------------------ |
| `sleep_sec` | int  |       No | `1`     | Optional delay for testing/debugging |

**Input Schema**

- Any `pyarrow.Table`

**Output Schema**

- Same as input table

---

#### DocIdHashOperator

**Purpose:** Generate a stable hash identifier from content.

**Category:** Functional

**Class:** `core.operators.functional.doc_id_hash.DocIdHashOperator`

**Availability:** Internal operator.

| Parameter     | Type   | Required | Default       | Description        |
| ------------- | ------ | -------: | ------------- | ------------------ |
| `doc_column`  | string |       No | `content`     | Input text column  |
| `doc_id_hash` | string |       No | `doc_id_hash` | Output hash column |

**Output Schema**

- `doc_id_hash`

### VectorDB Operators

#### VectorDBOperator

**Purpose:** Index documents and embeddings into a vector database through a provider adapter interface.

**Category:** VectorDB

**Class:** `core.operators.vectordb.vectordb_operator.VectorDBOperator`

| Parameter            | Type   | Required | Default       | Description                                                                 |
| -------------------- | ------ | -------: | ------------- | --------------------------------------------------------------------------- |
| `provider`           | string |      Yes | -             | VectorDB backend (`opensearch` or `milvus`)                                 |
| `doc_id_column`      | string |       No | `doc_id_hash` | Primary document id column                                                  |
| `provider_config`    | object |      Yes | -             | Connection parameters and resource name for the backend (see examples below)|
| `available_features` | object |       No | -             | Feature definitions for vector DB schema                                    |
| `feature_mappings`   | object |       No | -             | Mapping of PyArrow columns to vector DB fields                              |
| `doc_format`         | string |       No | `markdown`    | Content format of the incoming `content` column: `"markdown"` (default) or `"doclang"`. When `"doclang"`, DocLang XML is auto-transcoded to clean Markdown before indexing (both unchunked and chunked modes). Chunk metadata (bounding boxes, page numbers, header paths) is preserved in indexed document payloads. |

**Multi-Model Embeddings Support:**

The VectorDBOperator supports multiple embedding columns with different dimensions:

- **OpenSearch**: Full multi-model support
  - Automatically detects all vector columns from `available_features` (columns with `type: "vector"`)
  - Auto-detects dimension for each vector column from actual embedding data
  - Creates index fields for all vector columns with their respective dimensions
  - Example: Store both 384-dim and 768-dim embeddings in same document (e.g., `embeddings` and `embeddings_alt`)
  - Use with BranchingOperator + multiple EmbeddingsOperators + MergeOperator for multi-model pipelines
  - See `sample_flows/advanced/branching_dual_embeddings_with_ingest_report.json` for complete example
- **Milvus**: Single-model support (uses `embeddings` column only)
  - Dimension auto-detected from `embeddings` column data
  - Additional vector columns in the table are stored as metadata but not indexed as vectors
  - Multi-model support planned for future update
  - For multi-model scenarios with Milvus, use separate collections per embedding model

**Supported Vector Databases:**

1. **OpenSearch** (`provider: "opensearch"`)
   - Multiple KNN engines: NMSLIB, Faiss, Lucene
   - Configurable space types: cosinesimil, l2, innerproduct
   - HTTP/HTTPS connections with optional authentication

2. **Milvus** (`provider: "milvus"`)
   - **Index Types**:
     - Dense: HNSW, IVF_FLAT, IVF_SQ8, IVF_PQ, FLAT, DISKANN, AUTOINDEX
     - Sparse: SPARSE_INVERTED_INDEX, SPARSE_WAND
   - **Metric Types**:
     - Dense: L2 (Euclidean), IP (Inner Product), COSINE
     - Sparse: BM25 (required for sparse mode)
   - **Vector Modes**:
     - Dense vectors only (default)
     - Sparse + Dense vectors (dual storage with BM25 function)
   - **Deployment Options**:
     - Standalone Milvus (local or remote)
     - Watsonx.data Milvus (IBM Cloud, SSL-enabled)
   - **Features**:
     - Auto-detection of vector dimensions from embeddings
     - BM25 sparse vector generation from content
     - Configurable index parameters (M, efConstruction for HNSW)
     - Batch processing with configurable batch sizes
     - SSL/TLS support for secure connections

**OpenSearch Configuration Example:**

```json
{
  "operator": "vectordb",
  "config": {
    "provider": "opensearch",
    "provider_config": {
      "index_name": "my_documents",
      "host": "localhost",
      "port": 9200,
      "engine": "nmslib",
      "space_type": "cosinesimil",
      "username": "<value>",
      "password": "<value>"
    }
  }
}
```

**Milvus Standalone Configuration Example:**

```json
{
  "operator": "vectordb",
  "config": {
    "provider": "milvus",
    "add_sparse_vector": false,
    "provider_config": {
      "collection_name": "my_collection",
      "auth_type": "standalone",
      "host": "localhost",
      "port": 19530,
      "uri": null,
      "token": null,
      "username": "root",
      "password": "<your-milvus-password>",
      "database": "default",
      "secure": false,
      "index_type": "HNSW",
      "metric_type": "L2",
      "index_parameters": {
        "M": 16,
        "efConstruction": 256
      },
      "batch_size": 100,
      "primary_key_field": "pk"
    },
    "available_features": {
      "doc_id_hash": {
        "name": "Document ID",
        "available_for_vector_db": true,
        "mandatory_for_vector_db": true,
        "type": "string",
        "is_primary": true
      },
      "embeddings": {
        "name": "Embeddings",
        "available_for_vector_db": true,
        "mandatory_for_vector_db": true,
        "type": "vector"
      }
    },
    "feature_mappings": {
      "doc_id_hash": "pk",
      "embeddings": "vector_embeddings"
    }
  }
}
```

**Milvus Watsonx.data with gRPC Configuration Example:**

```json
{
  "operator": "vectordb",
  "config": {
    "provider": "milvus",
    "add_sparse_vector": false,
    "provider_config": {
      "collection_name": "wxdata_collection",
      "auth_type": "grpc",
      "host": "YOUR_WXDATA_HOST.lakehouse.ibmappdomain.cloud",
      "port": 32671,
      "uri": null,
      "token": null,
      "username": "ibmlhapikey_YOUR_USERNAME",
      "password": "<your-api-key>",
      "database": "default",
      "secure": true,
      "index_type": "HNSW",
      "metric_type": "L2",
      "index_parameters": {
        "M": 16,
        "efConstruction": 256
      },
      "batch_size": 100,
      "primary_key_field": "pk"
    }
  }
}
```

**Milvus Watsonx.data with IAM Token Configuration Example:**

```json
{
  "operator": "vectordb",
  "config": {
    "provider": "milvus",
    "add_sparse_vector": false,
    "provider_config": {
      "collection_name": "wxdata_token_collection",
      "auth_type": "token",
      "host": "YOUR_WXDATA_HOST.lakehouse.ibmappdomain.cloud",
      "port": 32671,
      "uri": null,
      "token": "YOUR_IAM_TOKEN",
      "username": "YOUR_USERNAME",
      "password": null,
      "database": "default",
      "secure": true,
      "index_type": "HNSW",
      "metric_type": "L2",
      "index_parameters": {
        "M": 16,
        "efConstruction": 256
      },
      "batch_size": 100,
      "primary_key_field": "pk"
    }
  }
}
```

**Provider Config Parameters:**

**OpenSearch:**

- `host`: OpenSearch server hostname
- `port`: OpenSearch server port (default: 9200)
- `engine`: KNN engine (nmslib, faiss, lucene)
- `space_type`: Distance metric (cosinesimil, l2, innerproduct)
- `username`: Optional authentication username
- **password**: Optional authentication password

**Milvus:**

- `auth_type`: **Required** - Authentication type (`standalone`, `grpc`, `uri`, or `token`)
- `host`: Milvus server hostname (required for `standalone`, `grpc`, `token`)
- `port`: Milvus server port (default: 19530, required for `standalone`, `grpc`, `token`)
- `uri`: Full connection URI (required for `uri` auth_type)
- `token`: IAM token (required for `token` auth_type)
- `username`: Authentication username (optional for `standalone`, required for `grpc` and `token`)
- **password**: Authentication password/API key (optional for `standalone`, required for `grpc` - should be API key)
- `database`: Database name (default: "default")
- `secure` : Required for IBM watsonx.data MilvusDB for https connection and is set to true in this case.
- `index_type`: Index algorithm (HNSW, IVF_FLAT, IVF_SQ8, IVF_PQ, FLAT, DISKANN, AUTOINDEX for dense; SPARSE_INVERTED_INDEX, SPARSE_WAND for sparse)
- `metric_type`: Distance metric (L2, IP, COSINE for dense; BM25 required for sparse mode)
- `index_parameters`: Index-specific parameters (e.g., M and efConstruction for HNSW)
- `batch_size`: Batch size for bulk operations (default: 100)
- `primary_key_field`: Name of the primary key field in Milvus collection (default: "pk")

**Milvus Authentication Types:**

- `standalone`: Local Milvus with optional username/password
- `grpc`: IBM wx.data with gRPC (username must have `ibmlhapikey_` prefix, password is API key)
- `uri`: Pre-constructed URI with embedded API key (format: `https://ibmlhapikey_<username>:<api-key>@<host>:<port>`)
- `token`: IAM token-based (constructs URI internally: `https://ibmlhtoken_<username>:<token>@<host>:<port>`)

**Sparse Vector Mode:**

When `add_sparse_vector: true` is set:

- Requires `metric_type: "BM25"` (validated)
- Creates BM25 function for automatic sparse vector generation from text content
- Feature mappings must include:
  - `embeddings` → `vector` (dense embeddings)
  - `sparse_embeddings` → `sparse_vector` (BM25-generated)
  - `content` → `text` (source text for BM25)
- Index type auto-set to `SPARSE_INVERTED_INDEX` if not specified
- See [`sample_flows/vectordb/milvus_integration.json`](../../sample_flows/vectordb/milvus_integration.json) for complete example

**Notes:**

- Vector dimensions are auto-detected from actual embedding data for each vector column
- OpenSearch supports multiple vector columns with different dimensions in a single index
- Milvus currently supports single vector column (multi-model support planned for future update)
- See [`docs/integrations/milvus/README.md`](../integrations/milvus/README.md) for detailed Milvus configuration
- See [`VectorDB Operator README`](../operators/vectordb/vectordb_readme.md) for provider configuration patterns

**Provider Config (OpenSearch)**

The `provider_config` object supports the following parameters for OpenSearch:

| Parameter              | Type   | Required | Default         | Description                                                                        |
| ---------------------- | ------ | -------: | --------------- | ---------------------------------------------------------------------------------- |
| `host`                 | string |       No | `localhost`     | OpenSearch host                                                                    |
| `port`                 | int    |       No | `9200`          | OpenSearch port                                                                    |
| `engine`               | string |       No | `faiss`         | KNN engine (faiss, lucene, nmslib, jvector)                                        |
| `algorithm`            | string |       No | `hnsw`          | KNN algorithm (hnsw, ivf)                                                          |
| `space_type`           | string |       No | `l2`            | Similarity metric (l2, cosine, inner_product)                                      |
| `schema_template_path` | string |       No | `null`          | Path to JSON schema template (relative to `src/docpipe/core/operators/vectordb/`) |
| `engine_parameters`    | object |       No | Auto-configured | Engine-specific parameters (ef_construction, m, nlist, nprobe)                     |
| `index_settings`       | object |       No | `{}`            | Additional OpenSearch index settings                                               |

**Schema Templates**

Schema templates provide reusable index configurations with placeholder-based dynamic values:

- **Built-in Templates**:
  - `schemas/default_schema.v1.json`: Basic schema with standard field types
  - `schemas/template_with_content_analyzer.v1.json`: Template with custom content analyzer for text processing

- **Placeholders**: Templates support the following placeholders that are replaced at runtime:
  - `__VECTOR_DIMENSION__`: Vector embedding dimension
  - `__ENGINE__`: KNN engine name
  - `__ALGORITHM__`: KNN algorithm name
  - `__SPACE_TYPE__`: Similarity metric
  - `__ENGINE_PARAMETERS__`: Engine-specific parameters object

- **Fallback Behavior**: If template is not found or invalid, the system falls back to dynamic schema generation with a warning

**Metadata Normalization**

The VectorDBOperator automatically normalizes and aggregates metadata columns:

- **Column Aliases**: Automatically maps common column name variations:
  - `path` → `source`
  - `pages_processed` → `page_count`
  - `mime_type`, `content_type` → `mimetype`

- **Field Derivation**: Automatically derives missing metadata fields:
  - `extension`: Derived from `name` or `source` if missing
  - `mimetype`: Derived from `extension` using standard MIME type mappings

- **Predefined Metadata Fields**: The following fields are automatically collected into a `metadata` object:
  - `name`, `size`, `created_time`, `modified_time`, `source`, `mimetype`, `extension`, `page_count`

**Input Schema**

- `doc_id_column`
- `embeddings_column`

**Output Schema**

- input table unchanged
- side effect: indexed vector records

**Exceptions**

- [`DocpipeException`](../../src/docpipe/exceptions/docpipe_exceptions.py)

**Example Configuration**

Basic usage with default schema:

```json
{
  "operator_type": "docpipe.core.operators.vectordb.vectordb_operator.VectorDBOperator",
  "operator_params": {
    "provider": "opensearch",
    "provider_config": {
      "index_name": "my_documents",
      "host": "localhost",
      "port": 9200,
      "engine": "faiss",
      "algorithm": "hnsw",
      "vector_dimension": 384
    }
  }
}
```

Using a schema template:

```json
{
  "operator_type": "docpipe.core.operators.vectordb.vectordb_operator.VectorDBOperator",
  "operator_params": {
    "provider": "opensearch",
    "provider_config": {
      "index_name": "document_chunks",
      "schema_template_path": "schemas/template_with_content_analyzer.v1.json",
      "host": "localhost",
      "port": 9200,
      "engine": "faiss",
      "algorithm": "hnsw",
      "vector_dimension": 768
    }
  }
}
```

---

### Storage Operators

#### DocumentSetOperator

**Purpose:** Store PyArrow table data and document-set metadata using a hexagonal architecture with pluggable metadata and data adapters.

**Category:** Storage

**Class:** `core.operators.document_sets.document_set_operator.DocumentSetOperator`

| Parameter           | Type   | Required | Default                            | Description                                              |
| ------------------- | ------ | -------: | ---------------------------------- | -------------------------------------------------------- |
| `document_set_name` | string |      Yes | -                                  | Unique name for the document set                         |
| `description`       | string |       No | `null`                             | Description of the document set                          |
| `metadata`          | object |       No | `null`                             | Additional metadata payload stored with the document set |
| `document_set_id`   | string |       No | `null`                             | Existing document set UUID for update flows              |
| `data_backend`      | string |       No | `duckdb`                           | Data store backend for PyArrow table data                |
| `database_path`     | string |       No | `data/duckdb/document_sets.duckdb` | Database file path used by DuckDB-backed adapters        |

**Description**

The Document Set operator persists table rows and document-set metadata through separate port interfaces:

- `DocumentSetMetadataRepository`
- `DocumentSetStorage`

The operator creates concrete adapters through:

- `MetadataRepositoryFactory`
- `DataStoreFactory`

The metadata backend is controlled by `global_config.metadata_storage_type` (default: `duckdb`). The data backend is controlled per-operator via `data_backend`. Current production support is DuckDB for both. The operator returns the input table unchanged, so it can be placed mid-pipeline without breaking downstream processing.

**Architecture**

- Hexagonal architecture with ports and adapters
- Separate metadata and data storage abstractions
- Factory-based backend creation
- Shared DuckDB storage reuse for current adapters

**Input Schema**

- `id` (required): UUID document identifier

Common upstream fields from the sample flow:

- `name`
- binary content from ingest
- `content`

**Output Schema**

- Input table unchanged (pass-through design)
- Side effect: data and metadata persisted through configured adapters

**Metadata Output**

- `document_set_id`: UUID of the document set
- `document_set_name`: Name of the document set
- `database_path`: Database path used for storage
- `stored_documents`: Number of rows written in the operation
- `total_size_bytes`: Total size in bytes of all stored rows
- `total_pages`: Total pages across all stored documents
- `table_name`: Backend-specific data location identifier populated by the storage adapter
- `metadata_storage_type`: Metadata adapter used (from `global_config.metadata_storage_type`)
- `data_storage_type`: Data adapter used (from `data_backend`)
- `error`: Error message when persistence fails

**Features**

- Persistent storage of document collections
- Hexagonal architecture for backend extensibility
- Separate metadata and data persistence layers
- Automatic schema handling through data-store adapters
- Automatic metric recomputation through `DocumentSetService`
- Pass-through design allows chaining with downstream operators

**Exceptions**

- [`FlowValidationException`](../../src/docpipe/exceptions/docpipe_exceptions.py): Invalid operator configuration
- [`FlowExecutionFailedException`](../../src/docpipe/exceptions/docpipe_exceptions.py): Storage execution failed
- [`DocpipeException`](../../src/docpipe/exceptions/docpipe_exceptions.py): Adapter, validation, or persistence error

**Sample Flow Configuration**

```json
{
  "type": "document_set",
  "name": "documents",
  "config": {
    "document_set_name": "documents_collection",
    "description": "Persistent storage of extracted document content with metadata tracking",
    "database_path": "./data/document_sets/extracted_docs.duckdb",
    "data_backend": "duckdb",
    "metadata": {
      "pipeline_version": "1.0",
      "extraction_method": "docling",
      "created_by": "docpipe_pipeline",
      "purpose": "demonstration_flow"
    }
  },
  "depends_on": ["extract_content"]
}
```

**Configuration Notes:**

- `global_config.metadata_storage_type` controls the metadata storage backend (default: `duckdb`)
- `database_path` in the operator config specifies the DuckDB file path for both metadata and data
- `data_backend` in the operator config controls the PyArrow table data adapter (default: `duckdb`)

**Flow Pattern**

```text
IngestSourceOperator -> ExtractOperator -> DocumentSetOperator
```

**End-to-End Flow Example**

```json
{
  "flow_name": "ingest-extract-documentset",
  "global_config": {
    "doc_column": "content",
    "storage": "in-memory",
    "execute_type": "local"
  },
  "flow": [
    {
      "type": "ingest_source",
      "name": "ingest_documents",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["./documents"]},
        "include_filter": "pdf,txt"
      }
    },
    {
      "type": "extract_operator",
      "name": "extract_content",
      "config": {
        "text_extraction": { "provider": "docling_library" }
      },
      "depends_on": ["ingest_documents"]
    },
    {
      "type": "document_set",
      "name": "store_documents",
      "config": {
        "document_set_name": "integration_test_documents",
        "description": "Integration test for hexagonal architecture",
        "database_path": "data/integration_test.db",
        "data_backend": "duckdb"
      },
      "depends_on": ["extract_content"]
    }
  ]
}
```

**API Integration**

Document sets are also exposed through `/api/v1/document-sets`:

- `POST /api/v1/document-sets`
- `GET /api/v1/document-sets`
- `GET /api/v1/document-sets/{id}`
- `PATCH /api/v1/document-sets/{id}`
- `DELETE /api/v1/document-sets/{id}`
- `GET /api/v1/document-sets/{id}/preview`

**Error Codes**

- `document_set_not_found`
- `document_set_invalid_data`
- `document_set_storage_error`
- `document_set_already_exists`
- `document_set_data_store_error`
- `document_set_table_not_found`

**Testing**

```bash
source .venv/bin/activate
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
uv run pytest tests/integration/api/test_document_sets_api.py -v
```

**Extension**

For new backends, implement the `DocumentSetStorage` and `DocumentSetMetadataRepository` ports, register the adapters with `DataStoreFactory` and `MetadataRepositoryFactory` respectively. Configure `data_backend` in the operator config to select the data adapter, and `global_config.metadata_storage_type` to select the metadata adapter. See [`ARCHITECTURE.md`](../../ARCHITECTURE.md).

---

#### StorageOutputOperator

**Purpose:** Write pipeline documents to a pluggable storage destination, supporting three modes: `processed_content`, `refetch_original`, and `comprehensive_export`.

**Category:** Storage

**Class:** `core.operators.storage.storage_output_operator.StorageOutputOperator`

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `mode` | string | Yes | — | `processed_content`, `refetch_original`, or `comprehensive_export` |
| `destination_config` | object | Yes | — | Destination connection configuration |
| `output_format` | object | No | `{}` | Controls content format and metadata sidecar output |
| `output_structure` | object | No | `{}` | Controls output directory structure and file naming |

**`destination_config` fields**

| Field | Type | Description |
| --- | --- | --- |
| `provider` | string | Adapter name: `filesystem`, `s3`, `ibm_cos`, `sharepoint`, `dropbox`, `onedrive`, or `google_drive` |
| `provider_config` | object | Provider-specific connection parameters (see operator README) |
| `credentials` | object | Provider-specific credentials |

**`output_format` fields**

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `content_format` | string | `md` | Content file extension: `md`, `txt`, or `json` |
| `include_metadata_sidecar` | bool | `false` | Write a `.meta.json` sidecar per document (`comprehensive_export` only) |

**`output_structure` fields**

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `type` | string | `flat` | `flat` or `hierarchical` (mirrors source directory tree) |
| `path_template` | string | `{name}.{ext}` | Template string for the output file path relative to `root_path` |
| `overwrite_existing` | bool | `true` | When `false`, existing files are skipped with `write_status = skipped` |

**Path template variables:** `{doc_id}`, `{name}`, `{ext}`, `{year}`, `{month}`, `{day}`, `{relative_dir}`

**Output Schema**

All input columns are passed through unchanged. The following columns are appended:

| Column | Type | Values |
| --- | --- | --- |
| `write_status` | string | `success`, `failed`, `skipped` |
| `destination_path` | string | Full path written; `null` on failure |
| `bytes_written` | int64 | Bytes written; `0` on failure |
| `write_error` | string | Error message; `null` on success |

**Sample Flow Configuration**

```json
{
  "type": "storage_output",
  "name": "write_output",
  "config": {
    "mode": "processed_content",
    "destination_config": {
      "provider": "filesystem",
      "provider_config": {
        "root_path": "/output/docs",
        "create_dirs": true
      },
      "credentials": {}
    },
    "output_format": { "content_format": "md" },
    "output_structure": { "path_template": "{year}/{month}/{doc_id}.{ext}" }
  },
  "depends_on": ["extract"]
}
```

**Flow Pattern**

```text
IngestSourceOperator -> ExtractOperator -> StorageOutputOperator
```

For full provider reference, operating mode details, and per-provider examples see [`docs/operators/storage/storage_output_readme.md`](../operators/storage/storage_output_readme.md).

---

## DocpipeFlowManager API

**Class:** [`DocpipeFlowManager`](../../src/docpipe/lib/docpipe_flow_manager.py#L24)

### Constructor
- `DocpipeFlowManager(flow_file=None, flow_def=None, job_id=None, job_run_id=None, flow_id=None, enable_custom_operators=None)`

Exactly one of `flow_file` or `flow_def` must be provided.

### `validate()`

Defined at [`validate()`](../../src/docpipe/lib/docpipe_flow_manager.py#L165).

Returns:

```python
{
  "valid": bool,
  "errors": list,
  "warnings": list
}
```

### `execute()`

Defined at [`execute()`](../../src/docpipe/lib/docpipe_flow_manager.py#L213).

Returns the result of flow execution from the executor.

### `get_execution_metadata()`

Defined at [`get_execution_metadata()`](../../src/docpipe/lib/docpipe_flow_manager.py#L245).

Returns job and flow metadata.

### `get_execution_logs()`

Defined at [`get_execution_logs()`](../../src/docpipe/lib/docpipe_flow_manager.py#L272).

Returns `list[str]`.

### `list_operators(verbose=False)`

Defined at [`list_operators()`](../../src/docpipe/lib/docpipe_flow_manager.py#L308).

Returns a formatted operator listing via [`docpipe.utils.operators.display.list_operators()`](../../src/docpipe/utils/operators/display.py).

**Display Modes:**

- **Default (verbose=False)**: Summary table with Owner, Attributes (count), Features (count) columns
- **Verbose (verbose=True)**: Detailed view with full operator parameters and descriptions

**Category Sorting Order:**
Operators are sorted by category: Ingest, Extract, Quality, Functional, VectorDB, Storage

### Method name note

The current class does **not** expose `execute_flow()` or `validate_flow()` methods. Use:

- [`execute()`](../../src/docpipe/lib/docpipe_flow_manager.py#L213)
- [`validate()`](../../src/docpipe/lib/docpipe_flow_manager.py#L165)

---

## CLI API Reference

**Entry point:** [`main()`](../../src/docpipe/cli/docpipe_cli.py#L147)

### Command forms

```bash
docling-pipelines --flow-file ./path/to/flow.json
docling-pipelines --flow-file ./path/to/flow.json --validate
docling-pipelines validate-flow ./path/to/flow.json
docling-pipelines --list-operators              # Summary table
docling-pipelines --list-operators --verbose    # Detailed view
```

### Global arguments

| Argument           | Short |    Required | Description                                    |
| ------------------ | ----- | ----------: | ---------------------------------------------- |
| `--flow-file`      | `-f`  | Conditional | Flow JSON path                                 |
| `--list-operators` | `-lo` |          No | List operators and exit (summary table format) |
| `--verbose`        | `-v`  |          No | Show detailed operator info (use with `-lo`)   |
| `--validate`       | -     |          No | Validate instead of executing                  |

### Exit codes

| Exit code | Meaning                                       |
| --------- | --------------------------------------------- |
| `0`       | Validation succeeded                          |
| `1`       | Validation failed or file/JSON loading failed |

---

## Flow Configuration API

Docling Pipelines uses a simplified authoring format for creating flows. See [`sample_flows/quickstart/complete_pipeline_ollama.json`](../../sample_flows/quickstart/complete_pipeline_ollama.json) for a complete example.

### Root structure

```json
{
  "flow_name": "invoice processing flow",
  "description": "description",
  "flow": [],
  "global_config": {
    "storage": "in-memory",
    "execute_type": "local"
  }
}
```
[`DocpipeFlowManager`](../../src/docpipe/lib/docpipe_flow_manager.py#L140) also accepts root-level flow definitions without a wrapping `flow` key.

### Flow fields

| Field           | Type   | Required | Description                  |
| --------------- | ------ | -------: | ---------------------------- |
| `flow_name`     | string |      Yes | Human-readable flow name     |
| `description`   | string |       No | Flow description             |
| `flow`          | array  |      Yes | Ordered operator definitions |
| `global_config` | object |       No | Shared runtime config        |

### Operator structure

```json
{
  "name": "operator_name",
  "type": "operator_type",
  "depends_on": ["upstream_operator"],
  "config": {}
}
```

### Operator fields

| Field        | Type   | Required | Description                                |
| ------------ | ------ | -------: | ------------------------------------------ |
| `name`       | string |      Yes | Unique operator name within the flow       |
| `type`       | string |      Yes | Registered operator type (e.g., `chunker`) |
| `depends_on` | array  |       No | List of upstream operator names            |
| `config`     | object |       No | Operator-specific configuration            |

### Dependency declaration

Operators declare dependencies using the `depends_on` field:

```json
{
  "name": "extract",
  "type": "extract_operator",
  "depends_on": ["ingest"],
  "config": {}
}
```

The system automatically generates the execution DAG from these dependencies.

### Validation rules

Validation is performed by [`FlowValidator`](../../src/docpipe/lib/docpipe_flow_manager.py#L20) and CLI validation helpers.

Practical rules from the reviewed code:

- operator short names must resolve to registered operators
- required operator config must validate
- required input features must be present
- branch and filter references must use valid columns
- flow file must be valid JSON

---

## Exception Reference

All custom exception types reviewed here come from [`docpipe_exceptions.py`](../../src/docpipe/exceptions/docpipe_exceptions.py).

### `DocpipeException`

Base exception for application-level failures.

Use when:

- a caller needs an HTTP status code
- an error code should propagate through middleware
- a general Docling Pipelines runtime/configuration failure occurs

### `FlowExecutionFailedException`

Raised for flow execution failures.

### `FlowValidationException`

Raised when a flow definition is invalid.

Carries:

- `errors`
- `warnings`

### `PrefectFlowFailed`

Raised when Prefect-backed orchestration fails for a task.

### `ValidationException`

Generic validation failure outside full flow validation.

### `ConfigurationError`

Raised for invalid or missing configuration.

### `DependencyError`

Raised when an optional dependency is missing.

### `ExternalServiceError`

Raised when external services fail.

Typical cases:

- API calls
- auth problems
- rate limits
- network failures

### `FlowNotFoundException`

Raised when requested flow storage entries do not exist.

### `FlowAlreadyExistsException`

Raised when creating a duplicate flow.

### `FlowInvalidDataException`

Raised when flow payload or fields are malformed.

### `FlowStorageException`

Raised when storage operations fail, such as file I/O problems.

### `RepositoryConfigurationException`

Raised when repository type or repository config is invalid.

### `ValidationAlert`

Dictionary-like validation payload used in warnings/errors.

### `ValidationAlertEncoder`

JSON encoder for validation alerts.

---

## Utilities API

### PyArrow handler utilities

Defined in [`pyarrow_handler.py`](../../src/docpipe/utils/data/pyarrow_handler.py)

#### `BaseParquetTableHandler`

Abstract contract for parquet read/write/delete operations.

Key methods:

- `read_table()` - Read PyArrow table from file
- `save_table()` - Save PyArrow table to file
- `delete_rows()` - Delete rows from table
- `delete_file()` - Delete file from storage

#### `CpdParquetTableHandler`

Concrete local-file implementation.

#### `get_parquet_table_handler()`

Defined at [`get_parquet_table_handler()`](../../src/docpipe/utils/data/pyarrow_handler.py) in docpipe utilities

Returns the default parquet handler implementation.

### Schema utilities

Defined in [`schema_utils.py`](../../src/docpipe/utils/data/schema_utils.py)

#### `align_table_schema(table, all_cols)`

Defined at [`align_table_schema()`](../../src/docpipe/utils/data/schema_utils.py) in schema utilities

Adds missing columns with null values and aligns ordering.

#### `_combine_tables(tables, table_type)`

Defined at [`_combine_tables()`](../../src/docpipe/utils/data/schema_utils.py) in schema utilities

Safely concatenates tables and warns on duplicate IDs.

#### `_total_rows(tables)`

Defined at [`_total_rows()`](../../src/docpipe/utils/data/schema_utils.py) in schema utilities

Computes total row counts across a table, list, dict, or `None`.

### Document class utilities

Defined in [`document_class_utils.py`](../../src/docpipe/utils/document_class_utils.py)

#### `DocumentClassUtils.normalize_filename(name)`

Defined at [`normalize_filename()`](../../src/docpipe/utils/document_class_utils.py) in document class utilities

Normalizes human labels into stable filenames.

#### `DocumentClassUtils.load_document_class(doc_class_path)`

Defined at [`load_document_class()`](../../src/docpipe/utils/document_class_utils.py) in document class utilities

Loads a document class JSON definition.

#### `DocumentClassUtils.generate_docling_template(doc_class_path, include_nested=True, max_fields=None)`

Defined at [`generate_docling_template()`](../../src/docpipe/utils/document_class_utils.py) in document class utilities

Builds a Docling extraction template from a document class schema.

**Raises**

- `FileNotFoundError`
- `json.JSONDecodeError`

### Operator display utility

Defined in [`display.py`](../../src/docpipe/utils/operators/display.py)

#### `list_operators(verbose=False)`

Defined at [`list_operators()`](../../src/docpipe/utils/operators/display.py)

Generates the same operator catalog used by the CLI and [`DocpipeFlowManager.list_operators()`](../../src/docpipe/lib/docpipe_flow_manager.py).

**Parameters:**

- `verbose` (bool): If True, shows detailed operator information with all parameters. If False (default), shows summary table with Owner, Attributes, Features columns.

**Output Format:**

- **Summary mode**: Table with columns: Owner (operator name), Attributes (parameter count), Features (capability count)
- **Verbose mode**: Detailed listing with full parameter descriptions, types, and default values
- **Category order**: Ingest, Extract, Quality, Functional, VectorDB, Storage
