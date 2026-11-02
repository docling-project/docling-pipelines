# backend/providers-api Specification

## Purpose

The providers-api capability is the REST API surface for querying LLM and embedding provider capabilities. It exposes a single endpoint that returns the models available on a given provider, used by the UI's embeddings and extract operator configuration panels to populate model dropdowns dynamically. Provider host resolution is server-side only — API base URLs are sourced from environment variables or validated against a known IBM Cloud WatsonX endpoint list; callers cannot supply arbitrary URLs.

## Requirements

### Requirement: List models for a supported provider
`GET /api/v1/providers/{provider}/models` SHALL return a `ModelsResponse` containing the normalised provider name and a list of `ModelInfo` objects. Supported providers are `ollama` and `watsonx`. An empty `models` list is a valid 200 response when the provider is reachable but has no models configured. The service instance SHALL be a singleton cached for the process lifetime.

#### Scenario: Ollama models listed successfully
- **WHEN** `GET /api/v1/providers/ollama/models` is called and the Ollama host is reachable
- **THEN** the response is 200 with `provider="ollama"` and a list of `ModelInfo` objects

#### Scenario: WatsonX models listed with server-side base URL
- **WHEN** `GET /api/v1/providers/watsonx/models` is called without `api_base` and `WATSONX_API_BASE_URL` is set
- **THEN** the response is 200 with `provider="watsonx"` and a list of available models

#### Scenario: WatsonX models listed with caller-supplied api_base
- **WHEN** `GET /api/v1/providers/watsonx/models?api_base=https://us-south.ml.cloud.ibm.com` is called
- **THEN** the response is 200 with models from the specified WatsonX deployment

#### Scenario: Empty model list is a valid 200
- **WHEN** the provider is reachable but has no models configured
- **THEN** the response is 200 with `models=[]`

### Requirement: Unsupported provider returns 400
A request for any provider name that is not in the supported set (`ollama`, `watsonx`) SHALL return 400 with `errors[0].code = "unsupported_provider"` and `target.name = "provider"`.

#### Scenario: Unknown provider returns 400
- **WHEN** `GET /api/v1/providers/openai/models` is called
- **THEN** the response is 400 with `errors[0].code = "unsupported_provider"`

### Requirement: Invalid WatsonX api_base returns 400
When `api_base` is supplied for WatsonX but is not in the allowed IBM Cloud WatsonX endpoint list, the request SHALL return 400 with `errors[0].code = "invalid_api_base"` and `target.name = "api_base"`.

#### Scenario: Disallowed api_base returns 400
- **WHEN** `GET /api/v1/providers/watsonx/models?api_base=https://evil.example.com` is called
- **THEN** the response is 400 with `errors[0].code = "invalid_api_base"`

### Requirement: Missing server configuration returns 400
When `api_base` is omitted for WatsonX and `WATSONX_API_BASE_URL` is not configured on the server, the request SHALL return 400 with `errors[0].code = "missing_configuration"`.

#### Scenario: Missing WATSONX_API_BASE_URL returns 400
- **WHEN** `GET /api/v1/providers/watsonx/models` is called without `api_base` and `WATSONX_API_BASE_URL` is unset
- **THEN** the response is 400 with `errors[0].code = "missing_configuration"`

### Requirement: Unavailable provider or missing SDK returns 503
When the upstream provider is unreachable, the response SHALL be 503 with `errors[0].code = "provider_unavailable"`. When the required provider SDK is not installed, the response SHALL be 503 with `errors[0].code = "provider_sdk_missing"`.

#### Scenario: Provider unreachable returns 503
- **WHEN** `GET /api/v1/providers/ollama/models` is called and the Ollama host is unreachable
- **THEN** the response is 503 with `errors[0].code = "provider_unavailable"`

#### Scenario: Missing SDK returns 503
- **WHEN** `GET /api/v1/providers/watsonx/models` is called and `ibm-watsonx-ai` is not installed
- **THEN** the response is 503 with `errors[0].code = "provider_sdk_missing"`
