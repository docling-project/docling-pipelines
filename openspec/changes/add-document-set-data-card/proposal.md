# Proposal

## Why

A document set is the durable output of a pipeline, but nothing records how it was produced. A consumer who finds a
document set cannot tell which flow, job, and run wrote it, which sources it was built from, how it was chunked or
embedded, or which vector index holds its derivatives. The domain model already has a `DataCard` field on
`DocumentSet` and every repository persists it, yet nothing populates it, the REST API does not expose it, and its
flat shape (one flow, one job, a list of operator names) cannot represent a document set that is refreshed by many
runs or fed by more than one flow.

The enterprise product already ships a data card for its document sets. OSS needs the same provenance record, with the
same field names where they apply, so that a card is meaningful on both sides and a later convergence is cheap.

## What Changes

- **Data card model.** Replace the unused flat `DataCard` with a nested provenance model: descriptive fields plus
  `flows[] -> jobs[] -> runs[] -> operators[]`, with per-operator `sources`, `embeddings`, `chunk_details`, and
  `derivative_store`. Field names follow the enterprise schema. Loading is lenient, so a card shaped like an enterprise
  card loads and re-serializes without losing known fields.
- **Automatic population.** The `document_set` operator records the current job run in the target document set's card
  after it stores rows. The run lists the operators upstream of the node, with details for ingest sources, chunker,
  embeddings, and vector database nodes, and derives `language` and `propagate_source_acls` from the flow.
- **Safe accumulation.** Recording is idempotent per job run (micro-batches rewrite the same entry), accumulates runs
  across jobs and flows, keeps the most recent 50 runs per flow entry, and never overwrites user-managed fields.
- **No secrets.** The card is built from an allowlist of non-secret fields. Credentials, vault references, query strings,
  and URL user info are never recorded.
- **Failure isolation.** A failure while recording the card is logged and reported in node metadata. It never fails
  the node or the flow.
- **REST API.** `GET /api/v1/document-sets/{id}/data-card` returns the card (flow names refreshed from the current flow
  when it still exists). `PATCH /api/v1/document-sets/{id}/data-card` updates the descriptive fields. The `flows`
  section is system-maintained and read-only over the API. Existing document set responses are unchanged.
- **Session context.** `SessionInfo` gains `flow_name`, set once by the orchestrator, so operators can read the flow
  name without parsing the flow definition.
- **BREAKING (Python API of an unused model).** The flat `DataCard(flow_id=..., operators=[...], lineage_metadata=...)`
  constructor is removed. Nothing in the repository constructs it outside tests, and no persisted data exists to migrate.
- **Docs.** A data card guide, REST API reference rows, the `document_set` operator README, and `OPERATORS.md`.

**Layers affected:** backend-only. No frontend, routing under `/ui`, BFF proxy, or Redux slice changes. The new REST
routes are additive.

**Affected REST routes:** new `GET` and `PATCH /api/v1/document-sets/{document_set_id}/data-card`. No existing route
changes its request or response shape.

**Affected operators:** `document_set` (records the card). Read-only inspection of the upstream `ingest_source`,
`chunker`, `embeddings`, `vectordb`, `lang_detect`, and `acl_operator` node definitions. None of them change.

**Affected storage adapters:** none. DuckDB, Postgres, and local adapters already persist the card through the asset
serialization. A new application service reads and writes through the existing repository port.

## Capabilities

### New Capabilities

- `backend/document-set-data-card`: The data card structure and its lenient loading, persistence with the document set,
  recording of job runs by the `document_set` operator, accumulation, retention, upstream operator provenance,
  operator-specific details, derived fields, secret exclusion, and failure isolation.

### Modified Capabilities

- `backend/document-sets-api`: Adds retrieval and update of a document set's data card.
- `backend/flow-execution-engine`: Adds the flow name to the session context available to operators.

## Non-goals

- **No enterprise change.** The enterprise repository (`datasift-api`) is not modified and does not import the OSS model.
  Convergence is a later, optional change. Compatibility is limited to field names and lenient loading.
- **No CAMS concepts.** No `resource_key` resolution, no container IDs resolved against a catalog, no asset
  relationships (`is_produced_by`, `has_a_source_of`, `creates_derivative`, `creates_derivatives_through`), no audit events, and
  no import/export asset-ID remapping. The information those relationships carry lives inside the card
  (`flow` id, `sources`, `derivative_store`).
- **No derivatives view.** No `include=derivatives` expansion, no entity-table or correlation detail, and no feeding of
  `is_derivative_available` on document library responses. The card records `derivative_store`, and a later change reads it.
- **No new operator parameter.** There is no switch to turn card recording off, so the operator metadata and the
  properties panel are unchanged.
- **No document byte sizes.** `input_size` and `processed_size` stay empty; job statistics do not track them.
- **No cross-process locking.** Concurrent writers in separate processes are not serialized beyond the idempotent
  per-run replacement described in the design. Writers in one process are serialized per document set.
- **No change to `CHANGELOG.md`.**

## Impact

- **Code (new):** `core/assets/document_sets/application/services/data_card_service.py`,
  `core/assets/document_sets/application/services/document_set_locks.py`,
  `core/operators/document_sets/data_card_run_builder.py`, `api/dto/data_card_dto.py`, and a data card mapper.
- **Code (changed):** `core/assets/document_sets/domain/models/data_card.py` (rewritten) and its `__init__.py` exports,
  `core/assets/document_sets/application/services/document_set_service.py` (takes the per-set lock around its two
  read-modify-write paths, no behaviour change),
  `core/operators/document_sets/document_set_operator.py`, `core/models/session_info.py`,
  `core/orchestration/abstract_orchestrator.py`, `api/routes/document_sets.py`, `api/dependencies.py`, and
  `core/constants/operator_constants.py` (metadata key).
- **Tests:** rewrite the flat `DataCard` tests in `tests/unit/core/operators/document_sets/test_document_set_models.py`;
  add model, service, builder, operator, and route tests plus an enterprise-shaped fixture.
- **Docs:** new `docs/guides/DOCUMENT_SET_DATA_CARD.md`; updates to `docs/api/REST_API_SERVER.md`,
  `docs/operators/storage/document_set_readme.md`, and `docs/reference/OPERATORS.md`.
- **Dependencies:** none added.
- **Related in-flight change:** `add-secret-management` removes resolved secrets from places they leak today.
  This change reads only allowlisted fields and does not depend on it, and it stays correct if that change lands first or later.
