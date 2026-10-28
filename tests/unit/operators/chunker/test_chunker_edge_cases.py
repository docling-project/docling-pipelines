"""ChunkerOperator and ChunkerValidator edge cases.

External models are replaced the same way as in test_chunker.py (the Ollama client, the
HybridChunker class); everything else runs for real: simple splitting, the DocLang deserializer
and its Markdown fallback, summarization adapter creation, memmap chunk files.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus, Metrics
from docpipe.core.operators.functional.chunker import ChunkerOperator
from docpipe.core.operators.functional.chunker_validator import ChunkerValidator
from docpipe.utils.core.memmap_file_utils import load_chunks_from_file

_TEXT = "First paragraph about chunking. " * 20


def _table(**columns: list[Any]) -> pa.Table:
    count = len(next(iter(columns.values())))
    data: dict[str, Any] = {"id": [f"doc{i}" for i in range(count)], "name": [f"doc{i}.md" for i in range(count)]}
    data.update(columns)
    return pa.table(data)


def _failure_reasons(metadata: dict[str, Any]) -> list[str]:
    return [doc["reason"] for doc in metadata[Metrics.External.FAILED_DOCS]]


def _always(value: bool):
    return lambda *, field_value: value


# ---------------------------------------------------------------------------
# ChunkerValidator (static helpers that receive should_validate_field as a callback)
# ---------------------------------------------------------------------------


class TestChunkerValidator:
    def test_simple_chunker_checks_are_skipped_when_fields_are_not_validated(self):
        errors: list[Any] = []

        ChunkerValidator.validate_simple_chunker(
            chunk_size="big",
            chunk_overlap=-1,
            chunk_type="bogus",
            should_validate_field_fn=_always(False),
            errors=errors,
        )

        assert errors == []

    def test_wrongly_typed_sizes_skip_the_range_checks(self):
        errors: list[Any] = []

        ChunkerValidator.validate_simple_chunker(
            chunk_size="big",
            chunk_overlap="some",
            chunk_type="simple",
            should_validate_field_fn=_always(True),
            errors=errors,
        )

        assert [e.message_code for e in errors] == [
            "CHUNKER_INVALID_CHUNK_SIZE_TYPE",
            "CHUNKER_INVALID_CHUNK_OVERLAP_TYPE",
        ]

    def test_none_sizes_are_accepted(self):
        errors: list[Any] = []

        ChunkerValidator.validate_simple_chunker(
            chunk_size=None,
            chunk_overlap=None,
            chunk_type="simple",
            should_validate_field_fn=_always(True),
            errors=errors,
        )

        assert errors == []

    @pytest.mark.parametrize(
        ("threshold_type", "amount", "error"),
        [
            ("percentile", 101, "Invalid breakpoint_threshold_amount for percentile: 101"),
            ("percentile", 95, None),
            ("standard_deviation", -1, "Invalid breakpoint_threshold_amount for standard_deviation: -1"),
            ("standard_deviation", 1.5, None),
            ("interquartile", -5, None),
            ("bogus", None, "Invalid breakpoint_threshold_type: bogus"),
        ],
        ids=[
            "percentile-range",
            "percentile-valid",
            "std-negative",
            "std-valid",
            "other-type-unchecked",
            "unknown-type",
        ],
    )
    def test_semantic_thresholds(self, threshold_type, amount, error):
        errors: list[Any] = []

        ChunkerValidator.validate_semantic_chunker(
            breakpoint_threshold_type=threshold_type,
            breakpoint_threshold_amount=amount,
            semantic_embeddings_model="all-minilm",
            should_validate_field_fn=_always(True),
            errors=errors,
        )

        assert [error in str(e) for e in errors] == ([] if error is None else [True])

    def test_semantic_checks_are_skipped_when_fields_are_not_validated(self):
        errors: list[Any] = []

        ChunkerValidator.validate_semantic_chunker(
            breakpoint_threshold_type="bogus",
            breakpoint_threshold_amount=500,
            semantic_embeddings_model="all-minilm",
            should_validate_field_fn=_always(False),
            errors=errors,
        )

        assert errors == []

    @pytest.mark.parametrize("validate", [True, False], ids=["validated", "skipped"])
    def test_docling_chunker_with_untyped_size(self, validate):
        errors: list[Any] = []

        ChunkerValidator.validate_docling_chunker(
            chunk_size=None,
            chunk_overlap=0,
            docling_tokenizer="  ",
            should_validate_field_fn=_always(validate),
            errors=errors,
        )

        assert errors == (["docling_tokenizer cannot be empty for hybrid chunking"] if validate else [])

    @pytest.mark.parametrize(
        ("validate", "percentage"),
        [(False, 99), (True, None)],
        ids=["skipped", "not-set"],
    )
    def test_overlap_percentage_not_checked(self, validate, percentage):
        errors: list[Any] = []
        warnings: list[Any] = []

        ChunkerValidator.validate_overlap_percentage(
            chunk_overlap_percentage=percentage,
            should_validate_field_fn=_always(validate),
            errors=errors,
            warnings=warnings,
        )

        assert (errors, warnings) == ([], [])

    def test_summarization_checks_are_skipped_when_fields_are_not_validated(self):
        errors: list[Any] = []

        ChunkerValidator.validate_summarization(
            enable_summarization=True,
            summarization_model="",
            should_validate_field_fn=_always(False),
            errors=errors,
            max_input_tokens=1,
        )

        assert errors == []

    def test_summarization_model_check_can_be_deferred_separately(self):
        errors: list[Any] = []

        ChunkerValidator.validate_summarization(
            enable_summarization=True,
            summarization_model="",
            should_validate_field_fn=lambda *, field_value: field_value is True,
            errors=errors,
            max_input_tokens=1,
            summary_sentences=99,
            summary_max_words=1,
        )

        assert errors == []

    @pytest.mark.parametrize(
        ("should_validate", "limits"),
        [
            (_always(True), (4000, 3, 50)),
            (lambda *, field_value: not isinstance(field_value, int) or isinstance(field_value, bool), (1, 99, 1)),
        ],
        ids=["valid-values", "numbers-deferred"],
    )
    def test_summarization_limits_without_errors(self, should_validate, limits):
        max_input_tokens, summary_sentences, summary_max_words = limits
        errors: list[Any] = []

        ChunkerValidator.validate_summarization(
            enable_summarization=True,
            summarization_model="openai/llama3",
            should_validate_field_fn=should_validate,
            errors=errors,
            max_input_tokens=max_input_tokens,
            summary_sentences=summary_sentences,
            summary_max_words=summary_max_words,
        )

        assert errors == []

    def test_summarization_ranges(self):
        errors: list[Any] = []

        ChunkerValidator.validate_summarization(
            enable_summarization=True,
            summarization_model=None,
            should_validate_field_fn=_always(True),
            errors=errors,
            max_input_tokens=500,
            summary_sentences=9,
            summary_max_words=5,
        )

        assert errors[0].startswith("Invalid model id.")
        assert errors[1:] == [
            "Invalid max_input_tokens: 500. Must be between 1000 and 32000.",
            "Invalid summary_sentences: 9. Must be between 1 and 5.",
            "Invalid summary_max_words: 5. Must be between 10 and 100.",
        ]


# ---------------------------------------------------------------------------
# ChunkerOperator.validate()
# ---------------------------------------------------------------------------


class TestOperatorValidate:
    def test_chunker_after_embeddings_is_reported(self):
        errors: list[Any] = []

        ChunkerOperator({"chunk_type": "simple"}).validate(errors, [], available_features=["content", "embeddings"])

        assert "CHUNKER_OPERATOR_MISPLACED" in [getattr(e, "message_code", None) for e in errors]

    def test_retain_original_content_type_is_deferred_while_validating_the_flow(self):
        errors: list[Any] = []

        ChunkerOperator({"chunk_type": "simple", "retain_original_content": "yes", "validating_flow": True}).validate(
            errors, [], available_features=["content"]
        )

        assert "CHUNKER_INVALID_RETAIN_ORIGINAL_CONTENT_TYPE" not in [getattr(e, "message_code", None) for e in errors]


# ---------------------------------------------------------------------------
# ChunkerOperator.transform()
# ---------------------------------------------------------------------------


class TestTransformFailures:
    def test_unknown_chunk_type_fails_the_document(self):
        tables, metadata = ChunkerOperator({"chunk_type": "bogus"}).transform(_table(content=[_TEXT]))

        assert tables[0].num_rows == 0
        assert "Invalid chunk type: bogus" in _failure_reasons(metadata)[0]

    def test_missing_content_column_fails_the_document(self):
        # With the default retain_original_content=False the operator currently crashes instead (#358)
        operator = ChunkerOperator({"chunk_type": "simple", "retain_original_content": True})

        tables, metadata = operator.transform(_table(body=[_TEXT]))

        assert tables[0].num_rows == 0
        assert "The column 'content' was not found in the input data" in _failure_reasons(metadata)[0]

    def test_summarization_that_cannot_start_is_skipped_with_a_warning(self):
        operator = ChunkerOperator(
            {
                "chunk_type": "simple",
                "summarization": {"provider": "no_such_provider", "provider_config": {"model_id": "m"}},
            }
        )

        tables, metadata = operator.transform(_table(content=[_TEXT]))

        assert tables[0].num_rows == 1
        assert operator.enable_summarization is False
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_WARNINGS.value
        assert metadata[Metrics.External.PROCESSING_MESSAGE].startswith("Failed to generate summary")

    @pytest.mark.parametrize("model", ["openai/llama3", "gpt-4o-mini"])
    def test_prefixed_summarization_models_are_kept(self, model):
        operator = ChunkerOperator({"chunk_type": "simple", "summarization": {"provider_config": {"model_id": model}}})

        assert operator.summarization_model == model


class TestFileBackedChunks:
    """Above memmap_threshold (MB) the chunks are written to files and the table keeps references."""

    @pytest.mark.parametrize("with_ids", [True, False], ids=["named-by-doc-id", "random-name"])
    def test_large_tables_store_chunks_in_files(self, tmp_path, monkeypatch, with_ids):
        monkeypatch.setenv(DocpipeConstants.DOCPIPE_DATA_PATH, str(tmp_path / "data"))
        table = _table(content=[_TEXT, _TEXT])
        if not with_ids:
            table = table.drop_columns(["id"])
        operator = ChunkerOperator({"chunk_type": "simple", "memmap_threshold": 1e-9})

        tables, _ = operator.transform(table)

        references = tables[0].column("chunked_content").to_pylist()
        files = [Path(ref[DocpipeConstants.CHUNKS_MEMMAP_FILE]) for ref in references]
        assert all(f.is_relative_to(tmp_path / "data") for f in files)
        assert ([f.name for f in files] == ["doc0_chunks.bin", "doc1_chunks.bin"]) is with_ids
        chunks = load_chunks_from_file(filepath=str(files[0]))
        assert "".join(c["chunk"] for c in chunks).replace(" ", "") == _TEXT.replace(" ", "")


class TestSemanticChunking:
    @patch("langchain_experimental.text_splitter.SemanticChunker")
    @patch("docpipe.core.operators.functional.chunker.OllamaClient")
    def test_threshold_amount_is_passed_to_the_splitter(self, ollama_client, semantic_chunker):
        semantic_chunker.return_value.create_documents.return_value = []
        operator = ChunkerOperator(
            {
                "chunk_type": "semantic",
                "semantic_embeddings_model": "all-minilm",
                "breakpoint_threshold_type": "standard_deviation",
                "breakpoint_threshold_amount": 1.5,
            }
        )

        operator.transform(_table(content=[_TEXT]))

        assert semantic_chunker.call_args.kwargs["breakpoint_threshold_amount"] == 1.5
        assert semantic_chunker.call_args.kwargs["breakpoint_threshold_type"] == "standard_deviation"

    @patch("langchain_experimental.text_splitter.SemanticChunker")
    @patch("docpipe.core.operators.functional.chunker.OllamaClient")
    def test_ollama_client_is_reused_after_a_failed_splitter_start(self, ollama_client, semantic_chunker):
        semantic_chunker.side_effect = [RuntimeError("model busy"), MagicMock(create_documents=lambda texts: [])]
        operator = ChunkerOperator({"chunk_type": "semantic", "semantic_embeddings_model": "all-minilm"})

        _, metadata = operator.transform(_table(content=[_TEXT, _TEXT]))

        assert ollama_client.call_count == 1
        assert "Failed to initialize SemanticChunker: model busy" in _failure_reasons(metadata)[0]


class TestDoclingChunking:
    def test_unloadable_tokenizer_fails_the_document(self, tmp_path):
        operator = ChunkerOperator({"chunk_type": "hybrid", "docling_tokenizer": str(tmp_path)})

        _, metadata = operator.transform(_table(content=[_TEXT]))

        assert "Failed to initialize Docling HybridChunker" in _failure_reasons(metadata)[0]

    @patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker")
    def test_chunking_error_fails_the_document(self, hybrid_chunker):
        hybrid_chunker.return_value.chunk.side_effect = RuntimeError("tokenizer exploded")
        operator = ChunkerOperator({"chunk_type": "hybrid"})

        _, metadata = operator.transform(_table(content=[_TEXT]))

        assert "Docling chunking failed: tokenizer exploded" in _failure_reasons(metadata)[0]

    def test_broken_doclang_falls_back_to_markdown(self):
        document = ChunkerOperator._create_docling_document_from_doclang(
            doclang_content="<doctag><text>Hello world", doc_name="broken.md"
        )

        assert "Hello world" in document.export_to_markdown()

    def test_doclang_without_deserializer_falls_back_to_markdown(self, monkeypatch):
        from docpipe.core.operators.operator_utils import OperatorUtils

        monkeypatch.setattr(OperatorUtils, "get_doclang_deserializer", staticmethod(lambda: None))

        document = ChunkerOperator._create_docling_document_from_doclang(
            doclang_content="<doctag><text>Hello world</text></doctag>"
        )

        assert "Hello world" in document.export_to_markdown()


class TestDoclingServeChunking:
    def test_empty_chunks_are_dropped(self):
        client = MagicMock()
        client.call_rest_json.return_value = {"chunks": [{"text": "first chunk"}, {"text": ""}, "second chunk"]}
        operator = ChunkerOperator({"chunk_type": "hybrid", "provider": "docling_serve"})
        operator._remote_chunking_client = client

        tables, _ = operator.transform(_table(content=[_TEXT]))

        assert [c["chunk"] for c in tables[0].column("chunked_content").to_pylist()[0]] == [
            "first chunk",
            "second chunk",
        ]
