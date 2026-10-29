# Design

## Context

`DocumentSet` has a free-form `metadata` dict persisted by the metadata repository (DuckDB or Postgres). The orchestrator has one observer slot (`AbstractOrchestrator._observer`) filled by `lineage_factory.create_lineage_observer()`; `_notify_observer` swallows errors unless `DOCPIPE_LINEAGE_STRICT=true`. `FlowCompleteContext` carries `flow_def` but not per-node metadata; `NodeCompleteContext` carries `operator_type`, `node_name`, and `metadata`. `DocumentSetOperator` puts the document set id into its node metadata.

## Goals / Non-Goals

Goals: a credential-free, queryable description of derived stores per document set; automatic recording; a read-only REST view; a port for consumers.
Non-goals: see proposal.

## DDD layers

```
core/assets/derivatives/
  domain/
    models/derivative.py            DocumentSetDerivative, VectorStoreDerivative, EntityTableDerivative,
                                    EmbeddingSpec, CorrelationDetail   (dataclasses, no framework imports)
    ports/derivative_resolver.py    DerivativeResolverPort (ABC)
    ports/derivative_store.py       DerivativeStorePort: load(document_set_id), save(document_set_id, derivative)
  application/
    services/derivative_builder.py  DerivativeBuilder (pure: flow_def + node metadata -> derivatives)
    services/derivative_recorder.py DerivativeRecorder (ExecutionLifecycleObserverPort impl)
    services/derivative_query_service.py  DerivativeQueryService (implements DerivativeResolverPort)
  adapters/
    document_set_metadata_store.py  DerivativeStorePort over DocumentSetService (merge into metadata["derivatives"])
core/orchestration/composite_observer.py   CompositeExecutionObserver
api/dto/derivative_dto.py, api/dto/derivative_mapper.py, api/routes/document_libraries.py (new route)
```

Rules respected: application never imports adapters; the factory in `dependencies.py` wires the adapter; routes return DTOs only; pure helpers are `@staticmethod`; multi-parameter functions are keyword-only.

## Decisions

### D1. Persist in `DocumentSet.metadata["derivatives"]` (merge)
No migration, works for DuckDB and Postgres repositories, and the document set already is the unit that a flow produces. `update_document_set` replaces `metadata`, so the store adapter reads, merges the `derivatives` key only, and writes the whole dict back. A concurrent metadata edit between read and write could lose that edit; the window is small and recording runs once per flow. Accepted risk, noted in tasks as a test.
Alternative: a dedicated `derivatives` table. Rejected for the first release: new schema, new repository ports, no query need beyond "by document set".

### D2. Hook: composite observer plus `on_node_complete` capture
Add `CompositeExecutionObserver(ExecutionLifecycleObserverPort)` that fans out each call in order and isolates exceptions (re-raising the first lineage error only when strict, after all observers ran). `OrchestratorFactory` builds it from enabled observers. `DerivativeRecorder` implements the port: `on_node_complete` stores `(node_name -> metadata)` for `document_set` nodes in a per-`job_run_id` dictionary; `on_flow_complete` builds and saves, then clears; `on_flow_fail` and `on_flow_abort` clear. All other methods are no-ops.
Alternative considered: call the recorder from `FlowExecutionEventHandler.after_flow_execution_complete`. Rejected because it couples the event handler to asset services and is not substitutable in tests.
Micro-batching: the same `document_set` node runs once per batch; the recorder keys by document set id and records once.
Prefect orchestrator: uses the same abstract base and factory, so it records too; verified by a task.

### D3. Builder works from the flow definition
`DerivativeBuilder` receives `flow_def` (as stored, with `depends_on`), computes ancestors of each `document_set` node by graph traversal, and for each ancestor reads `config` through an allowlist. The effective feature mappings come from `compute_default_feature_mappings` when the node has none. The nearest `embeddings` ancestor is the closest by edge distance along the path to the `vectordb` node; ties are broken by node order in the flow.
`id_field`: search the effective mappings for the target field fed by the ingest `id` source column; if the mapping source is `id`, `id_field` is its target name.
Config values containing `${`, `vault://`, or a URL userinfo section are dropped by an explicit filter in addition to the allowlist (defense in depth).

### D4. Entity table naming
Table name = `table_prefix` (default `entity_`) plus entity key, mirroring `EntityStoreOperator`. The recorder does not read the database. If the operator's naming changes, a unit test that builds names through the operator's own helper fails. Task: expose that helper as a `@staticmethod` if it is not already (no behavior change).

### D5. Correlation
`correlation_details` is computed at read time from the stored sides, not stored. Rule `id-prefix` is documented in `derivatives-api`. The anchored-regex join itself lives in `add-retrieval-service`.

### D6. Pagination bookmark
Bookmark = urlsafe base64 of JSON `{"o": <offset>, "v": 1}`. Decoding failure, wrong version, negative or non-integer offset gives 400 `derivative_invalid_bookmark`. Offset beyond the end returns an empty page with `next` null. Not signed: it contains no secret and is only a position.

### D7. Error codes
Add to `ErrorCode`: `DERIVATIVE_INVALID_BOOKMARK`, `DERIVATIVE_RECORD_FAILED`. Add `DerivativeInvalidBookmarkException(DocpipeException, 400)`. Not found cases reuse `DOCUMENT_LIBRARY_NOT_FOUND` / `DOCUMENT_SET_NOT_FOUND`.

### D8. DTO redaction
The domain object keeps `database_path`; the mapper builds DTOs from an explicit field list so a new domain field is hidden by default.

## Risks and trade-offs

| Risk | Mitigation |
|---|---|
| Secrets leak into metadata | Allowlist plus pattern filter plus a test that fuzzes `provider_config` with secret-like keys |
| Lost update on `metadata` | Read-merge-write in one adapter call; test for key preservation; documented |
| Recorder breaks flow completion | Isolated in composite observer; own try/except; warning only |
| Mappings omit `id` so retrieval cannot correlate | `correlatable` flag and warning; documented in OPERATORS docs |
| In-memory entity DB cannot be queried | `retrievable: false` and warning |
| Observer receives events per batch | Dedup by document set id |
| Stale derivative after a store is dropped or re-created | Replace-by-key on re-run; no automatic cleanup (non-goal); retrieval treats an unreachable store as a partial result |
| Document set deleted | Metadata goes with it; no orphan |

## Migration

None. Existing sets have no `derivatives` key and read as empty.

## Open questions

None blocking. Assumptions recorded: D1 storage location, D2 hook, D6 bookmark shape.
