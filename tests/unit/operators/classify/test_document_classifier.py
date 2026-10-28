#!/usr/bin/env python3
"""
Unit tests for document_classifier operator.
Tests the operator with sample documents from the fixtures directory.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants import DocpipeConstants, ExecutionStatus, Metrics
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.core.operators.quality.classification.document_classifier import DocumentClassifierOperator
from docpipe.core.operators.quality.classification.domain.models import ClassificationResponse


@pytest.fixture
def basic_litellm_config():
    """Fixture providing basic LiteLLM configuration for tests."""
    return {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "ollama",  # pragma: allowlist secret
        },
        "document_types": ["invoice", "receipt"],
    }


@pytest.mark.unit
def test_document_classifier_basic_litellm():
    """Test the DocumentClassifierOperator with basic classification using LiteLLM."""

    # Create sample documents with content (using supported file extensions)
    sample_docs = [
        {
            "id": "doc1",
            "name": "invoice.pdf",
            "content": "INVOICE\nInvoice Number: INV-001\nDate: 2024-01-15\nBill To: John Doe\nItem: Widget\nQuantity: 10\nPrice: $100\nTotal: $1000",
        },
        {
            "id": "doc2",
            "name": "contract.docx",
            "content": "CONTRACT AGREEMENT\nThis agreement is made between Party A and Party B.\nTerms and Conditions:\n1. Payment terms\n2. Delivery schedule\n3. Warranty provisions",
        },
        {
            "id": "doc3",
            "name": "receipt.pdf",
            "content": "RECEIPT\nStore: ABC Store\nDate: 2024-01-20\nTransaction ID: TXN-12345\nItems purchased:\n- Coffee: $5.00\n- Sandwich: $8.00\nTotal: $13.00\nPayment Method: Credit Card",
        },
    ]

    # Create PyArrow table
    table = pa.table(
        {
            "id": [doc["id"] for doc in sample_docs],
            "name": [doc["name"] for doc in sample_docs],
            "content": [doc["content"] for doc in sample_docs],
        }
    )

    # Initialize operator with litellm provider
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "<ollama>",  # pragma: allowlist secret
        },
        "document_types": {
            "invoice": "Business invoice with line items, totals, and payment terms",
            "receipt": "Payment receipt or transaction confirmation",
            "contract": "Legal contract or agreement document",
            "report": "Business or technical report",
            "letter": "Formal or informal letter",
        },
        "confidence_threshold": 7.0,
        "doc_column": "content",
        "output_column": "document_type",
        "include_confidence": True,
        "include_reasoning": True,
    }

    # Mock responses for each document
    mock_responses = [
        json.dumps(
            {
                "document_type": "invoice",
                "confidence": 9,
                "reasoning": "Document contains invoice number, date, bill to information, line items with quantities and prices, and total amount.",
            }
        ),
        json.dumps(
            {
                "document_type": "contract",
                "confidence": 8,
                "reasoning": "Document is a legal agreement between two parties with terms and conditions including payment terms, delivery schedule, and warranty provisions.",
            }
        ),
        json.dumps(
            {
                "document_type": "receipt",
                "confidence": 9,
                "reasoning": "Document is a payment receipt with store name, transaction ID, itemized purchases with prices, total amount, and payment method.",
            }
        ),
    ]

    with patch(
        "docpipe.integrations.litellm.client.LiteLLMLLMClient.chat",
        side_effect=mock_responses,
    ):
        operator = DocumentClassifierOperator(config)

        # Transform the table
        result_tables, metadata = operator.transform(table)
        result_table = result_tables[0]

        # Assertions
        assert "document_type" in result_table.column_names, "document_type column should exist"
        assert "document_type_confidence" in result_table.column_names, "confidence column should exist"
        assert "document_type_reasoning" in result_table.column_names, "reasoning column should exist"

        # Check classifications
        doc_types = result_table["document_type"].to_pylist()
        confidences = result_table["document_type_confidence"].to_pylist()

        assert doc_types[0] == "invoice", "First document should be classified as invoice"
        assert doc_types[1] == "contract", "Second document should be classified as contract"
        assert doc_types[2] == "receipt", "Third document should be classified as receipt"

        # Check confidence scores
        for confidence in confidences:
            assert 1 <= confidence <= 10, f"Confidence should be between 1 and 10, got {confidence}"

        # Check metadata
        assert metadata["documents_in_scope"] == 3, "Should have 3 documents"
        assert metadata["processed_docs"] == 3, "Should have processed 3 documents"


@pytest.mark.unit
def test_document_classifier_without_content_column():
    """Test the DocumentClassifierOperator when content column doesn't exist (should fetch from binary).

    With the hybrid approach, fetched content is stored in the temporary content column
    for potential reuse by the extract operator, not in the final 'content' column.
    """

    # Get test files
    fixtures_dir = Path(__file__).parent.parent.parent.parent / "fixtures" / "customer_support_docs"
    test_files = list(fixtures_dir.glob("*.pdf"))[:2]

    if len(test_files) < 2:
        pytest.skip("Need at least 2 pdf files for this test")

    # Prepare data without content column
    file_data: dict[str, list] = {"id": [], "name": [], "path": [], "binary_content": []}

    for file_path in test_files:
        with file_path.open("rb") as f:
            binary_content = f.read()

        file_data["id"].append(str(file_path))
        file_data["name"].append(file_path.name)
        file_data["path"].append(str(file_path))
        file_data["binary_content"].append(binary_content)

    # Create PyArrow table without content column
    table = pa.table(file_data)

    # Initialize operator with litellm
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "<ollama>",  # pragma: allowlist secret
        },
        "document_types": ["email", "letter", "form", "report", "other"],
        "confidence_threshold": 6.0,
        "doc_column": "content",
        "output_column": "document_type",
        "include_confidence": True,
        "include_reasoning": False,
    }

    # Mock responses for documents
    mock_responses = [
        json.dumps(
            {
                "document_type": "email",
                "confidence": 8,
                "reasoning": "Document appears to be an email communication.",
            }
        ),
        json.dumps(
            {
                "document_type": "letter",
                "confidence": 7,
                "reasoning": "Document appears to be a formal letter.",
            }
        ),
    ]

    with patch(
        "docpipe.integrations.litellm.client.LiteLLMLLMClient.chat",
        side_effect=mock_responses,
    ):
        operator = DocumentClassifierOperator(config)

        # Transform the table
        result_tables, metadata = operator.transform(table)
        result_table = result_tables[0]

        # Assertions - hybrid approach stores content in temporary column
        assert DocpipeConstants.TEMP_CONTENT_COLUMN in result_table.column_names, (
            "temporary content column should be added"
        )
        assert "content" not in result_table.column_names, "content column should NOT be in output (stored as temp)"
        assert "document_type" in result_table.column_names, "document_type column should exist"
        assert "document_type_confidence" in result_table.column_names, "confidence column should exist"
        assert "document_type_reasoning" not in result_table.column_names, "reasoning column should not exist"

        # Check that content was extracted and stored in temp column
        for idx in range(result_table.num_rows):
            content = result_table[DocpipeConstants.TEMP_CONTENT_COLUMN][idx].as_py()
            assert content is not None, f"Content should not be None for row {idx}"
            assert len(content) > 0, f"Content should not be empty for row {idx}"

        assert metadata["processed_docs"] > 0, "Should have processed at least one document"


@pytest.mark.unit
def test_document_classifier_get_metadata_watsonx(monkeypatch):
    """Test the get_metadata method with watsonx provider."""
    # Set required environment variables
    monkeypatch.setenv("WATSONX_API_KEY", "test-api-key")
    monkeypatch.setenv("WATSONX_CONTAINER_ID", "test-project-id")

    # Create operator with minimal config
    config = {
        "provider": "watsonx",
        "provider_config": {
            "model_id": "ibm/granite-3-8b-instruct",
            "api_base": "https://us-south.ml.cloud.ibm.com",
            "container_kind": "project",
        },
        "document_types": ["invoice", "receipt", "contract"],
    }

    operator = DocumentClassifierOperator(config)
    metadata = operator.get_metadata()

    # Assertions
    assert isinstance(metadata, dict), "Metadata should be a dictionary"
    assert "category" in metadata, "Metadata should have 'category' key"
    assert "features" in metadata, "Metadata should have 'features' key"
    assert "attributes" in metadata, "Metadata should have 'attributes' key"

    # Check features
    features = metadata["features"]
    assert "document_type" in features, "Features should include 'document_type'"
    assert "document_type_confidence" in features, "Features should include confidence"
    assert "document_type_reasoning" in features, "Features should include reasoning"

    # Check attributes
    attributes = metadata["attributes"]
    assert "provider" in attributes, "Attributes should include 'provider'"
    assert "document_types" in attributes, "Attributes should include 'document_types'"
    assert attributes["document_types"].get("default") == [], "document_types attribute should have default: []"
    # model_id is nested inside each provider schema under provider_config.providers.<provider>.properties
    assert "provider_config" in attributes, "Attributes should include 'provider_config'"
    assert "providers" in attributes["provider_config"], "provider_config should have 'providers'"
    assert "litellm" in attributes["provider_config"]["providers"], "provider_config.providers should include 'litellm'"
    litellm_schema = attributes["provider_config"]["providers"]["litellm"]
    assert "properties" in litellm_schema, "provider_config.providers.litellm should have 'properties'"
    assert "model_id" in litellm_schema["properties"], (
        "provider_config.providers.litellm.properties should include 'model_id'"
    )
    assert "document_types" in attributes, "Attributes should include 'document_types'"
    assert "confidence_threshold" in attributes, "Attributes should include 'confidence_threshold'"


@pytest.mark.unit
def test_document_classifier_validation_litellm():
    """Test the validation method with litellm provider."""

    # Test with valid config
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "<ollama>",  # pragma: allowlist secret
        },
        "document_types": ["invoice", "receipt"],
    }

    operator = DocumentClassifierOperator(config)
    errors: list[str] = []
    warnings: list[str] = []
    operator.validate(errors, warnings, [])

    assert len(errors) == 0, "Should have no validation errors"


@pytest.mark.unit
def test_document_classifier_empty_table():
    """Test the DocumentClassifierOperator with empty table."""

    # Create empty table
    table = pa.table({"id": [], "name": [], "content": []})

    # Initialize operator with litellm
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "<ollama>",  # pragma: allowlist secret
        },
        "document_types": ["invoice", "receipt"],
    }

    operator = DocumentClassifierOperator(config)

    # Transform the table
    result_tables, metadata = operator.transform(table)
    result_table = result_tables[0]

    # Assertions
    assert result_table.num_rows == 0, "Result table should be empty"
    assert metadata["documents_in_scope"] == 0, "Should have 0 documents"


@pytest.mark.unit
def test_document_classifier_with_existing_classification():
    """Test that operator skips if document_type column already exists."""

    # Create table with existing document_type column
    table = pa.table(
        {
            "id": ["doc1"],
            "name": ["test.txt"],
            "content": ["Test content"],
            "document_type": ["invoice"],
        }
    )

    # Initialize operator with litellm
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "<ollama>",  # pragma: allowlist secret
        },
        "document_types": ["invoice", "receipt"],
        "output_column": "document_type",
    }

    operator = DocumentClassifierOperator(config)

    # Transform the table
    result_tables, _metadata = operator.transform(table)
    result_table = result_tables[0]

    # Assertions - should return original table unchanged
    assert result_table.num_rows == 1, "Should have 1 row"
    assert result_table["document_type"][0].as_py() == "invoice", "Should keep existing classification"


@pytest.mark.unit
def test_document_classifier_list_document_types():
    """Test the DocumentClassifierOperator with list of document types (no descriptions)."""

    # Create sample document
    table = pa.table(
        {
            "id": ["doc1"],
            "name": ["invoice.pdf"],
            "content": ["INVOICE\nInvoice Number: INV-001\nTotal: $1000"],
        }
    )

    # Initialize operator with list of types
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "<ollama>",  # pragma: allowlist secret
        },
        "document_types": ["invoice", "receipt", "contract", "report"],
        "doc_column": "content",
        "output_column": "document_type",
        "include_confidence": True,
        "include_reasoning": False,
    }

    # Mock response for the document
    mock_response = json.dumps(
        {
            "document_type": "invoice",
            "confidence": 9,
            "reasoning": "Document contains invoice number and total amount.",
        }
    )

    with patch(
        "docpipe.integrations.litellm.client.LiteLLMLLMClient.chat",
        return_value=mock_response,
    ):
        operator = DocumentClassifierOperator(config)

        # Transform the table
        result_tables, _metadata = operator.transform(table)
        result_table = result_tables[0]

        # Assertions
        assert "document_type" in result_table.column_names, "document_type column should exist"
        assert result_table["document_type"][0].as_py() == "invoice", "Should classify as invoice"


@pytest.mark.unit
def test_ollama_provider_rejected():
    """Test that Ollama provider is rejected with clear error message."""
    config = {
        "provider": "ollama",
        "model_id": "granite4:latest",
        "provider_config": {
            "api_base": "http://localhost:11434",
        },
        "document_types": ["invoice", "receipt"],
    }

    # Should raise ValueError indicating Ollama is not supported
    with pytest.raises(ValueError, match="Ollama provider is no longer supported"):
        DocumentClassifierOperator(config)


@pytest.mark.unit
def test_document_classifier_progress_tracking_litellm():
    """Test that document classifier reports progress in metadata with litellm."""
    from docpipe.core.constants import Metrics

    # Create test table with content
    table = pa.table(
        {
            "id": ["doc1", "doc2", "doc3"],
            "name": ["test1.pdf", "test2.pdf", "test3.pdf"],
            "content": ["Invoice content", "Receipt content", "Contract content"],
        }
    )

    # Configure operator
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "<ollama>",  # pragma: allowlist secret
        },
        "document_types": ["invoice", "receipt", "contract"],
        "job_id": "test-job",
        "job_run_id": "test-run",
        "node_id": "test-node",
        "batch_id": "test-batch",
    }

    # Mock the classification responses
    mock_responses = [
        json.dumps({"document_type": "invoice", "confidence": 9}),
        json.dumps({"document_type": "receipt", "confidence": 8}),
        json.dumps({"document_type": "contract", "confidence": 9}),
    ]

    with patch(
        "docpipe.integrations.litellm.client.LiteLLMLLMClient.chat",
        side_effect=mock_responses,
    ):
        operator = DocumentClassifierOperator(config)
        _, metadata = operator.transform(table)

        # Check that metadata contains progress fields
        assert Metrics.External.TOTAL_DOCS in metadata
        assert Metrics.External.PROCESSED_DOCS in metadata
        assert metadata[Metrics.External.TOTAL_DOCS] == 3
        assert metadata[Metrics.External.PROCESSED_DOCS] == 3


@pytest.mark.unit
def test_document_classifier_file_extension_validation():
    """Test that document classifier validates and skips unsupported file extensions."""

    # Create sample documents with mixed file extensions
    sample_docs = [
        {
            "id": "doc1",
            "name": "invoice.pdf",  # Supported
            "content": "INVOICE\nInvoice Number: INV-001\nTotal: $1000",
        },
        {
            "id": "doc2",
            "name": "contract.txt",  # Unsupported
            "content": "CONTRACT AGREEMENT\nThis agreement is made between Party A and Party B.",
        },
        {
            "id": "doc3",
            "name": "receipt.docx",  # Supported
            "content": "RECEIPT\nStore: ABC Store\nTotal: $13.00",
        },
        {
            "id": "doc4",
            "name": "memo.md",  # Unsupported
            "content": "# Memo\nThis is a memo document.",
        },
    ]

    # Create PyArrow table
    table = pa.table(
        {
            "id": [doc["id"] for doc in sample_docs],
            "name": [doc["name"] for doc in sample_docs],
            "content": [doc["content"] for doc in sample_docs],
        }
    )

    # Initialize operator with litellm provider
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/granite3.1-dense:8b",
            "api_base": "http://localhost:11434/v1",
            "api_key": "<ollama>",
        },
        "document_types": ["invoice", "contract", "receipt"],
        "confidence_threshold": 7.0,
        "doc_column": "content",
        "output_column": "document_type",
    }

    # Mock the adapter factory to avoid actual LLM calls
    from unittest.mock import MagicMock

    mock_adapter = MagicMock()
    mock_adapter.classify_document.return_value = ClassificationResponse(
        document_type="invoice", confidence=9, reasoning="Test classification", success=True
    )

    with patch(
        "docpipe.core.operators.quality.classification.document_classifier.ClassificationAdapterFactory"
    ) as mock_factory:
        mock_factory.create_adapter.return_value = mock_adapter
        operator = DocumentClassifierOperator(config)
        operator.adapter = mock_adapter
        output_tables, metadata = operator.transform(table)

        # Verify that unsupported files were skipped (not failed)
        assert metadata["skipped_docs_count"] == 2, "Should have 2 skipped documents (.txt and .md)"
        assert len(metadata["skipped_docs"]) == 2, "Should have 2 skipped document records"

        # Verify skipped documents are the .txt and .md files
        skipped_names = {doc["name"] for doc in metadata["skipped_docs"]}
        assert "contract.txt" in skipped_names, ".txt file should be skipped"
        assert "memo.md" in skipped_names, ".md file should be skipped"

        # Verify error messages mention unsupported file extension
        for skipped_doc in metadata["skipped_docs"]:
            assert "Unsupported file extension" in skipped_doc["reason"]

        # Verify output table contains ALL files (skipped files remain in table)
        output_table = output_tables[0]
        assert output_table.num_rows == 4, "Should have 4 rows (all files remain)"

        # Verify all documents are present
        output_names = output_table.column("name").to_pylist()
        assert "invoice.pdf" in output_names, ".pdf file should remain"
        assert "receipt.docx" in output_names, ".docx file should remain"
        assert "contract.txt" in output_names, ".txt file should remain (marked as skipped)"
        assert "memo.md" in output_names, ".md file should remain (marked as skipped)"

        # Verify skipped files have None classification
        doc_types = output_table.column("document_type").to_pylist()
        name_to_type = dict(zip(output_names, doc_types, strict=False))
        assert name_to_type["contract.txt"] is None, ".txt file should have None classification"
        assert name_to_type["memo.md"] is None, ".md file should have None classification"


@pytest.mark.unit
def test_document_classifier_all_files_skipped():
    """Test that document classifier handles case where all files are skipped due to unsupported extensions."""

    # Create sample documents with only unsupported extensions
    sample_docs = [
        {
            "id": "doc1",
            "name": "file1.txt",
            "content": "Content 1",
        },
        {
            "id": "doc2",
            "name": "file2.md",
            "content": "Content 2",
        },
    ]

    # Create PyArrow table
    table = pa.table(
        {
            "id": [doc["id"] for doc in sample_docs],
            "name": [doc["name"] for doc in sample_docs],
            "content": [doc["content"] for doc in sample_docs],
        }
    )

    # Initialize operator — patch factory since all files are skipped before LLM is called
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/granite3.1-dense:8b",
            "api_base": "http://localhost:11434/v1",
            "api_key": "<ollama>",
        },
        "document_types": ["invoice", "contract"],
        "doc_column": "content",
    }

    from unittest.mock import MagicMock

    with patch(
        "docpipe.core.operators.quality.classification.document_classifier.ClassificationAdapterFactory"
    ) as mock_factory:
        mock_factory.create_adapter.return_value = MagicMock()
        operator = DocumentClassifierOperator(config)
    output_tables, metadata = operator.transform(table)

    # Verify all files were skipped (not failed)
    assert metadata["skipped_docs_count"] == 2, "All files should be skipped"
    assert metadata["failed_docs_count"] == 0, "No files should be failed"
    assert metadata["processed_docs"] == 0, "No files should be processed"

    # Verify output table contains all rows (skipped files remain)
    output_table = output_tables[0]
    assert output_table.num_rows == 2, "Output table should contain all rows"

    # Verify all documents have None classification
    doc_types = output_table.column("document_type").to_pylist()
    assert all(dt is None for dt in doc_types), "All documents should have None classification"


@pytest.mark.unit
def test_document_classifier_supported_extensions_only():
    """Test that document classifier accepts all supported file extensions."""

    # Create sample documents with supported extensions from CLASSIFICATION_FILE_EXTENSIONS
    sample_docs = [
        {"id": "doc1", "name": "file.pdf", "content": "PDF content"},
        {"id": "doc2", "name": "file.docx", "content": "DOCX content"},
        {"id": "doc3", "name": "file.pptx", "content": "PPTX content"},
        {"id": "doc4", "name": "file.xlsx", "content": "XLSX content"},
        {"id": "doc5", "name": "file.html", "content": "HTML content"},
        {"id": "doc6", "name": "file.png", "content": "PNG content"},
    ]

    # Create PyArrow table
    table = pa.table(
        {
            "id": [doc["id"] for doc in sample_docs],
            "name": [doc["name"] for doc in sample_docs],
            "content": [doc["content"] for doc in sample_docs],
        }
    )

    # Initialize operator
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/granite3.1-dense:8b",
            "api_base": "http://localhost:11434/v1",
            "api_key": "<ollama>",
        },
        "document_types": ["document"],
        "doc_column": "content",
    }

    # Mock the adapter factory to avoid actual LLM calls
    from unittest.mock import MagicMock

    mock_adapter = MagicMock()
    mock_adapter.classify_document.return_value = ClassificationResponse(
        document_type="document", confidence=9, reasoning="Test", success=True
    )

    with patch(
        "docpipe.core.operators.quality.classification.document_classifier.ClassificationAdapterFactory"
    ) as mock_factory:
        mock_factory.create_adapter.return_value = mock_adapter
        operator = DocumentClassifierOperator(config)
        operator.adapter = mock_adapter
        output_tables, metadata = operator.transform(table)

        # Verify no files were rejected
        assert metadata["failed_docs_count"] == 0, "No files should be rejected"
        assert metadata["processed_docs"] == 6, "All 6 files should be processed"

        # Verify output table contains all files
        output_table = output_tables[0]
        assert output_table.num_rows == 6, "All files should remain in output"


@pytest.mark.unit
def test_document_classifier_batch_progress_litellm():
    """Test that document classifier updates progress during batch processing with litellm."""
    from docpipe.core.constants import Metrics

    # Create larger test table
    num_docs = 10
    table = pa.table(
        {
            "id": [f"doc{i}" for i in range(num_docs)],
            "name": [f"test{i}.txt" for i in range(num_docs)],
            "content": [f"Test content {i}" for i in range(num_docs)],
        }
    )

    # Configure operator with parallel processing
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "<ollama>",  # pragma: allowlist secret
        },
        "document_types": ["invoice", "receipt"],
        "max_workers": 2,
        "job_id": "test-job",
        "job_run_id": "test-run",
        "node_id": "test-node",
        "batch_id": "test-batch",
    }

    # Mock responses for all documents
    mock_responses = [json.dumps({"document_type": "invoice", "confidence": 8})] * num_docs

    with patch(
        "docpipe.integrations.litellm.client.LiteLLMLLMClient.chat",
        side_effect=mock_responses,
    ):
        operator = DocumentClassifierOperator(config)
        _, metadata = operator.transform(table)

        # Check progress tracking
        assert metadata[Metrics.External.TOTAL_DOCS] == num_docs
        assert metadata[Metrics.External.PROCESSED_DOCS] >= 0
        assert metadata[Metrics.External.PROCESSED_DOCS] <= num_docs

        # Check that failed docs are tracked
        assert Metrics.External.FAILED_DOCS_COUNT in metadata


@pytest.mark.unit
def test_determine_execution_status_all_failed(basic_litellm_config):
    """Test determine_execution_status when all documents fail."""
    # Test case: All documents failed (processed=0, failed=2)
    status = OperatorUtils.determine_execution_status(processed_count=0, failed_count=2, skipped_count=0)

    assert status == ExecutionStatus.FAILED.value, f"Expected {ExecutionStatus.FAILED.value}, got {status}"


@pytest.mark.unit
def test_determine_execution_status_some_failed(basic_litellm_config):
    """Test determine_execution_status when some documents fail."""
    # Test case: Some documents failed (processed=1, failed=1)
    status = OperatorUtils.determine_execution_status(processed_count=1, failed_count=1, skipped_count=0)

    assert status == ExecutionStatus.COMPLETED_WITH_ERRORS.value, (
        f"Expected {ExecutionStatus.COMPLETED_WITH_ERRORS.value}, got {status}"
    )


@pytest.mark.unit
def test_determine_execution_status_all_succeeded(basic_litellm_config):
    """Test determine_execution_status when all documents succeed."""
    # Test case: All documents succeeded (processed=2, failed=0)
    status = OperatorUtils.determine_execution_status(processed_count=2, failed_count=0, skipped_count=0)

    assert status == ExecutionStatus.COMPLETED.value, f"Expected {ExecutionStatus.COMPLETED.value}, got {status}"


@pytest.mark.unit
def test_determine_execution_status_some_skipped(basic_litellm_config):
    """Test determine_execution_status when some documents are skipped."""
    # Test case: Some documents skipped (processed=1, skipped=1)
    status = OperatorUtils.determine_execution_status(processed_count=1, failed_count=0, skipped_count=1)

    assert status == ExecutionStatus.COMPLETED_WITH_WARNINGS.value, (
        f"Expected {ExecutionStatus.COMPLETED_WITH_WARNINGS.value}, got {status}"
    )


@pytest.mark.unit
def test_determine_execution_status_all_skipped(basic_litellm_config):
    """Test determine_execution_status when all documents are skipped."""
    # Test case: All documents skipped (processed=0, skipped=2)
    status = OperatorUtils.determine_execution_status(processed_count=0, failed_count=0, skipped_count=2)

    assert status == ExecutionStatus.COMPLETED_WITH_WARNINGS.value, (
        f"Expected {ExecutionStatus.COMPLETED_WITH_WARNINGS.value}, got {status}"
    )


@pytest.mark.unit
def test_determine_execution_status_mixed_failures_and_skips(basic_litellm_config):
    """Test determine_execution_status with mixed failures and skips."""
    # Test case: Mixed - some processed, some failed, some skipped
    # Failures take precedence over skips
    status = OperatorUtils.determine_execution_status(processed_count=1, failed_count=1, skipped_count=1)

    assert status == ExecutionStatus.COMPLETED_WITH_ERRORS.value, (
        f"Expected {ExecutionStatus.COMPLETED_WITH_ERRORS.value} (failures take precedence), got {status}"
    )


@pytest.mark.unit
def test_transform_sets_correct_status_on_all_failures(basic_litellm_config):
    """Test that transform method sets FAILED status when all documents fail."""

    # Create test table with supported file extensions
    table = pa.table(
        {
            "id": ["doc1", "doc2"],
            "name": ["test1.pdf", "test2.pdf"],
            "content": ["Test content 1", "Test content 2"],
        }
    )

    # Mock classification to fail for all documents
    with patch(
        "docpipe.integrations.litellm.client.LiteLLMLLMClient.chat",
        side_effect=Exception("API Error"),
    ):
        operator = DocumentClassifierOperator(basic_litellm_config)
        _, metadata = operator.transform(table)

        # Verify status is FAILED when all documents fail
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value, (
            f"Expected {ExecutionStatus.FAILED.value}, got {metadata[Metrics.External.NODE_STATUS]}"
        )
        assert metadata[Metrics.External.PROCESSED_DOCS] == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 2


@pytest.mark.unit
def test_transform_sets_correct_status_on_partial_failures(basic_litellm_config):
    """Test that transform method sets COMPLETED_WITH_ERRORS status when some documents fail."""

    # Create test table with supported file extensions
    table = pa.table(
        {
            "id": ["doc1", "doc2"],
            "name": ["test1.pdf", "test2.pdf"],
            "content": ["Test content 1", "Test content 2"],
        }
    )

    # Mock classification: first succeeds, second fails
    mock_responses = [
        json.dumps({"document_type": "invoice", "confidence": 9}),
        Exception("API Error"),
    ]

    with patch(
        "docpipe.integrations.litellm.client.LiteLLMLLMClient.chat",
        side_effect=mock_responses,
    ):
        operator = DocumentClassifierOperator(basic_litellm_config)
        _, metadata = operator.transform(table)

        # Verify status is COMPLETED_WITH_ERRORS when some documents fail
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS.value, (
            f"Expected {ExecutionStatus.COMPLETED_WITH_ERRORS.value}, got {metadata[Metrics.External.NODE_STATUS]}"
        )
        assert metadata[Metrics.External.PROCESSED_DOCS] == 1
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1


@pytest.mark.unit
def test_transform_sets_correct_status_on_success(basic_litellm_config):
    """Test that transform method sets COMPLETED status when all documents succeed."""

    # Create test table with supported file extensions
    table = pa.table(
        {
            "id": ["doc1", "doc2"],
            "name": ["test1.pdf", "test2.pdf"],
            "content": ["Test content 1", "Test content 2"],
        }
    )

    # Mock successful classification for all documents
    mock_responses = [
        json.dumps({"document_type": "invoice", "confidence": 9}),
        json.dumps({"document_type": "receipt", "confidence": 8}),
    ]

    with patch(
        "docpipe.integrations.litellm.client.LiteLLMLLMClient.chat",
        side_effect=mock_responses,
    ):
        operator = DocumentClassifierOperator(basic_litellm_config)
        _, metadata = operator.transform(table)

        # Verify status is COMPLETED when all documents succeed
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED.value, (
            f"Expected {ExecutionStatus.COMPLETED.value}, got {metadata[Metrics.External.NODE_STATUS]}"
        )
        assert metadata[Metrics.External.PROCESSED_DOCS] == 2
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0


@pytest.mark.unit
def test_temp_pages_processed_column_added():
    """Test that _temp_pages_processed column is added when content is fetched."""
    from unittest.mock import patch

    # Create sample table without content column (simulating content fetch scenario)
    table = pa.table(
        {
            "id": ["doc1", "doc2"],
            "name": ["test1.pdf", "test2.pdf"],
            "path": ["/path/to/test1.pdf", "/path/to/test2.pdf"],
        }
    )

    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "ollama",  # pragma: allowlist secret
        },
        "document_types": ["invoice", "receipt"],
        "doc_column": "content",
    }

    operator = DocumentClassifierOperator(config)

    # The adapter returns the text it extracted as a side product; the operator forwards it.
    mock_adapter = MagicMock()
    mock_adapter.classify_document.return_value = ClassificationResponse(
        document_type="invoice",
        confidence=9,
        reasoning="Test",
        success=True,
        extracted_content="A" * 3000,  # 1 page worth of content
        extraction_metadata={},
    )
    operator.adapter = mock_adapter

    with patch("docpipe.core.operators.operator_utils.OperatorUtils.prepare_document_content_fetch") as mock_prepare:
        mock_prepare.return_value = [
            {"idx": 0, "doc_id": "doc1", "doc_name": "test1.pdf", "binary_content": b"fake_binary"},
            {"idx": 1, "doc_id": "doc2", "doc_name": "test2.pdf", "binary_content": b"fake_binary"},
        ]

        result_tables, _ = operator.transform(table)
        result_table = result_tables[0]

    # The operator hands raw bytes (not text) to the adapter when there is no doc column
    for call in mock_adapter.classify_document.call_args_list:
        assert call.kwargs["binary_content"] == b"fake_binary"
        assert call.kwargs["existing_text"] is None

    # Verify _temp_content_for_extract column was added
    assert DocpipeConstants.TEMP_CONTENT_COLUMN in result_table.column_names
    assert result_table[DocpipeConstants.TEMP_CONTENT_COLUMN].to_pylist() == ["A" * 3000] * 2

    # Verify _temp_pages_processed column was added (both should be 1 page)
    assert DocpipeConstants.TEMP_PAGES_PROCESSED_COLUMN in result_table.column_names
    pages_column = result_table[DocpipeConstants.TEMP_PAGES_PROCESSED_COLUMN].to_pylist()
    assert pages_column == [1, 1]


@pytest.mark.unit
def test_no_temp_columns_when_adapter_returns_no_extracted_content():
    """Adapters that do not extract text (e.g. hybrid) must not cause temp columns to be written."""
    table = pa.table({"id": ["doc1"], "name": ["test1.pdf"], "path": ["/path/to/test1.pdf"]})
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "ollama",  # pragma: allowlist secret
        },
        "document_types": ["invoice"],
    }
    operator = DocumentClassifierOperator(config)
    mock_adapter = MagicMock()
    mock_adapter.classify_document.return_value = ClassificationResponse(
        document_type="invoice", confidence=9, reasoning="Test", success=True
    )
    operator.adapter = mock_adapter

    with (
        patch("docpipe.core.operators.operator_utils.OperatorUtils.prepare_document_content_fetch") as mock_prepare,
        patch("docpipe.core.operators.operator_utils.OperatorUtils.extract_content") as mock_extract,
    ):
        mock_prepare.return_value = [
            {"idx": 0, "doc_id": "doc1", "doc_name": "test1.pdf", "binary_content": b"fake_binary"}
        ]
        result_tables, metadata = operator.transform(table)

    mock_extract.assert_not_called()
    result_table = result_tables[0]
    assert DocpipeConstants.TEMP_CONTENT_COLUMN not in result_table.column_names
    assert DocpipeConstants.TEMP_PAGES_PROCESSED_COLUMN not in result_table.column_names
    assert metadata[Metrics.External.PROCESSED_DOCS] == 1


@pytest.mark.unit
def test_blank_extraction_is_recorded_as_skipped_not_failed():
    """A blank-extraction failure signalled by the adapter is a skip, matching previous behaviour."""
    table = pa.table({"id": ["doc1"], "name": ["test1.pdf"], "path": ["/path/to/test1.pdf"]})
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "ollama",  # pragma: allowlist secret
        },
        "document_types": ["invoice"],
    }
    operator = DocumentClassifierOperator(config)
    mock_adapter = MagicMock()
    mock_adapter.classify_document.return_value = ClassificationResponse(
        document_type="unknown",
        confidence=0,
        reasoning="",
        success=False,
        error="Empty content",
        extracted_content="  ",
        extraction_metadata={},
    )
    operator.adapter = mock_adapter

    with patch("docpipe.core.operators.operator_utils.OperatorUtils.prepare_document_content_fetch") as mock_prepare:
        mock_prepare.return_value = [
            {"idx": 0, "doc_id": "doc1", "doc_name": "test1.pdf", "binary_content": b"fake_binary"}
        ]
        _, metadata = operator.transform(table)

    assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 1
    assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0


@pytest.mark.unit
def test_document_classifier_provider_schemas():
    """Test _get_classifier_provider_schemas returns correct structure."""
    schemas = DocumentClassifierOperator._get_classifier_provider_schemas()
    assert "litellm" in schemas
    assert "watsonx" in schemas
    for name, schema in schemas.items():
        assert "properties" in schema, f"Schema for {name} missing 'properties'"


@pytest.mark.unit
def test_document_classifier_validate_unsupported_provider():
    """Test validate() reports unsupported provider."""
    config = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "ollama",  # pragma: allowlist secret
        },
        "document_types": ["invoice"],
    }
    operator = DocumentClassifierOperator(config)
    # Patch provider to something unsupported after init
    operator.provider = "unsupported_provider"
    errors: list[str] = []
    warnings: list[str] = []
    operator.validate(errors, warnings, [])
    assert any("unsupported_provider" in e for e in errors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
