"""Tests for DoclingEntityAdapter - custom model configuration validation and usage."""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter import (
    DoclingEntityAdapter,
)


@pytest.fixture
def mock_document_extractor():
    """Create a mock DocumentExtractor."""
    with patch("docling.document_extractor.DocumentExtractor") as mock_class:
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance

        # Mock extraction result
        mock_result = MagicMock()
        mock_page = MagicMock()
        mock_page.page_no = 1
        mock_page.extracted_data = {"test": "data"}
        mock_page.raw_text = "Test content"
        mock_page.errors = []
        mock_result.pages = [mock_page]
        mock_instance.extract.return_value = mock_result

        yield mock_class


@pytest.fixture
def basic_config():
    """Basic configuration without custom model."""
    return {
        "doc_column": "content",
        "output_column": "entities",
    }


@pytest.fixture
def inline_model_config():
    """Configuration with inline model."""
    return {
        "vlm_pipeline": {
            "model_type": "inline",
            "inline_model": {
                "repo_id": "numind/NuExtract-2.0-2B",
                "inference_framework": "transformers",
                "scale": 2.0,
                "temperature": 0.0,
                "max_new_tokens": 4096,
                "load_in_8bit": True,
                "torch_dtype": "bfloat16",
                "response_format": "markdown",
                "prompt": "",
            },
        }
    }


class TestDoclingEntityAdapterValidation:
    """Tests for configuration validation."""

    def test_validate_inline_model_config_valid(self, inline_model_config):
        """Test validation of valid inline model configuration."""
        adapter = DoclingEntityAdapter(config=inline_model_config)
        # Should not raise
        assert adapter.vlm_pipeline is not None
        assert adapter.vlm_pipeline["model_type"] == "inline"

    def test_validate_missing_model_type(self):
        """Test error when model_type is missing."""
        config = {"vlm_pipeline": {"inline_model": {"repo_id": "test/model"}}}
        # Should not raise - model_type is optional
        adapter = DoclingEntityAdapter(config=config)
        assert adapter.vlm_pipeline is not None

    def test_validate_invalid_model_type(self):
        """Test error when model_type is invalid."""
        config = {"vlm_pipeline": {"model_type": "invalid_type", "inline_model": {"repo_id": "test/model"}}}
        with pytest.raises(ValueError, match=r"model_type.*must be 'inline'"):
            DoclingEntityAdapter(config=config)

    def test_validate_inline_missing_repo_id(self):
        """Test error when repo_id is missing for inline model."""
        config = {"vlm_pipeline": {"model_type": "inline", "inline_model": {}}}
        with pytest.raises(ValueError, match=r"repo_id.*is required"):
            DoclingEntityAdapter(config=config)

    def test_validate_inline_invalid_repo_id_type(self):
        """Test error when repo_id is not a string."""
        config = {"vlm_pipeline": {"model_type": "inline", "inline_model": {"repo_id": 123}}}
        with pytest.raises(ValueError, match=r"repo_id.*must be a string"):
            DoclingEntityAdapter(config=config)

    def test_validate_vlm_pipeline_not_dict(self):
        """Test error when vlm_pipeline is not a dictionary."""
        config = {"vlm_pipeline": "not a dict"}
        with pytest.raises(ValueError, match=r"vlm_pipeline.*must be a dictionary"):
            DoclingEntityAdapter(config=config)

    def test_validate_model_type_not_string(self):
        """Test error when model_type is not a string."""
        config = {"vlm_pipeline": {"model_type": 123, "inline_model": {"repo_id": "test/model"}}}
        with pytest.raises(ValueError, match=r"model_type.*must be a string"):
            DoclingEntityAdapter(config=config)

    def test_validate_inline_model_not_dict(self):
        """Test error when inline_model is not a dictionary."""
        config = {"vlm_pipeline": {"model_type": "inline", "inline_model": "not a dict"}}
        with pytest.raises(ValueError, match=r"inline_model.*must be a dictionary"):
            DoclingEntityAdapter(config=config)

    def test_validate_inline_missing_inline_model(self):
        """Test error when inline_model is missing for inline type."""
        config = {"vlm_pipeline": {"model_type": "inline"}}
        with pytest.raises(ValueError, match=r"inline_model.*is required"):
            DoclingEntityAdapter(config=config)


class TestDoclingEntityAdapterInitialization:
    """Tests for adapter initialization."""

    def test_init_with_inline_model_config(self, inline_model_config):
        """Test initialization with inline model configuration."""
        adapter = DoclingEntityAdapter(config=inline_model_config)

        assert adapter.vlm_pipeline is not None
        assert adapter.vlm_pipeline["model_type"] == "inline"
        assert adapter.vlm_pipeline["inline_model"]["repo_id"] == "numind/NuExtract-2.0-2B"

    def test_init_without_custom_config(self, basic_config):
        """Test default initialization without custom model config (backward compatibility)."""
        adapter = DoclingEntityAdapter(config=basic_config)

        assert adapter.vlm_pipeline is None

    def test_init_with_minimal_inline_config(self):
        """Test initialization with minimal inline configuration."""
        config = {"vlm_pipeline": {"model_type": "inline", "inline_model": {"repo_id": "test/model"}}}
        adapter = DoclingEntityAdapter(config=config)

        assert adapter.vlm_pipeline is not None
        assert adapter.vlm_pipeline["inline_model"]["repo_id"] == "test/model"


class TestDoclingEntityAdapterVLMOptions:
    """Tests for VLM options building."""

    def test_build_vlm_options_inline(self, inline_model_config):
        """Verify inline model config fields are correctly applied to InlineVlmOptions."""
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import VlmExtractionPipelineOptions
        from docling.datamodel.pipeline_options_vlm_model import InlineVlmOptions

        adapter = DoclingEntityAdapter(config=inline_model_config)
        options = adapter._build_vlm_extraction_options(vlm_pipeline=adapter.vlm_pipeline)

        assert options is not None
        assert len(options) == 2  # PDF and IMAGE formats

        # Verify the pipeline_options is VlmExtractionPipelineOptions with InlineVlmOptions
        pdf_option = options[InputFormat.PDF]
        assert isinstance(pdf_option.pipeline_options, VlmExtractionPipelineOptions)
        assert isinstance(pdf_option.pipeline_options.vlm_options, InlineVlmOptions)

        # Verify user-provided fields were applied
        vlm_opts = pdf_option.pipeline_options.vlm_options
        assert vlm_opts.repo_id == "numind/NuExtract-2.0-2B"
        assert vlm_opts.scale == 2.0
        assert vlm_opts.temperature == 0.0

    def test_build_vlm_options_with_defaults(self):
        """Test that default values are applied correctly for inline model."""
        from docling.datamodel.base_models import InputFormat

        config = {
            "vlm_pipeline": {
                "model_type": "inline",
                "inline_model": {
                    "repo_id": "test/model"
                    # All other parameters should use defaults
                },
            }
        }
        adapter = DoclingEntityAdapter(config=config)

        options = adapter._build_vlm_extraction_options(vlm_pipeline=adapter.vlm_pipeline)
        assert options is not None

        pdf_option = options[InputFormat.PDF]
        vlm_opts = pdf_option.pipeline_options.vlm_options

        # User-provided field
        assert vlm_opts.repo_id == "test/model"
        # Default fields from NuExtract-2.0-2B preset
        assert vlm_opts.scale == 2.0
        assert vlm_opts.temperature == 0.0
        assert vlm_opts.max_new_tokens == 4096
        assert vlm_opts.load_in_8bit is True
        assert vlm_opts.prompt == ""

    def test_build_vlm_options_without_config(self, basic_config):
        """Test that None is returned when no custom config is provided."""
        adapter = DoclingEntityAdapter(config=basic_config)

        options = adapter._build_vlm_extraction_options(vlm_pipeline=adapter.vlm_pipeline)

        assert options is None

    def test_build_vlm_options_all_supported_fields(self):
        """Verify that all fields in _ALLOWED_VLM_FIELDS are correctly applied to InlineVlmOptions."""
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import VlmExtractionPipelineOptions
        from docling.datamodel.pipeline_options_vlm_model import (
            InferenceFramework,
            InlineVlmOptions,
            ResponseFormat,
            TransformersModelType,
            TransformersPromptStyle,
        )

        all_fields_config = {
            "vlm_pipeline": {
                "model_type": "inline",
                "inline_model": {
                    "repo_id": "ibm-granite/granite-vision-3.2-2b",
                    "inference_framework": "transformers",
                    "temperature": 0.3,
                    "max_new_tokens": 2048,
                    "load_in_8bit": False,
                    "torch_dtype": "float16",
                    "prompt": "custom prompt",
                    "response_format": "markdown",
                    "scale": 1.5,
                    "max_size": 1024,
                    "llm_int8_threshold": 5.0,
                    "quantized": True,
                    "transformers_model_type": "automodel-imagetexttotext",
                    "transformers_prompt_style": "chat",
                    "stop_strings": ["###", "END"],
                    "extra_generation_config": {"top_p": 0.95},
                    "extra_processor_kwargs": {"do_resize": True},
                    "use_kv_cache": False,
                },
            }
        }
        adapter = DoclingEntityAdapter(config=all_fields_config)
        options = adapter._build_vlm_extraction_options(vlm_pipeline=adapter.vlm_pipeline)

        assert options is not None
        pdf_option = options[InputFormat.PDF]
        assert isinstance(pdf_option.pipeline_options, VlmExtractionPipelineOptions)
        vlm_opts = pdf_option.pipeline_options.vlm_options
        assert isinstance(vlm_opts, InlineVlmOptions)

        assert vlm_opts.repo_id == "ibm-granite/granite-vision-3.2-2b"
        assert vlm_opts.inference_framework == InferenceFramework.TRANSFORMERS
        assert vlm_opts.temperature == 0.3
        assert vlm_opts.max_new_tokens == 2048
        assert vlm_opts.load_in_8bit is False
        assert vlm_opts.torch_dtype == "float16"
        assert vlm_opts.prompt == "custom prompt"
        assert vlm_opts.response_format == ResponseFormat.MARKDOWN
        assert vlm_opts.scale == 1.5
        assert vlm_opts.max_size == 1024
        assert vlm_opts.llm_int8_threshold == 5.0
        assert vlm_opts.quantized is True
        assert vlm_opts.transformers_model_type == TransformersModelType.AUTOMODEL_IMAGETEXTTOTEXT
        assert vlm_opts.transformers_prompt_style == TransformersPromptStyle.CHAT
        assert vlm_opts.stop_strings == ["###", "END"]
        assert vlm_opts.extra_generation_config == {"top_p": 0.95}
        assert vlm_opts.extra_processor_kwargs == {"do_resize": True}
        assert vlm_opts.use_kv_cache is False

    def test_build_vlm_options_ignores_unknown_and_skipped_fields(self, caplog):
        """Verify that revision, trust_remote_code, and unrecognised keys are ignored and logged."""
        from docling.datamodel.base_models import InputFormat

        config = {
            "vlm_pipeline": {
                "model_type": "inline",
                "inline_model": {
                    "repo_id": "test/model",
                    "revision": "custom-branch",
                    "trust_remote_code": True,
                    "malicious_field": "should-be-ignored",
                    "accelerator_options": "should-be-ignored",
                },
            }
        }
        with caplog.at_level("WARNING"):
            adapter = DoclingEntityAdapter(config=config)
            options = adapter._build_vlm_extraction_options(vlm_pipeline=adapter.vlm_pipeline)

        assert options is not None
        pdf_option = options[InputFormat.PDF]
        vlm_opts = pdf_option.pipeline_options.vlm_options
        assert vlm_opts.repo_id == "test/model"
        # revision and trust_remote_code should not be overridden from inline_model
        assert vlm_opts.trust_remote_code is False
        assert vlm_opts.revision != "custom-branch"

        # Verify warning was logged for ignored fields
        assert "Ignoring unrecognised inline_model keys" in caplog.text
        assert "revision" in caplog.text
        assert "trust_remote_code" in caplog.text
        assert "accelerator_options" in caplog.text
        assert "malicious_field" in caplog.text


class TestDoclingEntityAdapterExtraction:
    """Tests for entity extraction with custom models."""

    @patch("docling.document_extractor.DocumentExtractor")
    def test_extract_with_inline_model(self, mock_document_extractor, inline_model_config):
        """Test extraction using inline model configuration."""
        mock_instance = MagicMock()
        mock_document_extractor.return_value = mock_instance

        mock_page = MagicMock()
        mock_page.page_no = 1
        mock_page.extracted_data = {"test": "data"}
        mock_page.raw_text = "Test content"
        mock_page.errors = []
        mock_result = MagicMock()
        mock_result.pages = [mock_page]
        mock_instance.extract.return_value = mock_result

        adapter = DoclingEntityAdapter(config=inline_model_config)

        result = adapter.extract_entities_single(
            doc_id="doc1", doc_name="test.pdf", content=b"Test PDF content", schema={"document_type": "invoice"}
        )

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        assert OperatorConstants.Misc.ENTITIES in result
        mock_document_extractor.assert_called_once()

    @patch("docling.document_extractor.DocumentExtractor")
    def test_extract_without_custom_config(self, mock_document_extractor, basic_config):
        """Test extraction without custom model config (default behavior)."""
        mock_instance = MagicMock()
        mock_document_extractor.return_value = mock_instance

        mock_page = MagicMock()
        mock_page.page_no = 1
        mock_page.extracted_data = {"test": "data"}
        mock_page.raw_text = "Test content"
        mock_page.errors = []
        mock_result = MagicMock()
        mock_result.pages = [mock_page]
        mock_instance.extract.return_value = mock_result

        adapter = DoclingEntityAdapter(config=basic_config)

        result = adapter.extract_entities_single(
            doc_id="doc3", doc_name="test.pdf", content=b"Test PDF content", schema=None
        )

        assert result[OperatorConstants.Extraction.SUCCESS] is True
        mock_document_extractor.assert_called_once()

    @patch("docling.document_extractor.DocumentExtractor")
    def test_extract_handles_string_content(self, mock_document_extractor, inline_model_config):
        """Test that string content is converted to bytes."""
        mock_instance = MagicMock()
        mock_document_extractor.return_value = mock_instance

        mock_page = MagicMock()
        mock_page.page_no = 1
        mock_page.extracted_data = {"test": "data"}
        mock_page.raw_text = "Test content"
        mock_page.errors = []
        mock_result = MagicMock()
        mock_result.pages = [mock_page]
        mock_instance.extract.return_value = mock_result

        adapter = DoclingEntityAdapter(config=inline_model_config)

        result = adapter.extract_entities_single(
            doc_id="doc4", doc_name="test.txt", content="String content", schema=None
        )

        assert result[OperatorConstants.Extraction.SUCCESS] is True


class TestDoclingEntityAdapterErrorHandling:
    """Tests for error handling."""

    def test_extract_handles_import_error(self, basic_config):
        """Test handling of ImportError when DocumentExtractor is not available."""
        with patch("docling.document_extractor.DocumentExtractor", side_effect=ImportError("Module not found")):
            adapter = DoclingEntityAdapter(config=basic_config)

            result = adapter.extract_entities_single(
                doc_id="doc6", doc_name="test.pdf", content=b"Test content", schema=None
            )

            assert result[OperatorConstants.Extraction.SUCCESS] is False
            assert "DocumentExtractor not available" in result[OperatorConstants.Extraction.ERROR]

    def test_extract_handles_extraction_error(self, mock_document_extractor, basic_config):
        """Test handling of extraction errors."""
        mock_document_extractor.return_value.extract.side_effect = Exception("Extraction failed")

        adapter = DoclingEntityAdapter(config=basic_config)

        result = adapter.extract_entities_single(
            doc_id="doc7", doc_name="test.pdf", content=b"Test content", schema=None
        )

        assert result[OperatorConstants.Extraction.SUCCESS] is False
        assert "Extraction failed" in result[OperatorConstants.Extraction.ERROR]

    @patch(
        "docling.datamodel.pipeline_options.VlmExtractionPipelineOptions",
        side_effect=ImportError("VLM module not found"),
    )
    def test_build_vlm_options_handles_import_error(self, mock_vlm_options, inline_model_config):
        """Test handling of ImportError when building VLM options."""
        adapter = DoclingEntityAdapter(config=inline_model_config)
        with pytest.raises(ValueError, match="Docling VLM dependencies not available"):
            adapter._build_vlm_extraction_options(vlm_pipeline=adapter.vlm_pipeline)

    @patch(
        "docling.datamodel.pipeline_options.VlmExtractionPipelineOptions", side_effect=TypeError("Invalid parameter")
    )
    def test_build_vlm_options_handles_configuration_error(self, mock_vlm_options, inline_model_config):
        """Test handling of configuration errors when building VLM options."""
        adapter = DoclingEntityAdapter(config=inline_model_config)
        with pytest.raises(ValueError, match="Invalid VLM configuration"):
            adapter._build_vlm_extraction_options(vlm_pipeline=adapter.vlm_pipeline)


class TestDoclingEntityAdapterAdapterInfo:
    """Tests for adapter metadata."""

    def test_adapter_name(self):
        """Test adapter name constant."""
        assert DoclingEntityAdapter.ADAPTER_NAME == OperatorConstants.ExtractionModes.ENTITY_MODE_DOCLING

    def test_adapter_display_name(self):
        """Test adapter display name constant."""
        assert DoclingEntityAdapter.ADAPTER_DISPLAY_NAME == "Docling"
