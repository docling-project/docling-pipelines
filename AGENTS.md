# Docling Pipelines — Agent Context

## Project
- **Package**: `docpipe` | source root: `src/` | Python `>=3.12,<3.13`
- **Install**: `uv pip install -e .[dev]` | activate: `source .venv/bin/activate`
- **Key external dep**: `data_processing` comes from `data-prep-toolkit-transforms` (DPK); `AbstractTableTransform` is its base class for all operators
- **Lockfile**: Any change to `[project.dependencies]`, `[project.optional-dependencies]`, or `[tool.uv].override-dependencies` in `pyproject.toml` **must** be followed by `uv lock` to regenerate `uv.lock`, then `uv pip install -e ".[dev]"` to sync the venv. Commit both `pyproject.toml` and `uv.lock` together.

## Entrypoints
CLI::src/docpipe/cli/docpipe_cli.py::main → `docling-pipelines --flow-file <path>`
REST API::src/docpipe/api/main.py::app → `uvicorn docpipe.api.main:app --reload --host 0.0.0.0 --port 8000`
Python lib::src/docpipe/lib/docpipe_flow_manager.py::DocpipeFlowManager → `DocpipeFlowManager(flow_file=...).execute()`
Flow engine (internal)::src/docpipe/core/orchestration/flow_executor.py::FlowExecutor → used by CLI and lib

Micro-batching default behavior: CLI, REST job runs, and `DocpipeFlowManager` default `enable_micro_batching` to `true` when a flow does not define it. If the flow sets `global_config.enable_micro_batching`, that explicit value is used.

## Directory Map

| Path | Purpose |
|---|---|
| `src/docpipe/cli/` | CLI — parses args, loads flow JSON, calls `run_command_line_executor` |
| `src/docpipe/lib/` | `DocpipeFlowManager` — programmatic wrapper around `FlowExecutor` |
| `src/docpipe/api/` | FastAPI REST layer — routes, DTOs, mappers, auth, middleware |
| `src/docpipe/api/auth/` | LDAP auth, JWT handler, OAuth2/OIDC config and routes |
| `src/docpipe/api/dto/` | Pydantic DTOs + mappers for all API request/response shapes |
| `src/docpipe/api/routes/` | Route handlers: flows, operators, job_runs, documents, document_sets, document_libraries |
| `src/docpipe/api/middleware/` | Transaction ID injection, request logging, payload size validation, error handling |
| `src/docpipe/api/services/` | API-layer services: OpenSearch queries, ACL query builder |
| `src/docpipe/core/operators/abstract_operator.py` | `AbstractOperator` base — extends `data_processing.AbstractTableTransform`; defines contract |
| `src/docpipe/core/operators/operator_registry.py` | `DOCPIPE_OPERATORS` frozenset; `get_docpipe_operators()` merges OSS + external providers |
| `src/docpipe/core/operators/ingest/` | `IngestSourceOperator` |
| `src/docpipe/core/operators/extract/` | `ExtractOperator` — docling-based text + entity extraction |
| `src/docpipe/core/operators/functional/` | `BranchingOperator`, `ChunkerOperator`, `EmbeddingsOperator`, `MergeOperator`, `DocIdHashOperator`, `NOOPOperator`, `EntityCurationOperator` |
| `src/docpipe/core/operators/quality/` | `DocumentClassifierOperator`, `DocQuality`, `EdedupOperator`, `LanguageDetect`, `MLEnrichmentOperator`, `PIIAndHAPAnnotator`, `ReadabilityOperator`, `RedactionOperator`, `SQLFilterOperator` |
| `src/docpipe/core/operators/vectordb/` | `VectorDBOperator` — OpenSearch / Milvus adapters |
| `src/docpipe/core/operators/document_sets/` | `DocumentSetOperator` — Storage category |
| `src/docpipe/core/operators/acl/` | `ACLOperator` — access control on data |
| `src/docpipe/core/orchestration/flow_executor.py` | `FlowExecutor` — loads flow JSON, calls orchestrator |
| `src/docpipe/core/orchestration/flow_validator.py` | `FlowValidator` — validates DAG: operator existence, features, params |
| `src/docpipe/core/orchestration/operator_factory.py` | `OperatorFactory` — resolves `short_name` → class with priority; `OperatorFactoryProvider` caches factories |
| `src/docpipe/core/orchestration/batch_manager.py` | Micro-batching — splits large doc sets for parallel processing |
| `src/docpipe/core/orchestration/orchestrator_factory.py` | `OrchestratorFactory.create_orchestrator(orchestrator_name="python")` |
| `src/docpipe/core/orchestration/python/` | `PythonOrchestrator` + `PythonOperatorExecutor` — default in-process orchestrator |
| `src/docpipe/core/orchestration/prefect/` | `PrefectEngine` — Prefect-based distributed orchestrator |
| `src/docpipe/core/job_management/` | DDD job/job-run lifecycle — `domain/` (ports, models), `application/` (services), `adapters/` (DuckDB/Postgres) |
| `src/docpipe/core/assets/` | DDD asset management for flows, document_libraries, document_sets — each follows `domain/ application/ adapters/` pattern |
| `src/docpipe/core/constants/constants.py` | All string literals + enums: `ExecutionStatus`, `OrchestratorType`, `DocpipeConstants`, `EnvironmentVariables`, `ServiceConstants` |
| `src/docpipe/core/constants/operator_constants.py` | `OperatorConstants` — column names and config keys used across operators |
| `src/docpipe/core/adapters/` | LLM adapters: `HuggingFaceAdapter`, `LiteLLMAdapter`, `WatsonxAdapter`; factory: `llm_adapter_factory.py` |
| `src/docpipe/core/ports/` | Port interfaces: `LLMInferencePort`, `LLMEmbeddingPort`, `TextDetectionPort` |
| `src/docpipe/core/incremental_metadata/` | Tracks previously processed docs for incremental/delta runs |
| `src/docpipe/core/lineage/` | Optional OpenLineage support (hexagonal): `domain/` (models, ports), `application/` (`LineageService`, `lineage_factory`), `adapters/` (`openlineage/` observer + publisher, `noop/`), `dataset_naming.py` (provider config to dataset namespace/name); disabled unless `DOCPIPE_LINEAGE_ENABLED=true` |
| `src/docpipe/core/models/session_info.py` | `SessionInfo` — thread-local context: `job_id`, `job_run_id`; use `get_session_info()` / `set_session_info()` |
| `src/docpipe/core/data_access/` | Wraps `data_processing.DataAccess` — parquet-based document table IO |
| `src/docpipe/core/document_classes/` | YAML schema definitions for document column structures |
| `src/docpipe/integrations/` | External service clients: AWS, Docling, HuggingFace, LiteLLM, Ollama, WatsonX |
| `src/docpipe/storage/` | Storage abstraction: DuckDB + filesystem; interfaces `TableStorage`, `KeyValueStorage` in `storage/interfaces/`; default DuckDB paths: `data/duckdb/job_stats.duckdb`, `data/duckdb/document_sets.duckdb` |
| `src/docpipe/utils/infrastructure/logging.py` | `get_logger()` — always use this, never `logging.getLogger()` directly |
| `src/docpipe/utils/` | Shared: logging, pyarrow handlers (`utils/data/pyarrow_handler.py`), flow_utils, duckdb helpers, llm utils |
| `src/docpipe/exceptions/` | `DocpipeException`, `FlowValidationException`, `FlowExecutionFailedException` |
| `tests/` | pytest — mirrors `src/docpipe/` structure; unit tests under `tests/unit/`, integration under `tests/integration/` |
| `sample_flows/` | Example flow JSON files — reference before writing new flows |
| `docs/reference/OPERATORS.md` | Complete operator parameter specs — read before modifying operator configs |
| `docs/reference/GLOBAL_CONFIG.md` | All `global_config` flow-level parameters — read before writing flow JSON |
| `docs/guides/FLOW_CONFIGURATION_GUIDE.md` | End-to-end flow JSON authoring guide with examples |
| `docs/guides/CUSTOM_OPERATORS_GUIDE.md` | Step-by-step guide for creating custom operators |
| `docs/guides/DOCUMENTATION_STYLE_GUIDE.md` | Operator doc template, file naming rules, Mermaid conventions |

## Operator Registry — 21 OSS Operators
<!-- format: Class::short_name::Category::file (relative to src/docpipe/) -->
IngestSourceOperator::ingest_source::Ingest::core/operators/ingest/ingest_source.py
ExtractOperator::extract_operator::Extract::core/operators/extract/extract_operator.py
BranchingOperator::branching::Functional::core/operators/functional/branching_operator.py
ChunkerOperator::chunker::Functional::core/operators/functional/chunker.py
EmbeddingsOperator::embeddings::Functional::core/operators/functional/embeddings/embeddings_operator.py
DocIdHashOperator::doc_id_hash::Functional::core/operators/functional/doc_id_hash.py
MergeOperator::merge::Functional::core/operators/functional/merge.py
NOOPOperator::noop::Functional::core/operators/functional/noop.py
EntityCurationOperator::entity_curation::Functional::core/operators/functional/entity_curation/entity_curation_operator.py
DocumentClassifierOperator::document_classifier::Functional::core/operators/quality/classification/document_classifier.py
DocQuality::doc_quality::Quality::core/operators/quality/doc_quality.py
EdedupOperator::ededup::Quality::core/operators/quality/ededup.py
LanguageDetect::lang_detect::Quality::core/operators/quality/language_detection/lang_id.py
MLEnrichmentOperator::ml_enrichment::Quality::core/operators/quality/ml_enrichment.py
PIIAndHAPAnnotator::pii_and_hap::Quality::core/operators/quality/pii_and_hap/pii_and_hap_annotator.py
ReadabilityOperator::readability::Quality::core/operators/quality/readability/readability_operator.py
RedactionOperator::redaction::Quality::core/operators/quality/redaction.py
SQLFilterOperator::sql_filter::Quality::core/operators/quality/sql_filter.py
VectorDBOperator::vectordb::VectorDB::core/operators/vectordb/vectordb_operator.py
DocumentSetOperator::document_set::Storage::core/operators/document_sets/document_set_operator.py
ACLOperator::acl_operator::Extract::core/operators/acl/acl_operator.py

## Operator Contract

Minimum required structure for any new operator:
```python
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.utils.infrastructure.logging import get_logger
import pyarrow as pa

logger = get_logger()

class MyOperator(AbstractOperator):
    short_name: str = "my_operator"           # must match flow JSON "type" value
    category: OperatorCategory = OperatorCategory.Quality
    owner: str = "docpipe"                    # "docpipe" = built-in; None = custom

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        # read operator params from config dict here

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict]:
        metadata = self.create_base_metadata(total_docs_count=len(table))
        # ... process table ...
        return [table], metadata

    @staticmethod
    def get_metadata() -> dict:
        return {
            "short_name": "my_operator",
            "description": "...",
            "owner": "docpipe",
        }
```

After creating the class:
1. Add to `DOCPIPE_OPERATORS` frozenset in `src/docpipe/core/operators/operator_registry.py`
2. Add import at top of that file in the correct category block

Optional overrides: `validate(errors, warnings, available_features)`, `get_required_features() -> list[str]`, `get_static_required_features() -> list[str]`, `is_available() -> bool`

Helper methods inherited from `AbstractOperator`:
- `self.create_base_metadata(total_docs_count=N)` — initialise metadata dict
- `self.record_failed_document(metadata=m, doc_id=..., doc_name=..., reason=...)` — record a failure
- `self.record_skipped_document(metadata=m, doc_id=..., doc_name=..., reason=...)` — record a skip
- `self.doc_column` — the content column name (from config, default `"content"`)
- `self.job_id`, `self.job_run_id`, `self.common_log_arguments`

## Flow JSON Schema

```json
{
  "flow_name": "my-flow",
  "global_config": {
    "doc_column": "content",
    "storage": "in-memory",
    "execute_type": "local",
    "disable_validation": false,
    "force_ingest": false,
    "enable_micro_batching": false,
    "micro_batch_size": 100,
    "max_concurrent_batches": 10
  },
  "flow": [
    { "type": "ingest_source",    "name": "node_a", "config": { "provider": "filesystem", "connection_params": {"paths": ["./docs"]}, "include_filter": "pdf,docx" } },
    { "type": "extract_operator", "name": "node_b", "config": {}, "depends_on": ["node_a"] },
    { "type": "chunker",          "name": "node_c", "config": {}, "depends_on": ["node_b"] }
  ]
}
```

Pipeline patterns (short_name values):
- full: ingest_source → extract_operator → chunker → embeddings → vectordb
- quality: ingest_source → extract_operator → lang_detect → redaction → chunker → embeddings
- branch: ingest_source → extract_operator → branching → [branch_a, branch_b] → merge

## DDD Layer Pattern

`core/assets/` and `core/job_management/` follow strict DDD layering. When adding code to these areas:

```
domain/          ← models (Pydantic/dataclass), port interfaces (ABCs) — no framework imports
application/     ← services that orchestrate domain logic — calls ports, not adapters directly
adapters/        ← concrete implementations: DuckDB, Postgres, local filesystem
factories/       ← wires adapters to ports; called at startup
```

Never import an `adapters/` class from `domain/` or `application/`. Domain ports are defined as ABCs in `domain/ports/`.

## Architectural Rules

1. Inter-operator data must be `pa.Table`; `transform()` returns `tuple[list[pa.Table], dict]`
2. New operators must extend `AbstractOperator`; set `short_name`, `category`, `owner` as class attributes
3. Built-in operators (`owner="docpipe"`) must be registered in `DOCPIPE_OPERATORS` frozenset
4. `get_metadata()` must be `@staticmethod` — no `self`
5. All functions/methods with 2+ params (excl. `self`/`cls`) must use keyword-only `*` separator
6. No emoji or non-ASCII characters in Python logging statements
7. No f-strings inside `logger.*()` calls — use `%s` style: `logger.info("Processing %s", doc_id)`
8. Flow JSON is a DAG; edges via `depends_on`; exactly one root node (no `depends_on`), always an ingest operator
9. `SessionInfo` (`job_id`, `job_run_id`) is thread-local — access via `get_session_info()`, never pass as function args
10. Business logic in `transform()`; orchestration logic in orchestrator layer only
11. Operators use port interfaces (`LLMInferencePort`, `LLMEmbeddingPort`) — never import concrete adapter classes
12. External operator providers registered via `register_operator_provider()` — never mutate `DOCPIPE_OPERATORS` directly
13. Operators never call DuckDB or any DB directly — use storage abstraction layer
14. API handlers use DTOs only — never return domain model instances from routes
15. **Use `@staticmethod` or `@classmethod` unless `self`/`cls` is genuinely needed** — instance methods are the last resort, not the default. Apply the following decision tree when writing or reviewing any method:

    ```
    Does the method read or write instance state (self.x)?
    ├── Yes → instance method  (def foo(self, ...))
    └── No → does it need the class itself (cls) or class-level state?
             ├── Yes → @classmethod  (def foo(cls, ...))
             └── No → is it useful outside this class AND has no coupling to class internals?
                       ├── Yes → module-level function
                       └── No  → @staticmethod  (def foo(...))  ← default for pure helpers
    ```

    **Concrete rules:**
    - Every pure helper (formula, hash, type-mapping, formatting, graph utility) that takes only plain arguments → `@staticmethod`
    - Private helpers (`_` prefix) that don't read `self` → `@staticmethod` on the class; do NOT promote to module-level just because they're pure — keep them where they logically belong
    - Factory/constructor alternatives that use `cls` → `@classmethod`
    - `transform()`, `__init__`, lifecycle hooks, anything reading `self.*` → instance method
    - Never add `self` to a method signature just to satisfy a linter or to match surrounding style
    - Known violations being tracked in [#127](https://github.com/docling-project/docling-pipelines/issues/127)

16. **Use `_` and `__` name prefixes correctly** — they have distinct meanings and must not be used interchangeably:
    - `_name` (single underscore) — **internal by convention**: accessible from outside the class but signals "do not use directly". Use for private helpers, internal state, and implementation details that subclasses may legitimately access.
    - `__name` (double underscore) — **name-mangled**: Python rewrites it to `_ClassName__name`, making it genuinely inaccessible from outside the class and invisible to subclasses. Use only when you explicitly need to prevent subclass access or avoid accidental attribute collisions in deep inheritance hierarchies — **not** as a stronger form of `_`.
    - In practice, almost all private methods and attributes in this codebase should use `_` (single). Reserve `__` for the rare case where name mangling is the explicit intent.
    - Never use `__name__` (dunder) style for anything other than Python special/magic methods (`__init__`, `__repr__`, `__enter__`, etc.).

## Environment Variables

| Variable | Effect |
|---|---|
| `DS_LOG_LEVEL` | `INFO` (default) \| `DEBUG` \| `WARNING` \| `ERROR` |
| `OLLAMA_HOST` | LLM host, default `http://localhost:11434` |
| `PREFECT_API_URL` | Prefect server URL |
| `PREFECT_MODE` | `server` \| `ephemeral` |
| `DOCPIPE_ENABLE_CUSTOM_OPERATORS` | `true` (default) \| `false` |
| `DOCPIPE_CUSTOM_OPERATORS` | Comma-separated package paths injected as operator providers |
| `DOCPIPE_CONFIG_PATH` | Path to `docling-pipelines-config.yaml` |
| `DOCPIPE_STORAGE_BACKEND` | `duckdb` (default) \| `postgres` |
| `DOCPIPE_FRAMEWORK_TYPE` | `local` (default) \| `prefect` |
| `DOCPIPE_LINEAGE_ENABLED` | `false` (default) \| `true` — emit OpenLineage events (requires the `lineage` extra) |
| `DOCPIPE_LINEAGE_MODE` | `flow` (default) \| `operator` — add per-node events |
| `DOCPIPE_LINEAGE_NAMESPACE` | OpenLineage namespace, default `docpipe://local` |
| `DOCPIPE_LINEAGE_PRODUCER` | Producer URI embedded in facets, default `https://github.com/docling-project/docling-pipelines` |
| `DOCPIPE_LINEAGE_STRICT` | `false` (default) \| `true` — re-raise observer errors instead of logging a warning |
| `OPENLINEAGE__TRANSPORT__*` | OpenLineage SDK transport settings (`console` default, `file`, `http`); read by the SDK, not by docpipe |
| `DOCPIPE_POSTGRES_HOST/PORT/DB/USER/PASSWORD` | Postgres connection (when storage=postgres) |
| `CORS_ORIGINS` | Comma-separated allowed origins, default `http://localhost:3000` |

## Commands

```bash
source .venv/bin/activate                                        # always activate first

docling-pipelines --flow-file <path>                             # run a flow
docling-pipelines --flow-file flow.json --validate               # validate without running
docling-pipelines --list-operators --verbose                     # list all registered operators
DS_LOG_LEVEL=DEBUG docling-pipelines --flow-file flow.json       # debug logging

pytest                                                           # run tests
pytest tests/unit/core/operators/ -v                             # run specific test path
pytest --cov=src/docpipe --cov-report=html                       # with coverage

pre-commit run --from-ref origin/main --to-ref HEAD              # check committed branch changes before pushing
```

## Pre-commit Workflow

- Never run pre-commit with `--all-files`
- Stage and commit changes with `git commit -s`, then run `pre-commit run --from-ref origin/main --to-ref HEAD` before pushing
- Keep `origin/main` up to date; substitute the actual PR base for stacked branches
- If hooks modify files, stage and commit the fixes, then rerun the checks before pushing

## Key External Services

| Service | Default | Used by |
|---|---|---|
| Ollama | `http://localhost:11434` | `EmbeddingsOperator`, `ExtractOperator` (LLM modes) |
| OpenSearch | `http://localhost:9200` | `VectorDBOperator` |
| PYTHONPATH | must include `src/` | all `docpipe.*` imports |

Setup guide: [`USER_GUIDE_PIPELINE_SETUP.md`](USER_GUIDE_PIPELINE_SETUP.md)

## Documentation Rules

Full style guide: [`docs/guides/DOCUMENTATION_STYLE_GUIDE.md`](docs/guides/DOCUMENTATION_STYLE_GUIDE.md)

**Operator docs** — file: `docs/operators/<category>/<operator_name>_readme.md` — 8 required sections in order:
`Overview` → `Key Features` → `Operator Configuration` → `Parameters` → `Output Columns` → `Examples` → `Troubleshooting` → `Architecture` (optional, last)

**Forbidden in operator READMEs:** separate `*_config.md` file, architecture diagrams before `## Architecture`, migration history, `## Contributing`/`## License` sections, duplicating content from `docs/reference/OPERATORS.md`

**File naming:** `UPPER_SNAKE_CASE.md` for all docs (root-level and inside `docs/guides/`, `docs/reference/`, `docs/api/`, etc.); exception: operator readmes use `<operator_name>_readme.md` (lowercase) under `docs/operators/<category>/`

**Links:** relative paths only (`../guides/FOO.md`); descriptive link text (not "click here"); verify before PR

**Code fences:** exactly 3 backticks; language tag mandatory (`python`, `bash`, `json`, `yaml`, `mermaid`)

**Mermaid:** validate every diagram at [mermaid.live](https://mermaid.live) before committing; use `graph LR` for pipelines, `graph TD` for hierarchy

**Changelog:** maintainers manually update `CHANGELOG.md` at release time. Agents must not update it during PR or commit work unless explicitly requested.

## OpenSpec

This repo uses [OpenSpec](https://openspec.dev) for spec-driven development. Live specs in `openspec/specs/` describe the current observable behavior of every major API surface and engine capability. Read the relevant spec before modifying any capability it covers.

**Spec index** — `openspec list --specs` (requires `openspec` CLI, Node ≥20.19):

| Namespace | Coverage |
|---|---|
| `backend/flows-api` | Flow CRUD REST API (incl. cascade delete of job runs) |
| `backend/projects-api` | Project CRUD REST API |
| `backend/job-runs-api` | Job run lifecycle REST API |
| `backend/operators-api` | Operator metadata + flow validation REST API |
| `backend/document-sets-api` | Document set REST API |
| `backend/document-libraries-api` | Document library REST API |
| `backend/documents-api` | Document REST API |
| `backend/providers-api` | LLM/embedding provider model listing (ollama, watsonx) |
| `backend/custom-operators-api` | Custom operator upload, CRUD, directory tree |
| `backend/document-classes-api` | Document type definitions REST API |
| `backend/flow-execution-engine` | FlowExecutor, orchestration, micro-batching |
| `frontend/canvas-page` | Pipeline editor page |
| `frontend/properties-panel` + custom panels | Operator config side panel |
| `frontend/elyra-canvas`, `frontend/read-only-canvas` | Canvas components |
| `frontend/home-page`, `projects-page`, `project-detail-page`, `flow-detail-page`, `run-details-page` | UI pages |
| `frontend/state/assets-slice` | Shared flow + job run navigation asset maps |
| `frontend/state/notifications-slice` | Global toast / history / unread-counter notification system |
| `frontend/state/flows-slice`, `job-runs-slice`, `operators-slice`, `projects-slice` | Domain entity Redux slices |
| `frontend/common/*` | Shared UI components |

**Pre-commit Workflow** — OpenSpec operations:

```bash
# Before starting new feature or behavior change
openspec list --specs                             # read what's already specified

# Start a change
openspec new change <descriptive-name>
# → write openspec/changes/<name>/proposal.md
# → write openspec/changes/<name>/specs/<capability>/spec.md
# → write openspec/changes/<name>/design.md
# → write openspec/changes/<name>/tasks.md

# Validate before implementing
openspec validate <name> --strict

# After code review and tests pass
openspec archive <name>
```

**Rules:**
- Never modify `openspec/specs/` directly — only `openspec archive` writes there.
- Do not implement code before the change's `proposal.md` and spec delta are written and reviewed.
- Scope implementation strictly to the declared change — no opportunistic refactors.
- Run `openspec validate <name> --strict` before handing off for implementation.
- The `openspec/changes/archive/` directory is the historical record — do not edit archived changes.
- New capabilities must use `backend/*` for Python API/engine/operator work, or `frontend/*` for React page and component work.
