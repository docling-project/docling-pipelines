# Run Docling Pipelines with Docker Compose

Run all commands from repo root.

## Prerequisites

- Docker Engine 24.0+ and Docker Compose 2.24+; the Docker daemon must be running.
- At least 6 GB of RAM available for containers.
- Internet access to build images and download the embedding model.

## Step 0: Setup Environment

Set `OPENSEARCH_PASSWORD` in each terminal before running Docker Compose commands:

```bash
export OPENSEARCH_PASSWORD='MyStrongPass@123' # pragma: allowlist secret
```

## Step 1: Verify Configuration

```bash
docker compose -f docker/docker-compose.yml config --quiet
```

## Step 2: Build Image

```bash
docker compose -f docker/docker-compose.yml build
```

or, for a GPU build, use:

```bash
# docker compose -f docker/docker-compose.yml build --build-arg COMPUTE_BACKEND=gpu
```

## Step 3: Start Application

```bash
docker compose -f docker/docker-compose.yml up -d --no-build
```

### Check application health:

```bash
docker compose -f docker/docker-compose.yml ps
curl --fail http://localhost:8080/health
```

### View API logs (optional)

In a separate terminal, run this command to follow the API logs. Press `Ctrl+C` to stop the stream.

```bash
docker compose -f docker/docker-compose.yml logs -f docpipe
```

### View BFF logs (optional)

In a separate terminal, run this command to follow BFF logs. Press `Ctrl+C` to stop the stream.

```bash
docker compose -f docker/docker-compose.yml logs -f bff
```

API docs: `http://localhost:8080/api/v1/docs`.

## Step 4: API: Run a sample flow

Pull the embedding model:

```bash
docker compose -f docker/docker-compose.yml exec ollama ollama pull nomic-embed-text
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

Start the Job Run in the same terminal using the captured Flow ID:

```bash
curl --fail-with-body -sS \
  -X POST http://localhost:8080/api/v1/job_runs \
  -H 'Content-Type: application/json' \
  -d "{\"entity\":{\"job\":{\"asset_ref\":\"${FLOW_ID:?Run the flow upload command first}\"}}}"
```

## Step 5: UI: Run sample flow

1. Open the UI: `http://localhost:8080/ui/home`.
2. Click **Start** on **Get started with sample data**. The sample flow opens in the canvas.
3. Click **Run flow** in the canvas to run it and view its progress and results.

## Stop the stack

```bash
docker compose -f docker/docker-compose.yml down
```

Named data volumes are retained. Add `-v` to remove them.
