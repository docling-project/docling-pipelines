from unittest.mock import Mock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import Metrics
from docpipe.core.operators.functional.summarization import SummarizationOperator
from docpipe.core.operators.functional.summarization_service import SummarizationService
from docpipe.exceptions.docpipe_exceptions import DocpipeException


def _config(**overrides):
    config = {
        "provider": "litellm",
        "provider_config": {"model_id": "test-model"},
    }
    config.update(overrides)
    return config


def _operator(adapter: Mock, **overrides) -> SummarizationOperator:
    with patch(
        "docpipe.core.operators.functional.summarization.LLMAdapterFactory.create_inference_adapter",
        return_value=adapter,
    ):
        return SummarizationOperator(_config(**overrides))


def _adapter(*responses: str) -> Mock:
    adapter = Mock()
    adapter.validate.return_value = {"valid": True}
    adapter.chat.side_effect = responses
    return adapter


def test_short_content_adds_summary_and_preserves_columns():
    operator = _operator(_adapter("A short summary."))
    table = pa.table({"id": ["1"], "name": ["doc"], "content": ["Source text."], "extra": [7]})

    outputs, metadata = operator.transform(table)

    assert outputs[0].column_names == ["id", "name", "content", "extra", "summary"]
    assert outputs[0]["summary"].to_pylist() == ["A short summary."]
    assert outputs[0]["extra"].to_pylist() == [7]
    assert metadata[Metrics.External.PROCESSED_DOCS] == 1


def test_empty_content_is_skipped():
    adapter = _adapter("unused")
    operator = _operator(adapter)
    table = pa.table({"id": ["1"], "name": ["doc"], "content": ["  "]})

    outputs, metadata = operator.transform(table)

    assert outputs[0]["summary"].to_pylist() == [None]
    assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 1
    adapter.chat.assert_not_called()


def test_null_content_is_skipped():
    adapter = _adapter("unused")
    operator = _operator(adapter)
    table = pa.table({"content": pa.array([None], type=pa.string())})

    outputs, metadata = operator.transform(table)

    assert outputs[0]["summary"].to_pylist() == [None]
    assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 1
    adapter.chat.assert_not_called()


def test_missing_content_column_fails_explicitly():
    operator = _operator(_adapter("unused"))

    with pytest.raises(DocpipeException, match="Required column 'content'"):
        operator.transform(pa.table({"id": ["1"]}))


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"provider": "litellm"},
        {"provider": "litellm", "provider_config": {}},
        {"provider": "litellm", "provider_config": {"model_id": "m"}, "max_input_tokens": 0},
    ],
)
def test_invalid_configuration_is_rejected(config):
    with patch(
        "docpipe.core.operators.functional.summarization.LLMAdapterFactory.create_inference_adapter"
    ):
        with pytest.raises(DocpipeException):
            SummarizationOperator(config)


def test_long_content_uses_sentence_aware_map_reduce():
    adapter = _adapter("First partial.", "Second partial.", "Final summary.")
    operator = _operator(adapter, max_input_tokens=12, overlap_ratio=0)
    content = "One sentence here. Two sentence here. Three sentence here. Four sentence here."

    outputs, _ = operator.transform(pa.table({"content": [content]}))

    assert outputs[0]["summary"].to_pylist() == ["Final summary."]
    assert adapter.chat.call_count == 3
    for call in adapter.chat.call_args_list:
        assert "\n" in call.kwargs["messages"][0]["content"]


def test_multiple_rows_generate_independent_summaries():
    operator = _operator(_adapter("Summary one.", "Summary two."))
    table = pa.table({"content": ["First.", "Second."]})

    outputs, metadata = operator.transform(table)

    assert outputs[0]["summary"].to_pylist() == ["Summary one.", "Summary two."]
    assert metadata[Metrics.External.PROCESSED_DOCS] == 2


def test_custom_output_column_is_added():
    operator = _operator(_adapter("Custom summary."), output_column="document_summary")
    outputs, _ = operator.transform(pa.table({"content": ["Source."]}))

    assert "document_summary" in outputs[0].column_names
    assert outputs[0]["document_summary"].to_pylist() == ["Custom summary."]


def test_custom_document_column_is_used():
    operator = _operator(_adapter("Custom source summary."), doc_column="body")
    outputs, _ = operator.transform(pa.table({"body": ["Source."], "other": [1]}))

    assert outputs[0]["summary"].to_pylist() == ["Custom source summary."]
    assert outputs[0]["other"].to_pylist() == [1]


def test_custom_document_column_validation_uses_configured_column():
    operator = _operator(_adapter("Summary."), doc_column="body")
    errors: list[str] = []

    operator.validate(errors, [], ["body"])

    assert errors == []


def test_partial_window_failure_uses_successful_windows():
    adapter = _adapter("First partial.", RuntimeError("window failure"), "Final summary.")
    operator = _operator(adapter, max_input_tokens=12, overlap_ratio=0)
    content = "One sentence here. Two sentence here. Three sentence here. Four sentence here."

    outputs, _ = operator.transform(pa.table({"content": [content]}))

    assert outputs[0]["summary"].to_pylist() == ["Final summary."]
    assert adapter.chat.call_count == 3


def test_provider_failure_preserves_row_and_records_failure():
    adapter = _adapter("Summary one.")
    adapter.chat.side_effect = ["Summary one.", RuntimeError("provider unavailable")]
    operator = _operator(adapter)
    table = pa.table({"id": ["1", "2"], "name": ["one", "two"], "content": ["First.", "Second."]})

    outputs, metadata = operator.transform(table)

    assert outputs[0].num_rows == 2
    assert outputs[0]["summary"].to_pylist() == ["Summary one.", None]
    assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
    assert metadata[Metrics.External.FAILED_DOCS][0]["id"] == "2"
    assert metadata[Metrics.External.NODE_STATUS] == "CompletedWithErrors"


def test_service_generate_summary_empty_content_returns_empty():
    adapter = _adapter("unused")
    service = SummarizationService(llm_adapter=adapter)

    assert service.generate_summary(content="") == ""
    adapter.chat.assert_not_called()


def test_chunked_summary_api_remains_compatible():
    adapter = _adapter("Paragraph 0: Chunk summary.")
    service = SummarizationService(llm_adapter=adapter)
    chunks = [{"chunk": "Chunk content.", "start_index": 0}]

    service.generate_summary_for_chunked_content(chunked_content=chunks)

    assert chunks[0]["summary"] == "Chunk summary."
