# Changelog

All notable changes to `docling-pipelines` will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning 2.0.0](https://semver.org/).

---

## [Unreleased]

### Added

- File event support (`created`, `modified`, `deleted`) in the Box (#347) and Dropbox (#348) ingest source adapters
- Kafka event streaming integration, routing-key event mapping REST API (`/api/v1/event_mappings`), persistent mapping storage, and Docker Compose deployment with Kafka (#162, #233, #234)
- Local Presidio PII detection provider (`pii_provider: "presidio"`) and capability-based detection port split in `PIIAndHAPAnnotator` (#187)
- `DocumentClassProvider` port and static implementation (#285)
- CPU and GPU Docker build support (`COMPUTE_BACKEND` build arg) (#216)
- OpenSpec specification files covering backend and frontend capabilities (#155)
- Unified `Commit Verification` workflow (`.github/workflows/commit-verification.yml`) enforcing DCO sign-off, GPG verification, and PR template completeness on every PR; replaces `dco-advisor.yml` (#188, #189, #275, #308, #332)
- Project `CODE_OF_CONDUCT.md` (#325) and `dependabot.yml` configuration (#206)

### Changed

- Cross-document embedding sub-batching in `EmbeddingsOperator` for higher embedding throughput (#191)
- Enhanced `EdedupOperator` with persistent deduplication registry storage (#270)
- Hoisted hot-path imports in `ExtractOperator` (#142)
- Migrated regular expression matching from `re` to `google-re2` across operator hot-paths for ReDoS hardening (#240)
- Replaced `TagInput` with explicit Add button and table for provider list fields in the frontend (#273)
- Migrated hard-coded user-facing strings in frontend components and pages (#208, #251)
- Updated repository references from `IBM` to `docling-project` (#249)
- `sample_flows/README.md` — synchronized existing JSON flow catalog and storage output examples (#228, #237)

### Fixed

- Report missing `provider` in `IngestSourceOperator` during flow validation (#364)
- Retry `watsonx` embedding requests up to 3 times with jittered backoff (#350)
- Custom operator loader now properly loads discovered package operators (#327)
- Corrected OpenSearch image tag and Ollama healthcheck in the all-in-one Docker Compose file (#335)
- `docling-pipelines-slim` packaging fixes: added `dropbox`, `milvus-lite`, and `python-multipart` to base dependencies (#281) and included parent `src/docpipe` sources in wheel builds (#235, #274)
- LDAP authentication security hardening (#186)
- Replaced non-ASCII characters in logger messages (#232) and enforced lazy formatting in language detection adapters (#245)
- Security and dependency updates across backend, `slim`, and `frontend` (#236, #252, #269, #310–#336)

---

## [2.0.1] - 2026-10-09

### Added

- `docs/integrations/openlineage/OPENLINEAGE_GUIDE.md` — new integration guide covering OpenLineage support: installation, enabling, configuration reference (all env vars, HTTP and File transport), emission modes (flow vs operator), Marquez integration and architecture, event catalog by mode, custom facets reference, and a step-by-step guide for adding a custom lineage client (#178, #212)
- UI beta/experimental notice across the web application and documentation (#214)
- CI notebook validation with `nbQA` (#203)

### Changed

- Bumped `docling` and `docling-slim` from `2.130.0` to `2.132.0` (#204, #205)
- Reduced cognitive complexity in flow validation and converters (#199)

### Fixed

- Flow run report generation fix (#220)
- Empty `vlm_pipeline` and `asr_pipeline` objects enable their respective pipelines with defaults; omitted or `null` blocks keep them disabled. The default VLM preset is `granite_docling` (#123)

---

## [2.0.0] - 2026-10-07

### Added

- React frontend UI with Elyra-based pipeline canvas, per-operator properties panels, project/flow management, and Node.js BFF layer; bundled into the wheel and served at `/ui/` (#58)
- `StorageOutputOperator` — writes processed documents to a configurable destination with `processed_content`, `refetch_original`, and `comprehensive_export` modes (#58)
- `S3DestinationAdapter` — writes to S3 / IBM COS / MinIO with env-var credentials and bucket pre-flight validation (#58)
- `SharePointDestinationAdapter` — writes to SharePoint document libraries via Microsoft Graph API (#58)
- `GoogleDriveDestinationAdapter` — writes to Google Drive with resumable uploads and Service Account / OAuth2 auth (#58)
- `onedrive` provider alias for `SharePointDestinationAdapter` (#58)
- `ibm_cos` provider alias for `S3DestinationAdapter` (#58)
- Hierarchical multi-source path namespacing when `ingest_source` is configured with multiple `paths` (#58)
- Dropbox ingest source adapter with OAuth2 auth, cursor pagination, and extension/size filters (#44)
- Milvus Lite support (`auth_type: "lite"`) for container-free local vector storage in `VectorDBOperator` (#56)
- Full OCR engine exposure — `ocr.engine`, `ocr.mode`, `ocr.enabled`, and `ocr.engine_options` in `ExtractOperator` provider config (#58)
- GPU acceleration for `ExtractOperator` via `standard_pipeline.accelerator` in `provider_config` (#58)
- DocLang auto-transcoding support across extraction, redaction, and vector DB operators (#60)
- HashiCorp Vault integration — `vault://` URI scheme for resolving secrets in flow configs at runtime (#58)
- OpenLineage dependencies, domain models, port interfaces, application service, adapters, and orchestrator wiring (#62, #112)
- Kafka event streaming setup with JSON Schema support (#156)
- Cascade deletion of associated job runs when a flow is deleted (#158)
- `progress_timestamp` field on `JobStats`, DTOs, mappers, and storage adapters (#67)
- `docling-pipelines-slim` package variant excluding heavyweight operator dependencies (#58)
- Docker and Docker Compose configurations for API and UI deployment (#173, #200, #201)
- Comprehensive Vitest unit test suite for the frontend (149 files, 2155+ tests) (#81)
- Flow execution defaults `enable_micro_batching` to `true` when not set in the flow (#58)
- Deprecation policy (`docs/guides/DEPRECATION_POLICY.md`) and migration guide template (#58)
- Release process documentation (`RELEASE_PROCESS.md`) (#58)

### Changed

- **Breaking:** `IngestSourceOperator` migrated from `connection_params` + `credentials` to unified `provider_config`; all 8 source adapters and all sample flows updated (#152)
- `PIIAndHAPAnnotator` provider selection replaced with decorator-based `PIIAndHAPDetectionFactory` registry (#76)
- 33 self-free instance methods converted to `@staticmethod` across `FlowValidator`, `AuthoringCompiler`, `FlowExecutionReporter`, `MetadataAggregator`, and `IncrementalUpdateService` (#139)
- 18 self-free per-document hot-path methods converted to `@staticmethod` across `ReadabilityMetrics`, `JobReportGenerator`, `EmbeddingsOperator`, and `DuckDBTableStorage` (#139)

### Fixed

- Storage output now accepts cloud destination credentials and S3 `key_prefix` saved by the UI, resolves environment variables for `endpoint_url` and `region` (#176), retains support for separate `credentials` and legacy S3 `prefix`, and reads ingest source paths from normalized `provider_config`
- Separated `flow_id` from `flow_name` in `JobStats` (#179)
- Exposed numeric field constraints in operator metadata and enforced them in the provider-specific config UI (#137)
- Auto-applied `provider_config` defaults on node drop and panel open (#90)
- Updated JupyterLab to 4.6.4 in the full and slim notebooks extras to resolve security alerts (#51, #168)
- Notification panel now propagates `action_type` from backend validation and fixes stale alert detection (#91)
- Markdown chunking: send extracted content with `.md` filename to preserve source name in chunk metadata (#148)
- Job runs list response now populates the actual flow name instead of a blank value (#118)
- VectorDB enrichment: hydrate connection defaults into `provider_config` before API call (#80)
- Milvus auth fields, validation messages, `auth_type` persistence, advanced JSON validation, and SSL default corrected (#80, #175)
- Frontend wheel build is now mandatory; UI included in the distributed package (#125)
- `PII and HAP` operator validates `provider_config` and `model_id` during flow validation (#105)
- Node execution logs aligned with DAG pipeline order; active duration calculation fixed (#107)
- `scripts/test_examples.py --dry-run` skips prerequisites before probing Ollama or environment (#31)
- S3 benchmark flows use configured prefix and `max_files` without embedding a corpus-wide exclusion list

---

## [1.0.1] - 2026-09-07

### Fixed

- **`docling-pipelines-api` console command** — The entry point previously pointed at the FastAPI `app` object (`docpipe.api.main:app`), causing a `TypeError` on invocation. A `run()` launcher function has been added to `src/docpipe/api/main.py` and `pyproject.toml` now registers `docpipe.api.main:run` as the entry point. Running `docling-pipelines-api` now correctly starts a Uvicorn server on `127.0.0.1:8080`.

- **Ruff PTH123 compliance** — Replaced `open()` calls with `Path.open()` across the codebase.

### Changed

- Bumped vulnerable dependencies flagged by Dependabot.

---

## [1.0.0] - 2026-08-28

### Added

- Modular operator-based data processing framework for building document curation pipelines
- **Extract operators**: `ExtractOperator` with support for Docling document extraction, entity extraction, and multiple output modes
- **Ingest operators**: `IngestLocalOperator`, `IngestSourceOperator` with support for local filesystem, S3, Azure Blob, Google Cloud Storage, and Box
- **ACL operators**: `ACLOperator` for access control list management
- **Functional operators**: `ChunkerOperator`, `EmbeddingsOperator`, `BranchingOperator`, `NOOPOperator`, `MergeOperator`, `EntityCurationOperator`, `DocIdHashOperator`
- **Quality operators**: `EdedupOperator`, `RedactionOperator`, `LanguageDetect`, `SQLFilterOperator`, `DocumentClassifierOperator`, `ReadabilityOperator`, `PIIAndHAPAnnotator`, `MLEnrichmentOperator`, `DocQuality`
- **Storage operators**: `DocumentSetOperator` for document set management
- **VectorDB operators**: `VectorDBOperator` with OpenSearch adapter
- DAG-based flow execution model defined via JSON flow configuration files
- Prefect orchestration layer for parallel execution and task dependency management
- FastAPI REST service with OpenAPI / Swagger documentation
- CLI entry point (`docling-pipelines`) for flow execution, validation, and operator listing
- Python library interface via `DocpipeFlowManager`
- PyArrow table format for all inter-operator data transfer
- JSON structured logging (`DS_LOG_JSON=True`) via `ConditionalFormatter`
- Sensitive data sanitisation (`sanitize_sensitive_data()`) in REST API calls
- Job run tracking with metadata aggregation
- `detect-secrets` pre-commit hook integration
- SonarQube, ruff, mypy, and Mend CI quality gates
- Comprehensive documentation under `docs/`

[Unreleased]: https://github.com/docling-project/docling-pipelines/compare/v2.0.1...HEAD
[2.0.1]: https://github.com/docling-project/docling-pipelines/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/docling-project/docling-pipelines/compare/v1.0.1...v2.0.0
[1.0.1]: https://github.com/docling-project/docling-pipelines/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/docling-project/docling-pipelines/releases/tag/v1.0.0
