# Run Docling Pipelines with Docker Compose

Run all commands from repo root.

## Table of contents

- [Prerequisites](#prerequisites)
- [Step 0: Setup Environment](#step-0-setup-environment)
- [Step 1: Verify Configuration](#step-1-verify-configuration)
- [Step 2: Build Image](#step-2-build-image)
- [Step 3: Start Application](#step-3-start-application)
- [Step 4: Sample producer and consumer](#step-4-event-streaming-run-a-sample-producer-and-consumer)
- [Step 5: Create a document-processing flow](#step-5-create-a-document-processing-flow)
- [Step 6: Create an event mapping](#step-6-create-an-event-mapping)
- [Step 7: Publish a create event](#step-7-publish-a-create-event)
- [Step 8: Find the triggered job](#step-8-find-the-triggered-job)
- [Step 9: Verify the job and indexed document](#step-9-verify-the-job-and-indexed-document)
- [Stop the stack](#stop-the-stack)

## Prerequisites

- Python 3.12 and `uv` installed on the host.
- Docker Engine 24.0+ and Docker Compose 2.24+; the Docker daemon must be running.
- At least 6 GB of RAM available for containers.
- Internet access to build images and download the embedding model.

## Step 0: Setup Environment

```bash
cp -n docker/event-streaming/.env.example docker/event-streaming/.env
```

## Step 1: Verify Configuration

```bash
docker compose --env-file docker/event-streaming/.env -f docker/event-streaming/docker-compose.yml config --quiet
```

## Step 2: Build Image

```bash
docker compose --env-file docker/event-streaming/.env -f docker/event-streaming/docker-compose.yml build
```

or, for a GPU build, use:

```bash
# docker compose --env-file docker/event-streaming/.env -f docker/event-streaming/docker-compose.yml build --build-arg COMPUTE_BACKEND=gpu
```

## Step 3: Start Application

```bash
docker compose --env-file docker/event-streaming/.env -f docker/event-streaming/docker-compose.yml up -d --no-build
```

### Check application health:

```bash
docker compose --env-file docker/event-streaming/.env -f docker/event-streaming/docker-compose.yml ps
curl --fail http://localhost:8080/health
```

### View API logs (optional)

In a separate terminal, run this command to follow the API logs. Press `Ctrl+C` to stop the stream.

```bash
docker compose --env-file docker/event-streaming/.env -f docker/event-streaming/docker-compose.yml logs -f docpipe
```

## Step 4: Event Streaming: Run a sample producer and consumer

Install the Event Streaming dependencies:

```bash
uv sync --extra dev --extra event-streaming
```

### Confirm the topic was created

The stack creates the input topic at startup. Check the initialization logs before sending an event:

```bash
docker compose --env-file docker/event-streaming/.env -f docker/event-streaming/docker-compose.yml logs kafka-init
```

### Confirm the schema is ready

The stack registers the event schema at startup. Check the registration logs before sending an event:

```bash
docker compose --env-file docker/event-streaming/.env -f docker/event-streaming/docker-compose.yml logs register-schema
```

### Start listening for events

Open a new terminal and leave the consumer running. It will print each event as it arrives:

```bash
KAFKA_GROUP_ID=docpipe-sample-consumer uv run --env-file docker/event-streaming/.env \
  python docker/event-streaming/helpers/kafka_consumer.py
```

### Send a sample event

Open a new terminal, publish a sample `create` event. You should see it appear in the consumer output:

```bash
uv run --env-file docker/event-streaming/.env python docker/event-streaming/helpers/kafka_producer.py \
  --message '{"event_id":"00000000-0000-0000-0000-000000000000","event_timestamp":"2026-01-01T00:00:00Z","routing_key":"example","operation":"create","file_reference":"/documents/example.txt"}'
```

## Step 5: Create a document-processing flow

Run Steps 5–9 in the same terminal. Keep the consumer from Step 4 running.

Pull the embedding model:

```bash
docker compose --env-file docker/event-streaming/.env -f docker/event-streaming/docker-compose.yml \
  exec ollama ollama pull nomic-embed-text
```

Upload the sample flow and use `python3` to capture and print the returned Flow ID:

```bash
FLOW_ID=$(curl --fail-with-body -sS \
  -X POST http://localhost:8080/api/v1/flows \
  -H 'Content-Type: application/json' \
  --data-binary @sample_flows/quickstart/docker_e2e_ollama_opensearch.json \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["flow_id"])')
printf 'FLOW_ID=%s\n' "$FLOW_ID"
```

## Step 6: Create an event mapping

Create the mapping using the captured Flow ID:

```bash
curl --fail-with-body -sS \
  -X POST http://localhost:8080/api/v1/event_mappings \
  -H 'Content-Type: application/json' \
  -d "{\"key\":\"invoices-created\",\"flow_id\":\"${FLOW_ID:?Run the flow upload command first}\"}"
```

Verify the mapping:

```bash
curl --fail-with-body -sS http://localhost:8080/api/v1/event_mappings/invoices-created
```

## Step 7: Publish a create event

Publish an event for the mounted sample invoice:

```bash
EVENT_ID=$(python3 -c 'from uuid import uuid4; print(uuid4())')
EVENT_TIMESTAMP=$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')

uv run --env-file docker/event-streaming/.env python docker/event-streaming/helpers/kafka_producer.py \
  --message "{\"event_id\":\"$EVENT_ID\",\"event_timestamp\":\"$EVENT_TIMESTAMP\",\"routing_key\":\"invoices-created\",\"operation\":\"create\",\"file_reference\":\"/documents/TR-INV_001_3_2.1.pdf\"}"
```

Confirm the event appears in the consumer output and that the flow completes successfully in the API logs.

## Step 8: Find the triggered job

Find `Event job run submitted` for `invoices-created` and copy its `job_run_id`:

```bash
docker compose --env-file docker/event-streaming/.env -f docker/event-streaming/docker-compose.yml \
  logs --tail=100 docpipe
```

Set the returned Job Run ID in the same terminal:

```bash
JOB_RUN_ID="<job_run_id from the log>"
```

## Step 9: Verify the job and indexed document

Repeat until `job_stats.status` is `Completed` and `failed_docs` is `0`:

```bash
curl --fail-with-body -sS \
  "http://localhost:8080/api/v1/job_runs/${JOB_RUN_ID:?Set JOB_RUN_ID first}?include_logs=true" \
  | python3 -m json.tool
```

Enter `OPENSEARCH_PASSWORD` from `docker/event-streaming/.env` when prompted. Expect `count` greater than `0`:

```bash
curl --fail-with-body -sS -u admin \
  -X POST http://localhost:9200/docker-e2e-documents/_refresh

curl --fail-with-body -sS -u admin http://localhost:9200/docker-e2e-documents/_count
```

## Stop the stack

```bash
docker compose --env-file docker/event-streaming/.env -f docker/event-streaming/docker-compose.yml down
```

Named data volumes are retained. Add `-v` to remove them.
