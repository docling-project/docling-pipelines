## Context

`DocumentSet` already carries a `data_card` field. It is a flat dataclass (`flow_id`, `flow_name`, `job_id`,
`job_run_id`, `operators`, `lineage_metadata`), serialized by `DocumentSet.to_dict()` and persisted for free by every
asset repository (DuckDB, Postgres, local). Nothing writes it and no route returns it.

The `document_set` operator runs at the end of a flow. At that point it holds:

- the operator config, which already contains `job_id`, `job_run_id`, the whole `global_config`, and
  `flow_definition` (the compiled DAG: nodes with `id`, `name`, `operator`, `config`, `input_edges`);
- the stored `pa.Table`, which includes `embeddings` and `lang_name` columns when upstream operators produced them;
- access to `JobStatsService` through `get_default_factory().create_job_stats_service()` (as `document_classifier`
  already does) for the start time and document counters of the run.

The enterprise product models the same record as `DocumentSetDatacard` with `flows[] -> jobs[] -> runs[] -> operators[]`.
OSS adopts the field names and drops everything that depends on a catalog (resource keys, container IDs, asset
relationships).

## Goals / Non-Goals

**Goals**

- Every successful `document_set` write leaves a provenance entry in the card, with no operator parameter and no change
  to the table contract.
- The card loads and re-serializes enterprise-shaped JSON without losing documented fields.
- No secret, host, or credential can reach the card, by construction (allowlist, not denylist).
- A recording problem never fails a pipeline.
- Descriptive fields can be curated over REST without being clobbered by later runs.

**Non-Goals**

See the proposal: no enterprise change, no CAMS concepts, no derivatives view, no byte sizes, no cross-process
locking, no opt-out parameter.

## Decisions

### D1. Nested dataclasses in the domain layer, lenient `from_dict`

`domain/models/data_card.py` is rewritten with plain dataclasses, one per level: `DataCard`, `DataCardCurator`,
`DataCardFlow`, `DataCardFlowDetails`, `DataCardJob`, `DataCardDocuments`, `DataCardRun`, `DataCardOperator`,
`DataCardSource`, `DataCardEmbedding`, `DataCardChunkDetails`, `DataCardDerivativeStore`. Each has `to_dict()` and a
`from_dict(*, data)` classmethod.

- `from_dict` reads only known keys, ignores the rest, and tolerates missing keys and wrong container types (a
  non-list `flows` becomes an empty list). The former flat keys therefore load as an empty card.
- `to_dict()` emits only documented keys. Null values are emitted so the stored shape is stable.
- The domain layer stays free of Pydantic and framework imports, matching `DocumentSet`.

**Alternative rejected: reuse the enterprise Pydantic model.** It lives in a private repository, pulls CAMS-shaped
fields (`resource_key`, `container_id`) and would make OSS depend on enterprise releases.

### D2. Field naming mirrors enterprise; extra enterprise fields are ignored

Field names follow the enterprise schema (`purpose`, `summary`, `curator`, `language`, `collection_criteria`,
`propagate_source_acls`, `flows`). Enterprise-only fields such as `resource_key`, `container_id`, `container_type`,
`source_asset_id`, `vector_params`, `feature_mappings`, `schema_definition`, `entities`, and `link_names` are not modelled.
A card that carries them loads, and the unmodelled keys are dropped on re-serialization. The "round trip" requirement
therefore speaks of *documented* fields, and a contract fixture pins exactly which fields those are.

`FlowItem.type` for OSS-written entries is `docpipe_flow`. Enterprise values (`ibm_udp_flow`,
`ibm_unstructured_data_curation`) are preserved when loaded.

### D3. Application service owns the read-modify-write

`DataCardService` lives in `core/assets/document_sets/application/services/data_card_service.py`. It depends on the
`AssetRepository[DocumentSet]` port only.

```python
class DataCardService:
    def __init__(self, *, repository: AssetRepository[DocumentSet]) -> None: ...
    def get_card(self, *, document_set_id: str) -> DataCard
    def record_run(self, *, document_set_id: str, run: DataCardRunRecord) -> DataCard
    def update_descriptive_fields(self, *, document_set_id: str, updates: dict[str, Any]) -> DataCard
```

`DataCardRunRecord` is a small value object carrying `flow_id`, `flow_name`, `job_id`, the built
`DataCardRun`, the `DataCardDocuments`, and the derived `language` and `propagate_source_acls`. It is defined in the
application layer so that the operator layer builds it and the service merges it. The service does not know about
operators, DAGs, or pyarrow.

`record_run` does the following under the lock for that document set:

1. `find_by_id`, then take `document_set.data_card` or a new empty card.
2. Find or create the flow by `details.id`, then the job by `id`, then the run by `id`.
3. Replace the run if present (preserving its `executed_at`), otherwise append.
4. Apply retention (D6).
5. Set `language` and `propagate_source_acls` only if they are null.
6. `repository.update(asset=document_set)` and return the card.

`update_descriptive_fields` applies only the six allowed keys and ignores null values.

**Why the service reuses `repository.update`:** it already validates, checks name conflicts, bumps `updated_at`, and
works for all three adapters. No new port method and no schema change.

**Concern: `updated_at` moves on every recorded run.** That is acceptable and arguably correct, because the card is part
of the asset. The `document_set` operator already updates the set on every store.

### D4. Operator layer: `DataCardRunBuilder`

A pure module `core/operators/document_sets/data_card_run_builder.py`, with static methods, no I/O, and no repository
access. Input: the operator config, the stored table, and a small stats value. Output: a `DataCardRunRecord`.

**DAG walk.** From the `document_set` node (found by `config["id"]`, falling back to `node_id`), walk `input_edges`
(`node_id_ref`) breadth-first, collecting every ancestor. Visited set, so a diamond is listed once. Sort the ancestors
topologically (Kahn on the ancestor subgraph) so output is upstream to downstream and deterministic; ties broken by the
order nodes appear in the definition. Branches that feed a `merge` are naturally included because `merge` has several
input edges. A node that is not an ancestor, such as a sibling branch ending in another sink, is excluded.

If `flow_definition` is missing, not a dict, has no `dag`, or the node is not found, the builder returns an empty
`operators` list. This is the "missing flow definition" requirement, and it is also what a direct operator unit test
sees.

**Per-operator details (allowlist).** A dispatch table keyed by operator short name; unknown operators yield only
`type`, `node_id`, `name`.

| Operator | Recorded | Source of values |
|---|---|---|
| `ingest_source` | `sources[0]` = `{input: provider, name, paths}` | provider-specific location keys only (see D5) |
| `chunker` | `chunk_details = {type, size}` | `chunk_type`, `chunk_size` in node config |
| `embeddings` | `embeddings[0] = {type: "dense", model_id, feature, dimension_size}` | `provider_config.model_id`; `embeddings_column` (default `embeddings`); dimension from the stored table |
| `vectordb` | `derivative_store = {name: provider, path: index_name or collection_name}` | `provider`, `provider_config.index_name` / `collection_name` |
| `lang_detect`, `acl_operator` | `type`, `node_id`, `name` only | used for derived fields |

Everything is read with `.get()` and type-checked, so malformed node configs degrade to null fields.

**Embedding dimension.** Read from the stored table: take the embeddings column, find the first non-null value, and use
`len(value)`. For a list column this is a cheap scalar read of one element. If the column is absent or all null, the
dimension is null. The model is never loaded and no provider is called.

**Language.** If any ancestor is `lang_detect` and the table has `lang_name`, take the most frequent value that is not
`UNKNOWN`. Counting uses `pyarrow.compute.value_counts` on the column, so it does not materialise Python rows.

**ACL propagation.** True if any ancestor is `acl_operator`; otherwise null (not false, so an unrelated flow does not
override an earlier value).

### D5. Secret exclusion by allowlist

The builder never copies a config dict. It reads named location keys and nothing else.

**Why not reuse `core/lineage/dataset_naming.py`.** Its helpers are private and return lineage-style
`(namespace, name)` pairs (for example `s3://docs` and `incoming`), not the `name` and `paths` the card needs. It also
resolves `${VAR}` placeholders, which the card must not do. The builder therefore has its own closed table and copies
only the *stripping rules* that dataset_naming applies: drop the query and fragment, never keep user info, keep scheme,
host, port and path of a URL.

| Provider | `name` | `paths` |
|---|---|---|
| `filesystem`, `local`, `file` | first of `paths` | `paths` |
| `s3`, `ibm_cos` | `bucket` | `[prefix]` |
| `sharepoint`, `onedrive`, `dropbox` | `drive_id` or `document_library_id` when present | `[folder_path]` or `[file_path]` |
| `google_drive` | `drive_id` when present | `[folder_path]`, `[folder_id]` or `[file_id]` |
| `box`, `box_driver` | none | `[folder_id]` or `[file_id]` |
| `web` | host of the first URL | each URL reduced to scheme, host, port, path |

Rules that apply to every row:

- A value for which `is_vault_reference()` is true is skipped, so the card does not reveal that a field was a vault
  reference or what it pointed at.
- A `${VAR}` placeholder is recorded as written. The builder does not resolve environment variables, so a resolved secret
  can never enter the card.
- An unknown provider yields `input: provider` with no `name` and no `paths`. This is deliberately conservative:
  supporting a provider is a one-line table edit plus a test.

A single unit test feeds nodes seeded with sentinel secrets under every credential key the repository knows, serializes
the card to JSON, and asserts none of the sentinels appear. This test is the safety net for the "no secrets" requirement.

**Relation to `add-secret-management`.** That change deals with resolved secrets leaking from runtime stores. This one
is safe either way because it never reads credential keys. The two do not share code.

### D6. Idempotency, retention, ordering

- **Run identity.** `run.id = job_run_id`. Micro-batches in one run share the job run ID, so each re-recording replaces
  the same entry.
- **`executed_at`.** The first recording sets it from `JobStats.start_time` (epoch seconds, converted to UTC RFC 3339).
  If stats are unavailable, the recording time is used. A replacement copies the existing `executed_at`.
- **`duration`.** Whole seconds from `executed_at` to now, refreshed on each re-recording, so the last micro-batch leaves the
  final value.
- **Documents.** `input_count` and `processed_count` are overwritten on each recording with the latest stats
  (`total_docs`, `completed_docs`), and are null when stats are missing. Counts are per job, last write wins.
- **Operators.** Replaced on each re-recording of the run. Micro-batches share one flow definition, so the content is
  identical.
- **Retention.** After the merge, collect `(executed_at, flow, job, run)` for the flow entry, sort ascending, and drop the
  oldest until at most 50 remain, then delete jobs with no runs. 50 is a module constant (`MAX_RUNS_PER_FLOW`) and is not
  configurable in this change. Runs with unparsable `executed_at` sort as oldest, so bad data cannot pin the list.

### D7. Concurrency: per-document-set lock

A module-level registry (`document_set_locks.py` in the document sets application layer) maps `document_set_id` to a
`threading.RLock`, guarded by a small registry lock. `record_run` and `update_descriptive_fields` hold the document set's
lock across read-modify-write. This covers the Python orchestrator's thread pool and a concurrent REST PATCH against a
running flow in the same process.

**The lock must also guard the existing writers.** `DocumentSetService.update_document_set` and
`_compute_and_update_metrics_with_ref` (called by `store_data`) read the whole `DocumentSet` and write it back. Without
the lock, a micro-batch could read the set, a second micro-batch could record its card entry, and the first write would
then store the stale copy without that entry. Both methods therefore take the same per-set lock around their
read-modify-write. Their behaviour and signatures are otherwise unchanged. The lock is re-entrant, and `store_data` never
holds it across the data write itself, only across the metadata read-modify-write.

**Cross-process writers (Prefect process workers, multiple API replicas) are not serialized.** For Postgres-backed
deployments two processes can interleave a read-modify-write and lose one entry. Mitigations: runs are re-recorded on
every micro-batch, so a lost entry is restored by the next recording of the same run; and the loss window is the
milliseconds between read and write. A real fix needs a row-level lock or optimistic version on the asset repository
port, which is a separate change. This is documented in the guide.

### D8. Operator integration and failure isolation

In `DocumentSetOperator.transform()`, after `service.store_data(...)` succeeds on both the create and the update-by-ID
paths, call a private helper `_record_data_card(*, table, document_set_id, metadata)`:

```python
try:
    record = DataCardRunBuilder.build(config=self.config, table=table, stats=self._read_job_stats())
    DataCardService(repository=metadata_repository).record_run(document_set_id=document_set_id, run=record)
    metadata[META_DATA_CARD_STATUS] = "recorded"
except Exception as exc:  # noqa: BLE001 - card is best effort, must never fail the node
    logger.warning("Data card recording failed for document set %s: %s", document_set_id, type(exc).__name__)
    metadata[META_DATA_CARD_STATUS] = "failed"
    metadata[META_DATA_CARD_ERROR] = type(exc).__name__
```

- The helper is not reached for empty tables, a missing `id` column, or a failed store, because those paths return or
  raise earlier.
- Only the exception class name goes to metadata and the log, so no message text, which could contain paths or values,
  is propagated.
- The operator passes the metadata repository it already built for `DocumentSetService`, so no second connection is
  opened.
- `_read_job_stats()` calls `JobStatsService.get_job_run_stats(job_run_id=...)`, and returns `None` on any exception or
  when `job_run_id` is empty.
- The returned table is the untouched input table. The existing metadata keys are unchanged. Two keys are added in
  `OperatorConstants.DocumentSet`: `META_DATA_CARD_STATUS` and `META_DATA_CARD_ERROR` (values `data_card_status`,
  `data_card_error`). The unused `OperatorConstants.Metadata.META_DATA_CARD` stays untouched.

### D9. `SessionInfo.flow_name`

Add `flow_name=None` to `SessionInfo.__init__` and `create_session_info`. The abstract orchestrator, which already
computes `self.flow_name` from the flow definition at the start of `execute`, additionally calls
`update_session_info(flow_name=self.flow_name)`. The Prefect batch subflow, which already restores `orchestrator.flow_name`
from `flow_definition`, passes it into the `SessionInfo` it builds.

The `DocumentSetOperator` takes the name from `get_session_info().flow_name` and falls back to the flow definition `name`,
then to the flow ID. This is the only consumer in this change.

OSS has no job entity with a name, so a recorded job's `name` is always null and its `id` is the job ID.

`flow_id` and `job_id` continue to come from the operator config or session as today. When `flow_id` is empty (ad-hoc
CLI run with an inline flow), the builder uses the flow definition name as the flow key and records `id` equal to that
name, so the card still has a stable key. Flows without a name use the literal `"unknown-flow"`.

### D10. REST layer

- **DTOs** (`api/dto/data_card_dto.py`): `DataCardResponse` (all fields, nested response models),
  `DataCardUpdateRequest` with `model_config = ConfigDict(extra="forbid")` so `flows` and unknown fields fail
  validation. The global validation handler maps that to 400, matching the rest of the API. Limits reuse
  `DESCRIPTION_MAX_LENGTH` and `DESCRIPTION_PATTERN` from `field_definitions.py`, with new constants for `language` (64)
  and curator fields (256).
- **Mapper:** `DataCardMapper.to_response(*, card, flow_names)` maps the domain card to the DTO. Routes never return
  domain objects.
- **Routes** in `api/routes/document_sets.py`: `GET` and `PATCH /{document_set_id}/data-card`, using the existing
  `DocumentSetIdPath`, `DocumentSetServiceDep`, and a new `DataCardServiceDep` provided by `api/dependencies.py`
  (built from the same cached repository).
- **404 for an unknown set:** the route first calls the document set service's `get_document_set`, so the error type,
  message, and format are identical to existing routes.
- **Flow name refresh.** For `GET`, the route collects the distinct flow IDs in the card and calls the flow service
  `get_flow(flow_id)` once per ID, catching any exception to fall back to the recorded name. Lookups hit the local flow
  repository, and the number of distinct flows writing to one document set is small. The refreshed names go to the
  mapper only, never back to storage.

### D11. Why the card is not in `DocumentSetResponse`

The card can be large and is only needed on a detail page. Keeping `DocumentSetResponse` unchanged avoids growing every
list response and keeps the existing contract byte-for-byte. A consumer that wants the card calls the dedicated route.

## Alternatives Considered

| Alternative | Why not |
|---|---|
| Separate `document_set_data_cards` table | Requires new migrations on three adapters and a join. The card already persists through the asset serialization. |
| Store the card inside `metadata` | `metadata` is user-owned and replaced by `PATCH`, so a user update would erase provenance. |
| Keep the flat `DataCard` and add fields | Cannot represent several flows or a run history. It is unused, so replacing it costs nothing. |
| Record from the orchestrator instead of the operator | Puts operator-specific knowledge in the orchestrator and records even when no document set exists. Violates "business logic in transform, orchestration in orchestrator". |
| Denylist of secret keys | Fails open when a new credential key appears. The allowlist fails closed. |
| Opt-out parameter on `document_set` | Adds an operator parameter and properties-panel work for a metadata-only record. Deferred. |
| Unbounded run history | Grows the asset row on every scheduled run. |

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Lost update when two processes write the same card (Postgres, multi-replica, process workers) | Documented limitation. Idempotent per-run replacement heals lost entries on the next micro-batch. A repository-level lock or version is a separate change. |
| Stale write by `store_data` or `update_document_set` erasing a concurrently recorded run (same process) | Both take the same per-set lock as `record_run` (D7), with a test that races them. |
| Card growth | 50-run retention per flow. Only allowlisted fields are stored. |
| Enterprise schema drift | A hand-written enterprise-shaped fixture pins the documented fields, and the round-trip test fails if either side renames a field. |
| Secret leakage through a new provider key | Allowlist table plus the sentinel-secret test. Unknown providers record nothing but the provider name. |
| Micro-batch duplicates | Run ID as the identity, with a test of three sequential and N concurrent recordings. |
| Slow card write delaying the pipeline | One read, one write per `document_set` node execution, and the work is bounded by retention. Stats lookup failures return `None` immediately. |
| `updated_at` churn on the set | Accepted. The set is already updated on each store. |
| Embedding dimension read on a huge table | Reads one element of one column. No materialisation. |
| Flow renamed or deleted after a run | The card keys by ID. Names are refreshed on read and fall back to the recorded name. |
| Breaking removal of flat `DataCard` | Unused in `src/`, and referenced only by tests and a legacy repository import. Both are updated in the same change. |

## Migration Plan

None. No flat `DataCard` has ever been written, so no stored data needs conversion. A stored flat card, if one exists
somewhere, loads as an empty card (D1). Rollback is a revert. The old flat `from_dict` reads its keys with defaults, so a
stored nested card loads as an empty flat card and nothing fails. Provenance recorded since the change is then invisible
but not corrupt, and it reappears if the change is restored.

## Open Questions

None blocking. The following are deferred on purpose and recorded as non-goals: an opt-out parameter, the derivatives
view, and cross-process locking.
