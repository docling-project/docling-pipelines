# Tasks: Retrieval Observability & Offline Evaluation (Phase 3)

All tasks are `[backend]` and scoped to <= 2 hours each. Depends on `add-retrieval-service`.

- [ ] 1.1 `[backend]` Add pinned `prometheus-client` and optional `retrieval-eval = ["ragas==..."]` extra to `pyproject.toml`, run `uv lock`, and sync `.venv`.
- [ ] 1.2 `[backend]` Implement `MemoryEventStore` (`observability/events.py`), Prometheus `metrics.py` (with injectable `CollectorRegistry`), and lazy OTel wrapper `tracing.py` under `src/docpipe/core/retrieval/observability/`.
- [ ] 1.3 `[backend]` Instrument `SearchOrchestrator`, `SqlRetriever`, `VectorRetriever`, and `InferenceBridge` to emit lifecycle events, Prometheus metrics, and trace spans.
- [ ] 1.4 `[backend]` Implement `EvalService` (`application/eval_service.py`) with lazy `ragas` import and graceful `501` / no-op fallback when uninstalled.
- [ ] 1.5 `[backend]` Add DTOs and routes (`GET /v2/retrieval/metrics`, `GET /v2/retrieval/metrics/cachestats`, `GET /v2/retrieval/metrics/{request_id}`, `GET /v2/retrieval/events/{request_id}`, `POST /v2/retrieval/evaluate/offline`) in `retrieval_dto.py` and `routes/retrieval.py`.
- [ ] 1.6 `[backend]` Add unit and API tests in `tests/unit/core/retrieval/test_observability.py` and `tests/unit/api/routes/test_retrieval_observability.py`, then run `ruff`, `mypy`, `pytest`, and `openspec validate add-retrieval-observability-eval --strict`.
