# Event streaming guide

Event mapping is part of event streaming. It connects an event's routing key to a saved processing flow.

## Table of Contents

- [Event mapping](#event-mapping)
    - [What it does](#what-it-does)
    - [Setup](#setup)
    - [Create a mapping](#create-a-mapping)
    - [Get a mapping](#get-a-mapping)
    - [List mappings](#list-mappings)
    - [Update a mapping](#update-a-mapping)
    - [Delete a mapping](#delete-a-mapping)
- [Kafka event processing](#kafka-event-processing)
    - [Example: an invoice is created](#example-an-invoice-is-created)
    - [What the event triggers](#what-the-event-triggers)
    - [Update events](#update-events)
    - [Processing failures](#processing-failures)

## Event mapping

### What it does

An event mapping stores two fields:

| Field | Purpose |
| --- | --- |
| `key` | Routing key used to identify the target flow. |
| `flow_id` | UUID of an existing, saved flow. |

The event payload uses `routing_key`; the mapping API uses `key` for the same value. A mapping with `key: "invoices"`
associates events whose `routing_key` is `"invoices"` with the saved flow identified by `flow_id`.

Keys contain ASCII letters, digits, hyphens, and underscores. Lookups are case-insensitive, and responses preserve the
key's original letter casing.

### Setup

1. Follow the [Docker Compose setup](../deployment/DOCKER_COMPOSE.md) to start the application.
   The API runs at `http://localhost:8080`.
2. Create and save a flow through `POST /api/v1/flows`. Copy the `flow_id` from the response.

### Create a mapping

`POST /api/v1/event_mappings` registers a routing key with a saved flow.
Replace the example `flow_id` with the UUID returned when you saved your flow.

#### Command

```bash
curl --include --fail-with-body --request POST http://localhost:8080/api/v1/event_mappings \
  --header 'Content-Type: application/json' \
  --data '{"key":"invoices","flow_id":"550e8400-e29b-41d4-a716-446655440000"}'
```

#### Success

HTTP 201 with the created mapping:

```json
{
  "key": "invoices",
  "flow_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### Failure

| HTTP status | Cause |
| --- | --- |
| 400 | Malformed JSON, missing `key` or `flow_id`, invalid key or flow UUID, or unexpected request fields. |
| 404 | The UUID in `flow_id` does not identify a saved flow. |
| 409 | The key is already registered, including a different case variant such as `INVOICES`. |
| 413 | The request body exceeds 5 MiB. |
| 500 | An internal error occurs while checking the flow or storing the mapping. |

### Get a mapping

`GET /api/v1/event_mappings/{key}` returns the flow associated with one routing key.

#### Command

```bash
curl --include --fail-with-body http://localhost:8080/api/v1/event_mappings/invoices
```

#### Success

HTTP 200 with the registered mapping:

```json
{
  "key": "invoices",
  "flow_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### Failure

| HTTP status | Cause |
| --- | --- |
| 400 | The `key` in the URL contains unsupported characters, such as `invoices.pdf`. |
| 404 | No mapping exists for the key. |
| 500 | An internal error occurs while reading the mapping. |

### List mappings

`GET /api/v1/event_mappings` returns all registered mappings.

#### Command

```bash
curl --include --fail-with-body http://localhost:8080/api/v1/event_mappings
```

#### Success

HTTP 200 with an array of mappings:

```json
[
  {
    "key": "invoices",
    "flow_id": "550e8400-e29b-41d4-a716-446655440000"
  }
]
```

When no mappings exist, the API returns HTTP 200 with `[]`.

#### Failure

| HTTP status | Cause |
| --- | --- |
| 500 | An internal error occurs while loading the mappings. |

### Update a mapping

`PUT /api/v1/event_mappings/{key}` assigns a different saved flow to an existing routing key.
Replace the example UUID with the new flow's `flow_id`. The request body contains only `flow_id`; the key is in the URL.

#### Command

```bash
curl --include --fail-with-body --request PUT http://localhost:8080/api/v1/event_mappings/invoices \
  --header 'Content-Type: application/json' \
  --data '{"flow_id":"550e8400-e29b-41d4-a716-446655440001"}'
```

#### Success

HTTP 200 with the updated mapping:

```json
{
  "key": "invoices",
  "flow_id": "550e8400-e29b-41d4-a716-446655440001"
}
```

#### Failure

| HTTP status | Cause |
| --- | --- |
| 400 | Malformed JSON, invalid URL key, missing or invalid flow UUID, or unexpected request fields. |
| 404 | No mapping exists for the key. |
| 404 | The new `flow_id` does not identify a saved flow. |
| 413 | The request body exceeds 5 MiB. |
| 500 | An internal error occurs while checking the flow or updating the mapping. |

### Delete a mapping

`DELETE /api/v1/event_mappings/{key}` removes the mapping for a routing key.

#### Command

```bash
curl --include --fail-with-body --request DELETE http://localhost:8080/api/v1/event_mappings/invoices
```

#### Success

HTTP 204 with no response body. The mapping is removed; the saved flow is retained.

#### Failure

| HTTP status | Cause |
| --- | --- |
| 400 | The `key` in the URL contains unsupported characters, such as `invoices.pdf`. |
| 404 | No mapping exists for the key, including when it has already been deleted. |
| 500 | An internal error occurs while reading or deleting the mapping. |

## Kafka event processing

The Kafka listener connects incoming file events to the saved flows registered through event mappings. Each event
identifies a file and a routing key; the mapping determines which flow processes that file.

The [event streaming README](../../docker/event-streaming/README.md) contains the complete setup and commands for
running the sample flow, publishing events, and verifying the results.

### Example: an invoice is created

Assume the `invoices` mapping above points to a saved copy of the
[`docker-e2e-documents` sample flow](../../sample_flows/quickstart/docker_e2e_ollama_opensearch.json), with the example
`flow_id` of `550e8400-e29b-41d4-a716-446655440000`.

When a new invoice becomes available, an upstream producer publishes this event to Kafka:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440002",
  "event_timestamp": "2026-10-12T12:00:00Z",
  "routing_key": "invoices",
  "operation": "create",
  "file_reference": "/documents/TR-INV_001_3_2.1.pdf"
}
```

| Field | Meaning in this example |
| --- | --- |
| `event_id` | UUID identifying this invoice event. |
| `event_timestamp` | RFC 3339 timestamp indicating when the event occurred. |
| `routing_key` | `invoices` selects the registered flow; lookup is case-insensitive. |
| `operation` | `create` indicates that the invoice is newly available. |
| `file_reference` | Path to the invoice PDF accessible to the flow's filesystem ingest operator. |

All five fields are required, and additional fields are rejected. The listener validates the event against the
[event schema](../../docker/event-streaming/schemas/event_schema.json).

### What the event triggers

The listener resolves `invoices` to `550e8400-e29b-41d4-a716-446655440000` and submits that saved flow through the
job-run API. The resulting asynchronous job runs the `docker-e2e-documents` flow for the referenced invoice:

| Operator | Result |
| --- | --- |
| `ingest_source` | Reads `/documents/TR-INV_001_3_2.1.pdf`, replacing the configured input paths with this single file. |
| `extract_operator` | Extracts the invoice text using Docling. |
| `chunker` | Splits the extracted text into chunks. |
| `embeddings` | Generates embeddings for the chunks using Ollama's `nomic-embed-text` model. |
| `vectordb` | Stores the chunks and their embeddings in the OpenSearch `docker-e2e-documents` index. |

The event's routing key determines the flow. A different key mapped to another saved flow runs that flow's operators.
The `operation` value records the type of file event; it does not select a separate flow.

The event identifier, timestamp, routing key, and operation are attached to the job as metadata. The submission log
includes the resulting `job_run_id`, allowing the event to be traced to its processing run. Successful submission
means the job was accepted; completion depends on the flow's operators finishing successfully.

### Update events

An event with `operation: "update"` and the same `routing_key` runs the same saved flow against the current contents
of `file_reference`. Event ingestion forces reprocessing even when the file has previously been ingested.
The flow's include and exclude filters still apply, and downstream storage behavior follows the saved flow's
configuration.

File events currently support the filesystem, `box_driver` and `dropbox` providers. For the filesystem provider,
the referenced path must be a readable regular file in the environment where the flow runs; for the Docker sample,
`/documents` is the mounted invoice directory. For `box_driver`, `file_reference` is the Box file ID (for example
`"702199884861"`). For `dropbox`, `file_reference` is a Dropbox path (for example `/Reports/q1.pdf`) or file id
(for example `id:abc123`). In both cases the flow's own `provider_config` still supplies the credentials, which are
never read from the event.

### Processing failures

Invalid events, missing mappings, and job submission failures are logged. The listener commits the Kafka offset
after each dispatch attempt, including failed attempts, so these failures are not automatically retried.

Offsets are committed after job submission, before the flow completes. A later ingestion or operator failure is
reported on the job run and does not cause Kafka redelivery. An offset commit failure can cause an event to be
delivered again after a restart or rebalance.
