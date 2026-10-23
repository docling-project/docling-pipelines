#!/usr/bin/env python3
"""
Unit tests for ExtractOperator (unified extraction operator).
Tests the operator with sample PDF files from the fixtures directory.
"""

import json
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants

# Path setup is now automatic via conftest.py


@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Module-local autouse fixture for memory cleanup after each test."""
    import gc

    yield

    # Explicit garbage collection after each test
    gc.collect()

    # Clear safe repository-owned caches/singletons if present
    try:
        from docpipe.integrations.docling.client import DoclingClient

        if hasattr(DoclingClient, "_instance"):
            DoclingClient._instance = None
    except (ImportError, AttributeError):
        pass

    try:
        from docpipe.integrations.ollama.client import OllamaClient

        if hasattr(OllamaClient, "_instance"):
            OllamaClient._instance = None
    except (ImportError, AttributeError):
        pass


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.unit
def test_extract_operator_docling_library_mode(sample_pdf_files):
    """Test the ExtractOperator with docling_library text extraction mode."""
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Use fixture for test files (automatically skips if not found)
    test_files = sample_pdf_files[:1]  # Test with first file

    # Prepare data for PyArrow table
    file_data: dict[str, list] = {"id": [], "name": [], "path": [], "binary_content": []}

    for file_path in test_files:
        with file_path.open("rb") as f:
            binary_content = f.read()

        file_data["id"].append(str(file_path))
        file_data["name"].append(file_path.name)
        file_data["path"].append(str(file_path))
        file_data["binary_content"].append(binary_content)

    # Create PyArrow table
    table = pa.table(file_data)
    assert table.num_rows > 0, "Table should have rows"

    # Initialize operator with docling_library text extraction configuration
    config = {
        "text_extraction": {
            "provider": "docling_library",
            "doc_column": "doc_content",
        },
        "entity_extraction": {"provider": "none"},
        "max_workers": 2,
    }

    operator = ExtractOperator(config=config)

    # Transform the table
    result_tables, metadata = operator.transform(table)
    result_table = result_tables[0]

    # Assertions
    assert "doc_content" in result_table.column_names, "Content column should exist"
    assert "doc_id_hash" in result_table.column_names, "Hash ID column should exist"
    assert "pages_processed" in result_table.column_names, "Pages processed column should exist"

    # Check content
    first_content = result_table["doc_content"][0].as_py()
    assert first_content is not None, "Content should not be None"
    assert len(first_content) > 0, "Content should not be empty"

    # Check hash
    first_hash = result_table["doc_id_hash"][0].as_py()
    assert first_hash is not None, "Hash should not be None"
    assert len(first_hash) > 0, "Hash should not be empty"

    # Check pages_processed
    first_pages = result_table["pages_processed"][0].as_py()
    assert first_pages is not None, "Pages processed should not be None"
    assert first_pages > 0, "Pages processed should be greater than 0"

    # Check metadata
    assert metadata["documents_in_scope"] == table.num_rows, "Total docs should match input rows"
    assert metadata["processed_docs"] > 0, "Should have processed at least one document"
    assert "page_type_stats" in metadata, "Metadata should contain page_type_stats"
    assert "total_pages_converted" in metadata, "Metadata should contain total_pages_converted"
    assert isinstance(metadata["page_type_stats"], dict), "page_type_stats should be a dict"
    assert metadata["total_pages_converted"] > 0, "total_pages_converted should be greater than 0"


@pytest.mark.unit
def test_extract_operator_multi_format_output(sample_pdf_files):
    """Test the ExtractOperator with multiple output formats."""
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Use fixture for test files
    test_files = sample_pdf_files[:1]  # Test with first file

    # Prepare data for PyArrow table
    file_data: dict[str, list] = {"id": [], "name": [], "path": [], "binary_content": []}

    for file_path in test_files:
        with file_path.open("rb") as f:
            binary_content = f.read()

        file_data["id"].append(str(file_path))
        file_data["name"].append(file_path.name)
        file_data["path"].append(str(file_path))
        file_data["binary_content"].append(binary_content)

    # Create PyArrow table
    table = pa.table(file_data)
    assert table.num_rows > 0, "Table should have rows"

    # Initialize operator with additional output formats (markdown is always generated)
    config = {
        "text_extraction": {
            "provider": "docling_library",
            "doc_column": "doc_content",
            "provider_config": {
                "additional_formats": ["html", "json"],
            },
        },
        "entity_extraction": {"provider": "none"},
        "max_workers": 2,
    }

    operator = ExtractOperator(config=config)

    # Transform the table
    result_tables, metadata = operator.transform(table)
    result_table = result_tables[0]

    # Assertions for all format columns
    assert "doc_content" in result_table.column_names, "Markdown content column should exist"
    assert "content_html" in result_table.column_names, "HTML content column should exist"
    assert "content_json" in result_table.column_names, "JSON content column should exist"
    assert "doc_id_hash" in result_table.column_names, "Hash ID column should exist"

    # Check markdown content
    markdown_content = result_table["doc_content"][0].as_py()
    assert markdown_content is not None, "Markdown content should not be None"
    assert len(markdown_content) > 0, "Markdown content should not be empty"

    # Check HTML content
    html_content = result_table["content_html"][0].as_py()
    assert html_content is not None, "HTML content should not be None"
    assert len(html_content) > 0, "HTML content should not be empty"
    assert "<" in html_content, "HTML content should contain HTML tags"

    # Check JSON content
    json_content = result_table["content_json"][0].as_py()
    assert json_content is not None, "JSON content should not be None"
    assert len(json_content) > 0, "JSON content should not be empty"
    # Verify it's valid JSON
    json_data = json.loads(json_content)
    assert isinstance(json_data, dict), "JSON content should be a dictionary"

    # Check metadata
    assert metadata["documents_in_scope"] == table.num_rows, "Total docs should match input rows"
    assert metadata["processed_docs"] > 0, "Should have processed at least one document"


@pytest.mark.unit
def test_extract_operator_default_format(sample_pdf_files):
    """Test the ExtractOperator with default format (backward compatibility)."""
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Use fixture for test files
    test_files = sample_pdf_files[:1]

    # Prepare data for PyArrow table
    file_data: dict[str, list] = {"id": [], "name": [], "path": [], "binary_content": []}

    for file_path in test_files:
        with file_path.open("rb") as f:
            binary_content = f.read()

        file_data["id"].append(str(file_path))
        file_data["name"].append(file_path.name)
        file_data["path"].append(str(file_path))
        file_data["binary_content"].append(binary_content)

    # Create PyArrow table
    table = pa.table(file_data)

    # Initialize operator without additional_formats (should generate markdown only by default)
    config = {
        "text_extraction": {
            "provider": "docling_library",
            "doc_column": "doc_content",
        },
        "entity_extraction": {"provider": "none"},
        "max_workers": 2,
    }

    operator = ExtractOperator(config=config)

    # Transform the table
    result_tables, _ = operator.transform(table)
    result_table = result_tables[0]

    # Assertions - should only have markdown column
    assert "doc_content" in result_table.column_names, "Markdown content column should exist"
    assert "content_html" not in result_table.column_names, "HTML column should not exist by default"
    assert "content_json" not in result_table.column_names, "JSON column should not exist by default"

    # Check content
    markdown_content = result_table["doc_content"][0].as_py()

    assert markdown_content is not None, "Markdown content should not be None"
    assert len(markdown_content) > 0, "Markdown content should not be empty"


@pytest.mark.unit
@pytest.mark.skip(reason="Requires docling-serve service running")
def test_extract_operator_docling_serve_mode(sample_pdf_files):
    """Test the ExtractOperator with docling_serve text extraction mode."""
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Use fixture for test files
    test_files = sample_pdf_files[:1]

    # Prepare data for PyArrow table
    file_data: dict[str, list] = {"id": [], "name": [], "path": [], "binary_content": []}

    for file_path in test_files:
        with file_path.open("rb") as f:
            binary_content = f.read()

        file_data["id"].append(str(file_path))
        file_data["name"].append(file_path.name)
        file_data["path"].append(str(file_path))
        file_data["binary_content"].append(binary_content)

    # Create PyArrow table
    table = pa.table(file_data)

    # Initialize operator with docling_serve configuration
    config = {
        "text_extraction": {
            "provider": "docling_serve",
            "provider_config": {
                "base_url": "http://localhost:30501/",
                "timeout": 300,
                "poll_interval": 2,
                "max_retries": 3,
                "do_ocr": True,
                "ocr_engine": "easyocr",
                "pdf_backend": "dlparse_v2",
                "table_mode": "fast",
                "image_export_mode": "placeholder",
            },
            "doc_column": "doc_content",
        },
        "entity_extraction": {"provider": "none"},
        "max_workers": 2,
    }

    operator = ExtractOperator(config=config)

    # Transform the table
    result_tables, metadata = operator.transform(table)
    result_table = result_tables[0]

    # Assertions
    assert "doc_content" in result_table.column_names, "Content column should exist"
    assert "doc_id_hash" in result_table.column_names, "Hash ID column should exist"

    # Check content
    first_content = result_table["doc_content"][0].as_py()
    assert first_content is not None, "Content should not be None"
    assert len(first_content) > 0, "Content should not be empty"

    # Check metadata
    assert metadata["documents_in_scope"] == table.num_rows
    assert metadata["processed_docs"] > 0


@pytest.mark.unit
def test_extract_operator_docling_serve_config_validation():
    """Test docling_serve configuration parameter validation."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Test with minimal docling_serve configuration
    config = {
        "text_extraction": {
            "provider": "docling_serve",
            "provider_config": {
                "base_url": "http://localhost:30501/",
            },
        },
        "entity_extraction": {"provider": "none"},
    }

    operator = ExtractOperator(config=config)

    # Verify operator was created successfully
    assert operator.text_extraction_mode.value == "docling_serve"
    assert operator.entity_extraction_mode.value == "none"


@pytest.mark.unit
def test_extract_operator_docling_serve_with_api_key():
    """Test docling_serve configuration with API key."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_serve",
            "provider_config": {
                "base_url": "http://localhost:30501/",
                "api_key": "test-api-key-12345",  # pragma: allowlist secret
                "timeout": 600,
            },
        },
    }

    operator = ExtractOperator(config=config)

    # Verify configuration was accepted
    assert operator.text_extraction_mode.value == "docling_serve"


@pytest.mark.unit
def test_extract_operator_docling_serve_with_ocr_languages():
    """Test docling_serve configuration with OCR language specification."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_serve",
            "provider_config": {
                "base_url": "http://localhost:30501/",
                "do_ocr": True,
                "ocr_engine": "easyocr",
                "ocr_languages": ["en", "es", "fr"],
            },
        },
    }

    operator = ExtractOperator(config=config)

    # Verify configuration was accepted
    assert operator.text_extraction_mode.value == "docling_serve"


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.unit
def test_extract_operator_docling_library_with_entity_extraction_ollama(
    sample_pdf_files,
):
    """Test ExtractOperator with docling_library text extraction + LiteLLM entity extraction (Ollama-compatible)."""
    import json
    from unittest.mock import Mock, patch

    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Use fixture for test files
    test_files = sample_pdf_files[:1]

    # Prepare data for PyArrow table
    file_data: dict[str, list] = {"id": [], "name": [], "path": [], "binary_content": []}

    for file_path in test_files:
        with file_path.open("rb") as f:
            binary_content = f.read()

        file_data["id"].append(str(file_path))
        file_data["name"].append(file_path.name)
        file_data["path"].append(str(file_path))
        file_data["binary_content"].append(binary_content)

    # Create PyArrow table
    table = pa.table(file_data)

    # Initialize operator with both text and entity extraction
    config = {
        "text_extraction": {
            "provider": "docling_library",
            "doc_column": "doc_content",
        },
        "entity_extraction": {
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/llama3.2",
                "temperature": 0.0,
                "max_tokens": 4096,
                "api_base": "http://localhost:11434/v1",
                "api_key": "<ollama>",  # pragma: allowlist secret
            },
            "custom_schema": {
                "invoice_number": "string",
                "total_amount": "number",
                "date": "string",
            },
        },
        "max_workers": 2,
    }

    # Mock the LiteLLM client to avoid actual API calls
    with patch("docpipe.integrations.litellm.client.LiteLLMLLMClient") as mock_litellm_class:
        mock_instance = Mock()
        # Mock the chat method which is called by entity extraction
        mock_instance.chat.return_value = json.dumps(
            {"invoice_number": "INV-001", "total_amount": 1500.00, "date": "2024-01-15"}
        )
        mock_litellm_class.return_value = mock_instance

        operator = ExtractOperator(config=config)

        # Transform the table
        result_tables, _metadata = operator.transform(table)
        result_table = result_tables[0]

        # Assertions
        assert "doc_content" in result_table.column_names, "Content column should exist"
        assert "entities" in result_table.column_names, "Entities column should exist"
        assert "doc_id_hash" in result_table.column_names, "Hash ID column should exist"


@pytest.mark.unit
def test_extract_operator_docling_serve_with_entity_extraction():
    """Test ExtractOperator with docling_serve text + LiteLLM entity extraction."""
    from unittest.mock import Mock, patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Mock the LiteLLM client
    with patch("docpipe.integrations.litellm.client.LiteLLMLLMClient") as mock_litellm_class:
        mock_instance = Mock()
        mock_litellm_class.return_value = mock_instance

        # Test configuration combining docling_serve and entity extraction
        config = {
            "text_extraction": {
                "provider": "docling_serve",
                "provider_config": {
                    "base_url": "http://localhost:30501/",
                    "timeout": 300,
                },
                "doc_column": "doc_content",
            },
            "entity_extraction": {
                "provider": "litellm",
                "provider_config": {
                    "model_id": "openai/gpt-3.5-turbo",
                    "temperature": 0.0,
                    "max_tokens": 2000,
                    "api_key": "test-api-key",  # pragma: allowlist secret
                    "api_base": "https://api.test.local/v1",
                },
            },
            "max_workers": 2,
        }

        operator = ExtractOperator(config=config)

        # Verify both modes are configured
        assert operator.text_extraction_mode.value == "docling_serve"
        assert operator.entity_extraction_mode.value == "litellm"
        assert operator.entity_adapter is not None


@pytest.mark.unit
def test_extract_operator_invalid_text_mode():
    """Test ExtractOperator with invalid text extraction provider."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator
    from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

    config = {
        "text_extraction": {
            "provider": "invalid_mode",
        },
    }

    with pytest.raises(FlowExecutionFailedException) as exc_info:
        ExtractOperator(config=config)

    assert "Invalid text_extraction.provider" in str(exc_info.value)


@pytest.mark.unit
def test_extract_operator_invalid_entity_mode():
    """Test ExtractOperator with invalid entity extraction provider."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator
    from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

    config = {
        "text_extraction": {
            "provider": "docling_library",
        },
        "entity_extraction": {
            "provider": "invalid_mode",
        },
    }

    with pytest.raises(FlowExecutionFailedException) as exc_info:
        ExtractOperator(config=config)

    assert "Invalid entity_extraction.provider" in str(exc_info.value)


@pytest.mark.unit
def test_extract_operator_docling_library_vlm_mode_config():
    """Test ExtractOperator with docling_library VLM text extraction provider configuration."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "provider_config": {
                "vlm_pipeline": {
                    "preset": "granite_docling",
                    "engine": "transformers",
                },
            },
            "doc_column": "doc_content",
        },
        "max_workers": 2,
    }

    operator = ExtractOperator(config=config)

    # Verify docling_library with VLM mode is configured
    assert operator.text_extraction_mode.value == "docling_library"
    assert operator.entity_extraction_mode.value == "none"


@pytest.mark.unit
def test_extract_operator_get_metadata():
    """Test ExtractOperator metadata retrieval."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
        },
    }

    operator = ExtractOperator(config=config)
    metadata = operator.get_metadata()

    # Verify metadata structure
    assert "category" in metadata
    assert "features" in metadata
    assert "attributes" in metadata
    assert "is_operator_available" in metadata

    # Verify key attributes are present (now nested)
    attributes = metadata["attributes"]
    assert "text_extraction" in attributes
    assert "entity_extraction" in attributes
    assert "max_workers" in attributes

    # Verify text_extraction nested structure
    text_extraction = attributes["text_extraction"]
    assert "properties" in text_extraction
    text_props = text_extraction["properties"]
    assert "provider" in text_props
    assert "provider_config" in text_props

    # Verify entity_extraction nested structure
    entity_extraction = attributes["entity_extraction"]
    assert "properties" in entity_extraction
    entity_props = entity_extraction["properties"]
    assert "provider" in entity_props
    assert "provider_config" in entity_props

    # provider_config carries 'providers' (one schema per registered adapter)
    provider_config = text_props["provider_config"]
    assert "providers" in provider_config
    assert "docling_library" in provider_config["providers"]
    assert "docling_serve" in provider_config["providers"]

    # entity_extraction provider_config also carries 'providers'
    entity_provider_config = entity_props["provider_config"]
    assert "providers" in entity_provider_config
    assert "litellm" in entity_provider_config["providers"]
    assert "watsonx" in entity_provider_config["providers"]
    assert "docling" in entity_provider_config["providers"]

    # provider_config description references 'providers'
    assert "providers" in provider_config["description"]
    assert "providers" in entity_provider_config["description"]

    # docling_library schema has vlm_pipeline nested under its properties
    docling_library_schema = provider_config["providers"]["docling_library"]
    assert "properties" in docling_library_schema
    provider_config_props = docling_library_schema["properties"]
    assert "vlm_pipeline" in provider_config_props

    vlm_pipeline = provider_config_props["vlm_pipeline"]
    assert vlm_pipeline["type"] == "json"
    assert "name" in vlm_pipeline
    assert "properties" in vlm_pipeline

    vlm_props = vlm_pipeline["properties"]
    assert "preset" in vlm_props
    assert "engine" in vlm_props
    assert "engine_options" in vlm_props

    # Each scalar field carries translated docpipe type, name, and description
    assert vlm_props["preset"]["type"] == "string"
    assert vlm_props["preset"]["name"] == "Preset"
    assert "description" in vlm_props["preset"]

    assert vlm_props["engine"]["type"] == "string"
    assert vlm_props["engine"]["name"] == "Engine"
    assert "description" in vlm_props["engine"]

    # engine_options is dict[str, Any] — translated to "json"
    assert vlm_props["engine_options"]["type"] == "json"
    assert "description" in vlm_props["engine_options"]

    # docling_serve schema exposes base_url
    docling_serve_schema = provider_config["providers"]["docling_serve"]
    assert "properties" in docling_serve_schema
    assert "base_url" in docling_serve_schema["properties"]

    # Verify defaults match the actual adapter runtime values
    assert text_props["provider"]["default"] == "docling_library"
    assert entity_props["provider"]["default"] == "none"
    assert vlm_props["preset"]["default"] == "granite_docling"
    assert vlm_props["engine"]["default"] == "transformers"


@pytest.mark.unit
def test_extract_operator_asr_config_validation():
    """Test ASR configuration parameter validation."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "provider_config": {
                "asr_pipeline": {
                    "model_id": "whisper_turbo",
                },
            },
            "doc_column": "doc_content",
        },
    }

    operator = ExtractOperator(config=config)

    # Verify operator was created successfully with ASR config
    assert operator.text_extraction_mode.value == "docling_library"
    assert operator.entity_extraction_mode.value == "none"


@pytest.mark.unit
def test_extract_operator_asr_model_names():
    """Test various ASR model name configurations."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    valid_models = [
        "whisper_tiny",
        "whisper_small",
        "whisper_medium",
        "whisper_base",
        "whisper_large",
        "whisper_turbo",
    ]

    for model_name in valid_models:
        config = {
            "text_extraction": {
                "provider": "docling_library",
                "provider_config": {
                    "asr_pipeline": {
                        "model_id": model_name,
                    },
                },
                "doc_column": "doc_content",
            },
        }

        operator = ExtractOperator(config=config)
        assert operator.text_extraction_mode.value == "docling_library"


@pytest.mark.unit
def test_extract_operator_asr_without_model_name():
    """Test ASR configuration without explicit model name (should use default)."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "provider_config": {
                "asr_pipeline": {},
            },
            "doc_column": "doc_content",
        },
    }

    operator = ExtractOperator(config=config)
    assert operator.text_extraction_mode.value == "docling_library"


@pytest.mark.unit
@pytest.mark.skip(reason="Requires sample audio file and ASR dependencies")
def test_extract_operator_asr_with_audio_file():
    """
    Test ExtractOperator with ASR pipeline on audio file.
    This test requires:
    - Sample audio file (WAV format recommended)
    - Docling ASR dependencies installed
    - Sufficient system resources for ASR model
    """
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Prepare test data with audio file
    file_data = {
        "id": ["test_audio_1"],
        "name": ["sample.wav"],
        "path": ["/path/to/sample.wav"],
        "binary_content": [b"mock_audio_content"],  # Would be actual audio bytes
    }

    table = pa.table(file_data)

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "provider_config": {
                "asr_pipeline": {
                    "model_id": "whisper_turbo",
                },
            },
            "doc_column": "doc_content",
        },
    }

    operator = ExtractOperator(config=config)

    # Transform the table
    result_tables, metadata = operator.transform(table)
    result_table = result_tables[0]

    # Assertions
    assert "doc_content" in result_table.column_names
    assert result_table["doc_content"][0].as_py() is not None
    assert metadata["documents_in_scope"] == 1


@pytest.mark.unit
def test_extract_operator_asr_with_entity_extraction():
    """Test ASR pipeline combined with LiteLLM entity extraction."""
    from unittest.mock import Mock, patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    with patch("docpipe.integrations.litellm.client.LiteLLMLLMClient") as mock_litellm_class:
        mock_instance = Mock()
        mock_litellm_class.return_value = mock_instance

        config = {
            "text_extraction": {
                "provider": "docling_library",
                "provider_config": {
                    "asr_pipeline": {
                        "model_id": "whisper_turbo",
                    },
                },
                "doc_column": "doc_content",
            },
            "entity_extraction": {
                "provider": "litellm",
                "provider_config": {
                    "model_id": "gpt-3.5-turbo",
                    "temperature": 0.0,
                    "max_tokens": 2000,
                    "api_key": "test-api-key",  # pragma: allowlist secret
                    "api_base": "https://api.test.local/v1",
                },
                "custom_schema": {
                    "speaker": "string",
                    "topic": "string",
                    "key_points": "array",
                },
            },
        }

        operator = ExtractOperator(config=config)
        # Verify both ASR and entity extraction are configured
        assert operator.text_extraction_mode.value == "docling_library"
        assert operator.entity_extraction_mode.value == "litellm"


@pytest.mark.unit
def test_extract_operator_expand_extracted_data():
    """Test ExtractOperator with expand_extracted_data flag and LiteLLM."""
    from unittest.mock import Mock, patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Mock the LiteLLM client
    with patch("docpipe.integrations.litellm.client.LiteLLMLLMClient") as mock_litellm_class:
        mock_instance = Mock()
        mock_litellm_class.return_value = mock_instance

        config = {
            "text_extraction": {
                "provider": "docling_library",
            },
            "entity_extraction": {
                "provider": "litellm",
                "provider_config": {
                    "model_id": "gpt-3.5-turbo",
                    "temperature": 0.0,
                    "max_tokens": 2000,
                    "api_key": "test-api-key",  # pragma: allowlist secret
                    "api_base": "https://api.test.local/v1",
                },
                "expand_extracted_data": True,
                "custom_schema": {"invoice_number": "string", "amount": "number"},
            },
        }

        operator = ExtractOperator(config=config)

        # Verify configuration
        assert operator.expand_extracted_data is True
        assert operator.entity_adapter is not None


@pytest.mark.unit
def test_extract_operator_default_values():
    """Test ExtractOperator with default configuration values."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Minimal configuration - should use defaults
    config = {
        "text_extraction": {
            "provider": "docling_library",
        },
    }

    operator = ExtractOperator(config=config)

    # Verify defaults
    assert operator.text_extraction_mode.value == "docling_library"
    assert operator.entity_extraction_mode.value == "none"
    assert operator.doc_column == "content"
    assert operator.expand_extracted_data is False
    assert operator.entity_adapter is None


@pytest.mark.unit
def test_extract_operator_docling_serve_all_parameters():
    """Test ExtractOperator with all docling_serve parameters specified."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_serve",
            "provider_config": {
                "base_url": "http://localhost:30501/",
                "api_key": "secret-key",  # pragma: allowlist secret
                "timeout": 600,
                "poll_interval": 5,
                "max_retries": 5,
                "do_ocr": True,
                "ocr_engine": "tesseract",
                "ocr_languages": ["en", "de", "fr"],
                "pdf_backend": "pypdfium2",
                "table_mode": "accurate",
                "image_export_mode": "embedded",
            },
            "doc_column": "content",
        },
        "max_workers": 4,
    }

    operator = ExtractOperator(config=config)

    # Verify operator was created successfully with all parameters
    assert operator.text_extraction_mode.value == "docling_serve"
    assert operator.doc_column == "content"


@pytest.mark.unit
def test_extract_operator_mode_combinations():
    """Test various valid mode combinations."""
    from unittest.mock import Mock, patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Mock the Ollama client at the import location
    with (
        patch("docpipe.integrations.ollama.client.OllamaClient") as mock_ollama_class,
        patch("docpipe.core.adapters.litellm.litellm_adapter.LiteLLMLLMClient") as mock_litellm_class,
    ):
        mock_ollama_class.return_value = Mock()
        mock_litellm_instance = Mock()
        mock_litellm_instance.chat = Mock(
            return_value=json.dumps({"person_name": "John Doe", "invoice_number": "INV-123"})
        )
        mock_litellm_class.return_value = mock_litellm_instance

        # Test all valid text mode + entity mode combinations
        text_modes = ["docling_library", "docling_serve"]
        entity_modes = ["none", "litellm", "docling"]

        for text_mode in text_modes:
            for entity_mode in entity_modes:
                config: dict[str, Any] = {
                    "text_extraction": {
                        "provider": text_mode,
                    },
                }

                # Add mode-specific required parameters
                if text_mode == "docling_serve":
                    config["text_extraction"]["provider_config"] = {
                        "base_url": "http://localhost:5001",
                    }

                if entity_mode != "none":
                    config["entity_extraction"] = {
                        "provider": entity_mode,
                    }
                    if entity_mode == "litellm":
                        config["entity_extraction"]["provider_config"] = {
                            "model_id": "openai/llama3.2",
                            "api_key": "test-api-key",  # pragma: allowlist secret
                            "api_base": "https://api.test.local/v1",
                        }

                operator = ExtractOperator(config=config)
                assert operator.text_extraction_mode.value == text_mode
                assert operator.entity_extraction_mode.value == entity_mode


@pytest.mark.unit
def test_extract_operator_empty_table():
    """Test ExtractOperator with empty input table."""
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Create empty table
    schema = pa.schema(
        [
            ("id", pa.string()),
            ("name", pa.string()),
            ("path", pa.string()),
            ("binary_content", pa.binary()),
        ]
    )
    table = pa.table({"id": [], "name": [], "path": [], "binary_content": []}, schema=schema)

    config = {
        "text_extraction": {
            "provider": "docling_library",
        },
    }

    operator = ExtractOperator(config=config)
    result_tables, metadata = operator.transform(table)

    # Should handle empty table gracefully
    assert len(result_tables) == 1
    assert result_tables[0].num_rows == 0
    assert metadata["documents_in_scope"] == 0


def _build_pdf_input_table(*, sample_pdf_files, max_files: int = 1):
    """Build a PyArrow input table from sample PDF fixtures."""
    import pyarrow as pa

    test_files = sample_pdf_files[:max_files]
    file_data: dict[str, list[Any]] = {
        "id": [],
        "name": [],
        "path": [],
        "binary_content": [],
    }

    for file_path in test_files:
        with file_path.open("rb") as file_handle:
            binary_content = file_handle.read()

        file_data["id"].append(str(file_path))
        file_data["name"].append(file_path.name)
        file_data["path"].append(str(file_path))
        file_data["binary_content"].append(binary_content)

    return pa.table(file_data)


@pytest.mark.unit
def test_extract_operator_litellm_entity_mode():
    """Test ExtractOperator with LiteLLM entity extraction provider."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
        },
        "entity_extraction": {
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/gpt-3.5-turbo",
                "temperature": 0.0,
                "max_tokens": 2000,
                "api_key": "test-api-key",  # pragma: allowlist secret
                "api_base": "https://api.test.local/v1",
            },
            "custom_schema": {"company": "string", "date": "string"},
        },
    }

    with patch("docpipe.core.adapters.litellm.litellm_adapter.LiteLLMLLMClient") as mock_litellm_class:
        mock_litellm_class.return_value = Mock()

        operator = ExtractOperator(config=config)

    # Verify LiteLLM entity mode is configured
    assert operator.entity_extraction_mode.value == "litellm"
    assert operator.entity_adapter is not None


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.unit
def test_extract_operator_docling_library_with_entity_extraction_litellm_schema(
    sample_pdf_files,
):
    """Execute ExtractOperator with LiteLLM schema-based entity extraction."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    table = _build_pdf_input_table(sample_pdf_files=sample_pdf_files, max_files=1)

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "doc_column": "doc_content",
        },
        "entity_extraction": {
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/gpt-3.5-turbo",
                "temperature": 0.0,
                "max_tokens": 2000,
                "api_key": "test-api-key",  # pragma: allowlist secret
                "api_base": "https://api.test.local/v1",
            },
            "custom_schema": {
                "document_type": "invoice",
                "fields": [
                    {"name": "person_name", "type": "string"},
                    {"name": "invoice_date", "type": "string"},
                    {"name": "total_amount", "type": "number"},
                ],
            },
        },
        "max_workers": 2,
    }

    mocked_entities = {
        "person_name": "John Doe",
        "invoice_date": "2024-01-15",
        "total_amount": 1500.0,
    }

    with patch("docpipe.core.adapters.litellm.litellm_adapter.LiteLLMLLMClient") as mock_litellm_class:
        mock_instance = Mock()
        mock_instance.chat = Mock(return_value=json.dumps(mocked_entities))
        mock_litellm_class.return_value = mock_instance

        operator = ExtractOperator(config=config)
        result_tables, metadata = operator.transform(table)

    result_table = result_tables[0]

    assert "doc_content" in result_table.column_names
    assert "entities" in result_table.column_names
    assert "doc_id_hash" in result_table.column_names
    assert result_table.num_rows == 1
    assert metadata["documents_in_scope"] == table.num_rows
    assert metadata["processed_docs"] == 1
    assert metadata[Metrics.External.NODE_STATUS] in {
        ExecutionStatus.COMPLETED.value,
        ExecutionStatus.COMPLETED_WITH_WARNINGS.value,
        ExecutionStatus.COMPLETED_WITH_ERRORS.value,
    }

    extracted_entities = json.loads(result_table["entities"][0].as_py())
    assert extracted_entities == mocked_entities

    extracted_content = result_table["doc_content"][0].as_py()
    assert extracted_content is not None
    assert len(extracted_content) > 0

    mock_instance.chat.assert_called_once()
    chat_call = mock_instance.chat.call_args
    assert chat_call.kwargs["temperature"] == 0.0
    assert chat_call.kwargs["max_tokens"] == 2000
    assert len(chat_call.kwargs["messages"]) == 2


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.unit
def test_extract_operator_docling_library_with_entity_extraction_litellm_schema_free(
    sample_pdf_files,
):
    """Execute ExtractOperator with LiteLLM entity extraction with custom schema."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    table = _build_pdf_input_table(sample_pdf_files=sample_pdf_files, max_files=1)

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "doc_column": "doc_content",
        },
        "entity_extraction": {
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/gpt-3.5-turbo",
                "temperature": 0.0,
                "max_tokens": 1500,
                "api_key": "test-api-key",  # pragma: allowlist secret
                "api_base": "https://api.test.local/v1",
            },
            "custom_schema": {
                "document_type": "general",
                "fields": [
                    {"name": "person", "type": "string"},
                    {"name": "date", "type": "string"},
                    {"name": "amount", "type": "string"},
                    {"name": "organization", "type": "string"},
                ],
            },
        },
        "max_workers": 2,
    }

    mocked_entities = {
        "person": "Jane Smith",
        "date": "2024-02-20",
        "amount": "$950.00",
        "organization": "Acme Corp",
    }

    with patch("docpipe.core.adapters.litellm.litellm_adapter.LiteLLMLLMClient") as mock_litellm_class:
        mock_instance = Mock()
        mock_instance.chat = Mock(return_value=json.dumps(mocked_entities))
        mock_litellm_class.return_value = mock_instance

        operator = ExtractOperator(config=config)
        result_tables, metadata = operator.transform(table)

    result_table = result_tables[0]

    assert "entities" in result_table.column_names
    assert result_table.num_rows == 1
    assert metadata["processed_docs"] == 1

    extracted_entities = json.loads(result_table["entities"][0].as_py())
    assert extracted_entities == mocked_entities
    assert extracted_entities["person"] == "Jane Smith"
    assert extracted_entities["organization"] == "Acme Corp"

    chat_call = mock_instance.chat.call_args
    assert (
        chat_call.kwargs["messages"][0]["content"] == OperatorConstants.ExtractionModes.ENTITY_EXTRACTION_SYSTEM_PROMPT
    )


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.unit
def test_extract_operator_docling_library_with_entity_extraction_litellm_expanded_columns(
    sample_pdf_files,
):
    """Execute ExtractOperator with LiteLLM entity extraction and expanded columns."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    table = _build_pdf_input_table(sample_pdf_files=sample_pdf_files, max_files=1)

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "doc_column": "doc_content",
        },
        "entity_extraction": {
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/gpt-3.5-turbo",
                "temperature": 0.0,
                "max_tokens": 2000,
                "api_key": "test-api-key",  # pragma: allowlist secret
                "api_base": "https://api.test.local/v1",
            },
            "custom_schema": {
                "document_type": "invoice",
                "fields": [
                    {"name": "person_name", "type": "string"},
                    {"name": "invoice_date", "type": "string"},
                    {"name": "total_amount", "type": "number"},
                ],
            },
            "expand_extracted_data": True,
        },
        "max_workers": 2,
    }

    mocked_entities = {
        "person_name": "Alex Johnson",
        "invoice_date": "2024-03-01",
        "total_amount": 2750.5,
    }

    with patch("docpipe.core.adapters.litellm.litellm_adapter.LiteLLMLLMClient") as mock_litellm_class:
        mock_instance = Mock()
        mock_instance.chat = Mock(return_value=json.dumps(mocked_entities))
        mock_litellm_class.return_value = mock_instance

        operator = ExtractOperator(config=config)
        result_tables, metadata = operator.transform(table)

    result_table = result_tables[0]

    assert "entities" in result_table.column_names
    assert "entity_person_name" in result_table.column_names
    assert "entity_invoice_date" in result_table.column_names
    assert "entity_total_amount" in result_table.column_names
    assert metadata["processed_docs"] == 1

    assert result_table["entity_person_name"][0].as_py() == "Alex Johnson"
    assert result_table["entity_invoice_date"][0].as_py() == "2024-03-01"
    assert result_table["entity_total_amount"][0].as_py() == "2750.5"

    extracted_entities = json.loads(result_table["entities"][0].as_py())
    assert extracted_entities == mocked_entities


@pytest.mark.unit
def test_extract_operator_docling_entity_mode():
    """Test ExtractOperator with Docling template-based entity extraction."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
        },
        "entity_extraction": {
            "provider": "docling",
            "custom_schema": {"invoice_number": "string", "total": "number"},
        },
    }

    operator = ExtractOperator(config=config)

    # Verify Docling entity mode is configured
    assert operator.entity_extraction_mode.value == "docling"
    assert operator.entity_adapter is not None


@pytest.mark.unit
def test_extract_operator_invalid_text_extraction_provider_error():
    """Test ExtractOperator with completely invalid text extraction provider."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator
    from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

    config = {
        "text_extraction": {
            "provider": "nonexistent_mode",
        },
    }

    with pytest.raises(FlowExecutionFailedException) as exc_info:
        ExtractOperator(config=config)

    assert "Invalid text_extraction.provider" in str(exc_info.value)
    assert "nonexistent_mode" in str(exc_info.value)


@pytest.mark.unit
def test_extract_operator_invalid_entity_extraction_mode_error():
    """Test ExtractOperator with completely invalid entity extraction provider."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator
    from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

    config = {
        "text_extraction": {
            "provider": "docling_library",
        },
        "entity_extraction": {
            "provider": "nonexistent_entity_mode",
        },
    }

    with pytest.raises(FlowExecutionFailedException) as exc_info:
        ExtractOperator(config=config)

    assert "Invalid entity_extraction.provider" in str(exc_info.value)
    assert "nonexistent_entity_mode" in str(exc_info.value)


@pytest.mark.unit
def test_extract_operator_missing_required_columns(sample_pdf_files):
    """Test ExtractOperator with table missing both path and binary content.

    When all documents fail extraction (e.g., missing required columns),
    the operator should raise a FlowExecutionFailedException to prevent
    downstream operators from processing incomplete data.
    """
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator
    from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

    table = pa.table(
        {
            "id": ["doc1"],
            "name": ["test.pdf"],
        }
    )

    config = {
        "text_extraction": {
            "provider": "docling_library",
        },
    }

    operator = ExtractOperator(config=config)

    # When all documents fail extraction, operator raises FlowExecutionFailedException
    with pytest.raises(FlowExecutionFailedException) as exc_info:
        operator.transform(table)

    # Verify the error message indicates all documents failed
    error_message = str(exc_info.value).lower()
    assert "failed extraction" in error_message
    assert "cannot continue pipeline" in error_message


@pytest.mark.unit
def test_extract_operator_custom_doc_column():
    """Test ExtractOperator with custom doc_column name."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "doc_column": "custom_content_column",
        },
    }

    operator = ExtractOperator(config=config)

    assert operator.doc_column == "custom_content_column"


@pytest.mark.unit
def test_extract_operator_custom_output_columns():
    """Test ExtractOperator with custom output column configuration and LiteLLM."""
    from unittest.mock import Mock, patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Mock the LiteLLM client
    with patch("docpipe.integrations.litellm.client.LiteLLMLLMClient") as mock_litellm_class:
        mock_instance = Mock()
        mock_litellm_class.return_value = mock_instance

        config = {
            "text_extraction": {
                "provider": "docling_library",
                "doc_column": "my_doc",
            },
            "entity_extraction": {
                "provider": "litellm",
                "provider_config": {
                    "model_id": "openai/gpt-3.5-turbo",
                    "temperature": 0.0,
                    "max_tokens": 2000,
                    "api_key": "test-api-key",  # pragma: allowlist secret
                    "api_base": "https://api.test.local/v1",
                },
                "output_column": "my_entities",
            },
        }

        operator = ExtractOperator(config=config)

        assert operator.doc_column == "my_doc"
        assert operator.entity_adapter is not None


@pytest.mark.unit
def test_extract_operator_expand_extracted_data_flag():
    """Test ExtractOperator with expand_extracted_data enabled and LiteLLM."""
    from unittest.mock import Mock, patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Mock the LiteLLM client
    with patch("docpipe.integrations.litellm.client.LiteLLMLLMClient") as mock_litellm_class:
        mock_instance = Mock()
        mock_litellm_class.return_value = mock_instance

        config = {
            "text_extraction": {
                "provider": "docling_library",
            },
            "entity_extraction": {
                "provider": "litellm",
                "provider_config": {
                    "model_id": "openai/gpt-3.5-turbo",
                    "temperature": 0.0,
                    "max_tokens": 2000,
                    "api_key": "test-api-key",  # pragma: allowlist secret
                    "api_base": "https://api.test.local/v1",
                },
                "expand_extracted_data": True,
                "custom_schema": {"field1": "string", "field2": "number"},
            },
        }

        operator = ExtractOperator(config=config)

        assert operator.expand_extracted_data is True
        assert operator.entity_adapter is not None


@pytest.mark.unit
def test_extract_operator_max_workers_configuration():
    """Test ExtractOperator with custom max_workers setting."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
        },
        "max_workers": 8,
    }

    operator = ExtractOperator(config=config)

    # Verify operator was created (max_workers is passed to adapters)
    assert operator.text_adapter is not None


@pytest.mark.unit
def test_extract_operator_use_processes_flag():
    """Test ExtractOperator with use_processes flag."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
        },
        "use_processes": True,
    }

    operator = ExtractOperator(config=config)

    # Verify operator was created with process-based execution
    assert operator.text_adapter is not None


@pytest.mark.unit
def test_extract_operator_all_text_modes():
    """Test ExtractOperator initialization with all text extraction providers."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    text_modes = ["docling_library", "docling_serve"]

    for mode in text_modes:
        config: dict[str, Any] = {
            "text_extraction": {
                "provider": mode,
            },
        }

        # Add mode-specific required parameters
        if mode == "docling_serve":
            config["text_extraction"]["provider_config"] = {
                "base_url": "http://localhost:5001",
            }

        operator = ExtractOperator(config=config)
        assert operator.text_extraction_mode.value == mode
        assert operator.text_adapter is not None


@pytest.mark.unit
def test_extract_operator_all_entity_modes():
    """Test ExtractOperator initialization with all entity extraction modes."""
    from unittest.mock import Mock, patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Mock the LiteLLM client at the import location
    with patch("docpipe.integrations.litellm.client.LiteLLMLLMClient") as mock_litellm_class:
        mock_instance = Mock()
        mock_litellm_class.return_value = mock_instance

        entity_modes = ["none", "docling", "litellm"]

        for mode in entity_modes:
            config: dict[str, Any] = {
                "text_extraction": {
                    "provider": "docling_library",
                },
            }

            # Add mode-specific required parameters
            if mode != "none":
                config["entity_extraction"] = {
                    "provider": mode,
                }
                if mode == "litellm":
                    config["entity_extraction"]["provider_config"] = {
                        "model_id": "openai/test-model",
                        "api_base": "http://localhost:11434/v1",
                        "api_key": "test-key",  # pragma: allowlist secret
                    }

            operator = ExtractOperator(config=config)
            assert operator.entity_extraction_mode.value == mode

            if mode == "none":
                assert operator.entity_adapter is None
            else:
                assert operator.entity_adapter is not None


@pytest.mark.unit
def test_extract_operator_custom_schema_validation():
    """Test ExtractOperator with custom schema for LiteLLM entity extraction."""
    from unittest.mock import Mock, patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Mock the LiteLLM client
    with patch("docpipe.integrations.litellm.client.LiteLLMLLMClient") as mock_litellm_class:
        mock_instance = Mock()
        mock_litellm_class.return_value = mock_instance

        custom_schema = {
            "invoice_number": "string",
            "date": "string",
            "total_amount": "number",
            "vendor": {"name": "string", "address": "string"},
        }

        config = {
            "text_extraction": {
                "provider": "docling_library",
            },
            "entity_extraction": {
                "provider": "litellm",
                "provider_config": {
                    "model_id": "openai/gpt-3.5-turbo",
                    "temperature": 0.0,
                    "max_tokens": 2000,
                    "api_key": "test-api-key",  # pragma: allowlist secret
                    "api_base": "https://api.test.local/v1",
                },
                "custom_schema": custom_schema,
            },
        }

        operator = ExtractOperator(config=config)

        assert operator.entity_adapter is not None


@pytest.mark.unit
def test_extract_operator_temperature_and_max_tokens():
    """Test ExtractOperator with custom temperature and max_tokens for LiteLLM."""
    from unittest.mock import Mock, patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Mock the LiteLLM client
    with patch("docpipe.integrations.litellm.client.LiteLLMLLMClient") as mock_litellm_class:
        mock_instance = Mock()
        mock_litellm_class.return_value = mock_instance

        config = {
            "text_extraction": {
                "provider": "docling_library",
            },
            "entity_extraction": {
                "provider": "litellm",
                "provider_config": {
                    "model_id": "openai/gpt-3.5-turbo",
                    "temperature": 0.7,
                    "max_tokens": 2048,
                    "api_key": "test-api-key",  # pragma: allowlist secret
                    "api_base": "https://api.test.local/v1",
                },
            },
        }

        operator = ExtractOperator(config=config)

        assert operator.entity_adapter is not None


@pytest.mark.unit
def test_extract_operator_docling_serve_comprehensive():
    """Test ExtractOperator with comprehensive docling_serve parameters."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_serve",
            "provider_config": {
                "base_url": "http://test-server:8080",
                "api_key": "test-key-123",  # pragma: allowlist secret
                "timeout": 600,
                "poll_interval": 5,
                "max_retries": 5,
                "do_ocr": False,
                "ocr_engine": "tesseract",
                "ocr_languages": ["en", "fr", "de"],
                "pdf_backend": "pypdfium2",
                "table_mode": "accurate",
                "image_export_mode": "embedded",
            },
        },
    }

    operator = ExtractOperator(config=config)

    assert operator.text_extraction_mode.value == "docling_serve"
    assert operator.text_adapter is not None


@pytest.mark.unit
def test_extract_operator_docling_library_vlm_all_parameters():
    """Test ExtractOperator with docling_library VLM and all parameters."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "provider_config": {
                "vlm_pipeline": {
                    "preset": "granite_docling",
                    "engine": "transformers",
                    "api_key": "test-key",  # pragma: allowlist secret
                    "api_base_url": "http://localhost:8000",
                },
            },
        },
    }

    operator = ExtractOperator(config=config)

    assert operator.text_extraction_mode.value == "docling_library"
    assert operator.text_adapter is not None


@pytest.mark.unit
def test_extract_operator_metadata_structure():
    """Test ExtractOperator get_metadata returns correct structure."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
        },
    }

    operator = ExtractOperator(config=config)
    metadata = operator.get_metadata()

    # Verify metadata structure
    assert "category" in metadata
    assert "features" in metadata
    assert "attributes" in metadata
    assert "is_operator_available" in metadata

    # Verify key features
    features = metadata["features"]
    assert "content" in features or "doc_content" in features
    assert "doc_id_hash" in features

    # Verify key attributes (now nested)
    attributes = metadata["attributes"]
    assert "text_extraction" in attributes
    assert "entity_extraction" in attributes
    assert "max_workers" in attributes

    # Verify nested structure
    assert "properties" in attributes["text_extraction"]
    assert "properties" in attributes["entity_extraction"]


@pytest.mark.unit
def test_consolidate_metadata_merges_failed_and_skipped_docs_without_behavior_change():
    """Test metadata consolidation preserves merged output semantics."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    operator = ExtractOperator(
        config={
            "text_extraction": {
                "provider": "docling_library",
            },
        }
    )

    text_metadata = {
        Metrics.External.TOTAL_DOCS: 5,
        Metrics.External.FAILED_DOCS: [
            {
                OperatorConstants.Columns.ID: "doc-1",
                OperatorConstants.Misc.REASON: "text failed",
            },
            {
                OperatorConstants.Columns.ID: "doc-2",
                OperatorConstants.Misc.REASON: "text timeout",
            },
        ],
        Metrics.External.SKIPPED_DOCS: [
            {
                OperatorConstants.Columns.ID: "doc-3",
                OperatorConstants.Misc.REASON: "text skipped",
            },
        ],
    }
    entity_metadata = {
        Metrics.External.FAILED_DOCS: [
            {
                OperatorConstants.Columns.ID: "doc-1",
                OperatorConstants.Misc.REASON: "entity failed",
            },
            {
                OperatorConstants.Columns.ID: "doc-4",
                OperatorConstants.Misc.REASON: "entity parse failed",
            },
        ],
        Metrics.External.SKIPPED_DOCS: [
            {
                OperatorConstants.Columns.ID: "doc-3",
                OperatorConstants.Misc.REASON: "entity skipped",
            },
        ],
    }

    consolidated = operator._consolidate_metadata(
        text_metadata=text_metadata,
        entity_metadata=entity_metadata,
    )

    failed_docs = {doc[OperatorConstants.Columns.ID]: doc for doc in consolidated[Metrics.External.FAILED_DOCS]}
    skipped_docs = {doc[OperatorConstants.Columns.ID]: doc for doc in consolidated[Metrics.External.SKIPPED_DOCS]}

    assert consolidated[Metrics.External.TOTAL_DOCS] == 5
    assert consolidated[Metrics.External.FAILED_DOCS_COUNT] == 3
    assert consolidated[Metrics.External.SKIPPED_DOCS_COUNT] == 1
    assert consolidated[Metrics.External.PROCESSED_DOCS] == 1
    assert consolidated[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS.value

    assert failed_docs["doc-1"][OperatorConstants.Misc.REASON] == (
        "Text extraction: text failed | Entity extraction: entity failed"
    )
    assert failed_docs["doc-2"][OperatorConstants.Misc.REASON] == "text timeout"
    assert failed_docs["doc-4"][OperatorConstants.Misc.REASON] == "entity parse failed"
    assert skipped_docs["doc-3"][OperatorConstants.Misc.REASON] == (
        "Text extraction: text skipped | Entity extraction: entity skipped"
    )


@pytest.mark.unit
def test_consolidate_metadata_uses_default_reasons_and_doc_id_column():
    """Test metadata consolidation supports doc_id column and default reasons."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    operator = ExtractOperator(
        config={
            "text_extraction": {
                "provider": "docling_library",
            },
        }
    )

    text_metadata = {
        Metrics.External.TOTAL_DOCS: 3,
        Metrics.External.FAILED_DOCS: [
            {OperatorConstants.Columns.ID: "doc-1"},
        ],
        Metrics.External.SKIPPED_DOCS: [],
    }
    entity_metadata = {
        Metrics.External.FAILED_DOCS: [
            {
                OperatorConstants.Columns.ID: "doc-1",
                OperatorConstants.Misc.REASON: "entity missing schema",
            },
        ],
        Metrics.External.SKIPPED_DOCS: [
            {OperatorConstants.Columns.ID: "doc-2"},
        ],
    }

    consolidated = operator._consolidate_metadata(
        text_metadata=text_metadata,
        entity_metadata=entity_metadata,
    )

    failed_doc = consolidated[Metrics.External.FAILED_DOCS][0]
    skipped_doc = consolidated[Metrics.External.SKIPPED_DOCS][0]

    assert consolidated[Metrics.External.FAILED_DOCS_COUNT] == 1
    assert consolidated[Metrics.External.SKIPPED_DOCS_COUNT] == 1
    assert consolidated[Metrics.External.PROCESSED_DOCS] == 1
    assert failed_doc[OperatorConstants.Columns.ID] == "doc-1"
    assert failed_doc[OperatorConstants.Misc.REASON] == (
        f"Text extraction: {OperatorConstants.Extraction.ERROR} | Entity extraction: entity missing schema"
    )
    assert skipped_doc[OperatorConstants.Columns.ID] == "doc-2"
    assert OperatorConstants.Misc.REASON not in skipped_doc


@pytest.mark.unit
def test_consolidate_metadata_returns_text_metadata_when_entity_metadata_missing():
    """Test metadata consolidation returns text metadata unchanged when entity metadata is absent."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    operator = ExtractOperator(
        config={
            "text_extraction": {
                "provider": "docling_library",
            },
        }
    )

    text_metadata = {
        Metrics.External.TOTAL_DOCS: 2,
        Metrics.External.PROCESSED_DOCS: 2,
        Metrics.External.FAILED_DOCS_COUNT: 0,
        Metrics.External.FAILED_DOCS: [],
        Metrics.External.SKIPPED_DOCS_COUNT: 0,
        Metrics.External.SKIPPED_DOCS: [],
        Metrics.External.NODE_STATUS: ExecutionStatus.COMPLETED,
    }

    consolidated = operator._consolidate_metadata(
        text_metadata=text_metadata,
        entity_metadata=None,
    )

    assert consolidated is text_metadata


@pytest.mark.unit
def test_prepare_document_content_fetch_uses_path_when_id_missing():
    """Test document task preparation falls back to path before synthetic row ID."""
    import pyarrow as pa

    from docpipe.core.operators.operator_utils import OperatorUtils

    table = pa.table(
        {
            OperatorConstants.Columns.PATH: ["/tmp/sample.pdf"],
            OperatorConstants.Columns.NAME: ["sample.pdf"],
            OperatorConstants.Columns.BINARY_CONTENT: [b"binary-data"],
        }
    )

    doc_tasks = OperatorUtils.prepare_document_content_fetch(table=table)

    assert len(doc_tasks) == 1
    assert doc_tasks[0]["doc_id"] == "/tmp/sample.pdf"
    assert doc_tasks[0]["doc_name"] == "sample.pdf"


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.unit
def test_extract_operator_prefers_path_only_input_without_binary_content(
    sample_pdf_files,
):
    """Test ExtractOperator succeeds when only path is provided."""
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    test_file = sample_pdf_files[0]

    table = pa.table(
        {
            "path": [str(test_file)],
            "name": [test_file.name],
        }
    )

    operator = ExtractOperator(
        config={
            "text_extraction": {
                "provider": "docling_library",
                "doc_column": "doc_content",
            },
            "max_workers": 1,  # Reduce worker count to minimize memory overhead
        }
    )
    result_tables, metadata = operator.transform(table=table)
    result_table = result_tables[0]

    assert len(result_tables) == 1
    assert result_table["doc_content"][0].as_py()
    assert metadata["processed_docs"] == 1


@pytest.mark.unit
def test_consolidate_metadata_merges_document_in_both_failed_lists():
    """Test that a document failing in both text and entity extraction has merged reasons."""
    from unittest.mock import patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Mock LiteLLM client to avoid connection requirement
    with patch("docpipe.integrations.litellm.client.LiteLLMLLMClient") as mock_litellm:
        mock_instance = MagicMock()
        mock_litellm.return_value = mock_instance

        operator = ExtractOperator(
            config={
                "text_extraction": {
                    "provider": "docling_library",
                },
                "entity_extraction": {
                    "provider": "litellm",
                    "provider_config": {
                        "model_id": "openai/gpt-3.5-turbo",
                        "temperature": 0.0,
                        "max_tokens": 2000,
                        "api_key": "test-api-key",  # pragma: allowlist secret
                        "api_base": "https://api.test.local/v1",
                    },
                },
            }
        )

        text_metadata = {
            Metrics.External.TOTAL_DOCS: 3,
            Metrics.External.FAILED_DOCS: [
                {
                    OperatorConstants.Columns.ID: "doc-1",
                    OperatorConstants.Misc.REASON: "text extraction timeout",
                },
                {
                    OperatorConstants.Columns.ID: "doc-2",
                    OperatorConstants.Misc.REASON: "text parsing error",
                },
            ],
            Metrics.External.SKIPPED_DOCS: [],
        }
        entity_metadata = {
            Metrics.External.FAILED_DOCS: [
                {
                    OperatorConstants.Columns.ID: "doc-1",
                    OperatorConstants.Misc.REASON: "entity model unavailable",
                },
            ],
            Metrics.External.SKIPPED_DOCS: [],
        }

        consolidated = operator._consolidate_metadata(
            text_metadata=text_metadata,
            entity_metadata=entity_metadata,
        )

        failed_docs = {doc[OperatorConstants.Columns.ID]: doc for doc in consolidated[Metrics.External.FAILED_DOCS]}

        # Verify doc-1 appears once with merged reasons
        assert len(consolidated[Metrics.External.FAILED_DOCS]) == 2
        assert "doc-1" in failed_docs
        assert failed_docs["doc-1"][OperatorConstants.Misc.REASON] == (
            "Text extraction: text extraction timeout | Entity extraction: entity model unavailable"
        )
        # Verify doc-2 appears with only text reason
        assert "doc-2" in failed_docs
        assert failed_docs["doc-2"][OperatorConstants.Misc.REASON] == "text parsing error"


@pytest.mark.unit
def test_consolidate_metadata_merges_document_in_both_skipped_lists():
    """Test that a document skipped in both text and entity extraction has merged reasons."""
    from unittest.mock import patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Mock LiteLLM client to avoid connection requirement
    with patch("docpipe.integrations.litellm.client.LiteLLMLLMClient") as mock_litellm:
        mock_instance = MagicMock()
        mock_litellm.return_value = mock_instance

        operator = ExtractOperator(
            config={
                "text_extraction": {
                    "provider": "docling_library",
                },
                "entity_extraction": {
                    "provider": "litellm",
                    "provider_config": {
                        "model_id": "openai/gpt-3.5-turbo",
                        "temperature": 0.0,
                        "max_tokens": 2000,
                        "api_key": "test-api-key",  # pragma: allowlist secret
                        "api_base": "https://api.test.local/v1",
                    },
                },
            }
        )

        text_metadata = {
            Metrics.External.TOTAL_DOCS: 3,
            Metrics.External.FAILED_DOCS: [],
            Metrics.External.SKIPPED_DOCS: [
                {
                    OperatorConstants.Columns.ID: "doc-1",
                    OperatorConstants.Misc.REASON: "text unsupported format",
                },
                {
                    OperatorConstants.Columns.ID: "doc-2",
                    OperatorConstants.Misc.REASON: "text empty content",
                },
            ],
        }
        entity_metadata = {
            Metrics.External.FAILED_DOCS: [],
            Metrics.External.SKIPPED_DOCS: [
                {
                    OperatorConstants.Columns.ID: "doc-1",
                    OperatorConstants.Misc.REASON: "entity no schema match",
                },
            ],
        }

        consolidated = operator._consolidate_metadata(
            text_metadata=text_metadata,
            entity_metadata=entity_metadata,
        )

        skipped_docs = {doc[OperatorConstants.Columns.ID]: doc for doc in consolidated[Metrics.External.SKIPPED_DOCS]}

        # Verify doc-1 appears once with merged reasons
        assert len(consolidated[Metrics.External.SKIPPED_DOCS]) == 2
        assert "doc-1" in skipped_docs
        assert skipped_docs["doc-1"][OperatorConstants.Misc.REASON] == (
            "Text extraction: text unsupported format | Entity extraction: entity no schema match"
        )
        # Verify doc-2 appears with only text reason
        assert "doc-2" in skipped_docs
        assert skipped_docs["doc-2"][OperatorConstants.Misc.REASON] == "text empty content"


@pytest.mark.unit
def test_streaming_pipeline_stage_progress_in_metadata():
    """extraction_stage_progress must be written at the top level of the returned metadata
    by the streaming path (entity enabled, no content reuse)."""
    from unittest.mock import MagicMock

    operator = _make_operator_with_mocks()

    table = _make_table(n=2)
    metadata = operator.create_base_metadata(total_docs_count=table.num_rows)

    operator.text_adapter.extract_single_document = MagicMock(
        side_effect=lambda *, file_path, binary_content, **kw: _fake_text_result(content=f"text for {file_path}")
    )
    operator.entity_adapter.extract_entities_single = MagicMock(return_value=_fake_entity_result())

    _, result_meta = operator._run_streaming_pipeline(table=table, metadata=metadata)

    # extraction_stage_progress lives directly in the returned metadata dict,
    # not nested under node_metadata.
    assert OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS in result_meta, (
        "extraction_stage_progress must be present at the top level of the returned metadata"
    )

    stage_progress = result_meta[OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS]

    # Both stages must be reported
    assert OperatorConstants.Extraction.STAGE_TEXT_EXTRACTION in stage_progress
    assert OperatorConstants.Extraction.STAGE_ENTITY_EXTRACTION in stage_progress

    text_stage = stage_progress[OperatorConstants.Extraction.STAGE_TEXT_EXTRACTION]
    assert text_stage[OperatorConstants.Extraction.STAGE_STATUS] == OperatorConstants.Extraction.STAGE_STATUS_COMPLETED
    assert text_stage[OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL] == 2
    assert text_stage[OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED] == 2
    assert text_stage[OperatorConstants.Extraction.STAGE_DOCUMENTS_FAILED] == 0
    assert text_stage[OperatorConstants.Extraction.STAGE_PROGRESS_PERCENTAGE] == 100.0

    entity_stage = stage_progress[OperatorConstants.Extraction.STAGE_ENTITY_EXTRACTION]
    assert (
        entity_stage[OperatorConstants.Extraction.STAGE_STATUS] == OperatorConstants.Extraction.STAGE_STATUS_COMPLETED
    )
    assert entity_stage[OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL] == 2
    assert entity_stage[OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED] == 2
    assert entity_stage[OperatorConstants.Extraction.STAGE_DOCUMENTS_FAILED] == 0
    assert entity_stage[OperatorConstants.Extraction.STAGE_PROGRESS_PERCENTAGE] == 100.0


@pytest.mark.unit
def test_extract_content_reuse_with_temp_pages_and_hash():
    """Test that ExtractOperator handles content reuse metadata correctly."""
    import pyarrow as pa

    from docpipe.core.constants import DocpipeConstants
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    # Create table with reused content and temp pages column
    table = pa.table(
        {
            "id": ["doc1", "doc2"],
            "name": ["test1.pdf", "test2.pdf"],
            DocpipeConstants.TEMP_CONTENT_COLUMN: [
                {"text": "Content for doc1"},
                {"text": "Content for doc2"},
            ],
            DocpipeConstants.TEMP_PAGES_PROCESSED_COLUMN: [1, 2],
        }
    )

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "doc_column": "content",
        },
        "entity_extraction": {"provider": "none"},
    }

    operator = ExtractOperator(config=config)
    result_tables, _ = operator.transform(table)
    result_table = result_tables[0]

    # Verify temp column was renamed to final column
    assert OperatorConstants.Columns.PAGES_PROCESSED in result_table.column_names
    assert DocpipeConstants.TEMP_PAGES_PROCESSED_COLUMN not in result_table.column_names

    # Verify page counts are preserved
    pages_column = result_table[OperatorConstants.Columns.PAGES_PROCESSED].to_pylist()
    assert pages_column == [1, 2]

    # Verify doc_hash_id column was added
    assert OperatorConstants.Columns.DOC_ID_HASH_DEFAULT in result_table.column_names
    hash_column = result_table[OperatorConstants.Columns.DOC_ID_HASH_DEFAULT].to_pylist()
    assert all(h is not None for h in hash_column)


# =============================================================================
# Streaming pipeline tests  (_run_streaming_pipeline)
# =============================================================================


def _make_operator_with_mocks(*, custom_schema=None):
    """Helper: build an ExtractOperator with both adapters pointing at mocks.

    Uses patch.object on LiteLLMLLMClient.__init__ to avoid a live network call
    during operator construction. patch.object is preferred over string-path patch()
    because it fails fast if the import path changes during a refactor.
    """
    from unittest.mock import patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator
    from docpipe.integrations.litellm.client import LiteLLMLLMClient

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "doc_column": "doc_content",
        },
        "entity_extraction": {
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/llama3.2",
                "api_base": "http://localhost:11434/v1",
                "api_key": "test",  # pragma: allowlist secret
                "temperature": 0.0,
                "max_tokens": 256,
            },
            "custom_schema": custom_schema or {"title": "string"},
        },
        "max_workers": 2,
    }
    with patch.object(LiteLLMLLMClient, "__init__", return_value=None):
        return ExtractOperator(config=config)


def _make_table(*, n: int = 2):
    """Helper: minimal PyArrow table accepted by the streaming pipeline."""
    import pyarrow as pa

    return pa.table(
        {
            "id": [f"doc_{i}" for i in range(n)],
            "name": [f"doc_{i}.txt" for i in range(n)],
            "path": [f"/tmp/doc_{i}.txt" for i in range(n)],
            "binary_content": [f"content {i}".encode() for i in range(n)],
        }
    )


def _fake_text_result(*, content: str = "hello world") -> dict:
    """Simulated successful text-extraction result.

    The key for the extracted text must match OperatorConstants.Columns.DOC_COLUMN_DEFAULT
    which is "content", not the operator's doc_column name.
    """
    return {
        "success": True,
        "content": content,  # must be DOC_COLUMN_DEFAULT = "content"
        "metadata": {"page_count": 1},
    }


def _fake_text_failure(*, error: str = "network timeout") -> dict:
    """Simulated failed text-extraction result.

    Uses a non-recoverable-keyword-free error message so the minimal test table
    (which lacks id/modified_time columns) does not trigger process_non_recoverable_errors.
    """
    return {
        "success": False,
        "content": None,
        "error": error,
        "metadata": {},
    }


def _fake_entity_result(*, entities: dict | None = None) -> dict:
    """Simulated successful entity-extraction result."""
    return {
        "success": True,
        "entities": entities or {"title": "Test Document"},
        "error": None,
    }


@pytest.mark.unit
def test_streaming_pipeline_happy_path():
    """All documents succeed in both text and entity extraction."""
    import json
    from unittest.mock import MagicMock

    operator = _make_operator_with_mocks()

    table = _make_table(n=3)
    metadata = operator.create_base_metadata(total_docs_count=table.num_rows)

    # Patch both single-document extraction methods
    operator.text_adapter.extract_single_document = MagicMock(
        side_effect=lambda *, file_path, binary_content, **kw: _fake_text_result(content=f"text for {file_path}")
    )
    operator.entity_adapter.extract_entities_single = MagicMock(return_value=_fake_entity_result())

    result_tables, result_meta = operator._run_streaming_pipeline(table=table, metadata=metadata)

    result = result_tables[0]

    # All three rows should survive
    assert result.num_rows == 3
    # Correct columns exist
    assert "doc_content" in result.column_names
    assert "entities" in result.column_names
    assert "doc_id_hash" in result.column_names
    assert "pages_processed" in result.column_names

    # Every document has non-empty text content
    for row_content in result["doc_content"].to_pylist():
        assert row_content is not None
        assert "text for" in row_content

    # Every entity column is valid JSON
    for row_entities in result["entities"].to_pylist():
        parsed = json.loads(row_entities)
        assert isinstance(parsed, dict)

    # Entity method was called once per document
    assert operator.entity_adapter.extract_entities_single.call_count == 3

    # Metadata counts are correct
    from docpipe.core.constants.constants import Metrics

    assert result_meta[Metrics.External.PROCESSED_DOCS] == 3
    assert result_meta[Metrics.External.FAILED_DOCS_COUNT] == 0


@pytest.mark.unit
def test_streaming_pipeline_text_failure_blocks_entity():
    """A document that fails text extraction must not reach entity extraction."""
    from unittest.mock import MagicMock

    from docpipe.core.constants.constants import Metrics

    operator = _make_operator_with_mocks()

    table = _make_table(n=3)
    metadata = operator.create_base_metadata(total_docs_count=table.num_rows)

    call_count = {"n": 0}

    def text_side_effect(*, file_path, binary_content, **kw):
        call_count["n"] += 1
        # Fail the second document (use a plain non-recoverable-free message)
        if "doc_1" in file_path:
            return _fake_text_failure(error="network timeout for doc_1")
        return _fake_text_result(content=f"ok content {file_path}")

    operator.text_adapter.extract_single_document = MagicMock(side_effect=text_side_effect)
    operator.entity_adapter.extract_entities_single = MagicMock(return_value=_fake_entity_result())

    result_tables, result_meta = operator._run_streaming_pipeline(table=table, metadata=metadata)

    # One row should have been removed
    assert result_tables[0].num_rows == 2

    # Entity extraction called only for the 2 successful docs
    assert operator.entity_adapter.extract_entities_single.call_count == 2

    # Failure recorded in metadata
    assert result_meta[Metrics.External.FAILED_DOCS_COUNT] == 1


@pytest.mark.unit
def test_streaming_pipeline_all_text_fail_raises():
    """When every document fails text extraction a ValueError must be raised."""
    from unittest.mock import MagicMock

    operator = _make_operator_with_mocks()

    table = _make_table(n=2)
    metadata = operator.create_base_metadata(total_docs_count=table.num_rows)

    operator.text_adapter.extract_single_document = MagicMock(return_value=_fake_text_failure(error="all broken"))
    operator.entity_adapter.extract_entities_single = MagicMock()

    with pytest.raises(ValueError, match="failed text extraction"):
        operator._run_streaming_pipeline(table=table, metadata=metadata)

    # Entity extraction must never have been called
    operator.entity_adapter.extract_entities_single.assert_not_called()


@pytest.mark.unit
def test_streaming_pipeline_entity_failure_does_not_drop_row():
    """A document that fails entity extraction stays in the table with empty entities."""
    import json
    from unittest.mock import MagicMock

    from docpipe.core.constants.constants import Metrics

    operator = _make_operator_with_mocks()

    table = _make_table(n=2)
    metadata = operator.create_base_metadata(total_docs_count=table.num_rows)

    operator.text_adapter.extract_single_document = MagicMock(
        side_effect=lambda *, file_path, binary_content, **kw: _fake_text_result()
    )

    call_index = {"n": 0}

    def entity_side_effect(*, doc_id, doc_name, content, schema=None):
        idx = call_index["n"]
        call_index["n"] += 1
        if idx == 0:
            # First doc entity extraction fails
            return {"success": False, "entities": {}, "error": "LLM timeout"}
        return _fake_entity_result()

    operator.entity_adapter.extract_entities_single = MagicMock(side_effect=entity_side_effect)

    result_tables, result_meta = operator._run_streaming_pipeline(table=table, metadata=metadata)

    result = result_tables[0]

    # Both rows survive (entity failure does not remove the row)
    assert result.num_rows == 2

    # Both rows have an entities column (failed one gets '{}')
    entities_col = result["entities"].to_pylist()
    assert all(e is not None for e in entities_col)
    parsed = [json.loads(e) for e in entities_col]
    assert any(p == {} for p in parsed)  # at least one empty
    assert any(p != {} for p in parsed)  # at least one success

    # The entity failure is recorded in metadata
    assert result_meta[Metrics.External.FAILED_DOCS_COUNT] >= 1


@pytest.mark.unit
def test_streaming_pipeline_not_invoked_when_entity_disabled():
    """When entity_adapter is None the streaming pipeline must not be called."""
    from unittest.mock import patch

    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "doc_column": "doc_content",
        },
        "entity_extraction": {"provider": "none"},
        "max_workers": 2,
    }

    operator = ExtractOperator(config=config)
    assert operator.entity_adapter is None

    table = _make_table(n=1)

    # Patch text_adapter.transform (the sequential path) instead of the streaming method
    with (
        patch.object(operator, "_run_streaming_pipeline") as mock_streaming,
        patch.object(operator.text_adapter, "transform") as mock_text_transform,
    ):
        mock_text_transform.return_value = (
            [table.append_column("doc_content", pa.array(["hello"]))],
            operator.create_base_metadata(total_docs_count=1),
        )

        operator.transform(table)

    # Streaming pipeline should not have been called
    mock_streaming.assert_not_called()


@pytest.mark.unit
def test_streaming_pipeline_writes_progress_periodically():
    """_write_streaming_progress fires at least once per drain loop.

    time.time() is patched to return a strictly increasing sequence so the
    5-second interval check is always satisfied for every document: values step
    by 10 seconds on each call, so (t_now - t_last) >= 5 is always True.
    """
    from itertools import count
    from unittest.mock import MagicMock, patch

    import docpipe.core.operators.extract.extract_operator as _mod

    operator = _make_operator_with_mocks()

    table = _make_table(n=2)
    metadata = operator.create_base_metadata(total_docs_count=table.num_rows)

    operator.text_adapter.extract_single_document = MagicMock(
        side_effect=lambda *, file_path, binary_content, **kw: _fake_text_result(content=f"text for {file_path}")
    )
    operator.entity_adapter.extract_entities_single = MagicMock(return_value=_fake_entity_result())

    # Each call to time.time() returns the next multiple of 10: 0, 10, 20, ...
    # so (current - last) is always 10 >= 5, and last_progress_update is updated
    # to the current value, then the next call is 10 seconds later — always fires.
    time_counter = count(0, 10)

    # Patch time.time in the extract_operator module so the interval check always fires.
    # Patch _write_streaming_progress to avoid a real DB call.
    with (
        patch.object(_mod.time, "time", side_effect=lambda: next(time_counter)),
        patch.object(operator, "_write_streaming_progress") as mock_write,
    ):
        result_tables, _ = operator._run_streaming_pipeline(table=table, metadata=metadata)

    # Both drain loops (text + entity) each processed 2 documents and the timer
    # fires on every document — expect >= 2 calls total (at minimum one per loop).
    assert mock_write.call_count >= 2

    # Pipeline must still deliver correct results regardless of progress writes.
    assert result_tables[0].num_rows == 2

    # Verify the kwargs passed to the last call contain both stage counter keys
    last_call_kwargs = mock_write.call_args.kwargs
    assert "text_completed" in last_call_kwargs
    assert "entity_completed" in last_call_kwargs
    assert "text_total" in last_call_kwargs
    assert "entity_total" in last_call_kwargs


# =============================================================================
# _build_doc_id_map tests
# =============================================================================


@pytest.mark.unit
def test_build_doc_id_map_returns_id_keyed_dict():
    """_build_doc_id_map indexes documents by their ID for O(1) lookup."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    operator = ExtractOperator(config={"text_extraction": {"provider": "docling_library"}})

    doc_list = [
        {OperatorConstants.Columns.ID: "doc-1", OperatorConstants.Misc.REASON: "err-a"},
        {OperatorConstants.Columns.ID: "doc-2", OperatorConstants.Misc.REASON: "err-b"},
    ]

    result = operator._build_doc_id_map(doc_list=doc_list)

    assert set(result.keys()) == {"doc-1", "doc-2"}
    assert result["doc-1"][OperatorConstants.Misc.REASON] == "err-a"
    assert result["doc-2"][OperatorConstants.Misc.REASON] == "err-b"


@pytest.mark.unit
def test_build_doc_id_map_preserves_first_match_on_duplicate_id():
    """When the same ID appears twice, the first document wins (setdefault behaviour)."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    operator = ExtractOperator(config={"text_extraction": {"provider": "docling_library"}})

    first = {OperatorConstants.Columns.ID: "doc-1", OperatorConstants.Misc.REASON: "first"}
    second = {OperatorConstants.Columns.ID: "doc-1", OperatorConstants.Misc.REASON: "second"}

    result = operator._build_doc_id_map(doc_list=[first, second])

    assert len(result) == 1
    assert result["doc-1"][OperatorConstants.Misc.REASON] == "first"


@pytest.mark.unit
def test_build_doc_id_map_falls_back_to_doc_id_column():
    """_build_doc_id_map accepts the doc_id column as an alternative key."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    operator = ExtractOperator(config={"text_extraction": {"provider": "docling_library"}})

    doc = {OperatorConstants.Columns.DOC_ID_COLUMN: "doc-99", "extra": "data"}

    result = operator._build_doc_id_map(doc_list=[doc])

    assert "doc-99" in result
    assert result["doc-99"]["extra"] == "data"


@pytest.mark.unit
def test_build_doc_id_map_skips_non_dict_entries():
    """Non-dict entries in the list are ignored without raising."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    operator = ExtractOperator(config={"text_extraction": {"provider": "docling_library"}})

    doc_list = [
        "not-a-dict",
        None,
        {OperatorConstants.Columns.ID: "doc-1"},
    ]

    result = operator._build_doc_id_map(doc_list=doc_list)  # type: ignore[arg-type]

    assert list(result.keys()) == ["doc-1"]


@pytest.mark.unit
def test_build_doc_id_map_empty_list_returns_empty_dict():
    """Empty input produces an empty map."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    operator = ExtractOperator(config={"text_extraction": {"provider": "docling_library"}})

    assert operator._build_doc_id_map(doc_list=[]) == {}


# =============================================================================
# _add_page_statistics tests
# =============================================================================


@pytest.mark.unit
def test_add_page_statistics_groups_by_extension():
    """Pages are summed per file extension and stored in page_type_stats."""
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    table = pa.table(
        {
            OperatorConstants.Columns.NAME: ["a.pdf", "b.pdf", "c.txt"],
            OperatorConstants.Columns.PAGES_PROCESSED: [3, 5, 1],
        }
    )

    result = ExtractOperator._add_page_statistics(metadata={}, table=table)

    assert result[OperatorConstants.Metadata.PAGE_TYPE_STATS] == {"pdf": 8, "txt": 1}
    assert result[OperatorConstants.Metadata.TOTAL_PAGES_PROCESSED] == 9


@pytest.mark.unit
def test_add_page_statistics_lowercases_extension():
    """Mixed-case extensions are normalised to lowercase."""
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    table = pa.table(
        {
            OperatorConstants.Columns.NAME: ["report.PDF", "notes.Txt"],
            OperatorConstants.Columns.PAGES_PROCESSED: [2, 4],
        }
    )

    result = ExtractOperator._add_page_statistics(metadata={}, table=table)

    stats = result[OperatorConstants.Metadata.PAGE_TYPE_STATS]
    assert "pdf" in stats
    assert "txt" in stats


@pytest.mark.unit
def test_add_page_statistics_no_extension_uses_unknown():
    """Files with no extension get bucketed under the UNKNOWN sentinel."""
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    table = pa.table(
        {
            OperatorConstants.Columns.NAME: ["README", "Makefile"],
            OperatorConstants.Columns.PAGES_PROCESSED: [1, 1],
        }
    )

    result = ExtractOperator._add_page_statistics(metadata={}, table=table)

    stats = result[OperatorConstants.Metadata.PAGE_TYPE_STATS]
    assert OperatorConstants.Misc.UNKNOWN in stats
    assert stats[OperatorConstants.Misc.UNKNOWN] == 2


@pytest.mark.unit
def test_add_page_statistics_missing_pages_column_returns_metadata_unchanged():
    """Missing pages_processed column → warning logged, metadata returned as-is."""
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    table = pa.table({OperatorConstants.Columns.NAME: ["a.pdf"]})
    original: dict = {"existing_key": "existing_value"}

    result = ExtractOperator._add_page_statistics(metadata=original, table=table)

    assert result is original
    assert OperatorConstants.Metadata.PAGE_TYPE_STATS not in result


@pytest.mark.unit
def test_add_page_statistics_missing_name_column_returns_metadata_unchanged():
    """Missing name column → warning logged, metadata returned as-is."""
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    table = pa.table({OperatorConstants.Columns.PAGES_PROCESSED: [1, 2]})
    original: dict = {"existing_key": "existing_value"}

    result = ExtractOperator._add_page_statistics(metadata=original, table=table)

    assert result is original
    assert OperatorConstants.Metadata.PAGE_TYPE_STATS not in result


@pytest.mark.unit
def test_add_page_statistics_preserves_existing_metadata_keys():
    """Keys already in metadata are preserved alongside the new statistics."""
    import pyarrow as pa

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    table = pa.table(
        {
            OperatorConstants.Columns.NAME: ["doc.docx"],
            OperatorConstants.Columns.PAGES_PROCESSED: [7],
        }
    )
    metadata = {"prior_key": "prior_value"}

    result = ExtractOperator._add_page_statistics(metadata=metadata, table=table)

    assert result["prior_key"] == "prior_value"
    assert result[OperatorConstants.Metadata.PAGE_TYPE_STATS] == {"docx": 7}
    assert result[OperatorConstants.Metadata.TOTAL_PAGES_PROCESSED] == 7


@pytest.mark.unit
def test_get_text_extraction_provider_schemas_structure_and_fields():
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    schemas = ExtractOperator._get_text_extraction_provider_schemas()

    assert isinstance(schemas, dict)
    assert "docling_library" in schemas
    assert "docling_serve" in schemas

    # --- docling_library ---
    lib_props = schemas["docling_library"]["properties"]
    assert set(lib_props.keys()) == {"additional_formats", "asr_pipeline", "ocr", "standard_pipeline", "vlm_pipeline"}

    # --- docling_serve: all DoclingServeConfig fields must be present ---
    serve_props = schemas["docling_serve"]["properties"]
    expected_serve_fields = {
        "base_url",
        "api_key",
        "timeout",
        "poll_interval",
        "max_retries",
        "verify_ssl",
        "do_ocr",
        "pdf_backend",
        "ocr_engine",
        "ocr_languages",
        "ocr",
        "table_mode",
        "image_export_mode",
    }
    assert set(serve_props.keys()) == expected_serve_fields


@pytest.mark.unit
def test_get_entity_extraction_provider_schemas_structure_and_fields():
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    schemas = ExtractOperator._get_entity_extraction_provider_schemas()

    assert isinstance(schemas, dict)
    assert set(schemas.keys()) == {"litellm", "watsonx", "docling"}

    # --- litellm ---
    litellm_props = schemas["litellm"]["properties"]
    assert set(litellm_props.keys()) == {"model_id", "api_base", "api_key", "temperature", "max_tokens"}

    # --- watsonx ---
    watsonx_props = schemas["watsonx"]["properties"]
    assert set(watsonx_props.keys()) == {
        "model_id",
        "api_base",
        "api_key",
        "temperature",
        "max_tokens",
        "url",
        "project_id",
        "container_id",
        "container_kind",
    }

    # --- docling ---
    docling_props = schemas["docling"]["properties"]
    assert set(docling_props.keys()) == {"vlm_pipeline"}


# ---------------------------------------------------------------------------
# _write_streaming_progress
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_streaming_progress_noop_when_no_job_run_id():
    """_write_streaming_progress is a silent no-op when job_run_id is not set."""
    operator = _make_operator_with_mocks()
    operator.text_adapter.job_run_id = None
    operator.text_adapter.node_id = "node1"

    # Should not raise and should not attempt any DB import
    operator._write_streaming_progress(
        text_completed=1,
        text_failed=0,
        text_total=1,
        entity_completed=1,
        entity_failed=0,
        entity_total=1,
    )


@pytest.mark.unit
def test_write_streaming_progress_noop_when_no_node_id():
    """_write_streaming_progress is a silent no-op when node_id is not set."""
    operator = _make_operator_with_mocks()
    operator.text_adapter.job_run_id = "job-123"
    operator.text_adapter.node_id = None

    operator._write_streaming_progress(
        text_completed=1,
        text_failed=0,
        text_total=1,
        entity_completed=0,
        entity_failed=0,
        entity_total=1,
    )


@pytest.mark.unit
def test_write_streaming_progress_swallows_store_exception():
    """Any exception inside _write_streaming_progress must not propagate."""
    operator = _make_operator_with_mocks()
    operator.text_adapter.job_run_id = "job-123"
    operator.text_adapter.node_id = "node-1"
    operator.text_adapter.node_name = "ExtractOperator"
    operator.text_adapter.batch_id = None

    from unittest.mock import MagicMock, patch

    mock_store = MagicMock()
    mock_store.get_node_stats_by_batch_and_node.side_effect = RuntimeError("db down")
    mock_store.store_node_stats.side_effect = RuntimeError("db down")

    mock_factory = MagicMock()
    mock_factory.create_job_stats_store.return_value = mock_store

    with patch(
        "docpipe.core.operators.extract.extract_operator.ExtractOperator._write_streaming_progress",
        wraps=operator._write_streaming_progress,
    ):
        # Call the real method with mocked imports — it must not raise
        try:
            with patch(
                "docpipe.core.operators.extract.extract_operator.get_default_factory",
                return_value=mock_factory,
            ):
                operator._write_streaming_progress(
                    text_completed=1,
                    text_failed=0,
                    text_total=2,
                    entity_completed=0,
                    entity_failed=0,
                    entity_total=2,
                )
        except Exception as exc:
            pytest.fail(f"_write_streaming_progress must not propagate exceptions, got: {exc}")


@pytest.mark.unit
def test_write_streaming_progress_calls_store_when_ids_set():
    """_write_streaming_progress calls store_node_stats when job_run_id and node_id are set."""
    from unittest.mock import MagicMock, patch

    operator = _make_operator_with_mocks()
    operator.text_adapter.job_run_id = "job-abc"
    operator.text_adapter.node_id = "node-abc"
    operator.text_adapter.node_name = "ExtractOperator"
    operator.text_adapter.batch_id = "batch-1"

    from docpipe.core.job_management.adapters.stores.json.json_job_stats_store import JsonJobStatsStore

    mock_store = MagicMock(spec=JsonJobStatsStore)
    mock_store.get_node_stats_by_batch_and_node.return_value = None
    mock_store.try_store_node_stats.return_value = True

    mock_factory = MagicMock()
    mock_factory.create_job_stats_store.return_value = mock_store

    with patch(
        "docpipe.core.operators.extract.extract_operator.get_default_factory",
        return_value=mock_factory,
    ):
        operator._write_streaming_progress(
            text_completed=2,
            text_failed=0,
            text_total=2,
            entity_completed=1,
            entity_failed=1,
            entity_total=2,
        )

    mock_store.try_store_node_stats.assert_called_once()


@pytest.mark.unit
def test_write_streaming_progress_validate_noop_when_no_job_run_id():
    """When validate is called and there is no job_run_id the function returns early."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {"text_extraction": {"provider": "docling_library"}}
    operator = ExtractOperator(config=config)

    errors: list = []
    warnings: list = []
    operator.validate(errors, warnings, ["content"])

    # No error about unknown format when additional_formats is not set
    assert not any("additional_formats" in str(e) for e in errors)


@pytest.mark.unit
def test_validate_warns_on_unknown_additional_formats():
    """validate() appends a warning when additional_formats contains unknown values."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "provider_config": {"additional_formats": ["html", "banana"]},
        }
    }
    operator = ExtractOperator(config=config)
    errors: list = []
    warnings: list = []
    operator.validate(errors, warnings, ["content"])

    assert any("banana" in str(w) for w in warnings)


@pytest.mark.unit
def test_validate_no_warning_for_known_additional_formats():
    """validate() produces no warning when all additional_formats values are valid."""
    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    config = {
        "text_extraction": {
            "provider": "docling_library",
            "provider_config": {"additional_formats": ["html", "json"]},
        }
    }
    operator = ExtractOperator(config=config)
    errors: list = []
    warnings: list = []
    operator.validate(errors, warnings, ["content"])

    assert not any("additional_formats" in str(w) for w in warnings)


# ===========================================================================
# Unit tests — null extraction config handling and max_workers guard
# These tests use mocked adapter factories so no Docling install is required.
# ===========================================================================


def _make_operator(config: dict):
    """Instantiate ExtractOperator with adapter factories fully mocked."""
    from unittest.mock import MagicMock, patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    mock_text_adapter = MagicMock()
    mock_text_adapter.max_workers = 4

    with (
        patch(
            "docpipe.core.operators.extract.extract_operator.TextExtractionAdapterFactory.create_adapter",
            return_value=mock_text_adapter,
        ),
        patch(
            "docpipe.core.operators.extract.extract_operator.EntityExtractionAdapterFactory.create_adapter",
            return_value=MagicMock(),
        ),
    ):
        return ExtractOperator(config=config)


# ── text_extraction null handling ────────────────────────────────────────────


def test_extract_operator_text_extraction_null_raises_clear_error() -> None:
    """text_extraction: null must raise FlowExecutionFailedException, not AttributeError."""
    from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

    with pytest.raises(FlowExecutionFailedException, match="text_extraction"):
        _make_operator({"text_extraction": None, "entity_extraction": None})


def test_extract_operator_text_extraction_missing_raises_clear_error() -> None:
    """Absent text_extraction key must raise FlowExecutionFailedException."""
    from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

    with pytest.raises(FlowExecutionFailedException, match="text_extraction"):
        _make_operator({})


def test_extract_operator_text_extraction_empty_dict_raises_clear_error() -> None:
    """text_extraction: {} must raise FlowExecutionFailedException."""
    from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

    with pytest.raises(FlowExecutionFailedException, match="text_extraction"):
        _make_operator({"text_extraction": {}})


# ── entity_extraction null handling ──────────────────────────────────────────


def test_extract_operator_entity_extraction_null_treated_as_none_mode() -> None:
    """entity_extraction: null must succeed and default to EntityExtractionMode.NONE."""
    from docpipe.core.operators.extract.domain.models import EntityExtractionMode

    op = _make_operator(
        {
            "text_extraction": {"provider": "docling_library"},
            "entity_extraction": None,
        }
    )
    assert op.entity_extraction_mode == EntityExtractionMode.NONE


def test_extract_operator_entity_extraction_absent_treated_as_none_mode() -> None:
    """Absent entity_extraction key must succeed and default to EntityExtractionMode.NONE."""
    from docpipe.core.operators.extract.domain.models import EntityExtractionMode

    op = _make_operator({"text_extraction": {"provider": "docling_library"}})
    assert op.entity_extraction_mode == EntityExtractionMode.NONE


def test_extract_operator_entity_extraction_provider_none_string_treated_as_none_mode() -> None:
    """entity_extraction: {provider: 'none'} must succeed and set EntityExtractionMode.NONE."""
    from docpipe.core.operators.extract.domain.models import EntityExtractionMode

    op = _make_operator(
        {
            "text_extraction": {"provider": "docling_library"},
            "entity_extraction": {"provider": "none"},
        }
    )
    assert op.entity_extraction_mode == EntityExtractionMode.NONE


# ── max_workers guard ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("invalid_value", [None, 0, -1, "auto (CPU-based)", "4", 0.5])
def test_extract_operator_invalid_max_workers_falls_back_to_auto(invalid_value: object) -> None:
    """Invalid max_workers values must fall back to auto-detected CPU-based default."""
    from unittest.mock import patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator
    from docpipe.core.operators.operator_utils import OperatorUtils

    auto_workers = OperatorUtils.get_optimal_workers(is_cpu_intensive=False)
    mock_text_adapter = MagicMock()
    mock_text_adapter.max_workers = auto_workers

    with (
        patch(
            "docpipe.core.operators.extract.extract_operator.TextExtractionAdapterFactory.create_adapter",
            return_value=mock_text_adapter,
        ) as mock_create,
        patch(
            "docpipe.core.operators.extract.extract_operator.EntityExtractionAdapterFactory.create_adapter",
            return_value=MagicMock(),
        ),
    ):
        ExtractOperator(
            config={
                "text_extraction": {"provider": "docling_library"},
                "max_workers": invalid_value,
            }
        )
        assert mock_create.call_args.kwargs["max_workers"] == auto_workers


def test_extract_operator_valid_max_workers_passed_through() -> None:
    """A valid positive integer max_workers must be passed to the adapter factory."""
    from unittest.mock import patch

    from docpipe.core.operators.extract.extract_operator import ExtractOperator

    mock_text_adapter = MagicMock()
    mock_text_adapter.max_workers = 8

    with (
        patch(
            "docpipe.core.operators.extract.extract_operator.TextExtractionAdapterFactory.create_adapter",
            return_value=mock_text_adapter,
        ) as mock_create,
        patch(
            "docpipe.core.operators.extract.extract_operator.EntityExtractionAdapterFactory.create_adapter",
            return_value=MagicMock(),
        ),
    ):
        ExtractOperator(
            config={
                "text_extraction": {"provider": "docling_library"},
                "max_workers": 8,
            }
        )
        assert mock_create.call_args.kwargs["max_workers"] == 8
