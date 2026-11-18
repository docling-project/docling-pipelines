# EdedupOperator

Removes repeated normalized content. Short name: `ededup`; category: Quality.

## Overview

Use this operator after extraction to remove repeated content before downstream processing.
Each batch reduces its input to one candidate per content hash. A shared registry then admits only one candidate
per job, flow node, run, and hash, even when different batches execute in separate processes.

A sequential flow has one ededup node. When extraction is followed by branching, each branch's ededup node
admits content independently. Workers executing the same node must use its stable flow node ID.
Merging branch outputs does not automatically remove duplicates between branches. Later runs can process the same content again.

## Key Features

- Atomic bulk PostgreSQL admission across pods, with no per-document search requests.
- Filesystem support for instances and processes sharing a local storage directory.
- Input order and schema preservation, with row-level skipped-document reporting.
- Independent state for overlapping runs and separate ededup nodes.
- Existing content normalization preserved; case, spaces, newlines and ASCII punctuation are ignored.

## Operator Configuration

```json
{
  "name": "deduplicate",
  "type": "ededup",
  "depends_on": ["extract"],
  "config": {}
}
```

The operator resolves its store through its dedicated ededup factory. It does not initialize incremental source tracking.
Configure all worker pods with the same PostgreSQL database and schema.

## Parameters

See the [operator parameter reference](../../reference/OPERATORS.md#ededupoperator) for supported columns and context rules.

## Output Columns

The operator filters rows without adding or modifying columns. Skipped rows retain source IDs, names and paths in metadata.

## Examples

### PostgreSQL configuration

Set this section in `docling-pipelines-config.yaml` (or the file selected by `DOCPIPE_CONFIG_PATH`):

```yaml
ededup:
  storage:
    type: postgresql
    config:
      postgres:
        schema: ededup_registry
```

Supply connection settings using `DOCPIPE_POSTGRES_HOST`, `DOCPIPE_POSTGRES_PORT`, `DOCPIPE_POSTGRES_DB`,
`DOCPIPE_POSTGRES_USER`, and `DOCPIPE_POSTGRES_PASSWORD`. The database role needs permission to create the schema/tables.
The store creates `hashes` with a composite primary key. Candidates are inserted in bounded bulk statements
within one transaction, and only newly inserted hashes pass through after commit. A failure rolls back all chunks.
Existing node-scoped records remain valid when the store is reopened.

### Independent storage configuration

Storage selection uses `ededup.storage`, then `global_storage`, then the filesystem default. Shared PostgreSQL
connection environment variables remain supported. Incremental service-specific settings and
`DOCPIPE_INCREMENTAL_BASE_DIR` do not configure ededup. The PostgreSQL adapter creates only its admission table.

If a previous setup used `incremental_metadata.storage` for ededup, copy its backend and connection/schema settings into
`ededup.storage`. For filesystem storage, set `ededup.storage.config.base_dir` to the previous registry's base directory.
The default PostgreSQL location is `ededup_registry.hashes`. Filesystem registries use
`<base_dir>/ededup_registry/hashes_<scope_hash>.parquet`, with matching `hashes_<scope_hash>.lock` files.
The scope hash is SHA-256 of the JSON-encoded `[job_id, node_id, job_run_id]`.
Existing data under the previous `dedup_registry` namespace and legacy `ededup_hashes` tables/folders are not automatically migrated or read. To keep using PostgreSQL data from the previous default, set the schema to `dedup_registry`. For filesystem storage, move the previous registry directory into the new `ededup_registry` directory under the same base directory.

### Filesystem and standalone use

The default ededup backend is filesystem. All workers must share the same storage directory for shared
admission; separate pod-local directories do not coordinate. File locking and atomic replacement preserve independent
job, node, and run records. Without job/run context, standalone operator instances keep only their own in-memory history.

### Rename and later runs

If `test.txt` becomes `test2.txt` with unchanged content, a new run can admit it independently in each branch and record
the new document ID. In the same run and node, an already admitted hash is skipped without replacing its original ID.
A different branch's node can still accept that hash if it has not seen it. These rules apply to documents reaching deduplication.
By default a newly admitted document is processed normally.
This operator does not detect renames, update downstream filenames, or reuse existing chunks and embeddings.

See the [branching pipeline sample](../../../sample_flows/advanced/quality_branching_merge_pipeline.json).

## Troubleshooting

- Missing content or document hash/ID column: check upstream extraction and the configured column names.
- PostgreSQL unavailable: registration fails the operator; it does not silently accept or discard documents.
- Unexpected near-identical matches: normalization intentionally ignores case, spaces, newlines and ASCII punctuation.
- Failed batch after admission: its hashes remain registered for that node and run. A same-node retry skips them; a new run can admit them again. This is not a successful-output guarantee.
- Growing registry: records are retained across runs and source deletion. Apply retention only to runs whose workers
  have stopped; deleting an active run's records can allow duplicates.
- Registry cleanup: delete records only for completed runs after their workers have stopped. For PostgreSQL, inspect and
  remove one scope with its complete job, node, and run key:

  ```sql
  SELECT count(*)
  FROM ededup_registry.hashes
  WHERE job_id = 'JOB_ID' AND node_id = 'NODE_ID' AND job_run_id = 'JOB_RUN_ID';

  DELETE FROM ededup_registry.hashes
  WHERE job_id = 'JOB_ID' AND node_id = 'NODE_ID' AND job_run_id = 'JOB_RUN_ID';
  ```

  Replace the schema if configured differently. For filesystem storage, the same scope is stored in one file named from
  `sha256(json.dumps([job_id, node_id, job_run_id]).encode()).hexdigest()`. After workers stop, compute the filename and
  remove that `.parquet` file and its matching `.lock` file from `<base_dir>/ededup_registry/`:

  ```python
  import hashlib
  import json
  from pathlib import Path

  job_id, node_id, job_run_id = "JOB_ID", "NODE_ID", "JOB_RUN_ID"
  base_dir = Path("./data")  # Use ededup.storage.config.base_dir if configured.
  scope = hashlib.sha256(json.dumps([job_id, node_id, job_run_id]).encode()).hexdigest()
  registry = base_dir / "ededup_registry"
  (registry / f"hashes_{scope}.parquet").unlink(missing_ok=True)
  (registry / f"hashes_{scope}.lock").unlink(missing_ok=True)
  ```

  Verify the job, node, run, schema, and base directory before deleting. Removing a scope permits its content to be
  admitted again if that same run is retried.
- Custom ededup backends: implement `EdedupStore` and register the adapter with `EdedupStoreFactory.register`.
