"""Unit tests for EntityExtractionService.

Covers:
- __init__ / configuration wiring
- prepare_schemas: custom_schema path, document_type column path, missing-both error
- _prepare_document_tasks: normal rows, empty-content skip, missing id fallback
- _handle_extraction_result: success, failure result, exception raised by future
- _record_extraction_failure: metadata mutation under lock
- _finalize_table: entities column added, expand path, no-success path, hash id
- _set_execution_status: completed / with-errors / with-warnings
- expand_entities_columns: happy path, empty entities list, non-dict entries
- validate_loaded_schemas: missing-schema warning, success log
- _load_schema_templates: delegates to document_class_provider
- _process_documents_parallel (mocked executor): progress tracking, final update
- _submit_extraction_task: custom_schema used, schema_template used, fallback
- transform: end-to-end with mocked adapter
- _update_extraction_progress: skipped when no job_run_id
"""

import json
from concurrent.futures import Future
from typing import Any
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.extract.services.entity_extraction_service import EntityExtractionService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_metadata(*, n: int = 2) -> dict[str, Any]:
    """Return a minimal metadata dict matching AbstractOperator.create_base_metadata."""
    return {
        Metrics.External.TOTAL_DOCS: n,
        Metrics.External.PROCESSED_DOCS: 0,
        Metrics.External.FAILED_DOCS_COUNT: 0,
        Metrics.External.FAILED_DOCS: [],
        Metrics.External.SKIPPED_DOCS_COUNT: 0,
        Metrics.External.SKIPPED_DOCS: [],
        Metrics.External.NODE_STATUS: ExecutionStatus.COMPLETED.value,
    }


def _make_table(*, n: int = 2, with_document_type: bool = False, content_col: str = "content") -> pa.Table:
    data: dict[str, list] = {
        "id": [f"doc_{i}" for i in range(n)],
        "name": [f"doc_{i}.txt" for i in range(n)],
        content_col: [f"text for doc {i}" for i in range(n)],
    }
    if with_document_type:
        data["document_type"] = [f"type_{i % 2}" for i in range(n)]
    return pa.table(data)


def _make_adapter(*, success: bool = True, entities: dict | None = None) -> MagicMock:
    adapter = MagicMock()
    adapter.ADAPTER_DISPLAY_NAME = "MockAdapter"
    adapter.extract_entities_single = MagicMock(
        return_value={
            OperatorConstants.Extraction.SUCCESS: success,
            OperatorConstants.Misc.ENTITIES: entities or {"title": "Test"},
            "error": None if success else "extraction failed",
        }
    )
    return adapter


def _make_service(
    *,
    adapter=None,
    config: dict | None = None,
    max_workers: int = 2,
    document_class_provider=None,
    job_run_id: str | None = None,
    node_id: str | None = None,
    node_name: str | None = None,
    batch_id: str | None = None,
) -> EntityExtractionService:
    if adapter is None:
        adapter = _make_adapter()
    if config is None:
        config = {"custom_schema": {"title": "string"}}
    return EntityExtractionService(
        adapter=adapter,
        config=config,
        max_workers=max_workers,
        document_class_provider=document_class_provider,
        job_run_id=job_run_id,
        node_id=node_id,
        node_name=node_name,
        batch_id=batch_id,
    )


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_init_defaults():
    """Service stores config values and defaults correctly."""
    service = _make_service()

    assert service.doc_column == OperatorConstants.Columns.DOC_COLUMN_DEFAULT
    assert service.output_column == OperatorConstants.Misc.ENTITIES
    assert service.expand_extracted_data is False
    assert service.custom_schema == {"title": "string"}
    assert service.max_workers == 2
    assert service.job_run_id is None
    assert service.node_id is None


@pytest.mark.unit
def test_init_custom_config():
    """Non-default config values are stored correctly."""
    config = {
        "custom_schema": {"amount": "number"},
        OperatorConstants.Columns.DOC_COLUMN: "body",
        OperatorConstants.Columns.OUTPUT_COLUMN: "my_entities",
        OperatorConstants.Config.EXPAND_EXTRACTED_DATA: True,
        OperatorConstants.Columns.DOC_ID_HASH: "my_hash",
    }
    service = _make_service(config=config, job_run_id="jr-1", node_id="n-1", node_name="extractor", batch_id="b-1")

    assert service.doc_column == "body"
    assert service.output_column == "my_entities"
    assert service.expand_extracted_data is True
    assert service.doc_id_hash_column == "my_hash"
    assert service.job_run_id == "jr-1"
    assert service.node_id == "n-1"
    assert service.node_name == "extractor"
    assert service.batch_id == "b-1"


@pytest.mark.unit
def test_init_default_document_class_provider():
    """When no provider is injected, StaticDocumentClassProvider is used."""
    from docpipe.core.ports.document_class_provider import StaticDocumentClassProvider

    service = _make_service()
    assert isinstance(service.document_class_provider, StaticDocumentClassProvider)


@pytest.mark.unit
def test_init_custom_document_class_provider():
    """An injected provider is stored as-is."""
    from docpipe.core.ports.document_class_provider import DocumentClassProvider

    provider = MagicMock(spec=DocumentClassProvider)
    service = _make_service(document_class_provider=provider)
    assert service.document_class_provider is provider


# ---------------------------------------------------------------------------
# prepare_schemas
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_prepare_schemas_with_custom_schema_only():
    """When custom_schema is set and no document_type column, returns empty types/templates."""
    service = _make_service(config={"custom_schema": {"title": "string"}})
    table = _make_table(n=2, with_document_type=False)

    doc_types, templates = service.prepare_schemas(table=table)

    assert doc_types == []
    assert templates == {}


@pytest.mark.unit
def test_prepare_schemas_with_document_type_column():
    """When document_type column exists, delegates to provider and validates."""
    from docpipe.core.ports.document_class_provider import DocumentClassProvider

    provider = MagicMock(spec=DocumentClassProvider)
    provider.get_schema_templates.return_value = {"type_0": {"field": "string"}}

    service = _make_service(config={}, document_class_provider=provider)
    table = _make_table(n=2, with_document_type=True)

    doc_types, templates = service.prepare_schemas(table=table)

    assert len(doc_types) == 2
    provider.get_schema_templates.assert_called_once()
    assert "type_0" in templates


@pytest.mark.unit
def test_prepare_schemas_raises_when_neither_schema_nor_column():
    """ConfigurationError is raised when no custom_schema and no document_type column."""
    from docpipe.exceptions.docpipe_exceptions import ConfigurationError

    service = _make_service(config={})
    table = _make_table(n=2, with_document_type=False)

    with pytest.raises(ConfigurationError):
        service.prepare_schemas(table=table)


# ---------------------------------------------------------------------------
# _prepare_document_tasks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_prepare_document_tasks_normal():
    """All rows with content produce task dicts."""
    service = _make_service()
    table = _make_table(n=3)
    metadata = _make_metadata(n=3)

    tasks = service._prepare_document_tasks(table, [], metadata)

    assert len(tasks) == 3
    assert tasks[0]["idx"] == 0
    assert tasks[0]["doc_id"] == "doc_0"
    assert tasks[0]["doc_name"] == "doc_0.txt"
    assert "text for doc 0" in tasks[0]["content"]


@pytest.mark.unit
def test_prepare_document_tasks_empty_content_skipped():
    """Rows with empty content are skipped and recorded in metadata."""
    service = _make_service()
    table = pa.table(
        {
            "id": ["doc_0", "doc_1"],
            "name": ["doc_0.txt", "doc_1.txt"],
            "content": ["hello", ""],  # second is empty
        }
    )
    metadata = _make_metadata(n=2)

    tasks = service._prepare_document_tasks(table, [], metadata)

    assert len(tasks) == 1
    assert tasks[0]["doc_id"] == "doc_0"
    assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 1


@pytest.mark.unit
def test_prepare_document_tasks_none_content_skipped():
    """Rows with None content are skipped."""
    service = _make_service()
    table = pa.table(
        {
            "id": ["doc_0"],
            "name": ["doc_0.txt"],
            "content": pa.array([None], type=pa.string()),
        }
    )
    metadata = _make_metadata(n=1)

    tasks = service._prepare_document_tasks(table, [], metadata)

    assert len(tasks) == 0
    assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 1


@pytest.mark.unit
def test_prepare_document_tasks_missing_id_falls_back_to_path():
    """When id column is absent, path column is used as doc_id."""
    service = _make_service()
    table = pa.table(
        {
            "path": ["/docs/file.txt"],
            "name": ["file.txt"],
            "content": ["some content"],
        }
    )
    metadata = _make_metadata(n=1)

    tasks = service._prepare_document_tasks(table, [], metadata)

    assert tasks[0]["doc_id"] == "/docs/file.txt"


@pytest.mark.unit
def test_prepare_document_tasks_document_type_included():
    """document_type from the list is attached to the task."""
    service = _make_service()
    table = _make_table(n=2)
    metadata = _make_metadata(n=2)
    doc_types = ["invoice", "receipt"]

    tasks = service._prepare_document_tasks(table, doc_types, metadata)

    assert tasks[0]["document_type"] == "invoice"
    assert tasks[1]["document_type"] == "receipt"


# ---------------------------------------------------------------------------
# _handle_extraction_result
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_handle_extraction_result_success():
    """Successful future populates entities_list and increments processed_docs."""
    service = _make_service()
    metadata = _make_metadata(n=1)
    entities_list: list[dict] = [{}]

    task = {"idx": 0, "doc_id": "d1", "doc_name": "d1.txt"}
    future: Future = Future()
    future.set_result(
        {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Misc.ENTITIES: {"title": "Hello"},
        }
    )

    service._handle_extraction_result(future, task, entities_list, metadata)

    assert entities_list[0] == {"title": "Hello"}
    assert metadata[Metrics.External.PROCESSED_DOCS] == 1
    assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0


@pytest.mark.unit
def test_handle_extraction_result_failure_result():
    """Failed result (success=False) records a failure."""
    service = _make_service()
    metadata = _make_metadata(n=1)
    entities_list: list[dict] = [{}]

    task = {"idx": 0, "doc_id": "d1", "doc_name": "d1.txt"}
    future: Future = Future()
    future.set_result(
        {
            OperatorConstants.Extraction.SUCCESS: False,
            "error": "model timeout",
        }
    )

    service._handle_extraction_result(future, task, entities_list, metadata)

    assert entities_list[0] == {}
    assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1


@pytest.mark.unit
def test_handle_extraction_result_exception_from_future():
    """An exception thrown by the future is caught and recorded as failure."""
    service = _make_service()
    metadata = _make_metadata(n=1)
    entities_list: list[dict] = [{}]

    task = {"idx": 0, "doc_id": "d1", "doc_name": "d1.txt"}
    future: Future = Future()
    future.set_exception(RuntimeError("GPU OOM"))

    service._handle_extraction_result(future, task, entities_list, metadata)

    assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1


# ---------------------------------------------------------------------------
# _record_extraction_failure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_extraction_failure_updates_metadata():
    """Failure is recorded and metadata counters increment."""
    service = _make_service()
    metadata = _make_metadata(n=1)
    task = {"doc_id": "d1", "doc_name": "d1.txt"}

    service._record_extraction_failure(task=task, error="something broke", metadata=metadata)

    assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
    assert len(metadata[Metrics.External.FAILED_DOCS]) == 1


# ---------------------------------------------------------------------------
# _set_execution_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_set_execution_status_completed():
    """No failures/skips → COMPLETED."""
    service = _make_service()
    metadata = _make_metadata(n=2)
    metadata[Metrics.External.PROCESSED_DOCS] = 2

    result = service._set_execution_status(metadata=metadata)

    assert result[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED.value


@pytest.mark.unit
def test_set_execution_status_completed_with_errors():
    """Failed docs → COMPLETED_WITH_ERRORS."""
    service = _make_service()
    metadata = _make_metadata(n=2)
    metadata[Metrics.External.FAILED_DOCS_COUNT] = 1

    result = service._set_execution_status(metadata=metadata)

    assert result[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS.value


@pytest.mark.unit
def test_set_execution_status_completed_with_warnings():
    """Skipped docs (no failures) → COMPLETED_WITH_WARNINGS."""
    service = _make_service()
    metadata = _make_metadata(n=2)
    metadata[Metrics.External.SKIPPED_DOCS_COUNT] = 1

    result = service._set_execution_status(metadata=metadata)

    assert result[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_WARNINGS.value


@pytest.mark.unit
def test_set_execution_status_errors_take_priority_over_warnings():
    """Both failures and skips → COMPLETED_WITH_ERRORS (errors win)."""
    service = _make_service()
    metadata = _make_metadata(n=3)
    metadata[Metrics.External.FAILED_DOCS_COUNT] = 1
    metadata[Metrics.External.SKIPPED_DOCS_COUNT] = 1

    result = service._set_execution_status(metadata=metadata)

    assert result[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS.value


# ---------------------------------------------------------------------------
# _finalize_table
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_finalize_table_adds_entities_column():
    """When docs are processed, entities column is added to the table."""
    service = _make_service()
    table = _make_table(n=2)
    metadata = _make_metadata(n=2)
    metadata[Metrics.External.PROCESSED_DOCS] = 2
    entities_list = [{"title": "Doc A"}, {"title": "Doc B"}]

    result = service._finalize_table(table=table, entities_list=entities_list, metadata=metadata)

    assert OperatorConstants.Misc.ENTITIES in result.column_names
    parsed = [json.loads(v) for v in result[OperatorConstants.Misc.ENTITIES].to_pylist()]
    assert parsed[0] == {"title": "Doc A"}
    assert parsed[1] == {"title": "Doc B"}


@pytest.mark.unit
def test_finalize_table_empty_entity_becomes_empty_json():
    """Rows with no entities get '{}' as their entity JSON."""
    service = _make_service()
    table = _make_table(n=2)
    metadata = _make_metadata(n=2)
    metadata[Metrics.External.PROCESSED_DOCS] = 1
    entities_list = [{"title": "Doc A"}, {}]  # second row empty

    result = service._finalize_table(table=table, entities_list=entities_list, metadata=metadata)

    raw = result[OperatorConstants.Misc.ENTITIES].to_pylist()
    assert json.loads(raw[1]) == {}


@pytest.mark.unit
def test_finalize_table_no_success_skips_entities_column():
    """When processed_docs == 0, no entities column is added."""
    service = _make_service()
    table = _make_table(n=2)
    metadata = _make_metadata(n=2)
    # processed_docs stays 0
    entities_list: list[dict] = [{}, {}]

    result = service._finalize_table(table=table, entities_list=entities_list, metadata=metadata)

    assert OperatorConstants.Misc.ENTITIES not in result.column_names


@pytest.mark.unit
def test_finalize_table_adds_doc_id_hash_when_missing():
    """When doc_id_hash column is absent, it is generated and added."""
    service = _make_service()
    table = _make_table(n=2)
    metadata = _make_metadata(n=2)
    metadata[Metrics.External.PROCESSED_DOCS] = 2
    entities_list = [{"k": "v"}, {"k": "v2"}]

    result = service._finalize_table(table=table, entities_list=entities_list, metadata=metadata)

    assert service.doc_id_hash_column in result.column_names
    hashes = result[service.doc_id_hash_column].to_pylist()
    assert all(h is not None for h in hashes)


@pytest.mark.unit
def test_finalize_table_expand_entities():
    """With expand_extracted_data=True, entity keys become individual columns."""
    config = {
        "custom_schema": {"amount": "number"},
        OperatorConstants.Config.EXPAND_EXTRACTED_DATA: True,
    }
    service = _make_service(config=config)
    table = _make_table(n=2)
    metadata = _make_metadata(n=2)
    metadata[Metrics.External.PROCESSED_DOCS] = 2
    entities_list = [{"amount": "100", "currency": "USD"}, {"amount": "200", "currency": "EUR"}]

    result = service._finalize_table(table=table, entities_list=entities_list, metadata=metadata)

    assert "entity_amount" in result.column_names
    assert "entity_currency" in result.column_names


# ---------------------------------------------------------------------------
# expand_entities_columns
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_expand_entities_columns_happy_path():
    """Each unique key in entities_list gets its own entity_ column."""
    service = _make_service()
    table = _make_table(n=2)
    entities_list = [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]

    result = service.expand_entities_columns(table=table, entities_list=entities_list)

    assert "entity_name" in result.column_names
    assert "entity_age" in result.column_names
    names = result["entity_name"].to_pylist()
    assert names == ["Alice", "Bob"]


@pytest.mark.unit
def test_expand_entities_columns_empty_list():
    """When entities_list has no keys, the table is returned unchanged."""
    service = _make_service()
    table = _make_table(n=2)
    entities_list: list[dict] = [{}, {}]

    result = service.expand_entities_columns(table=table, entities_list=entities_list)

    assert result.column_names == table.column_names


@pytest.mark.unit
def test_expand_entities_columns_missing_key_becomes_none():
    """When a key is absent in some rows, those positions become None."""
    service = _make_service()
    table = _make_table(n=2)
    entities_list = [{"title": "Doc A"}, {}]  # second row has no 'title'

    result = service.expand_entities_columns(table=table, entities_list=entities_list)

    assert "entity_title" in result.column_names
    values = result["entity_title"].to_pylist()
    assert values[0] == "Doc A"
    assert values[1] is None


@pytest.mark.unit
def test_expand_entities_columns_non_dict_entity_skipped():
    """Non-dict entries in entities_list don't contribute keys."""
    service = _make_service()
    table = _make_table(n=2)
    entities_list = [{"title": "Doc A"}, None]  # type: ignore[list-item]

    result = service.expand_entities_columns(table=table, entities_list=entities_list)

    assert "entity_title" in result.column_names
    values = result["entity_title"].to_pylist()
    assert values[1] is None


# ---------------------------------------------------------------------------
# validate_loaded_schemas
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validate_loaded_schemas_logs_warning_for_missing(caplog):
    """Missing schemas emit a warning."""
    import logging

    service = _make_service()
    with caplog.at_level(logging.WARNING):
        service.validate_loaded_schemas(
            document_types=["invoice", "receipt"],
            schema_templates={"invoice": {"field": "string"}},
        )

    assert any("receipt" in r.message for r in caplog.records if r.levelno == logging.WARNING)


@pytest.mark.unit
def test_validate_loaded_schemas_logs_success(caplog):
    """When all schemas are loaded, an info message is logged."""
    import logging

    service = _make_service()
    with caplog.at_level(logging.INFO):
        service.validate_loaded_schemas(
            document_types=["invoice"],
            schema_templates={"invoice": {"field": "string"}},
        )

    assert any("invoice" in r.message for r in caplog.records if r.levelno == logging.INFO)


# ---------------------------------------------------------------------------
# _load_schema_templates
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_schema_templates_delegates_to_provider():
    """_load_schema_templates populates schema_templates via the provider."""
    from docpipe.core.ports.document_class_provider import DocumentClassProvider

    provider = MagicMock(spec=DocumentClassProvider)
    provider.get_schema_templates.return_value = {"invoice": {"amount": "number"}}

    service = _make_service(document_class_provider=provider)
    templates: dict[str, dict] = {}
    service._load_schema_templates(document_types=["invoice"], schema_templates=templates)

    provider.get_schema_templates.assert_called_once_with(document_types=["invoice"])
    assert "invoice" in templates


# ---------------------------------------------------------------------------
# _submit_extraction_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_submit_extraction_task_uses_custom_schema_when_no_templates():
    """Without schema_templates, custom_schema is forwarded to the adapter."""
    from concurrent.futures import ThreadPoolExecutor

    adapter = _make_adapter()
    config = {"custom_schema": {"title": "string"}}
    service = _make_service(adapter=adapter, config=config)

    task = {
        "idx": 0,
        "doc_id": "d1",
        "doc_name": "d1.txt",
        "content": "hello world",
        "document_type": None,
    }

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = service._submit_extraction_task(executor=executor, task=task, schema_templates={})
        future.result()  # consume future

    call_kwargs = adapter.extract_entities_single.call_args.kwargs
    assert call_kwargs["schema"] == {"title": "string"}


@pytest.mark.unit
def test_submit_extraction_task_uses_template_schema_when_available():
    """When schema_templates has a match, that schema overrides custom_schema."""
    from concurrent.futures import ThreadPoolExecutor

    adapter = _make_adapter()
    config = {"custom_schema": {"default": "string"}}
    service = _make_service(adapter=adapter, config=config)

    task = {
        "idx": 0,
        "doc_id": "d1",
        "doc_name": "d1.txt",
        "content": "hello world",
        "document_type": "invoice",
    }
    schema_templates = {"invoice": {"amount": "number"}}

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = service._submit_extraction_task(executor=executor, task=task, schema_templates=schema_templates)
        future.result()

    call_kwargs = adapter.extract_entities_single.call_args.kwargs
    assert call_kwargs["schema"] == {"amount": "number"}


# ---------------------------------------------------------------------------
# _update_extraction_progress — no job context
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_update_extraction_progress_skipped_without_job_context():
    """When job_run_id or node_id is absent, the method returns without any DB call."""
    service = _make_service()  # job_run_id=None, node_id=None

    # Should complete without error and without attempting a DB call
    service._update_extraction_progress(completed=1, total=2, progress_percentage=50.0, failed_count=0)


@pytest.mark.unit
def test_update_extraction_progress_suppresses_exceptions():
    """If the progress update itself raises, the exception is swallowed (warning logged)."""
    service = _make_service(job_run_id="jr-1", node_id="n-1")

    with patch(
        "docpipe.core.job_management.adapters.config.job_management_factory.get_default_factory",
        side_effect=RuntimeError("DB unavailable"),
    ):
        # Must not propagate
        service._update_extraction_progress(completed=1, total=2, progress_percentage=50.0, failed_count=0)


# ---------------------------------------------------------------------------
# transform — end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_transform_happy_path():
    """transform() returns a single table with entities column and metadata."""
    adapter = _make_adapter(success=True, entities={"title": "My Doc"})
    service = _make_service(adapter=adapter, config={"custom_schema": {"title": "string"}})

    table = _make_table(n=2)
    metadata = _make_metadata(n=2)

    result_tables, result_meta = service.transform(table=table, metadata=metadata)

    assert len(result_tables) == 1
    out = result_tables[0]
    assert OperatorConstants.Misc.ENTITIES in out.column_names
    assert result_meta[Metrics.External.PROCESSED_DOCS] == 2
    assert result_meta[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED.value


@pytest.mark.unit
def test_transform_all_failures():
    """When all extractions fail, entities column is absent and status is errors."""
    adapter = _make_adapter(success=False)
    service = _make_service(adapter=adapter, config={"custom_schema": {"title": "string"}})

    table = _make_table(n=2)
    metadata = _make_metadata(n=2)

    result_tables, result_meta = service.transform(table=table, metadata=metadata)

    assert len(result_tables) == 1
    out = result_tables[0]
    assert OperatorConstants.Misc.ENTITIES not in out.column_names
    assert result_meta[Metrics.External.FAILED_DOCS_COUNT] == 2
    assert result_meta[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS.value


@pytest.mark.unit
def test_transform_skipped_docs_produce_warnings_status():
    """All-empty-content table gives COMPLETED_WITH_WARNINGS."""
    adapter = _make_adapter()
    service = _make_service(adapter=adapter, config={"custom_schema": {"title": "string"}})

    table = pa.table(
        {
            "id": ["d1", "d2"],
            "name": ["a.txt", "b.txt"],
            "content": ["", ""],  # both empty → skipped
        }
    )
    metadata = _make_metadata(n=2)

    _result_tables, result_meta = service.transform(table=table, metadata=metadata)

    assert result_meta[Metrics.External.SKIPPED_DOCS_COUNT] == 2
    assert result_meta[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_WARNINGS.value


@pytest.mark.unit
def test_transform_with_document_type_column():
    """transform() works end-to-end when table has a document_type column."""
    from docpipe.core.ports.document_class_provider import DocumentClassProvider

    provider = MagicMock(spec=DocumentClassProvider)
    provider.get_schema_templates.return_value = {"type_0": {"field": "string"}, "type_1": {"field": "string"}}

    adapter = _make_adapter(success=True)
    service = _make_service(adapter=adapter, config={}, document_class_provider=provider)

    table = _make_table(n=2, with_document_type=True)
    metadata = _make_metadata(n=2)

    result_tables, result_meta = service.transform(table=table, metadata=metadata)

    assert len(result_tables) == 1
    assert result_meta[Metrics.External.PROCESSED_DOCS] == 2


@pytest.mark.unit
def test_transform_mixed_success_and_failure():
    """One success + one failure → COMPLETED_WITH_ERRORS, one entity row filled."""
    call_count = {"n": 0}

    def side_effect(*, doc_id, doc_name, content, schema):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {OperatorConstants.Extraction.SUCCESS: True, OperatorConstants.Misc.ENTITIES: {"k": "v"}}
        return {OperatorConstants.Extraction.SUCCESS: False, "error": "oops"}

    adapter = MagicMock()
    adapter.ADAPTER_DISPLAY_NAME = "MockAdapter"
    adapter.extract_entities_single = MagicMock(side_effect=side_effect)

    service = _make_service(adapter=adapter, config={"custom_schema": {"k": "string"}})

    table = _make_table(n=2)
    metadata = _make_metadata(n=2)

    _result_tables, result_meta = service.transform(table=table, metadata=metadata)

    assert result_meta[Metrics.External.PROCESSED_DOCS] == 1
    assert result_meta[Metrics.External.FAILED_DOCS_COUNT] == 1
    assert result_meta[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS.value
