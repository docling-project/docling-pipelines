# ExtractOperator

Converts raw document files to markdown text and optionally extracts structured entities.

- **Short Name:** `extract_operator`
- **Category:** Extract

---

## Overview

The operator follows hexagonal architecture principles, separating business logic from infrastructure concerns:

- **Domain Layer**: Core models (`TextExtractionMode`, `EntityExtractionMode`, extraction requests/results)
- **Port Layer**: Interfaces defining extraction contracts (`TextExtractionPort`, `EntityExtractionPort`)
- **Adapter Layer**: Concrete implementations for different extraction strategies
- **Factory Layer**: Creates appropriate adapters based on configuration

This architecture enables:
- Easy addition of new extraction strategies
- Clear separation of concerns
- Testability through dependency injection
- Flexibility in switching between implementations

## Key Features

- **Dual-Mode Operation**: Supports both text extraction and entity extraction in a single operator
- **Multiple Text Extraction Strategies**: Docling Library (with optional VLM and ASR pipeline) and Docling Serve API
- **Multiple Entity Extraction Strategies**: LiteLLM (including Ollama via openai/ prefix), Docling template-based, and WatsonX
- **Streaming Pipeline**: When entity extraction is enabled, each document is submitted for entity extraction immediately after its text extraction completes, without waiting for the full batch. The two stages run concurrently, reducing end-to-end latency on large batches.
- **Estimated Page Count Calculation**: Automatically calculates estimated page counts for extracted text
- **Parallel Processing**: Automatic worker optimization based on CPU count
- **Flexible Configuration**: Provider-specific parameters with sensible defaults
- **Consistent Error Handling**: Unified error handling and metadata across all modes

## Operator Configuration

```json
{
  "type": "extract_operator",
  "name": "extract_documents",
  "config": {
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content",
      "provider_config": {}
    },
    "entity_extraction": {
      "provider": "none"
    }
  },
  "depends_on": ["ingest_documents"]
}
```

## Text Extraction Providers

### 1. Docling Library Provider (Default)

Standard document extraction using the Docling library locally. Supports optional VLM (Vision-Language Model) pipeline for enhanced extraction and ASR (Automatic Speech Recognition) pipeline for audio/video processing.

**Basic Configuration:**
```json
{
  "max_workers": 4,
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
```

**VLM Pipeline Configuration:**

Enable VLM pipeline for enhanced extraction with vision-language models:

```json
{
  "max_workers": 1,
  "text_extraction": {
    "provider": "docling_library",
    "doc_column": "content",
    "provider_config": {
      "vlm_pipeline": {
        "preset": "granite_docling",
        "engine": "transformers",
        "engine_options": {}
      }
    }
  },
  "entity_extraction": {
    "provider": "none"
  }
}
```

**GPU Acceleration Configuration:**

Enable GPU-accelerated standard pipeline processing for PDF and image documents. The GPU `DocumentConverter` is taken from the process-wide converter pool (see [Converter Reuse and Pool Sizing](#converter-reuse-and-pool-sizing)), so model weights are loaded onto the GPU once per configuration and reused across documents and micro-batches.

> **Note:** Cannot be combined with `vlm_pipeline`. Requires `max_workers: 1` and `use_processes: false`.

When `device` is omitted, the best available GPU is auto-detected at runtime via torch (CUDA → MPS → XPU). Specify `device` explicitly to pin a particular GPU.

```json
{
  "max_workers": 1,
  "use_processes": false,
  "text_extraction": {
    "provider": "docling_library",
    "doc_column": "content",
    "provider_config": {
      "standard_pipeline": {
        "accelerator": {
          "num_threads": 6
        }
      }
    }
  },
  "entity_extraction": {
    "provider": "none"
  }
}
```

Or with an explicit device:

```json
{
  "max_workers": 1,
  "use_processes": false,
  "text_extraction": {
    "provider": "docling_library",
    "doc_column": "content",
    "provider_config": {
      "standard_pipeline": {
        "accelerator": {
          "device": "cuda",
          "num_threads": 6
        }
      }
    }
  },
  "entity_extraction": {
    "provider": "none"
  }
}
```

**Supported GPU Devices:**
- `mps` — Apple Metal Performance Shaders (Apple Silicon: M1/M2/M3/M4)
- `cuda` — NVIDIA CUDA (automatic device selection)
- `cuda:<index>` — NVIDIA CUDA on a specific device (e.g. `cuda:0`, `cuda:1`)
- `xpu` — Intel XPU

**Supported VLM Engines:**
- `transformers`: Local inference using Transformers library
- `mlx`: Local inference optimized for macOS (Apple Silicon)
- `api_ollama`: Ollama API
- `api_openai`: OpenAI API
- `api_watsonx`: IBM watsonx.ai API
- `api_lmstudio`: LM Studio API
- `api`: Generic API endpoint

**VLM Pipeline Configuration Examples:**

Ollama:
```json
{
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
  }
}
```

OpenAI:
```json
{
  "text_extraction": {
    "provider": "docling_library",
    "provider_config": {
      "vlm_pipeline": {
        "preset": "qwen",
        "engine": "api_openai",
        "engine_options": {
          "api_base": "https://api.openai.com",
          "model_id": "gpt-4-vision-preview",
          "api_key": "<your-api-key>"
        }
      }
    }
  }
}
```

**ASR Pipeline Configuration:**

Enable ASR pipeline for audio and video file transcription:

```json
{
  "max_workers": 2,
  "text_extraction": {
    "provider": "docling_library",
    "doc_column": "content",
    "provider_config": {
      "asr_pipeline": {
        "model_id": "whisper_turbo"
      }
    }
  },
  "entity_extraction": {
    "provider": "none"
  }
}
```

**Use Cases:**
- Simple document conversion to markdown (without VLM)
- Complex document layouts (with VLM)
- Documents with mixed content types (with VLM)
- Audio/video transcription (with ASR)
- Local processing without external dependencies
- High-accuracy extraction requirements (with VLM)
- Quick prototyping and testing

**Sample Flows:**
- Basic: [`sample_flows/quickstart/basic_ingest_extract.json`](../../../sample_flows/quickstart/basic_ingest_extract.json)
- Complete: [`sample_flows/quickstart/complete_pipeline_ollama.json`](../../../sample_flows/quickstart/complete_pipeline_ollama.json)
- Audio/Video: [`sample_flows/use_cases/audio_video_extraction.json`](../../../sample_flows/use_cases/audio_video_extraction.json)

### 2. Docling Serve Provider

REST API-based extraction using the Docling-Serve service for scalable, production-ready document processing.

**Configuration:**
```json
{
  "text_extraction": {
    "provider": "docling_serve",
    "provider_config": {
      "base_url": "http://localhost:5001",
      "timeout": 300,
      "poll_interval": 2,
      "max_retries": 3,
      "ocr": {
        "enabled": true,
        "engine": "easyocr",
        "engine_options": {
          "lang": ["en"]
        }
      },
      "pdf_backend": "dlparse_v4",
      "table_mode": "accurate",
      "image_export_mode": "embedded"
    }
  },
  "entity_extraction": {
    "provider": "none"
  }
}
```

**File Handling:**
- `.txt` files are processed locally using basic text extraction (not sent to Docling Serve)
- Binary content submissions preserve the original filename for proper MIME type detection
- Supported MIME types are automatically detected based on file extension

**MIME Type Mapping:**

| Extension | MIME Type |
|-----------|-----------|
| `.html`, `.htm` | `text/html` |
| `.md` | `text/markdown` |
| `.txt` | `text/plain` |
| `.pdf` | `application/pdf` |
| `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| `.doc` | `application/msword` |
| `.xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| `.xls` | `application/vnd.ms-excel` |
| `.pptx` | `application/vnd.openxmlformats-officedocument.presentationml.presentation` |
| `.ppt` | `application/vnd.ms-powerpoint` |
| Other | `application/octet-stream` |

**Prerequisites:**
```bash
# Start docling-serve locally
docker run -p 5001:5001 ds4sd/docling-serve:latest

# Or use docker-compose
docker-compose -f docker-compose.docling-serve.yml up -d
```

**Features:**
- **OCR Support**: Process scanned documents and images
  - EasyOCR engine (supports 80+ languages)
  - Tesseract engine
  - Multi-language support
- **Multiple PDF Backends**:
  - `dlparse_v4`: Latest Docling parser (recommended)
  - `dlparse_v3`: Legacy Docling parser
  - `pypdfium2`: PyPDFium2 backend
- **Table Extraction Modes**:
  - `accurate`: High accuracy (slower)
  - `fast`: Fast processing (less accurate)
- **Image Export Options**:
  - `placeholder`: Replace images with a placeholder (default)
  - `embedded`: Embed images in output
  - `referenced`: Reference images by path
  - `none`: Skip image export

**Use Cases:**
- Production document processing pipelines
- High-volume document ingestion
- Scanned document processing with OCR
- Multi-language document processing
- Distributed processing architectures

**Sample Flow:** [`sample_flows/quickstart/complete_pipeline_ollama.json`](../../../sample_flows/quickstart/complete_pipeline_ollama.json)

## Entity Extraction Providers

Entity extraction can be combined with any text extraction provider to extract structured data from the extracted text.

### 1. None Provider (Default)

No entity extraction is performed. Only text extraction is executed.

**Configuration:**
```json
{
  "text_extraction": {
    "provider": "docling_library"
  },
  "entity_extraction": {
    "provider": "none"
  }
}
```

### 2. Docling Provider (VLM-Based)

Vision-Language Model (VLM) based entity extraction using Docling's VLM pipeline for structured data extraction from documents.

**Basic Configuration:**
```json
{
  "text_extraction": {
    "provider": "docling_library"
  },
  "entity_extraction": {
    "provider": "docling",
    "custom_schema": {
      "invoice_number": "string",
      "invoice_date": "string",
      "total_amount": "number",
      "line_items": [
        {
          "description": "string",
          "quantity": "number",
          "unit_price": "number"
        }
      ]
    }
  }
}
```

**Custom Model Configuration:**

Users can configure custom inline VLM models for entity extraction using the `vlm_pipeline` parameter. Only inline models (HuggingFace) are supported as DocumentExtractor does not support remote API endpoints.

**Inline Model (HuggingFace with Transformers):**
```json
{
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
      "invoice_number": "string",
      "total_amount": "number"
    }
  }
}
```

**Note:** API model configuration is not supported. For API-based entity extraction, use `entity_extraction.provider: "litellm"` instead.

**Supported Model Types:**
- **Inline Models**: HuggingFace models with Transformers, vLLM, or MLX backends
- **API Models**: Ollama, vLLM server, OpenAI-compatible endpoints

**Supported Backends (for inline models):**
- `transformers`: HuggingFace Transformers library
- `vllm`: vLLM inference engine
- `mlx`: Apple MLX framework (macOS only)

**Use Cases:**
- Extracting structured data from standardized forms
- Processing documents with known schema
- Vision-based entity extraction from complex layouts
- Custom model integration for specialized domains
- Template-driven workflows with VLM enhancement

**Sample Flow:** [`sample_flows/quickstart/complete_pipeline_ollama.json`](../../../sample_flows/quickstart/complete_pipeline_ollama.json)

### 3. LiteLLM Provider

Multi-provider LLM extraction using LiteLLM for accessing 100+ LLM providers (OpenAI, Anthropic, Cohere, Ollama, etc.).

**Configuration (OpenAI):**
```json
{
  "text_extraction": {
    "provider": "docling_library"
  },
  "entity_extraction": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/gpt-3.5-turbo",
      "api_key": "your-api-key",  # pragma: allowlist secret
      "api_base": "https://api.openai.com/v1",
      "temperature": 0.0,
      "max_tokens": 2000
    },
    "custom_schema": {
      "invoice_number": "string",
      "total_amount": "number"
    }
  }
}
```

**Configuration (Ollama via LiteLLM):**
```json
{
  "text_extraction": {
    "provider": "docling_library"
  },
  "entity_extraction": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/llama3.2",
      "api_base": "http://localhost:11434/v1",
      "api_key": "<ollama_key>",
      "temperature": 0.0,
      "max_tokens": 4096
    },
    "custom_schema": {
      "invoice_number": "string",
      "total_amount": "number"
    }
  }
}
```

**Configuration (Remote vLLM with Streaming & Extended Timeout):**

For high-concurrency scenarios with remote vLLM clusters processing large documents, use streaming and extended timeouts to prevent connection drops:

```json
{
  "text_extraction": {
    "provider": "docling_library"
  },
  "entity_extraction": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/granite4:latest",
      "api_base": "https://your-vllm-route/v1",
      "api_key": "YOUR_API_KEY",  # pragma: allowlist secret
      "temperature": 0.0,
      "max_tokens": 5000,
      "stream": true,
      "timeout": 1800
    },
    "custom_schema": {
      "invoice_number": "string",
      "total_amount": "number"
    }
  }
}
```

**Advanced Provider Configuration Parameters:**
- `stream` (boolean, default: `false`): Enable HTTP chunked transfer encoding to keep connections alive during long-running requests. Recommended for remote vLLM clusters processing large documents.
- `timeout` (integer, default: `60`): HTTP client read timeout in seconds. Set to 1800 (30 minutes) for large documents that require extended generation time.

**Why Streaming & Extended Timeout?**

During high-concurrency scalability testing with remote vLLM clusters, connection issues were identified:
1. **Infrastructure Idle Timeout**: Load balancers (IBM Cloud Edge, HAProxy) reset idle connections after ~100 seconds without data transmission. With `stream=false`, vLLM waits until entire generation completes (150+ seconds for large documents) before sending response, causing connections to be dropped mid-generation.
2. **Extended Processing Time**: Large documents requiring 5000+ tokens at ~88 tokens/sec take 150+ seconds to generate, exceeding typical load balancer idle timeouts.

**Solution**: Combining `stream=true` with `timeout=1800` ensures:
- Continuous packet flow (streaming chunks) prevents idle timeout detection by load balancers
- Extended timeout (30 minutes) allows completion of large document processing
- Connections remain stable under high concurrency (10,000+ documents)

**Supported Providers:**
- OpenAI (GPT-3.5, GPT-4, GPT-4o)
- Anthropic (Claude 3 Opus, Sonnet, Haiku)
- Cohere (Command, Command-R)
- Google (Gemini Pro, Gemini Ultra)
- Azure OpenAI
- AWS Bedrock
- Ollama (via openai/ model prefix)
- And 100+ other providers via LiteLLM

**Prerequisites for Ollama:**
- Ollama server running on `http://localhost:11434`
- Model pulled: `ollama pull llama3.2`

**Use Cases:**
- Multi-provider LLM support without code changes
- Enterprise LLM deployments (Azure, AWS Bedrock)
- Cost optimization by switching between providers
- Fallback strategies across multiple providers
- Schema-based and schema-free entity extraction
- Local LLM processing via Ollama

**Sample Flows:**
- [`sample_flows/operators/entity_extraction_litellm.json`](../../../sample_flows/operators/entity_extraction_litellm.json)

### 4. WatsonX Provider

IBM WatsonX.ai LLM-based entity extraction for enterprise deployments.

**Configuration:**
```json
{
  "text_extraction": {
    "provider": "docling_library"
  },
  "entity_extraction": {
    "provider": "watsonx",
    "provider_config": {
      "model_id": "ibm/granite-13b-chat-v2",
      "api_key": "${WATSONX_API_KEY}",
      "container_id": "${WATSONX_CONTAINER_ID}",
      "api_base": "https://us-south.ml.cloud.ibm.com",
      "container_kind": "project",
      "temperature": 0.0,
      "max_tokens": 2000
    },
    "custom_schema": {
      "invoice_number": "string",
      "total_amount": "number"
    }
  }
}
```

**Environment Variables:**
- `WATSONX_API_KEY`: WatsonX API key (required)
- `WATSONX_CONTAINER_ID`: WatsonX project or space ID (required)
- `WATSONX_API_BASE_URL`: WatsonX API base URL (optional, defaults to us-south)
- `WATSONX_CONTAINER_KIND`: Container type - "project" or "space" (optional, defaults to "project")

**Use Cases:**
- Enterprise LLM deployments with IBM WatsonX.ai
- Regulated industries requiring on-premises or private cloud LLM
- Schema-based entity extraction with IBM Granite models
- Integration with existing IBM Cloud infrastructure

**Sample Flow:** [`sample_flows/operators/entity_extraction_watsonx.json`](../../../sample_flows/operators/entity_extraction_watsonx.json)

## Configuration Parameters

### Common Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `text_extraction.provider` | string | `"docling_library"` | Text extraction strategy: `"docling_library"` or `"docling_serve"` |
| `text_extraction.doc_column` | string | `"doc_content"` | Column name for storing extracted content |
| `text_extraction.provider_config.additional_formats` | array | `[]` | Additional output formats (e.g., `["html", "markdown"]`) |
| `max_workers` | integer | auto | Maximum number of parallel workers (auto-detected based on CPU) |
| `use_processes` | boolean | `false` | Use ProcessPoolExecutor instead of ThreadPoolExecutor (top-level parameter) |
| `entity_extraction.provider` | string | `"none"` | Entity extraction strategy: `"litellm"` (includes Ollama via openai/ prefix), `"docling"`, `"watsonx"`, or `"none"` |
| `entity_extraction.custom_schema` | object | `{}` | Schema dictionary for structured extraction (top-level entity_extraction parameter) |
| `entity_extraction.expand_extracted_data` | boolean | `false` | Expand entity data JSON into individual columns (entity extraction only) |

### Docling Library Provider Parameters

| Parameter             | Type    | Default             | Description                                                         |
|-----------------------|---------|---------------------|---------------------------------------------------------------------|
| `text_extraction.provider_config.vlm_pipeline`        | object  | `null`              | VLM (Vision-Language Model) pipeline configuration object. Provide empty dict `{}` to enable with defaults, or omit to disable. |
| `text_extraction.provider_config.vlm_pipeline.preset` | string  | `"granite_docling"` | VLM preset name. Valid presets: `smoldocling`, `granite_docling`, `deepseek_ocr`, `granite_vision`, `pixtral`, `got_ocr`, `phi4`, `qwen`, `nanonets_ocr2`, `gemma_12b`, `gemma_27b`, `dolphin`, `glm_ocr`, `lightonocr`, `falcon_ocr` |
| `text_extraction.provider_config.vlm_pipeline.engine` | string  | `"api_ollama"`      | VLM engine type. Valid engines: `api_ollama`, `api_openai`, `api_watsonx`, `api_lmstudio`, `api` (generic), `transformers` (local), `mlx` (macOS) |
| `text_extraction.provider_config.vlm_pipeline.engine_options` | object | `{}`        | Engine-specific options (api_base, model_id, etc.)                  |
| `text_extraction.provider_config.asr_pipeline`        | object  | `null`              | ASR (Automatic Speech Recognition) pipeline configuration object. Provide empty dict `{}` to enable with defaults, or omit to disable. |
| `text_extraction.provider_config.asr_pipeline.model_id` | string | `"whisper_turbo"` | ASR model name. Valid values: `whisper_tiny`, `whisper_small`, `whisper_medium`, `whisper_base`, `whisper_large`, `whisper_turbo`, and their `_mlx`/`_native` variants (e.g., `whisper_tiny_mlx`, `whisper_tiny_native`) |
| `text_extraction.provider_config.standard_pipeline` | object | `null` | Standard pipeline acceleration block. Omit entirely to use default Docling behaviour. |
| `text_extraction.provider_config.standard_pipeline.accelerator` | object | `null` | GPU accelerator options. When present, the GPU `DocumentConverter` is pooled process-wide and reused across documents and micro-batches. **Requires `max_workers: 1` and `use_processes: false`. Cannot be combined with `vlm_pipeline`.** |
| `text_extraction.provider_config.standard_pipeline.accelerator.device` | string | auto-detected | GPU device. Accepted: `mps`, `cuda`, `cuda:<index>` (e.g. `cuda:0`), `xpu`. When omitted, best available device is auto-detected via torch (CUDA → MPS → XPU). Validated at runtime via torch backends. |
| `text_extraction.provider_config.standard_pipeline.accelerator.num_threads` | int | `4` | CPU-side pipeline thread count. Must be a positive integer (booleans rejected). |

### Docling Serve Provider Parameters

| Parameter              | Type     | Default                   | Description                                                   |
|------------------------|----------|---------------------------|---------------------------------------------------------------|
| `text_extraction.provider_config.base_url`             | string   | `"http://localhost:5001"` | Docling Serve API endpoint URL                                |
| `text_extraction.provider_config.api_key`              | string   | `null`                    | Optional API key for authentication                           |
| `text_extraction.provider_config.timeout`              | integer  | `300`                     | Request timeout in seconds                                    |
| `text_extraction.provider_config.poll_interval`        | integer  | `2`                       | Polling interval in seconds                                   |
| `text_extraction.provider_config.max_retries`          | integer  | `3`                       | Maximum retry attempts                                        |
| `text_extraction.provider_config.additional_formats`   | array    | `[]`                      | Additional output formats beyond markdown (e.g., `["html", "json", "text", "doctags", "doclang"]`) |
| `text_extraction.provider_config.ocr`                  | object   | `null`                    | **Canonical OCR config block** (see OCR Configuration section below) |
| `text_extraction.provider_config.pdf_backend`          | string   | `"dlparse_v2"`            | PDF backend: `"dlparse_v4"`, `"dlparse_v3"`, or `"pypdfium2"` |
| `text_extraction.provider_config.table_mode`           | string   | `null`                    | Table extraction mode: `"accurate"` or `"fast"`. Not set by default; the Docling Serve instance uses its own default. |
| `text_extraction.provider_config.image_export_mode`    | string   | `"placeholder"`           | Image export mode: `"placeholder"`, `"embedded"`, `"referenced"`, or `"none"` |


### OCR Configuration

Both `docling_library` and `docling_serve` providers accept an `ocr` block inside `provider_config`. Omitting the block entirely uses docling-pipelines defaults (OCR enabled, RapidOCR engine, default mode).

```json
"provider_config": {
  "ocr": {
    "enabled": true,
    "engine": "easyocr",
    "mode": "pdf_aware_layout_regions",
    "engine_options": {
      "lang": ["en", "fr"],
      "use_gpu": false,
      "confidence_threshold": 0.5
    }
  }
}
```

#### OCR Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `ocr.enabled` | bool | `true` | Enable OCR processing. Set `false` to skip OCR entirely. |
| `ocr.engine` | string | `"rapidocr"` | OCR engine. `"rapidocr"` is the default. |
| `ocr.mode` | string | `"default"` | OCR scanning mode. `"pdf_aware_layout_regions"` is most efficient for mixed PDFs. |
| `ocr.engine_options` | object | `null` | Engine-specific parameters (see table below). |

#### Supported Engines

| Engine | Value | Install extra | Notes |
|---|---|---|---|
| Auto-select | `"auto"` | none | Optional runtime selection when you explicitly want Docling to choose an installed backend. |
| EasyOCR | `"easyocr"` | `easyocr` | Cross-platform alternative; 80+ languages. |
| Tesseract (Python bindings) | `"tesserocr"` | `tesserocr` | Linux-focused local OCR option; 3-letter ISO 639-2 lang codes; PSM control. |
| Tesseract (CLI) | `"tesseract"` | `tesseract` binary | Same as above via CLI; portable. |
| RapidOCR | `"rapidocr"` | included in base install | Default OCR engine for new users; PaddlePaddle-based; multiple backends. |
| macOS Vision | `"ocrmac"` | `ocrmac` | Optional macOS-specific alternative; Apple-only. |
| KServe V2 | `"kserve_v2_ocr"` | custom | Remote KServe/Triton inference server. |
| Nemotron OCR | `"nemotron-ocr"` | custom | NVIDIA Nemotron v2. |

#### Installation Guidance by OS

RapidOCR is included in the default PyPI install, and `ocr.engine: "rapidocr"` is the default runtime behaviour for first-run OCR.

| OS / environment | Default install behaviour | Notes |
|---|---|---|
| macOS | `pip install docling-pipelines` | RapidOCR works out of the box. Install `docling-pipelines[ocrmac]` only if you want Apple's Vision OCR explicitly. |
| Linux | `pip install docling-pipelines` | RapidOCR works out of the box. Install `docling-pipelines[tesserocr]` only if you want Tesseract bindings explicitly. |
| Cross-platform / unsure | `pip install docling-pipelines` | Recommended for new users. First OCR run should work without extra setup. |

#### Supported Modes

| Mode | Value | Behaviour |
|---|---|---|
| Default | `"default"` | Docling picks automatically |
| Full page | `"full_page"` | Scan entire page as one region |
| Layout regions | `"layout_regions"` | Scan only layout-detected text regions |
| PDF-aware layout regions | `"pdf_aware_layout_regions"` | Skip regions with an existing PDF text layer — most efficient for mixed PDFs |

#### `engine_options` Reference

| Engine | Key | Type | Notes |
|---|---|---|---|
| `easyocr` | `lang` | list[str] | ISO 639-1 codes, e.g. `["en", "fr"]` |
| `easyocr` | `use_gpu` | bool/null | `null` = auto-detect |
| `easyocr` | `confidence_threshold` | float | 0.0–1.0 |
| `tesserocr` / `tesseract` | `lang` | list[str] | 3-letter ISO 639-2, e.g. `["eng", "fra"]` |
| `tesserocr` / `tesseract` | `psm` | int | Page segmentation mode 0–13 |
| `tesserocr` / `tesseract` | `path` | str/null | Tessdata directory |
| `rapidocr` | `lang` | list[str] | Language list |
| `rapidocr` | `backend` | string | `"onnxruntime"`, `"openvino"`, `"paddle"`, `"torch"` |
| `rapidocr` | `text_score` | float | Detection confidence threshold |
| `ocrmac` | `lang` | list[str] | Locale format, e.g. `["en-US"]` |
| `ocrmac` | `recognition` | string | `"accurate"` or `"fast"` |


### Docling Entity Extraction Parameters

| Parameter               | Type   | Default | Description                                                                                     |
|-------------------------|--------|---------|-------------------------------------------------------------------------------------------------|
| `entity_extraction.provider_config.vlm_pipeline` | object | `null`  | Custom VLM model configuration (see Custom Model Configuration section above for full details) |

**vlm_pipeline Structure:**

Only `"inline"` models (HuggingFace) are supported. API model types are not supported by Docling's `DocumentExtractor`; use `entity_extraction.provider: "litellm"` for API-based extraction instead.

Example (all fields shown with their defaults; only `repo_id` is required):
```json
{
  "model_type": "inline",
  "inline_model": {
    "repo_id": "numind/NuExtract-2.0-2B",
    "inference_framework": "transformers",
    "scale": 2.0,
    "temperature": 0.0,
    "max_new_tokens": 4096,
    "load_in_8bit": true,
    "torch_dtype": "bfloat16",
    "prompt": "",
    "response_format": "markdown"
  }
}
```

| `inline_model` field      | Type    | Default        | Description                                                              |
|---------------------------|---------|----------------|--------------------------------------------------------------------------|
| `repo_id`                 | string  | required       | HuggingFace repository ID (e.g., `"numind/NuExtract-2.0-2B"`)           |
| `inference_framework`     | string  | `"transformers"` | Inference backend: `"transformers"`, `"vllm"`, or `"mlx"`             |
| `scale`                   | float   | `2.0`          | Image scale factor for rendering                                         |
| `temperature`             | float   | `0.0`          | Sampling temperature                                                     |
| `max_new_tokens`          | integer | `4096`         | Maximum tokens to generate                                               |
| `load_in_8bit`            | boolean | `false`        | Load model in 8-bit quantization                                         |
| `torch_dtype`             | string  | `"bfloat16"`   | Torch data type: `"bfloat16"`, `"float16"`, `"float32"`                 |
| `prompt`                  | string  | `""`           | Custom prompt override (leave empty to use model default)                |
| `response_format`         | string  | `"markdown"`   | Expected response format from the model                                  |

### LiteLLM Entity Extraction Parameters

All parameters are nested under `entity_extraction.provider_config`:

| Parameter                | Type    | Default           | Description                                                                                        |
|--------------------------|---------|-------------------|----------------------------------------------------------------------------------------------------|
| `model_id`      | string  | `"gpt-3.5-turbo"` | LLM model identifier. **Must include provider prefix** when using LiteLLM (e.g., `openai/gpt-4`, `openai/llama3.2` for Ollama, `anthropic/claude-3-opus`)                  |
| `temperature`     | float   | `0.0`             | Sampling temperature                                                                               |
| `max_tokens`      | integer | `2000`            | Maximum response tokens                                                                            |
| `api_key` | string  | `null`              | API key for the provider. For Ollama, can be any value |
| `api_base` | string  | `null`              | API base URL. For Ollama, set to `http://localhost:11434/v1` |
| `stream` | boolean  | `false`              | Enable HTTP chunked transfer encoding. For remote vLLM with large documents, use `stream: true` and `timeout: 1800` |
| `timeout` | integer  | `60`              | HTTP client read timeout in seconds. For remote vLLM with large documents, use `stream: true` and `timeout: 1800` |

### WatsonX Entity Extraction Parameters

All parameters are nested under `entity_extraction.provider_config`:

| Parameter                | Type    | Default                     | Description                                                                                        |
|--------------------------|---------|-----------------------------|----------------------------------------------------------------------------------------------------|
| `model_id`      | string  | `"ibm/granite-13b-chat-v2"` | WatsonX model identifier                                                                           |
| `temperature`     | float   | `0.0`                       | Sampling temperature                                                                               |
| `max_tokens`      | integer | `2000`                      | Maximum response tokens                                                                            |
| `api_key` | string  | required                        | WatsonX API key |
| `container_id` | string  | required                        | WatsonX project or space ID |
| `api_base` | string  | `"https://us-south.ml.cloud.ibm.com"` | WatsonX API base URL (optional) |
| `container_kind` | string  | `"project"` | Container type: "project" or "space" (optional) |

## Input/Output Data Formats

### Input columns (from IngestSourceOperator)

| Column | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | Document identifier |
| `name` | string | Yes | Document name/filename |
| `path` | string | Yes | Document file path |
| `document_type` | string | No | Document type for template-based entity extraction |

---

## Output Columns

All input columns are preserved. The operator appends:

| Column | PyArrow Type | Description |
|---|---|---|
| `doc_content` | `string` | Extracted markdown text |
| `doc_id_hash` | `string` | Hash ID generated from document content |
| `pages_processed` | `int32` | Estimated page count (3000 chars = 1 page) |
| `entities` | `string` | JSON string of extracted entities (when entity extraction is enabled) |
| `extracted_data` | `string` | Structured data from template extraction (when applicable) |

When `expand_extracted_data: true`, entity fields are expanded into individual columns.

---

## Examples

### Example 1: Basic Text Extraction Only

```json
{

  "operator_params": {
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

### Example 2: Text + Entity Extraction with Ollama (via LiteLLM)

```json
{

  "operator_params": {
    "max_workers": 2,
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content"
    },
    "entity_extraction": {
      "provider": "litellm",
      "provider_config": {
        "model_id": "openai/llama3.2",
        "api_base": "http://localhost:11434/v1",
        "api_key": "<ollama_key>",
        "temperature": 0.0,
        "max_tokens": 4096
      },
      "custom_schema": {
        "invoice_number": "string",
        "vendor_name": "string",
        "total_amount": "number"
      }
    }
  }
}
```

### Example 3: VLM Pipeline Text Extraction

```json
{

  "operator_params": {
    "max_workers": 1,
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content",
      "provider_config": {
        "vlm_pipeline": {
          "preset": "granite_docling",
          "engine": "transformers",
          "engine_options": {}
        }
      }
    },
    "entity_extraction": {
      "provider": "none"
    }
  }
}
```

### Example 4: Docling Serve with OCR

```json
{
  "operator_params": {
    "max_workers": 4,
    "text_extraction": {
      "provider": "docling_serve",
      "doc_column": "content",
      "provider_config": {
        "base_url": "http://localhost:5001",
        "ocr": {
          "enabled": true,
          "engine": "tesseract",
          "mode": "layout_regions",
          "engine_options": {
            "lang": ["eng", "spa"]
          }
        },
        "pdf_backend": "dlparse_v4",
        "table_mode": "accurate"
      }
    },
    "entity_extraction": {
      "provider": "none"
    }
  }
}
```

### Example 5: Template-Based Entity Extraction

```json
{

  "operator_params": {
    "max_workers": 2,
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content"
    },
    "entity_extraction": {
      "provider": "docling",
      "custom_schema": {
        "invoice_number": "string",
        "invoice_date": "string",
        "vendor_name": "string",
        "vendor_address": "string",
        "total_amount": "number",
        "currency": "string",
        "line_items": [
          {
            "description": "string",
            "quantity": "number",
            "unit_price": "number",
            "total": "number"
          }
        ]
      }
    }
  }
}
```

### Example 6: VLM Pipeline + Ollama Entity Extraction (via LiteLLM)

```json
{

  "operator_params": {
    "max_workers": 1,
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content",
      "provider_config": {
        "vlm_pipeline": {
          "preset": "granite_docling",
          "engine": "transformers",
          "engine_options": {}
        }
      }
    },
    "entity_extraction": {
      "provider": "litellm",
      "provider_config": {
        "model_id": "openai/llama3.2",
        "api_base": "http://localhost:11434/v1",
        "api_key": "<ollama_key>",
        "temperature": 0.0
      }
    }
  }
}
```

### Example 7: ASR Pipeline for Audio/Video Transcription

```json
{

  "operator_params": {
    "max_workers": 2,
    "text_extraction": {
      "provider": "docling_library",
      "doc_column": "content",
      "provider_config": {
        "asr_pipeline": {
          "model_id": "whisper_turbo"
        }
      }
    },
    "entity_extraction": {
      "provider": "none"
    }
  }
}
```

## Integration Requirements

### ASR Dependencies (for Audio/Video Processing)

**Requirement:** ASR (Automatic Speech Recognition) dependencies must be installed to process audio and video files

**Installation:**
```bash
# Install ASR dependencies
uv pip install -e '.[asr]'
```

**Supported Audio/Video Formats (when ASR is installed):**
- Audio: MP3, WAV, M4A, FLAC, OGG
- Video: MP4, AVI, MOV, MKV

**Note:** If ASR dependencies are not installed, the operator will only support standard document formats (PDF, DOCX, PPTX, etc.) and will log a warning if `use_asr_pipeline=true` is configured.

**Used By:** Text extraction with ASR when `use_asr_pipeline=true`

### ffmpeg (for Audio/Video Processing)

**Requirement:** ffmpeg must be installed and available on your PATH for processing certain audio and video formats

**Required For:**
- Audio formats: M4A, AAC, OGG, FLAC
- All video formats: MP4, AVI, MOV, etc.

**Not Required For:**
- Audio formats: WAV, MP3
- Document formats: PDF, images, etc.

**Installation:**

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

**Verify Installation:**
```bash
ffmpeg -version
```

**Used By:** Text extraction with ASR (Automatic Speech Recognition) when processing audio/video files

### Ollama Integration (for LiteLLM entity extraction with Ollama)

**Requirement:** Ollama server must be running on `http://localhost:11434`

**Setup:**
```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull required model
ollama pull llama3.2

# Verify Ollama is running
curl http://localhost:11434/api/tags
```

**Used By:** Entity extraction when `entity_extraction.provider="litellm"` with `entity_extraction.provider_config.model_id="openai/llama3.2"` and `entity_extraction.provider_config.api_base="http://localhost:11434/v1"`

### Docling Serve Integration (for docling_serve text extraction)

**Requirement:** Docling Serve must be running (default: `http://localhost:5001`)

**Setup:**
```bash
# Using Docker
docker run -p 5001:5001 ds4sd/docling-serve:latest

# Or using docker-compose
docker-compose -f docker-compose.docling-serve.yml up -d

# Verify service is running
curl http://localhost:5001/health
```

**Used By:** Text extraction when `text_extraction.provider="docling_serve"`

## Mode Comparison

| Feature                   | Docling Library (Basic)   | Docling Library (VLM)  | Docling Serve            |
|---------------------------|---------------------------|------------------------|--------------------------|
| **Processing Location**   | Local                     | Local/API              | Remote API               |
| **OCR Support**           | No                        | Limited                | Yes (EasyOCR, Tesseract) |
| **Multi-language OCR**    | No                        | No                     | Yes                      |
| **Scalability**           | Low                       | Medium                 | High                     |
| **Setup Complexity**      | Low                       | Medium                 | Medium                   |
| **Processing Speed**      | Fast                      | Slow                   | Medium                   |
| **Accuracy**              | Good                      | Excellent              | Excellent                |
| **External Dependencies** | None                      | Model files            | Docker container         |

| Feature                   | LiteLLM (Ollama) | LiteLLM (Cloud) | Docling   | WatsonX             |
|---------------------------|------------------|-----------------|-----------|---------------------|
| **Processing Location**   | Local            | Remote API      | Local     | Remote API          |
| **Schema Support**        | Yes              | Yes             | Yes       | Yes                 |
| **Schema-Free Mode**      | Yes              | Yes             | No        | Yes                 |
| **Setup Complexity**      | Medium           | Low             | Low       | Medium              |
| **Processing Speed**      | Medium           | Fast            | Fast      | Medium              |
| **Accuracy**              | High             | High            | Good      | High                |
| **External Dependencies** | Ollama server    | API keys        | None      | WatsonX credentials |

## Best Practices

### When to Use Each Text Extraction Provider

**Use Docling Library Provider (Basic) When:**
- Processing simple documents locally
- No OCR required
- Quick prototyping
- Minimal setup needed

**Use Docling Library Provider (VLM Pipeline) When:**
- Complex document layouts
- High accuracy requirements
- Local processing preferred
- GPU available for inference

**Use Docling Serve Provider When:**
- Production deployment
- OCR required for scanned documents
- Multi-language support needed
- Horizontal scaling required
- Processing high document volumes

### When to Use Each Entity Extraction Provider

**Use None Provider When:**
- Only text extraction is needed
- Entity extraction will be done in a separate step

**Use LiteLLM Provider When:**
- Multi-provider LLM support needed
- Cloud-based or local (Ollama) LLM processing
- Cost optimization by switching between providers
- Flexible entity extraction without predefined templates
- Schema-based or schema-free extraction needed

**Use Docling Provider When:**
- Extracting structured data from standardized forms
- Processing documents with known schema
- Fast, deterministic extraction required
- Template-driven workflows

**Use WatsonX Provider When:**
- Enterprise LLM deployments with IBM WatsonX.ai
- Regulated industries requiring private cloud LLM
- Integration with existing IBM Cloud infrastructure
- IBM Granite models preferred

### Performance Optimization

1. **Worker Configuration:**
   - Text extraction: Use default auto-detection (typically 4-8 workers)
   - Entity extraction with LLM: Reduce to 1-2 workers to avoid overwhelming the LLM
   - VLM extraction: Use 1 worker due to high memory requirements

2. **Document Size:**
   - For large documents with entity extraction, adjust `entity_max_doc_chars` to control LLM input size
   - Consider chunking very large documents before extraction

3. **Parallel Processing:**
   - Set top-level `use_processes: true` for CPU-intensive tasks
   - Use `use_processes: false` (default) for I/O-bound tasks

#### Converter Reuse and Pool Sizing

The `docling_library` text provider and the `docling` entity provider lease Docling `DocumentConverter` / `DocumentExtractor` instances from a process-wide pool instead of building new ones per worker thread and micro-batch. Each instance keeps its initialised model pipelines (layout, TableFormer, OCR, VLM), so models are loaded once per configuration and reused by later batches and operator instances. An instance is only ever used by one worker at a time, and configurations that differ in any option value never share an instance.

Because the pool is shared by every flow and job in the process (CLI, Python library and REST API alike), its limits are process-wide runtime settings, not flow or operator parameters. Set them in the `docling.converter_pool` section of the runtime config file `docling-pipelines-config.yaml` (path override: `DOCPIPE_CONFIG_PATH`) or with environment variables. An environment variable takes precedence over the config file, which takes precedence over the built-in default; an invalid value is ignored with a warning and the next source is used. Settings are read when the pool is first used, so changes take effect after a restart.

```yaml
docling:
  converter_pool:
    size: 8                 # default: min(2 x CPU count, 16)
    idle_ttl_seconds: 600   # 0 = keep idle converters until the process exits
```

| Environment variable | Config file key | Default | Description |
|----------------------|-----------------|---------|-------------|
| `DOCPIPE_DOCLING_CONVERTER_POOL_SIZE` | `docling.converter_pool.size` | `min(2 x CPU count, 16)` | Maximum number of live converters/extractors in the process, across all configurations and concurrent micro-batches. When all are busy, workers wait for a free one instead of loading more models. Minimum `1`. |
| `DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS` | `docling.converter_pool.idle_ttl_seconds` | `600` | Idle converters are released after this many seconds so a long-running API server frees model memory between jobs. `0` keeps them until the process exits. |

- The default pool size equals the default text-extraction worker count, so a single batch at default settings never waits. If you set `max_workers` higher than the pool size, the extra workers wait for a converter; raise the pool size together with `max_workers` if you have the memory for more converters.
- Each converter runs its models with Docling's own thread count (`AcceleratorOptions.num_threads`, default `4`, overridable with `DOCLING_NUM_THREADS` or `OMP_NUM_THREADS`). Up to `pool size x num_threads` inference threads can run at once (for example 16 x 4 = 64 on a 16-core host). If CPU usage is oversubscribed, lower `DOCLING_NUM_THREADS` or the pool size so that their product is close to the number of cores. These settings change throughput only, not the extracted content.

## Execution Metadata

The operator provides the following metadata after execution:

- **`page_type_stats`** (dict): Aggregate estimated pages grouped by source document format (e.g., `{"pdf": 120, "docx": 45}`)
- **`total_pages_converted`** (int): Total estimated pages across all successfully processed documents

These metrics are available through the operator's metadata and can be used for tracking document processing volume and performance analysis.

## Sample Flows

Complete sample flows are available in [`sample_flows/`](../../../sample_flows/):

- [`sample_flows/quickstart/basic_ingest_extract.json`](../../../sample_flows/quickstart/basic_ingest_extract.json) - Basic text extraction without entity extraction
- [`sample_flows/quickstart/complete_pipeline_ollama.json`](../../../sample_flows/quickstart/complete_pipeline_ollama.json) - Complete extraction with VLM and entity extraction (Ollama)
- [`sample_flows/quickstart/complete_pipeline_watsonx.json`](../../../sample_flows/quickstart/complete_pipeline_watsonx.json) - Complete extraction with WatsonX
- [`sample_flows/operators/entity_extraction_litellm.json`](../../../sample_flows/operators/entity_extraction_litellm.json) - LiteLLM entity extraction
- [`sample_flows/operators/entity_extraction_watsonx.json`](../../../sample_flows/operators/entity_extraction_watsonx.json) - WatsonX entity extraction
- [`sample_flows/use_cases/audio_video_extraction.json`](../../../sample_flows/use_cases/audio_video_extraction.json) - Audio and video extraction

## Troubleshooting

### Common Issues

**Issue: "Failed to initialize text extraction adapter"**
- Verify the `text_extraction.provider` value is valid: `"docling_library"` or `"docling_serve"`
- For VLM pipeline (when `vlm_pipeline` is configured), ensure required model files are available
- For Docling Serve provider, verify the service is running and accessible

**Issue: "Failed to initialize entity extraction adapter"**
- Verify the `entity_extraction.provider` value is valid: `"litellm"`, `"docling"`, `"watsonx"`, or `"none"`
- For LiteLLM provider with Ollama, ensure Ollama server is running and the model is pulled, and use `openai/` model prefix
- For WatsonX provider, ensure environment variables `WATSONX_API_KEY` and `WATSONX_CONTAINER_ID` are set
- Check that required parameters (model_name, etc.) are provided

**Issue: "Ollama connection refused"**
- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Check that the specified model is available: `ollama list`
- Ensure no firewall is blocking port 11434

**Issue: "Docling Serve timeout"**
- Increase `timeout` value
- Check Docling Serve service health: `curl http://localhost:5001/health`
- Verify network connectivity to the Docling Serve endpoint

**Issue: "Entity extraction returns empty results"**
- Verify document content is not empty after text extraction
- Check `entity_max_doc_chars` is not too restrictive
- For schema-based extraction, ensure the schema matches the document structure
- Review LLM model capabilities for the extraction task

**Issue: "Audio/video processing fails with codec errors"**
- Ensure ffmpeg is installed: `ffmpeg -version`
- Verify ffmpeg is in your PATH: `which ffmpeg` (macOS/Linux) or `where ffmpeg` (Windows)
- Install ffmpeg if missing:
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg` or `sudo dnf install ffmpeg`
- Supported formats requiring ffmpeg: M4A, AAC, OGG, FLAC (audio), MP4, AVI, MOV (video)
- WAV and MP3 audio files do not require ffmpeg

**Issue: Extraction workers stall or memory stays high after a job**
- Workers wait when every pooled converter is busy; the log shows `Docling converter pool is at capacity` once. Raise `DOCPIPE_DOCLING_CONVERTER_POOL_SIZE` or lower `max_workers`
- Idle converters keep model memory until the idle TTL (`DOCPIPE_DOCLING_CONVERTER_IDLE_TTL_SECONDS` or `docling.converter_pool.idle_ttl_seconds`) elapses; lower it to free memory sooner (see [Converter Reuse and Pool Sizing](#converter-reuse-and-pool-sizing))

**Issue: "ffmpeg not found" error during audio/video extraction**
- Verify ffmpeg installation: `ffmpeg -version`
- Add ffmpeg to your PATH if installed but not found
- Restart your terminal/shell after installing ffmpeg
- On macOS, ensure Homebrew's bin directory is in PATH: `export PATH="/opt/homebrew/bin:$PATH"`

## Architecture Details

### Hexagonal Architecture

The ExtractOperator follows hexagonal architecture (ports and adapters pattern) with clear separation of concerns:

```
ExtractOperator (Orchestrator)
    ↓
┌─────────────────────────────────────────────────────────────┐
│ Domain Layer                                                 │
│  - EntityExtractionService (business logic)                  │
│  - Domain Models (TextExtractionMode, EntityExtractionMode)  │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ Port Layer (Interfaces)                                      │
│  - TextExtractionPort                                        │
│  - EntityExtractionPort                                      │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ Adapter Layer (Implementations)                              │
│  Text Extraction:                                            │
│   - DoclingAdapter (docling_library provider, optional VLM/ASR)  │
│   - DoclingServeAdapter (docling_serve provider)                 │
│  Entity Extraction:                                          │
│   - LLMEntityAdapter (litellm and watsonx providers - unified)   │
│   - DoclingEntityAdapter (docling provider)                      │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ Factory Layer                                                │
│  - TextExtractionAdapterFactory                              │
│  - EntityExtractionAdapterFactory                            │
└─────────────────────────────────────────────────────────────┘
```

**Architecture Components:**

- **Domain Layer**: `EntityExtractionService` handles business logic (prompt building, schema validation, response parsing)
- **Port Layer**: Interfaces define extraction contracts without implementation details
- **Adapter Layer**: Concrete implementations for different extraction strategies
- **Factory Layer**: Creates appropriate adapters based on configuration mode

**Key Benefits:**
- Easy addition of new extraction strategies by implementing ports
- Clear separation between business logic, interfaces, and implementations
- Testability through dependency injection and mocking
- Unified LLM support: Both `litellm` and `watsonx` use the same `LLMEntityAdapter`

### Execution Flow

1. **Initialization:**
   - Parse extraction providers from configuration
   - Create text extraction adapter via `TextExtractionAdapterFactory`
   - Create entity extraction adapter via `EntityExtractionAdapterFactory` (if enabled)
   - Initialize `EntityExtractionService` with the entity adapter

2. **Text Extraction:**
   - Delegate to text extraction adapter
   - Process documents in parallel using worker pool
   - Collect extracted content and metadata

3. **Entity Extraction (if enabled):**
   - `EntityExtractionService` builds prompts with schema
   - Delegate to entity extraction adapter
   - Process extracted text in parallel
   - Extract structured entities based on schema or LLM
   - Service parses and validates responses

4. **Result Assembly:**
   - Combine text and entity extraction results
   - Update metadata with processing statistics
   - Return transformed PyArrow table

## Related Documentation

- [Docling Documentation](https://github.com/DS4SD/docling)
- [Ollama Documentation](https://ollama.com/docs)
- [Sample Flows](../../../sample_flows/)
