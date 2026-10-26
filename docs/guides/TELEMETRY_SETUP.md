# OpenTelemetry Telemetry Setup Guide

## Overview

Docling Pipelines supports OpenTelemetry (OTEL) for distributed tracing and observability. This guide covers installation, configuration, and usage of the telemetry features.

## Features

- **Automatic HTTP Request Tracing**: All API requests are automatically traced with latency metrics
- **Operator Execution Tracing**: Track execution time, success rate, and error counts per operator
- **Metrics Collection**: HTTP and operator metrics exported via OTLP alongside traces
- **Log-Trace Correlation**: Every JSON log record includes `trace_id` and `span_id` for direct navigation from logs to traces
- **Head-Based Sampling**: Reduce trace volume in high-traffic environments via `OTEL_TRACES_SAMPLER_ARG`
- **Zero Overhead When Disabled**: No performance impact when telemetry is disabled
- **Vendor Agnostic**: Works with any OTLP-compatible monitoring backend
- **Non-Breaking**: Optional feature that doesn't affect existing functionality

## Prerequisites

- Python 3.12+
- Docling Pipelines installed
- OTLP-compatible monitoring backend (Jaeger, Grafana Tempo, Datadog, etc.)

## Installation

### 1. Install Telemetry Dependencies

```bash
# Install Docling Pipelines with telemetry support
uv pip install -e ".[telemetry]"
```

This installs the following packages:
- `opentelemetry-api` - Core OTEL API
- `opentelemetry-sdk` - OTEL SDK implementation
- `opentelemetry-exporter-otlp-proto-grpc` - OTLP gRPC exporter
- `opentelemetry-instrumentation-fastapi` - FastAPI auto-instrumentation

### 2. Choose a Monitoring Backend

Docling Pipelines works with any OTLP-compatible backend. Popular options:

- **Jaeger** (recommended for local development)
- **Grafana Tempo**
- **Datadog**
- **New Relic**
- **AWS X-Ray** (via OTEL Collector)
- **Google Cloud Trace** (via OTEL Collector)

## Quick Start with Jaeger (Local Development)

### Option 1: Docker Compose (Recommended)

Start Jaeger and Docling Pipelines API together:

```bash
# From project root
docker-compose -f docker/docker-compose.telemetry.yml up -d

# Verify services are running
docker-compose -f docker/docker-compose.telemetry.yml ps
```

Access services:
- **Jaeger UI**: http://localhost:16686
- **Docling Pipelines API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

Test telemetry:
```bash
# Make a request
curl http://localhost:8000/api/v1/operators

# View traces in Jaeger UI
open http://localhost:16686
```

Stop services:
```bash
docker-compose -f docker/docker-compose.telemetry.yml down
```

### Option 2: Jaeger Only (Docker)

If you want to run Jaeger separately:

```bash
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  -p 4318:4318 \
  jaegertracing/all-in-one:latest
```

### 2. Configure Environment Variables

Create or update your `.env` file:

```bash
# Enable telemetry
TELEMETRY_ENABLED=true

# Service identification
OTEL_SERVICE_NAME=docling-pipelines-dev
OTEL_SERVICE_VERSION=0.1.0
OTEL_DEPLOYMENT_ENVIRONMENT=development

# OTLP endpoint (Jaeger)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

### 3. Run Docling Pipelines

Run any flow normally - telemetry will be automatically enabled:

```bash
# CLI
docling-pipelines --flow-file sample_flows/quickstart/basic_ingest_extract.json

# API
docling-pipelines-api
```

### 4. View Traces

Open Jaeger UI in your browser:

```
http://localhost:16686
```

Select "docling-pipelines-dev" from the service dropdown and click "Find Traces".

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEMETRY_ENABLED` | Master switch — enables both traces and metrics | `false` |
| `OTEL_SERVICE_NAME` | Service name in traces/metrics | `docling-pipelines` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint URL | `http://localhost:4317` |
| `OTEL_SERVICE_VERSION` | Service version | `0.1.0` |
| `OTEL_DEPLOYMENT_ENVIRONMENT` | Environment name | `development` |
| `OTEL_EXPORTER_OTLP_HEADERS` | Authentication headers (e.g. `Authorization=Basic ...`) | _(none)_ |
| `OTEL_TRACES_SAMPLER_ARG` | Head-based sampling rate, 0.0–1.0 (1.0 = 100%) | `1.0` |
| `OTEL_METRIC_EXPORT_INTERVAL` | Metrics flush interval in milliseconds | `60000` |

### Deployment-Level Configuration

Telemetry is configured once at deployment level, not per-flow:

**Docker Compose:**
```yaml
services:
  docling-pipelines:
    environment:
      - TELEMETRY_ENABLED=true
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

**Kubernetes:**
```yaml
env:
  - name: TELEMETRY_ENABLED
    value: "true"
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://otel-collector:4317"
```

## What Gets Collected

### HTTP Requests (Automatic)

All API requests are automatically traced and measured:

**Spans** — attributes captured:
- `http.method`, `http.url`, `http.scheme`, `http.target`
- `http.status_code`, `transaction.id`, `error`

**Metrics** — instruments:
- `http.server.request.count` — counter, labelled by method / route / status code
- `http.server.request.duration` — histogram in milliseconds

### Operator Execution (Automatic)

All operator executions are automatically traced and measured:

**Spans** — attributes captured:
- `operator.name`, `operator.short_name`, `operator.category`
- `job.id`, `job_run.id`
- `operator.processed_docs`, `operator.failed_docs`, `operator.total_docs`

**Metrics** — instruments:
- `operator.execution.count` — counter, labelled by operator name / category / success
- `operator.execution.duration` — histogram in milliseconds
- `operator.error.count` — counter, labelled by operator name / category

### Log-Trace Correlation (Automatic)

When JSON logging is enabled (`DS_LOG_JSON=True`) and telemetry is active, every log record includes:

```json
{
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7"
}
```

Use these fields in Grafana to jump directly from a log line to its trace.

### Example Trace

```
Flow Execution
├── HTTP POST /api/v1/flows/execute
│   ├── operator.IngestSourceOperator
│   │   └── processed_docs: 10
│   ├── operator.ExtractOperator
│   │   └── processed_docs: 10
│   └── operator.EmbeddingsOperator
│       └── processed_docs: 10
```

## Production Deployment

### 1. Use OTEL Collector

For production, route traces through an OTEL Collector:

```yaml
# docker-compose.yml
services:
  otel-collector:
    image: otel/opentelemetry-collector:latest
    ports:
      - "4317:4317"  # OTLP gRPC
    volumes:
      - ./otel-collector-config.yaml:/etc/otel-collector-config.yaml
    command: ["--config=/etc/otel-collector-config.yaml"]

  docling-pipelines:
    environment:
      - TELEMETRY_ENABLED=true
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

### 2. Configure Sampling

Docling Pipelines supports head-based sampling natively — no collector required:

```bash
# Sample 10% of traces (reduces both trace volume and exporter overhead)
OTEL_TRACES_SAMPLER_ARG=0.1
```

For tail-based sampling or more advanced strategies, route through an OTEL Collector:

```yaml
# otel-collector-config.yaml
processors:
  probabilistic_sampler:
    sampling_percentage: 10
```

### 3. Security

For production deployments:

1. **Use TLS**: Configure secure OTLP endpoints
2. **Authentication**: Add authentication headers if required
3. **Network Policies**: Restrict access to telemetry endpoints

## Monitoring Backends

### Jaeger

```bash
# Local
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Production
OTEL_EXPORTER_OTLP_ENDPOINT=https://jaeger.example.com:4317
```

### Grafana Cloud (Managed Tempo)

Grafana Cloud provides managed observability with Tempo for distributed tracing.

#### 1. Get Credentials

1. Log in to [Grafana Cloud](https://grafana.com/)
2. Navigate to **Connections** → **Add new connection** → **OpenTelemetry**
3. Note your credentials:
   - **Endpoint**: `https://otlp-gateway-{region}.grafana.net/otlp`
   - **Instance ID**: Your numeric instance ID (e.g., `123456`)
   - **API Token**: Generate with "MetricsPublisher" role (starts with `glc_`)

#### 2. Encode Credentials

Grafana Cloud requires Basic authentication:

```bash
# Format: instance_id:api_token
echo -n "123456:glc_your_api_token_here" | base64
# Output: MTIzNDU2OmdsY195b3VyX2FwaV90b2tlbl9oZXJl
```

#### 3. Configure Environment

```bash
# Enable telemetry
TELEMETRY_ENABLED=true

# Service identification
OTEL_SERVICE_NAME=docling-pipelines-prod
OTEL_DEPLOYMENT_ENVIRONMENT=production

# Grafana Cloud endpoint (replace region: prod-us-east-0, prod-eu-west-0, etc.)
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-prod-us-east-0.grafana.net/otlp

# Authentication (use your base64-encoded credentials)
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic {base64_encoded_credentials}
```

#### 4. Docker Compose Example

```yaml
services:
  docling-pipelines:
    environment:
      - TELEMETRY_ENABLED=true
      - OTEL_SERVICE_NAME=docling-pipelines-prod
      - OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-prod-us-east-0.grafana.net/otlp
      - OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic MTIzNDU2OmdsY195b3VyX2FwaV90b2tlbl9oZXJl
```

#### 5. Kubernetes with Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: grafana-cloud-creds
type: Opaque
stringData:
  auth-header: "Authorization=Basic MTIzNDU2OmdsY195b3VyX2FwaV90b2tlbl9oZXJl"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: docling-pipelines
spec:
  template:
    spec:
      containers:
      - name: app
        env:
        - name: TELEMETRY_ENABLED
          value: "true"
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: "https://otlp-gateway-prod-us-east-0.grafana.net/otlp"
        - name: OTEL_EXPORTER_OTLP_HEADERS
          valueFrom:
            secretKeyRef:
              name: grafana-cloud-creds
              key: auth-header
```

#### 6. View Traces

1. Go to your Grafana Cloud instance
2. Navigate to **Explore** → Select **Tempo** data source
3. Query with TraceQL:
   ```
   { service.name="docling-pipelines-prod" }
   ```

### Self-Hosted Grafana Tempo

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://tempo.example.com:4317
```

### Datadog

```bash
# Via OTEL Collector with Datadog exporter
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

### AWS X-Ray

```bash
# Via OTEL Collector with X-Ray exporter
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

## Troubleshooting

### Traces Not Appearing

1. **Check telemetry is enabled:**
   ```bash
   echo $TELEMETRY_ENABLED
   # Should output: true
   ```

2. **Verify OTLP endpoint is reachable:**
   ```bash
   curl http://localhost:4317
   ```

3. **Check logs for initialization:**
   ```bash
   # Look for: "Telemetry initialized successfully"
   docling-pipelines --flow-file flow.json 2>&1 | grep -i telemetry
   ```

### Performance Issues

1. **Disable telemetry:**
   ```bash
   TELEMETRY_ENABLED=false
   ```

2. **Reduce trace volume with head-based sampling:**
   ```bash
   OTEL_TRACES_SAMPLER_ARG=0.1   # sample 10%
   ```

3. **Increase metrics export interval** to reduce exporter frequency:
   ```bash
   OTEL_METRIC_EXPORT_INTERVAL=120000   # flush every 2 minutes
   ```

4. **Check OTLP endpoint latency**

### Missing Dependencies

If you see warnings about missing OpenTelemetry packages:

```bash
# Reinstall with telemetry dependencies
uv pip install -e ".[telemetry]"
```

## Verification

### 1. Check Telemetry Status

```python
from docpipe.utils.infrastructure import get_telemetry_service

telemetry = get_telemetry_service()
print(f"Telemetry enabled: {telemetry.is_enabled}")
print(f"Metrics enabled:   {telemetry.metrics_enabled}")
```

### 2. Test with Sample Flow

```bash
# Run a simple flow
docling-pipelines --flow-file sample_flows/quickstart/complete_pipeline_ollama.json

# Check Jaeger UI for traces
open http://localhost:16686
```

### 3. Verify Span Attributes

In Jaeger UI, click on a trace and verify:
- HTTP spans have `http.method`, `http.url`, `http.status_code`
- Operator spans have `operator.name`, `operator.category`
- Transaction IDs are present

### 4. Verify Metrics

In Grafana, query the Prometheus/OTLP data source:
```
http_server_request_count_total
operator_execution_count_total
operator_error_count_total
```

## Best Practices

1. **Use Descriptive Service Names**: Set `OTEL_SERVICE_NAME` to identify your instance
2. **Tag Environments**: Use `OTEL_DEPLOYMENT_ENVIRONMENT` to distinguish dev/staging/prod
3. **Enable Head-Based Sampling in Production**: Set `OTEL_TRACES_SAMPLER_ARG=0.1` for 10% sampling
4. **Correlate Logs and Traces**: Enable `DS_LOG_JSON=True` to get `trace_id`/`span_id` in log records
5. **Secure Endpoints**: Use TLS and authentication for production OTLP endpoints
6. **Monitor Metrics Alongside Traces**: Use `operator.error.count` to alert on operator failures

## Additional Resources

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/)
- [OTLP Specification](https://opentelemetry.io/docs/specs/otlp/)


## Support

For issues or questions:
1. Review logs for telemetry-related messages
2. Verify OTLP endpoint connectivity
3. Ensure telemetry dependencies are installed
