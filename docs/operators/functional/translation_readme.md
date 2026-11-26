# TranslationOperator

Translates document text into a target language using a configurable LLM provider.

- **Short Name:** `translation`
- **Category:** Functional

---

## Overview

`TranslationOperator` translates text from a configured input column while preserving the original document and all existing table columns. It uses the shared LLM inference interface and supports LiteLLM and WatsonX.

Long text is split into smaller chunks before translation. Each document is processed independently so that a translation failure does not stop processing other documents.

## Key Features

- Provider support for LiteLLM and WatsonX
- Configurable source and target languages
- Automatic chunking for long text
- Optional Markdown preservation
- Per-document error handling
- Empty text is skipped
- Original columns and row count are preserved
- Adds translated text and language metadata columns

---

## Operator Configuration

```json
{
  "type": "translation",
  "name": "translate_documents",
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/gpt-4o-mini",
      "api_key": "${OPENAI_API_KEY}"
    },
    "doc_column": "content",
    "output_column": "translated_content",
    "source_language": "auto",
    "target_language": "French",
    "preserve_markdown": true,
    "max_input_tokens": 4096
  },
  "depends_on": ["previous_operator"]
}
```

Replace `previous_operator` with the name of the upstream operator in your flow.

---

## Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `provider` | string | Yes | — | Inference provider: `litellm` or `watsonx` |
| `provider_config` | object | Yes | — | Provider configuration, including `model_id` and required provider credentials/settings |
| `doc_column` | string | No | `"content"` | Input column containing text to translate |
| `output_column` | string | No | `"translated_content"` | Column receiving translated text |
| `source_language` | string | No | `"auto"` | Source language or `auto` |
| `target_language` | string | Yes | — | Language to translate into |
| `preserve_markdown` | boolean | No | `true` | Instructs the model to preserve Markdown formatting |
| `max_input_tokens` | integer | No | `4096` | Approximate maximum input size used to determine chunk length |

### LiteLLM `provider_config`

| Field | Type | Description |
|---|---|---|
| `model_id` | string | Required model identifier supported by LiteLLM |
| `api_key` | string | Provider API key, where required |
| `api_base` | string | Optional custom API endpoint |
| `timeout` | integer | Optional request timeout, if supported by the configured adapter |

### WatsonX `provider_config`

| Field | Type | Description |
|---|---|---|
| `model_id` | string | Required WatsonX model identifier |
| `api_key` | string | IBM Cloud API key |
| `api_base` | string | WatsonX endpoint URL |
| `container_id` | string | Project or space identifier, as required by the adapter |
| `container_kind` | string | Project or space configuration, as supported by the adapter |

Provider-specific requirements depend on the selected model and adapter configuration. Keep credentials in environment variables rather than committing secrets.

---

## Output Columns

All original columns are preserved. The operator adds or updates these columns:

| Column | PyArrow Type | Description |
|---|---|---|
| `translated_content` (or configured `output_column`) | `string` | Translated document text; null for skipped or failed rows |
| `translation_source_language` | `string` | Configured source language |
| `translation_target_language` | `string` | Configured target language |

The output retains the original number of rows. Empty input text is skipped, and a failed translation does not prevent other rows from being processed.

---

## Examples

### Example 1 — Translate English into French using LiteLLM

```json
{
  "type": "translation",
  "name": "translate_to_french",
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/gpt-4o-mini",
      "api_key": "${OPENAI_API_KEY}"
    },
    "doc_column": "content",
    "target_language": "French"
  },
  "depends_on": ["previous_operator"]
}
```

### Example 2 — Translate while preserving Markdown

```json
{
  "type": "translation",
  "name": "translate_markdown",
  "config": {
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/gpt-4o-mini",
      "api_key": "${OPENAI_API_KEY}"
    },
    "source_language": "English",
    "target_language": "Spanish",
    "preserve_markdown": true,
    "max_input_tokens": 4096
  },
  "depends_on": ["previous_operator"]
}
```

---

## Troubleshooting

- **Missing target language:** Set a non-empty `target_language`.
- **Invalid provider:** Use `litellm` or `watsonx`.
- **Missing model identifier:** Set `provider_config.model_id`.
- **Missing input column:** Ensure the configured `doc_column` exists in the input table.
- **Empty translated output:** Check the selected model, credentials, endpoint, and provider response.
- **Some rows have null translations:** Empty rows are skipped; failed translations are recorded individually.
- **Markdown formatting changes:** Keep `preserve_markdown` enabled. Model output may still vary, especially when content is split into chunks.

---

## Architecture

`TranslationOperator` uses `LLMAdapterFactory` to create the configured inference adapter. `TranslationService` contains the translation prompt and chunking logic and depends on the shared `LLMInferencePort`, keeping translation logic independent of the specific provider implementation.
