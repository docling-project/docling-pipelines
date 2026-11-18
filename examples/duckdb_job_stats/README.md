# DuckDB Job Stats Storage Example

This example demonstrates how to use DuckDB as a storage backend for job statistics and logs in docpipe.

## Overview

DuckDB is an embedded analytical database that provides:
- **No server required** - single file database
- **Fast analytical queries** - optimized for OLAP workloads
- **SQL interface** - familiar query language
- **Easy backup** - just copy the database file

## Prerequisites

1. **Virtual environment activated**:
   ```bash
   source .venv/bin/activate
   ```

2. **PYTHONPATH set**:
   ```bash
   export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
   ```

3. **DuckDB configuration enabled** in `docling-pipelines-config.yaml`:
   ```yaml
   job_management:
     storage:
       type: duckdb
       config:
         database_path: ./data/duckdb/job_stats.duckdb
   ```

## Quick Start

1. **Uncomment DuckDB configuration** in `docling-pipelines-config.yaml` (lines 20-22):
   ```yaml
   job_management:
     storage:
       type: duckdb
       config:
         database_path: ./data/duckdb/job_stats.duckdb
   ```

2. **Run the example**:
   ```bash
   python examples/duckdb_job_stats/duckdb_job_store_example.py
   ```

## What the Example Does

1. **Creates test data** automatically in `./test_data/sample_document.txt`
2. **Loads configuration** automatically from `docling-pipelines-config.yaml`
3. **Executes a complete pipeline** using `examples/docpipe_flow_manager/sample_flow.json`:
   - Ingest documents from test_data
   - Extract text using Docling
   - Chunk content
   - Generate embeddings with Ollama
4. **Stores job statistics** in DuckDB database
5. **Queries and displays** the stored statistics

## Files

- `duckdb_job_store_example.py` - Main example script (creates test data automatically)
- `README.md` - This file

**Note:** This example uses the existing `examples/docpipe_flow_manager/sample_flow.json` flow definition and creates test data dynamically.

## Configuration

The DuckDB storage backend is configured in `docling-pipelines-config.yaml`:

```yaml
job_management:
  storage:
    type: duckdb  # Use DuckDB instead of json/postgresql
    config:
      database_path: ./data/duckdb/job_stats.duckdb  # Database file location
```

### Configuration Options

- `type`: Must be `duckdb`
- `database_path`: Path to DuckDB database file (created automatically if it doesn't exist)

## Querying Job Statistics

### Using Python

```python
import duckdb

conn = duckdb.connect('./data/duckdb/job_stats.duckdb', read_only=True)

# List all jobs
jobs = conn.execute("""
    SELECT job_run_id, status, total_docs, duration
    FROM job_stats
    ORDER BY start_time DESC
""").fetchall()

for job in jobs:
    print(f"Job: {job[0]}, Status: {job[1]}, Docs: {job[2]}, Duration: {job[3]}s")

conn.close()
```

### Using DuckDB CLI

```bash
# Open database
duckdb ./data/duckdb/job_stats.duckdb

# List all jobs
SELECT job_run_id, status, total_docs FROM job_stats;

# Get job statistics summary
SELECT status, COUNT(*) as count, AVG(duration) as avg_duration
FROM job_stats GROUP BY status;

# View node performance
SELECT node_id, name, AVG(time_taken) as avg_time
FROM node_stats GROUP BY node_id, name;
```

## Database Schema

### job_stats Table

| Column | Type | Description |
|--------|------|-------------|
| job_run_id | VARCHAR | Unique job run identifier (PRIMARY KEY) |
| job_id | VARCHAR | Job identifier |
| flow_id | VARCHAR | Flow identifier |
| status | VARCHAR | Job status (RUNNING, COMPLETED, FAILED) |
| start_time | TIMESTAMP | Job start time |
| end_time | TIMESTAMP | Job end time |
| duration | DOUBLE | Job duration in seconds |
| heartbeat_timestamp | BIGINT | Last heartbeat timestamp (epoch seconds); tracks worker liveness |
| progress_timestamp | BIGINT | Last forward-progress timestamp (epoch seconds); stale value with fresh heartbeat indicates a stalled worker |
| total_docs | INTEGER | Total documents to process |
| processed_docs | INTEGER | Documents processed |
| completed_docs | INTEGER | Documents completed successfully |
| failed_docs | INTEGER | Documents that failed |
| skipped_docs | INTEGER | Documents skipped |
| orchestrator | VARCHAR | Orchestrator type |
| metadata | VARCHAR | Additional metadata (JSON) |

### node_stats Table

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Auto-increment ID (PRIMARY KEY) |
| job_run_id | VARCHAR | Job run identifier (FOREIGN KEY) |
| node_id | VARCHAR | Node identifier |
| name | VARCHAR | Node name |
| node_status | VARCHAR | Node status |
| start_time | TIMESTAMP | Node start time |
| end_time | TIMESTAMP | Node end time |
| time_taken | DOUBLE | Time taken in seconds |
| docs_completed_count | INTEGER | Documents completed |
| docs_failed_count | INTEGER | Documents failed |
| metadata | VARCHAR | Additional metadata (JSON) |

## Comparison with Other Backends

| Feature | DuckDB | JSON | PostgreSQL |
|---------|--------|------|------------|
| Server Required | No | No | Yes |
| Query Performance | Fast | Slow | Fast |
| Concurrent Access | Limited | No | Yes |
| SQL Interface | Yes | No | Yes |
| Backup | Copy file | Copy file | pg_dump |
| Best For | Local dev/testing | Simple cases | Production |

## Troubleshooting

### Database file not found
- The database file is created automatically on first use
- Check that the `database_path` in config is correct
- Ensure the directory exists (created automatically)

### Permission errors
- Ensure you have write permissions to the database directory
- Check that no other process has the database file locked

### Import errors
- Ensure virtual environment is activated
- Verify PYTHONPATH is set correctly
- Run `uv sync --extra dev` to install dependencies

### Test data directory not found
- The example creates `./test_data/` automatically
- If you see "paths" does not exist", ensure you're running from the project root

## Next Steps

- Try modifying the flow to process more documents
- Query the database to analyze job performance
- Compare DuckDB performance with JSON backend
- Explore advanced SQL queries for analytics

## Related Documentation

- [Job Management Architecture](../../README.md)
- [DocpipeFlowManager Examples](../docpipe_flow_manager/)
- [Operator Reference](../../docs/reference/OPERATORS.md)
