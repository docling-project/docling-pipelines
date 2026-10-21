#!/usr/bin/env python3
"""
Integration tests for content column management between document_classifier and extract operators.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pytest

from docpipe.core.constants import DocpipeConstants, Metrics, OperatorConstants
from docpipe.core.operators.extract import ExtractOperator
from docpipe.core.operators.quality.classification.document_classifier import DocumentClassifierOperator
from docpipe.core.operators.quality.classification.domain.models import ClassificationResponse

PDF_FIXTURE_PATH = Path("tests/fixtures/invoices/TR-INV_001_3_2.1.pdf")
CLASSIFIER_TEMP_COLUMN = DocpipeConstants.TEMP_CONTENT_COLUMN
REUSED_CONTENT = "Classifier-prefetched content for reuse path."
FRESH_LIBRARY_CONTENT = "Fresh docling_library extraction content."
FRESH_SERVE_CONTENT = "Fresh docling_serve extraction content."


def _build_pdf_input_table() -> pa.Table:
    binary_content = PDF_FIXTURE_PATH.read_bytes()
    return pa.table(
        {
            OperatorConstants.Columns.ID: ["doc-1"],
            OperatorConstants.Columns.NAME: [PDF_FIXTURE_PATH.name],
            OperatorConstants.Columns.PATH: [str(PDF_FIXTURE_PATH)],
            OperatorConstants.Columns.BINARY_CONTENT: [binary_content],
        }
    )


def _build_classifier_config() -> dict:
    return {
        OperatorConstants.Config.PROVIDER: "litellm",
        OperatorConstants.Config.PROVIDER_CONFIG: {
            "model_id": "openai/granite4:latest",
            "api_base": "http://localhost:11434/v1",
            "api_key": "<ollama>",  # pragma: allowlist secret
        },
        OperatorConstants.Config.DOCUMENT_TYPES: ["invoice", "receipt", "contract"],
        OperatorConstants.Config.CONFIDENCE_THRESHOLD: 7.0,
        OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
        OperatorConstants.Columns.OUTPUT_COLUMN: OperatorConstants.Columns.DOCUMENT_TYPE,
        OperatorConstants.Config.INCLUDE_CONFIDENCE: True,
        OperatorConstants.Config.INCLUDE_REASONING: True,
        OperatorConstants.Config.MAX_WORKERS: 1,
    }


def _build_extract_config(*, text_extraction_mode: str, provider_config: dict | None = None) -> dict:
    text_extraction_config = {
        OperatorConstants.Config.PROVIDER: text_extraction_mode,
        OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
    }
    if text_extraction_mode == OperatorConstants.ExtractionModes.TEXT_MODE_DOCLING_SERVE:
        text_extraction_config[OperatorConstants.Config.BASE_URL] = "http://localhost:5001"
    if provider_config:
        text_extraction_config[OperatorConstants.Config.PROVIDER_CONFIG] = provider_config

    return {
        OperatorConstants.Config.TEXT_EXTRACTION: text_extraction_config,
        OperatorConstants.Config.ENTITY_EXTRACTION: {
            OperatorConstants.Config.PROVIDER: OperatorConstants.ExtractionModes.ENTITY_MODE_NONE,
        },
        OperatorConstants.Config.MAX_WORKERS: 1,
        OperatorConstants.Config.USE_PROCESSES: False,
    }


def _mock_classification_response() -> str:
    return json.dumps(
        {
            "document_type": "invoice",
            "confidence": 9,
            "reasoning": "The document contains invoice-like content.",
        }
    )


@pytest.mark.integration
def test_classifier_content_reuse_with_docling_library():
    extract_operator = ExtractOperator(
        config=_build_extract_config(text_extraction_mode=OperatorConstants.ExtractionModes.TEXT_MODE_DOCLING_LIBRARY)
    )

    classifier_output = pa.table(
        {
            OperatorConstants.Columns.ID: ["doc-1"],
            OperatorConstants.Columns.NAME: [PDF_FIXTURE_PATH.name],
            OperatorConstants.Columns.PATH: [str(PDF_FIXTURE_PATH)],
            OperatorConstants.Columns.BINARY_CONTENT: [PDF_FIXTURE_PATH.read_bytes()],
            CLASSIFIER_TEMP_COLUMN: [REUSED_CONTENT],
            OperatorConstants.Columns.DOCUMENT_TYPE: ["invoice"],
        }
    )
    with patch(
        "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content"
    ) as mock_docling_extract_content:
        extract_tables, extract_metadata = extract_operator.transform(
            classifier_output,
            metadata=extract_operator.create_base_metadata(total_docs_count=classifier_output.num_rows),
        )
        extract_output = extract_tables[0]

        # Verify content reuse: extraction method should not be called
        mock_docling_extract_content.assert_not_called()
        assert OperatorConstants.Columns.DOC_COLUMN_DEFAULT in extract_output.column_names
        assert CLASSIFIER_TEMP_COLUMN not in extract_output.column_names
        assert extract_output[OperatorConstants.Columns.DOC_COLUMN_DEFAULT].to_pylist() == [REUSED_CONTENT]
        assert extract_metadata[Metrics.External.PROCESSED_DOCS] == 1


@pytest.mark.integration
def test_classifier_content_reextraction_with_docling_serve():
    input_table = _build_pdf_input_table()

    classifier = DocumentClassifierOperator(_build_classifier_config())

    with (
        patch.object(
            classifier.adapter._service,
            "classify_document",
            return_value=ClassificationResponse(
                success=True,
                document_type="invoice",
                confidence=9,
                reasoning="The document contains invoice-like content.",
            ),
        ),
        patch(
            "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter.OperatorUtils.extract_content",
            side_effect=lambda *args, **kwargs: {
                OperatorConstants.Extraction.SUCCESS: True,
                OperatorConstants.Columns.DOC_COLUMN_DEFAULT: REUSED_CONTENT,
                OperatorConstants.Metadata.METADATA: {"page_count": 1},
            },
        ) as mock_extract_content,
        patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter.DoclingServeClient"
        ) as mock_docling_serve_client_class,
    ):
        mock_docling_serve_client = mock_docling_serve_client_class.return_value
        mock_docling_serve_client.process_document.return_value = {
            "document": {"md_content": FRESH_SERVE_CONTENT},
            "processing_time": 1.25,
            "page_count": 1,
        }

        classifier_tables, _classifier_metadata = classifier.transform(input_table)
        classifier_output = classifier_tables[0]

        assert CLASSIFIER_TEMP_COLUMN in classifier_output.column_names
        assert classifier_output[CLASSIFIER_TEMP_COLUMN].to_pylist() == [REUSED_CONTENT]
        extract_operator = ExtractOperator(
            config=_build_extract_config(text_extraction_mode=OperatorConstants.ExtractionModes.TEXT_MODE_DOCLING_SERVE)
        )
        extract_tables, extract_metadata = extract_operator.transform(
            classifier_output,
            metadata=extract_operator.create_base_metadata(total_docs_count=classifier_output.num_rows),
        )
        extract_output = extract_tables[0]

        assert mock_extract_content.call_count == 1
        mock_docling_serve_client.process_document.assert_called_once()
        assert OperatorConstants.Columns.DOC_COLUMN_DEFAULT in extract_output.column_names
        assert CLASSIFIER_TEMP_COLUMN not in extract_output.column_names
        assert extract_output[OperatorConstants.Columns.DOC_COLUMN_DEFAULT].to_pylist() == [FRESH_SERVE_CONTENT]
        assert extract_metadata[Metrics.External.PROCESSED_DOCS] == 1


@pytest.mark.integration
def test_classifier_content_no_reuse_with_provider_config():
    """Test that prefetched content is NOT reused when provider_config is set, even with docling_library mode."""
    extract_operator = ExtractOperator(
        config=_build_extract_config(
            text_extraction_mode=OperatorConstants.ExtractionModes.TEXT_MODE_DOCLING_LIBRARY,
            provider_config={"some_key": "some_value"},
        )
    )

    classifier_output = pa.table(
        {
            OperatorConstants.Columns.ID: ["doc-1"],
            OperatorConstants.Columns.NAME: [PDF_FIXTURE_PATH.name],
            OperatorConstants.Columns.PATH: [str(PDF_FIXTURE_PATH)],
            OperatorConstants.Columns.BINARY_CONTENT: [PDF_FIXTURE_PATH.read_bytes()],
            CLASSIFIER_TEMP_COLUMN: [REUSED_CONTENT],
            OperatorConstants.Columns.DOCUMENT_TYPE: ["invoice"],
        }
    )
    with patch(
        "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
        return_value={
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: FRESH_LIBRARY_CONTENT,
            OperatorConstants.Metadata.METADATA: {"page_count": 1},
        },
    ) as mock_docling_extract_content:
        extract_tables, extract_metadata = extract_operator.transform(
            classifier_output,
            metadata=extract_operator.create_base_metadata(total_docs_count=classifier_output.num_rows),
        )
        extract_output = extract_tables[0]

        # Verify content is NOT reused: extraction method should be called
        mock_docling_extract_content.assert_called_once()
        assert OperatorConstants.Columns.DOC_COLUMN_DEFAULT in extract_output.column_names
        assert CLASSIFIER_TEMP_COLUMN not in extract_output.column_names
        assert extract_output[OperatorConstants.Columns.DOC_COLUMN_DEFAULT].to_pylist() == [FRESH_LIBRARY_CONTENT]
        assert extract_metadata[Metrics.External.PROCESSED_DOCS] == 1


@pytest.mark.integration
def test_extract_backward_compatibility_without_classifier():
    input_table = _build_pdf_input_table()

    with patch(
        "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
        return_value={
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: FRESH_LIBRARY_CONTENT,
            OperatorConstants.Metadata.METADATA: {"page_count": 1},
        },
    ) as mock_docling_extract_content:
        extract_operator = ExtractOperator(
            config=_build_extract_config(
                text_extraction_mode=OperatorConstants.ExtractionModes.TEXT_MODE_DOCLING_LIBRARY
            )
        )
        extract_tables, extract_metadata = extract_operator.transform(input_table)
        extract_output = extract_tables[0]

        mock_docling_extract_content.assert_called_once()
        assert OperatorConstants.Columns.DOC_COLUMN_DEFAULT in extract_output.column_names
        assert CLASSIFIER_TEMP_COLUMN not in extract_output.column_names
        assert extract_output[OperatorConstants.Columns.DOC_COLUMN_DEFAULT].to_pylist() == [FRESH_LIBRARY_CONTENT]
        assert extract_metadata[Metrics.External.PROCESSED_DOCS] == 1
