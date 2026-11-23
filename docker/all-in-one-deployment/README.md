# Docling Pipelines All-in-One Docker Compose Setup

This directory contains a simplified Docker Compose configuration for running Docling Pipelines with all required services in a single deployment.

> **⚠️ Beta notice:** This deployment includes the Docling Pipelines web UI, which is **experimental and not yet production-ready**. The UI may change significantly between releases. For production workloads, use the CLI, Python API, or REST API directly.

## Quick Start

### Prerequisites
- Docker Engine 20.10+
- Docker Compose v2.0+
- At least 6GB RAM available for containers

### Basic Usage

1. **Setup directory permissions (first time only):**
   ```bash
   cd docker/all-in-one-deployment
   ```

2. **Start all services:**
   ```bash
   docker-compose up -d
   ```

3. **View logs:**
   ```bash
   docker-compose logs -f
   ```

4. **Stop all services:**
   ```bash
   docker-compose down
   ```

5. **Stop and remove volumes (clean slate):**
   ```bash
   docker-compose down -v
   ```

## Services

The default `docker-compose.yml` includes:

| Service | Port | Description |
|---------|------|-------------|
| **docpipe** | 8080 | Main Docling Pipelines application API |
| **bff** | 3001 (internal) | Backend-For-Frontend proxy service |
| **postgres** | 5432 | PostgreSQL database |
| **ollama** | 11434 | Ollama LLM service |
| **opensearch** | 9200, 9600 | OpenSearch vector database |

## Configuration

### Configuration File (`docling-pipelines-config.yaml`)

The all-in-one deployment mounts [`docling-pipelines-config.yaml`](./docling-pipelines-config.yaml) into the `docpipe-app` container at `/opt/app-root/src/config/docling-pipelines-config.yaml` (configured via `DOCPIPE_CONFIG_PATH`).

This configuration routes all backend services and asset repositories to writable paths under `./data`:
- **Flows Repository (`assets_management.flow_repository`)**: Local filesystem at `/opt/app-root/src/data/flows`
- **Projects Repository (`projects_management.project_repository`)**: Local filesystem at `/opt/app-root/src/data/projects`
- **Document Sets & Libraries (`documentset_repository`, `documentlibrary_repository`)**: DuckDB at `/opt/app-root/src/data/duckdb/document_sets.duckdb`
- **Job Management Storage (`job_management.storage`)**: Filesystem at `/opt/app-root/src/data/job_stats_store_data`
- **Snapshots & Metadata (`flow_definition_snapshot`, `incremental_metadata`)**: Filesystem at `/opt/app-root/src/data`

### Environment Variables

Copy the example environment file and customize:

```bash
cp .env.example .env
# Edit .env with your preferred values
```

Key variables configured in `.env` / `docker-compose.yml`:
- `POSTGRES_PASSWORD` - PostgreSQL password (default: docpipe_password)
- `OPENSEARCH_PASSWORD` - OpenSearch admin password (default: MyStrongPass123!)
- `OPENSEARCH_JAVA_OPTS` - OpenSearch JVM memory (default: -Xms1g -Xmx1g)
- `DOCPIPE_PORT` - Docling Pipelines API port (default: 8080)
- `BFF_URL` - Internal Backend-For-Frontend URL (`http://bff:3001`)
- `DOCPIPE_CONFIG_PATH` - Path to configuration file (`/opt/app-root/src/config/docling-pipelines-config.yaml`)
- `FLOW_REPOSITORY_BASE_DIR` - Directory for flow definitions (`/opt/app-root/src/data/flows`)
- `PROJECT_REPOSITORY_BASE_DIR` - Directory for project definitions (`/opt/app-root/src/data/projects`)

### Ollama Models

The Ollama service automatically pulls these models on first startup:
- `llama3.2` - LLM for text generation
- `nomic-embed-text` - Embeddings model

**Note:** Initial startup takes 5-10 minutes while models download.

## Health Checks

Check service health:

```bash
# All services
docker-compose ps

# Docling Pipelines API
curl http://localhost:8080/health

# OpenSearch
curl -u admin:MyStrongPass123! http://localhost:9200/_cluster/health

# Ollama
curl http://localhost:11434/api/tags
```

## Data Persistence

Data is persisted in Docker volumes:
- `postgres-data` - PostgreSQL database
- `ollama-data` - Ollama models (~4GB)
- `opensearch-data` - OpenSearch indices

Local directories mounted from the host (owned by UID 1000):
- `./data` - Docling Pipelines application data:
  - `./data/flows` - Persisted flow definitions (previously written to ephemeral `~/Documents/pipeline/assets`)
  - `./data/projects` - Persisted project definitions (previously written to ephemeral `~/Documents/pipeline/projects`)
  - `./data/duckdb` - Embedded DuckDB databases for document sets and document libraries
  - `./data/job_stats_store_data` - Job execution statistics and history
- `./logs` - Application logs

> **Note on Behavior Change:** Flows and projects now persist in `./data/flows` and `./data/projects` on the host bind mount. In earlier configurations, these defaulted to `~/Documents/pipeline/...` in the container's unmounted home directory and were lost when containers were recreated. Data previously saved inside the unmounted container home directory is not carried over automatically.


## Permission Issues

If you encounter permission errors with `/data` or `/logs`:

1. **Run the setup script:**
   ```bash
   sudo chown -R 1000:1000 ./data ./logs
   sudo chmod -R 755 ./data ./logs
   ```

2. **Verify ownership:**
   ```bash
   ls -la ./data ./logs
   ```

## Troubleshooting

### Ollama models not loading
```bash
# Check Ollama logs
docker-compose logs ollama

# Manually pull models
docker-compose exec ollama ollama pull llama3.2
docker-compose exec ollama ollama pull nomic-embed-text
```

### OpenSearch memory errors
Increase heap size in `.env`:
```
OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g
```

### Port conflicts
Change ports in `.env`:
```
DOCPIPE_PORT=8081
POSTGRES_PORT=5433
```

### Reset everything
```bash
docker-compose down -v
docker-compose up -d
```

## Production Considerations

For production deployments:

1. **Use strong passwords** - Change all default passwords in `.env`
2. **Enable SSL** - Configure OpenSearch with proper certificates
3. **Pin versions** - Replace `:latest` tags with specific versions
4. **Resource limits** - Add memory/CPU limits to services
5. **Backup volumes** - Implement backup strategy for data volumes
6. **Use secrets** - Consider Docker secrets or external secret management

## Alternative Configurations

- `../docker-compose.distributed.yml` - Full distributed setup with Prefect, MinIO, and multiple workers
- `../docker-compose.opensearch.yml` - OpenSearch only with dashboards

## Support

For issues or questions:
- Check logs: `docker-compose logs -f [service-name]`
- Review documentation in `/docs`
- Open an issue on GitHub
