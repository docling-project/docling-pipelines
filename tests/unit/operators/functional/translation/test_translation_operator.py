
"""Unit tests for TranslationOperator."""

from unittest.mock import Mock, patch

import pyarrow as pa
import pytest

from docpipe.core.operators.functional.translation_operator import TranslationOperator


@pytest.fixture
def translation_config():
    return {
        "provider": "litellm",
        "provider_config": {
            "model_id": "test-model",
            "api_key": "test-key",
        },
        "target_language": "French",
    }


@pytest.fixture
def mock_adapter():
    adapter = Mock()
    adapter.chat.return_value = "Bonjour"
    return adapter


@pytest.fixture
def sample_table():
    return pa.table(
        {
            "doc_id": ["1", "2"],
            "doc_name": ["first.txt", "second.txt"],
            "content": ["Hello", "Good morning"],
            "category": ["greeting", "greeting"],
        }
    )


class TestTranslationOperator:
    @patch(
        "docpipe.core.operators.functional.translation_operator."
        "LLMAdapterFactory.create_inference_adapter"
    )
    def test_translates_content_and_preserves_columns(
        self, factory, translation_config, mock_adapter, sample_table
    ):
        factory.return_value = mock_adapter
        mock_adapter.chat.side_effect = ["Bonjour", "Bonjour matin"]

        operator = TranslationOperator(translation_config)
        tables, metadata = operator.transform(sample_table)
        result = tables[0]

        assert result.num_rows == sample_table.num_rows
        assert result["content"].to_pylist() == ["Hello", "Good morning"]
        assert result["category"].to_pylist() == ["greeting", "greeting"]
        assert result["translated_content"].to_pylist() == [
            "Bonjour",
            "Bonjour matin",
        ]
        assert result["translation_source_language"].to_pylist() == [
            "auto",
            "auto",
        ]
        assert result["translation_target_language"].to_pylist() == [
            "French",
            "French",
        ]
        assert metadata["processed_docs"] == 2
        assert metadata["failed_docs_count"] == 0
        assert metadata["skipped_docs_count"] == 0

    @patch(
        "docpipe.core.operators.functional.translation_operator."
        "LLMAdapterFactory.create_inference_adapter"
    )
    def test_empty_content_is_skipped(
        self, factory, translation_config, mock_adapter
    ):
        factory.return_value = mock_adapter
        operator = TranslationOperator(translation_config)
        table = pa.table({"content": ["", None, "   "]})

        tables, metadata = operator.transform(table)

        assert tables[0]["translated_content"].to_pylist() == [
            None,
            None,
            None,
        ]
        mock_adapter.chat.assert_not_called()
        assert metadata["processed_docs"] == 0
        assert metadata["skipped_docs_count"] == 3
        assert metadata["failed_docs_count"] == 0

    @patch(
        "docpipe.core.operators.functional.translation_operator."
        "LLMAdapterFactory.create_inference_adapter"
    )
    def test_missing_content_column_raises(
        self, factory, translation_config, mock_adapter
    ):
        factory.return_value = mock_adapter
        operator = TranslationOperator(translation_config)

        with pytest.raises(ValueError, match="missing column"):
            operator.transform(pa.table({"other": ["text"]}))

    def test_output_column_cannot_conflict_with_language_metadata(
        self, translation_config
    ):
        translation_config["output_column"] = "translation_target_language"

        with pytest.raises(ValueError, match="cannot conflict"):
            TranslationOperator(translation_config)

    def test_output_column_cannot_overwrite_source(
        self, translation_config
    ):
        translation_config["output_column"] = "content"

        with pytest.raises(ValueError, match="must differ from doc_column"):
            TranslationOperator(translation_config)

    def test_invalid_provider_raises(self, translation_config):
        translation_config["provider"] = "unsupported"

        with pytest.raises(ValueError, match="provider must be"):
            TranslationOperator(translation_config)

    def test_missing_target_language_raises(self, translation_config):
        translation_config.pop("target_language")

        with pytest.raises(ValueError, match="target_language"):
            TranslationOperator(translation_config)

    @patch(
        "docpipe.core.operators.functional.translation_operator."
        "LLMAdapterFactory.create_inference_adapter"
    )
    def test_one_row_failure_does_not_stop_other_rows(
        self, factory, translation_config, mock_adapter
    ):
        factory.return_value = mock_adapter
        mock_adapter.chat.side_effect = [
            "Bonjour",
            RuntimeError("provider unavailable"),
            "Au revoir",
        ]

        operator = TranslationOperator(translation_config)
        table = pa.table(
            {
                "doc_id": ["1", "2", "3"],
                "doc_name": ["a.txt", "b.txt", "c.txt"],
                "content": ["Hello", "Good morning", "Goodbye"],
            }
        )

        tables, metadata = operator.transform(table)

        assert tables[0]["translated_content"].to_pylist() == [
            "Bonjour",
            None,
            "Au revoir",
        ]
        assert tables[0]["content"].to_pylist() == [
            "Hello",
            "Good morning",
            "Goodbye",
        ]
        assert mock_adapter.chat.call_count == 3
        assert metadata["processed_docs"] == 2
        assert metadata["failed_docs_count"] == 1
        assert len(metadata["failed_docs"]) == 1
        assert metadata["failed_docs"][0].id == "2"
        assert metadata["skipped_docs_count"] == 0
