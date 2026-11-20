# SummarizationOperator

Generates one LLM summary for every non-empty document row without requiring
document chunking.

## Overview

`SummarizationOperator` reads text from a configurable input column and writes
one summary to a configurable output column. Existing rows and columns are
preserved. Empty content is skipped, and provider failures preserve the row
with a null summary.

## Key Features

- LiteLLM and WatsonX through the shared inference adapter factory
- Sentence-aware map-reduce handling for long documents
- Configurable input/output columns and summary limits
- Per-document failure and skip metadata

## Operator Configuration

```json
{
  "type": "summarization",
  "name": "summarize_documents",
  "config": {
    "doc_column": "content",
    "output_column": "summary",
    "provider": "litellm",
    "provider_config": {
      "model_id": "openai/llama3.1",
      "api_base": "http://localhost:11434/v1",
      "api_key": "<ollama>"
    }
  }
}
```

## Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---:|---|---|
| `doc_column` | string | No | `content` | Input text column |
| `output_column` | string | No | `summary` | Output summary column |
| `provider` | string | Yes | - | `litellm` or `watsonx` |
| `provider_config` | object | Yes | - | Provider settings, including `model_id` |
| `max_input_tokens` | integer | No | `4096` | Maximum estimated input tokens per request |
| `overlap_ratio` | number | No | `0.1` | Overlap between long-document windows |
| `summary_sentences` | integer | No | `3` | Target maximum number of sentences |
| `summary_max_words` | integer | No | `50` | Target maximum number of words |

## Output Columns

All input columns and rows are preserved. The configured output column is a
nullable string containing the generated summary.

## Examples

See [`sample_flows/operators/summarization.json`](../../../sample_flows/operators/summarization.json).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Configuration validation fails | `provider`, `provider_config`, or `provider_config.model_id` is missing | Provide all required provider settings |
| Rows have null summaries | A provider request failed | Check provider connectivity and credentials; the row is retained for downstream handling |
| Empty rows have null summaries | Input content is blank | This is expected; empty documents are recorded as skipped |

## Architecture

The operator creates an `LLMInferencePort` adapter through `LLMAdapterFactory`
and delegates summary generation to `SummarizationService`. Long documents
are split at sentence boundaries, summarized independently, then reduced into
one final summary.
