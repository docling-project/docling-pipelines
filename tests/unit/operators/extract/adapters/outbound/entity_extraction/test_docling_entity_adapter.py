"""Unit tests for DoclingEntityAdapter — covering init, config validation,
get_config_schema, _build_vlm_extraction_options, extract_entities_single, and
the DoclingEntityExtractionService helper class."""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Docling is a core dependency and the adapter imports it lazily, so no
# import-time stubbing is needed. Tests that require fake Docling classes patch
# them locally via patch.dict(sys.modules, ...), which restores the real modules
# afterwards. Do not install module-level sys.modules stubs here: they leak into
# every later test in the session and break real `docling.*` imports.
from docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter import (
    DoclingEntityAdapter,
)
from docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_config import (
    DoclingEntityConfig,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_config():
    return {
        "provider": "docling",
        "doc_column": "doc_content",
        "output_column": "entities",
        "max_workers": 1,
    }


@pytest.fixture
def adapter(base_config):
    with patch("docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_inference_adapter"):
        return DoclingEntityAdapter(config=base_config)


# ---------------------------------------------------------------------------
# Init / config validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_adapter_initializes_without_vlm_pipeline(base_config):
    adapter = DoclingEntityAdapter(config=base_config)
    assert adapter.vlm_pipeline is None
    assert adapter.extraction_format_options is None


@pytest.mark.unit
def test_adapter_validate_rejects_invalid_doc_column():
    adapter = DoclingEntityAdapter(config={"provider": "docling"})
    with pytest.raises(ValueError, match="doc_column"):
        adapter.validate(config={"provider": "docling", "doc_column": 123})


@pytest.mark.unit
def test_adapter_validate_rejects_non_dict_vlm_pipeline():
    adapter = DoclingEntityAdapter(config={"provider": "docling"})
    with pytest.raises(ValueError, match="must be a dictionary"):
        adapter.validate(config={"provider": "docling", "vlm_pipeline": "not-a-dict"})


@pytest.mark.unit
def test_adapter_validate_rejects_invalid_model_type():
    adapter = DoclingEntityAdapter(config={"provider": "docling"})
    config = {
        "provider": "docling",
        "vlm_pipeline": {
            "model_type": "api",  # only 'inline' is allowed
            "inline_model": {"repo_id": "some/model"},
        },
    }
    with pytest.raises(ValueError, match="must be 'inline'"):
        adapter.validate(config=config)


@pytest.mark.unit
def test_adapter_validate_rejects_missing_inline_model():
    adapter = DoclingEntityAdapter(config={"provider": "docling"})
    with pytest.raises(ValueError, match=r"inline_model.*required"):
        adapter.validate(config={"provider": "docling", "vlm_pipeline": {"model_type": "inline"}})


@pytest.mark.unit
def test_adapter_validate_rejects_missing_repo_id():
    adapter = DoclingEntityAdapter(config={"provider": "docling"})
    config = {
        "provider": "docling",
        "vlm_pipeline": {
            "model_type": "inline",
            "inline_model": {},  # no repo_id
        },
    }
    with pytest.raises(ValueError, match=r"repo_id.*required"):
        adapter.validate(config=config)


@pytest.mark.unit
def test_adapter_validate_rejects_non_string_repo_id():
    adapter = DoclingEntityAdapter(config={"provider": "docling"})
    config = {
        "provider": "docling",
        "vlm_pipeline": {
            "model_type": "inline",
            "inline_model": {"repo_id": 42},
        },
    }
    with pytest.raises(ValueError, match=r"repo_id.*must be a string"):
        adapter.validate(config=config)


# ---------------------------------------------------------------------------
# get_config_schema
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_config_schema_returns_docling_entity_config():
    schema = DoclingEntityAdapter.get_config_schema()
    assert schema is DoclingEntityConfig


# ---------------------------------------------------------------------------
# _build_vlm_extraction_options
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_vlm_extraction_options_returns_none_for_empty_pipeline():
    result = DoclingEntityAdapter._build_vlm_extraction_options(vlm_pipeline=None)
    assert result is None


@pytest.mark.unit
def test_build_vlm_extraction_options_returns_none_for_non_inline_type():
    result = DoclingEntityAdapter._build_vlm_extraction_options(vlm_pipeline={"model_type": "api"})
    assert result is None


@pytest.mark.unit
def test_build_vlm_extraction_options_raises_on_import_error():
    # If Docling isn't installed, expect a ValueError wrapping ImportError
    with patch.dict(sys.modules, {"docling.datamodel.pipeline_options_vlm_model": None}):
        with pytest.raises((ValueError, ImportError)):
            DoclingEntityAdapter._build_vlm_extraction_options(
                vlm_pipeline={
                    "model_type": "inline",
                    "inline_model": {"repo_id": "some/model"},
                }
            )


# ---------------------------------------------------------------------------
# extract_entities_single — error paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extract_entities_single_returns_false_on_import_error(adapter):
    with patch.dict(sys.modules, {"docling.document_extractor": None}):
        result = adapter.extract_entities_single(
            doc_id="doc1",
            doc_name="test.pdf",
            content=b"PDF content",
        )
    # Should return a failure dict (ImportError caught)
    assert result.get("success") is False


@pytest.mark.unit
def test_extract_entities_single_returns_false_on_general_exception(adapter):
    with patch(
        "docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter.DoclingEntityAdapter.extract_entities_single",
        side_effect=Exception("boom"),
    ):
        # Call through the real method but mocked to raise
        pass  # We test the error path via the method's internal try/except

    # Test the actual error-handling path by mocking DocumentExtractor
    mock_extractor_cls = MagicMock()
    mock_extractor_cls.return_value.extract.side_effect = RuntimeError("extraction error")
    with patch.dict(
        sys.modules,
        {
            "docling.document_extractor": MagicMock(DocumentExtractor=mock_extractor_cls),
            "docling.datamodel.base_models": MagicMock(InputFormat=MagicMock()),
            "docling_core.types.io": MagicMock(DocumentStream=MagicMock()),
        },
    ):
        result = adapter.extract_entities_single(
            doc_id="doc1",
            doc_name="test.pdf",
            content=b"PDF content",
        )
    assert result.get("success") is False


# ---------------------------------------------------------------------------
# AdapterFactory registration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_docling_entity_adapter_is_registered_in_factory():
    from docpipe.core.operators.extract.adapters.outbound.factories.entity_extraction_adapter_factory import (
        EntityExtractionAdapterFactory,
    )

    assert "docling" in EntityExtractionAdapterFactory._registry


@pytest.mark.unit
def test_entity_extraction_factory_list_adapters_includes_docling():
    from docpipe.core.operators.extract.adapters.outbound.factories.entity_extraction_adapter_factory import (
        EntityExtractionAdapterFactory,
    )

    names = EntityExtractionAdapterFactory.list_adapters()
    assert "docling" in names


# ---------------------------------------------------------------------------
# DoclingEntityConfig schema
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_docling_entity_config_default_has_no_vlm_pipeline():
    cfg = DoclingEntityConfig()
    assert cfg.vlm_pipeline is None


@pytest.mark.unit
def test_docling_entity_config_accepts_vlm_pipeline():
    cfg = DoclingEntityConfig(vlm_pipeline={"model_type": "inline", "inline_model": {"repo_id": "some/model"}})
    assert cfg.vlm_pipeline is not None


@pytest.mark.unit
def test_docling_entity_config_ignores_extra_fields():
    cfg = DoclingEntityConfig(unknown_field="ignored")
    assert not hasattr(cfg, "unknown_field")


# ---------------------------------------------------------------------------
# _init_adapter_config — logging branches
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_adapter_init_with_inline_vlm_pipeline_logs_repo_id():
    """_init_adapter_config should not raise when a valid inline vlm_pipeline is given."""
    config = {
        "provider": "docling",
        "vlm_pipeline": {
            "model_type": "inline",
            "inline_model": {"repo_id": "some/model"},
        },
    }
    adapter = DoclingEntityAdapter(config=config)
    assert adapter.vlm_pipeline is not None
    # extraction_format_options is either a dict (docling installed) or None (not installed)
    assert adapter.extraction_format_options is None or isinstance(adapter.extraction_format_options, dict)


@pytest.mark.unit
def test_adapter_init_vlm_build_warning_on_import_error(base_config):
    """When _build_vlm_extraction_options raises, extraction_format_options stays None."""
    config = {
        **base_config,
        "vlm_pipeline": {
            "model_type": "inline",
            "inline_model": {"repo_id": "some/model"},
        },
    }
    with patch.object(
        DoclingEntityAdapter,
        "_build_vlm_extraction_options",
        side_effect=ValueError("VLM deps missing"),
    ):
        adapter = DoclingEntityAdapter(config=config)
    assert adapter.extraction_format_options is None


# ---------------------------------------------------------------------------
# validate — additional branches
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_adapter_validate_rejects_invalid_output_column():
    adapter = DoclingEntityAdapter(config={"provider": "docling"})
    with pytest.raises(ValueError, match="output_column"):
        adapter.validate(config={"provider": "docling", "output_column": 99})


@pytest.mark.unit
def test_adapter_validate_rejects_non_string_model_type():
    adapter = DoclingEntityAdapter(config={"provider": "docling"})
    config = {
        "provider": "docling",
        "vlm_pipeline": {"model_type": 42},
    }
    with pytest.raises(ValueError, match="must be a string"):
        adapter.validate(config=config)


@pytest.mark.unit
def test_adapter_validate_rejects_non_dict_inline_model():
    adapter = DoclingEntityAdapter(config={"provider": "docling"})
    config = {
        "provider": "docling",
        "vlm_pipeline": {
            "model_type": "inline",
            "inline_model": "not-a-dict",
        },
    }
    with pytest.raises(ValueError, match="must be a dictionary"):
        adapter.validate(config=config)


@pytest.mark.unit
def test_adapter_validate_passes_with_no_model_type():
    """vlm_pipeline with no model_type should not raise."""
    adapter = DoclingEntityAdapter(config={"provider": "docling"})
    # Should not raise
    adapter.validate(config={"provider": "docling", "vlm_pipeline": {}})


# ---------------------------------------------------------------------------
# _build_vlm_extraction_options — happy path with mocked docling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_vlm_extraction_options_inline_returns_dict():
    """With fully mocked Docling classes the inline path returns a dict."""
    mock_input_format = MagicMock()
    mock_input_format.PDF = "pdf"
    mock_input_format.IMAGE = "image"

    mock_extraction_option = MagicMock()
    mock_extractor_cls = MagicMock(return_value=mock_extraction_option)

    mocks = {
        "docling.backend.docling_parse_backend": MagicMock(DoclingParseDocumentBackend=MagicMock()),
        "docling.backend.pypdfium2_backend": MagicMock(PyPdfiumDocumentBackend=MagicMock()),
        "docling.datamodel.base_models": MagicMock(InputFormat=mock_input_format),
        "docling.datamodel.pipeline_options": MagicMock(VlmPipelineOptions=MagicMock()),
        "docling.datamodel.pipeline_options_vlm_model": MagicMock(InlineVlmOptions=MagicMock()),
        "docling.document_extractor": MagicMock(ExtractionFormatOption=mock_extractor_cls),
        "docling.pipeline.extraction_vlm_pipeline": MagicMock(ExtractionVlmPipeline=MagicMock()),
    }
    with patch.dict(sys.modules, mocks):
        result = DoclingEntityAdapter._build_vlm_extraction_options(
            vlm_pipeline={
                "model_type": "inline",
                "inline_model": {"repo_id": "some/model"},
            }
        )
    assert isinstance(result, dict)
    assert len(result) == 2


@pytest.mark.unit
def test_build_vlm_extraction_options_raises_on_general_exception():
    """A non-ImportError from inside the build path is re-raised as ValueError."""
    mocks = {
        "docling.backend.docling_parse_backend": MagicMock(DoclingParseDocumentBackend=MagicMock()),
        "docling.backend.pypdfium2_backend": MagicMock(PyPdfiumDocumentBackend=MagicMock()),
        "docling.datamodel.base_models": MagicMock(InputFormat=MagicMock()),
        "docling.datamodel.pipeline_options": MagicMock(VlmPipelineOptions=MagicMock(side_effect=RuntimeError("bad"))),
        "docling.datamodel.pipeline_options_vlm_model": MagicMock(InlineVlmOptions=MagicMock()),
        "docling.document_extractor": MagicMock(ExtractionFormatOption=MagicMock()),
        "docling.pipeline.extraction_vlm_pipeline": MagicMock(ExtractionVlmPipeline=MagicMock()),
    }
    with patch.dict(sys.modules, mocks):
        with pytest.raises(ValueError, match="Invalid VLM configuration"):
            DoclingEntityAdapter._build_vlm_extraction_options(
                vlm_pipeline={
                    "model_type": "inline",
                    "inline_model": {"repo_id": "some/model"},
                }
            )


# ---------------------------------------------------------------------------
# extract_entities_single — happy path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extract_entities_single_success(adapter):
    """Happy path: DocumentExtractor returns pages with extracted_data."""
    mock_page = MagicMock()
    mock_page.page_no = 1
    mock_page.extracted_data = {"field": "value"}
    mock_page.raw_text = None
    mock_page.errors = []

    mock_result = MagicMock()
    mock_result.pages = [mock_page]

    mock_extractor_instance = MagicMock()
    mock_extractor_instance.extract.return_value = mock_result
    mock_extractor_instance.extraction_format_to_options = {}

    mock_extractor_cls = MagicMock(return_value=mock_extractor_instance)

    mocks = {
        "docling.document_extractor": MagicMock(DocumentExtractor=mock_extractor_cls),
        "docling.datamodel.base_models": MagicMock(InputFormat=MagicMock(IMAGE="image", PDF="pdf")),
        "docling_core.types.io": MagicMock(DocumentStream=MagicMock()),
    }
    with patch.dict(sys.modules, mocks):
        result = adapter.extract_entities_single(
            doc_id="doc1",
            doc_name="test.pdf",
            content=b"binary content",
        )

    assert result["success"] is True
    assert len(result["entities"]) == 1
    assert result["entities"][0]["extracted_data"] == {"field": "value"}


@pytest.mark.unit
def test_extract_entities_single_parses_raw_text_json_when_extracted_data_is_none(adapter):
    """When extracted_data is None and raw_text contains JSON, it should be parsed."""
    mock_page = MagicMock()
    mock_page.page_no = 1
    mock_page.extracted_data = None
    mock_page.raw_text = '{"parsed": true}'
    mock_page.errors = []

    mock_result = MagicMock()
    mock_result.pages = [mock_page]

    mock_extractor_instance = MagicMock()
    mock_extractor_instance.extract.return_value = mock_result
    mock_extractor_instance.extraction_format_to_options = {}

    mocks = {
        "docling.document_extractor": MagicMock(DocumentExtractor=MagicMock(return_value=mock_extractor_instance)),
        "docling.datamodel.base_models": MagicMock(InputFormat=MagicMock()),
        "docling_core.types.io": MagicMock(DocumentStream=MagicMock()),
    }
    with patch.dict(sys.modules, mocks):
        result = adapter.extract_entities_single(
            doc_id="doc1",
            doc_name="test.pdf",
            content="text content",
        )

    assert result["success"] is True
    assert result["entities"][0]["extracted_data"] == {"parsed": True}


@pytest.mark.unit
def test_extract_entities_single_with_extraction_format_options(base_config):
    """When extraction_format_options is set, it is passed to DocumentExtractor."""
    mock_page = MagicMock()
    mock_page.page_no = 1
    mock_page.extracted_data = {}
    mock_page.raw_text = None
    mock_page.errors = []

    mock_result = MagicMock()
    mock_result.pages = [mock_page]

    mock_extractor_instance = MagicMock()
    mock_extractor_instance.extract.return_value = mock_result
    mock_extractor_instance.extraction_format_to_options = {}

    mock_extractor_cls = MagicMock(return_value=mock_extractor_instance)

    adapter = DoclingEntityAdapter(config=base_config)
    adapter.extraction_format_options = {"pdf": MagicMock()}  # simulate pre-built options

    mocks = {
        "docling.document_extractor": MagicMock(DocumentExtractor=mock_extractor_cls),
        "docling.datamodel.base_models": MagicMock(InputFormat=MagicMock(IMAGE="image", PDF="pdf")),
        "docling_core.types.io": MagicMock(DocumentStream=MagicMock()),
    }
    with patch.dict(sys.modules, mocks):
        result = adapter.extract_entities_single(
            doc_id="doc1",
            doc_name="test.pdf",
            content=b"content",
        )

    assert result["success"] is True
    # Verify DocumentExtractor was called with extraction_format_options
    call_kwargs = mock_extractor_cls.call_args.kwargs
    assert "extraction_format_options" in call_kwargs


@pytest.mark.unit
def test_extract_entities_single_reuses_pooled_extractor(base_config):
    """DocumentExtractor is built once per configuration and reused across documents and adapters."""
    mock_page = MagicMock(page_no=1, extracted_data={"k": "v"}, raw_text=None, errors=[])
    mock_extractor_cls = MagicMock(
        side_effect=lambda **_: MagicMock(
            extract=MagicMock(return_value=MagicMock(pages=[mock_page])), extraction_format_to_options={}
        )
    )
    mocks = {
        "docling.document_extractor": MagicMock(DocumentExtractor=mock_extractor_cls),
        "docling.datamodel.base_models": MagicMock(InputFormat=MagicMock(IMAGE="image", PDF="pdf")),
        "docling_core.types.io": MagicMock(DocumentStream=MagicMock()),
    }
    with patch.dict(sys.modules, mocks):
        for _ in range(2):  # two adapter instances, e.g. two micro-batches
            adapter = DoclingEntityAdapter(config=base_config)
            for idx in range(3):
                result = adapter.extract_entities_single(doc_id=f"d{idx}", doc_name="x.pdf", content=b"pdf")
                assert result["success"] is True

    assert mock_extractor_cls.call_count == 1


@pytest.mark.unit
def test_build_document_extractor_raises_runtime_error_without_docling_vlm():
    """A missing DocumentExtractor surfaces as a RuntimeError with an install hint."""
    with patch.dict(sys.modules, {"docling.document_extractor": None}):
        with pytest.raises(RuntimeError, match="DocumentExtractor is not available"):
            DoclingEntityAdapter._build_document_extractor(allowed_formats=["pdf"], extraction_format_options=None)


@pytest.mark.unit
def test_extract_entities_single_reports_missing_document_extractor(base_config):
    """extract_entities_single returns a failed result when DocumentExtractor cannot be imported."""
    mocks = {
        "docling.document_extractor": None,
        "docling.datamodel.base_models": MagicMock(InputFormat=MagicMock(IMAGE="image", PDF="pdf")),
        "docling_core.types.io": MagicMock(DocumentStream=MagicMock()),
    }
    with patch.dict(sys.modules, mocks):
        result = DoclingEntityAdapter(config=base_config).extract_entities_single(
            doc_id="d1", doc_name="x.pdf", content=b"pdf"
        )

    assert result["success"] is False
    assert "DocumentExtractor is not available" in result["error"]


# ---------------------------------------------------------------------------
# transform
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_transform_delegates_to_service(adapter):
    """transform() creates DoclingEntityExtractionService and delegates to it."""
    import pyarrow as pa

    from docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter import (
        DoclingEntityExtractionService,
    )

    table = pa.table({"id": ["d1"], "name": ["f.pdf"], "doc_content": ["text"]})
    metadata: dict = {}

    expected_table = pa.table({"id": ["d1"], "entities": [None]})
    with patch.object(
        DoclingEntityExtractionService,
        "transform",
        return_value=([expected_table], metadata),
    ) as mock_transform:
        result_tables, _result_meta = adapter.transform(table=table, metadata=metadata)

    mock_transform.assert_called_once_with(table=table, metadata=metadata)
    assert result_tables[0] is expected_table


# ---------------------------------------------------------------------------
# _prepare_document_tasks (adapter-level)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_adapter_prepare_document_tasks(adapter):
    """_prepare_document_tasks merges document_type into each task dict."""
    import pyarrow as pa

    table = pa.table({"id": ["d1", "d2"], "name": ["a.pdf", "b.pdf"], "path": ["/a.pdf", "/b.pdf"]})
    document_types = ["invoice", "receipt"]

    fake_tasks = [
        {"idx": 0, "doc_id": "d1", "doc_name": "a.pdf", "content": b""},
        {"idx": 1, "doc_id": "d2", "doc_name": "b.pdf", "content": b""},
    ]
    with patch(
        "docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter.OperatorUtils.prepare_document_content_fetch",
        return_value=fake_tasks,
    ):
        tasks = adapter._prepare_document_tasks(table, document_types, {})

    assert tasks[0]["document_type"] == "invoice"
    assert tasks[1]["document_type"] == "receipt"


@pytest.mark.unit
def test_adapter_prepare_document_tasks_empty_document_types(adapter):
    """When document_types is empty, document_type is set to None."""
    import pyarrow as pa

    table = pa.table({"id": ["d1"], "name": ["a.pdf"], "path": ["/a.pdf"]})
    fake_tasks = [{"idx": 0, "doc_id": "d1", "doc_name": "a.pdf", "content": b""}]

    with patch(
        "docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter.OperatorUtils.prepare_document_content_fetch",
        return_value=fake_tasks,
    ):
        tasks = adapter._prepare_document_tasks(table, [], {})

    assert tasks[0]["document_type"] is None


# ---------------------------------------------------------------------------
# _load_schema_templates (adapter-level)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_adapter_load_schema_templates(adapter):
    """_load_schema_templates populates schema_templates via DocumentClassUtils."""
    with patch(
        "docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter.DocumentClassUtils.generate_docling_templates_for_types",
        return_value={"invoice": {"fields": []}},
    ):
        schema_templates: dict = {}
        adapter._load_schema_templates(document_types=["invoice"], schema_templates=schema_templates)

    assert "invoice" in schema_templates


# ---------------------------------------------------------------------------
# DoclingEntityExtractionService
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_docling_entity_extraction_service_init(adapter):
    """DoclingEntityExtractionService stores global_config."""
    from docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter import (
        DoclingEntityExtractionService,
    )

    service = DoclingEntityExtractionService(
        adapter=adapter,
        config={"doc_column": "doc_content"},
        max_workers=2,
        job_run_id="job-1",
        node_id="node-1",
        node_name="ExtractOperator",
        batch_id="batch-1",
        global_config={"storage": "local"},
    )
    assert service.global_config == {"storage": "local"}


@pytest.mark.unit
def test_docling_entity_extraction_service_default_global_config(adapter):
    """global_config defaults to empty dict when not provided."""
    from docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter import (
        DoclingEntityExtractionService,
    )

    service = DoclingEntityExtractionService(
        adapter=adapter,
        config={"doc_column": "doc_content"},
    )
    assert service.global_config == {}


@pytest.mark.unit
def test_service_prepare_document_tasks_merges_document_type(adapter):
    """Service._prepare_document_tasks merges document_type into tasks."""
    import pyarrow as pa

    from docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter import (
        DoclingEntityExtractionService,
    )

    service = DoclingEntityExtractionService(
        adapter=adapter,
        config={"doc_column": "doc_content"},
        global_config={},
    )

    table = pa.table({"id": ["d1", "d2"], "name": ["a.pdf", "b.pdf"], "path": ["/a.pdf", "/b.pdf"]})
    fake_tasks = [
        {"idx": 0, "doc_id": "d1", "doc_name": "a.pdf", "content": b""},
        {"idx": 1, "doc_id": "d2", "doc_name": "b.pdf", "content": b""},
    ]
    with patch(
        "docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter.OperatorUtils.prepare_document_content_fetch",
        return_value=fake_tasks,
    ):
        tasks = service._prepare_document_tasks(table, ["invoice", "receipt"], {})

    assert tasks[0]["document_type"] == "invoice"
    assert tasks[1]["document_type"] == "receipt"


@pytest.mark.unit
def test_service_load_schema_templates(adapter):
    """Service._load_schema_templates delegates to DocumentClassUtils."""
    from docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter import (
        DoclingEntityExtractionService,
    )

    service = DoclingEntityExtractionService(
        adapter=adapter,
        config={"doc_column": "doc_content"},
    )

    with patch(
        "docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter.DocumentClassUtils.generate_docling_templates_for_types",
        return_value={"invoice": {"fields": []}},
    ):
        schema_templates: dict = {}
        service._load_schema_templates(document_types=["invoice"], schema_templates=schema_templates)

    assert "invoice" in schema_templates
