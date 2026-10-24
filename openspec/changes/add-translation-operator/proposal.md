# Proposal

## Why

Docling Pipelines needs a provider-agnostic translation operator so documents can be translated using supported LLM providers without coupling pipeline behavior to a specific provider. The change formalizes translation requirements before implementation review and improves consistency with existing pipeline conventions.

## What Changes

- Define translation behavior using the existing LLM adapter infrastructure, including LiteLLM and WatsonX.
- Preserve original document data and attach translated content and language metadata.
- Specify handling for empty content, long-document chunking, and translation failures.
- Integrate translation into an existing sample flow rather than maintaining a separate translation-only flow.
- Reuse existing constants and follow the simplest architecture that meets the operator's requirements.
- Document expected behavior and testing requirements.

## Capabilities

### New Capabilities

- `document-translation`: Provider-agnostic document translation, language metadata, chunking, and failure handling.

### Modified Capabilities

None.

## Impact

- Translation operator and service under `src/docpipe/operators/functional/`.
- Operator registry and existing sample flows.
- Translation tests and operator documentation.
- Existing LLM adapter infrastructure; no new provider integration should be introduced without need.