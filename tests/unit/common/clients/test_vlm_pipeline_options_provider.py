"""Unit tests for VLM pipeline options providers."""

import pytest
from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
from docling.datamodel.pipeline_options_vlm_model import ResponseFormat

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.integrations.docling.vlm_pipeline_options_provider import (
    GenericApiPipelineOptionsProvider,
    LMStudioPipelineOptionsProvider,
    MlxPipelineOptionsProvider,
    OllamaPipelineOptionsProvider,
    OpenAIPipelineOptionsProvider,
    TransformersPipelineOptionsProvider,
    VlmPipelineOptionsProviderFactory,
    WatsonxPipelineOptionsProvider,
)


class TestVlmPipelineOptionsProviderFactory:
    """Test VlmPipelineOptionsProviderFactory."""

    def test_get_provider_watsonx(self):
        """Test getting watsonx provider."""
        provider = VlmPipelineOptionsProviderFactory.get_provider(
            engine_type=OperatorConstants.Config.VLM_ENGINE_API_WATSONX
        )
        assert isinstance(provider, WatsonxPipelineOptionsProvider)

    def test_get_provider_openai(self):
        """Test getting OpenAI provider."""
        provider = VlmPipelineOptionsProviderFactory.get_provider(
            engine_type=OperatorConstants.Config.VLM_ENGINE_API_OPENAI
        )
        assert isinstance(provider, OpenAIPipelineOptionsProvider)

    def test_get_provider_ollama(self):
        """Test getting Ollama provider."""
        provider = VlmPipelineOptionsProviderFactory.get_provider(
            engine_type=OperatorConstants.Config.VLM_ENGINE_API_OLLAMA
        )
        assert isinstance(provider, OllamaPipelineOptionsProvider)

    def test_get_provider_lmstudio(self):
        """Test getting LMStudio provider."""
        provider = VlmPipelineOptionsProviderFactory.get_provider(
            engine_type=OperatorConstants.Config.VLM_ENGINE_API_LMSTUDIO
        )
        assert isinstance(provider, LMStudioPipelineOptionsProvider)

    def test_get_provider_generic_api(self):
        """Test getting generic API provider."""
        provider = VlmPipelineOptionsProviderFactory.get_provider(engine_type=OperatorConstants.Config.VLM_ENGINE_API)
        assert isinstance(provider, GenericApiPipelineOptionsProvider)

    def test_get_provider_transformers(self):
        """Test getting Transformers provider."""
        provider = VlmPipelineOptionsProviderFactory.get_provider(
            engine_type=OperatorConstants.Config.VLM_ENGINE_TRANSFORMERS
        )
        assert isinstance(provider, TransformersPipelineOptionsProvider)

    def test_get_provider_mlx(self):
        """Test getting MLX provider."""
        provider = VlmPipelineOptionsProviderFactory.get_provider(engine_type=OperatorConstants.Config.VLM_ENGINE_MLX)
        assert isinstance(provider, MlxPipelineOptionsProvider)

    def test_get_provider_unknown(self):
        """Test getting unknown provider (raises ValueError)."""
        with pytest.raises(ValueError, match="Unknown VLM engine type"):
            VlmPipelineOptionsProviderFactory.get_provider(engine_type="unknown_engine")


class TestWatsonxPipelineOptionsProvider:
    """Test WatsonxPipelineOptionsProvider."""

    def test_validate_config_valid(self):
        """Test validation with valid config."""
        provider = WatsonxPipelineOptionsProvider()
        config = {
            "api_key": "test_key",  # pragma: allowlist secret
            "container_id": "12345678-1234-1234-1234-123456789abc",
            "model_id": "test_model",
            "api_base": "https://us-south.ml.cloud.ibm.com/ml/v1/text/chat",
        }
        # Should not raise
        provider.validate_config(config=config)

    def test_validate_config_missing_api_key(self):
        """Test validation with missing api_key."""
        provider = WatsonxPipelineOptionsProvider()
        config = {
            "container_id": "12345678-1234-1234-1234-123456789abc",
            "model_id": "test_model",
            "api_base": "https://us-south.ml.cloud.ibm.com/ml/v1/text/chat",
        }
        with pytest.raises(ValueError, match="'api_key' is required"):
            provider.validate_config(config=config)

    def test_validate_config_missing_container_id(self):
        """Test validation with missing container_id."""
        provider = WatsonxPipelineOptionsProvider()
        config = {
            "api_key": "test_key",  # pragma: allowlist secret
            "model_id": "test_model",
            "api_base": "https://us-south.ml.cloud.ibm.com/ml/v1/text/chat",
        }
        with pytest.raises(ValueError, match="'container_id' is required"):
            provider.validate_config(config=config)

    def test_create_pipeline_options(self, mocker):
        """Test creating pipeline options."""
        provider = WatsonxPipelineOptionsProvider()
        config = {
            "api_key": "test_key",  # pragma: allowlist secret
            "container_id": "12345678-1234-1234-1234-123456789abc",
            "model_id": "test_model",
            "api_base": "https://us-south.ml.cloud.ibm.com/ml/v1/text/chat",
        }

        # Mock RestClient.call_rest_json to return fake IAM token
        mocker.patch(
            "docpipe.integrations.docling.vlm_pipeline_options_provider.RestClient.call_rest_json",
            return_value={"access_token": "fake_token_12345"},
        )

        options = provider.create_pipeline_options(preset="granite_docling", config=config)

        assert isinstance(options, VlmPipelineOptions)
        assert options.enable_remote_services is True


class TestOpenAIPipelineOptionsProvider:
    """Test OpenAIPipelineOptionsProvider."""

    def test_validate_config_valid(self):
        """Test validation with valid config."""
        provider = OpenAIPipelineOptionsProvider()
        config = {
            "api_key": "test_key",  # pragma: allowlist secret
            "model_id": "gpt-4-vision-preview",
            "api_base": "https://api.openai.com/v1",
        }
        # Should not raise
        provider.validate_config(config=config)

    def test_validate_config_missing_api_key(self):
        """Test validation with missing api_key."""
        provider = OpenAIPipelineOptionsProvider()
        config = {
            "model_id": "gpt-4-vision-preview",
            "api_base": "https://api.openai.com/v1",
        }
        with pytest.raises(ValueError, match="'api_key' is required"):
            provider.validate_config(config=config)

    def test_validate_config_missing_model_name(self):
        """Test validation with missing model_name."""
        provider = OpenAIPipelineOptionsProvider()
        config = {
            "api_key": "test_key",  # pragma: allowlist secret
            "api_base": "https://api.openai.com/v1",
        }
        with pytest.raises(ValueError, match="'model_id' is required"):
            provider.validate_config(config=config)

    def test_create_pipeline_options(self):
        """Test creating pipeline options."""
        provider = OpenAIPipelineOptionsProvider()
        config = {
            "api_key": "test_key",  # pragma: allowlist secret
            "model_id": "gpt-4-vision-preview",
            "api_base": "https://api.openai.com/v1",
        }

        options = provider.create_pipeline_options(preset="granite_docling", config=config)

        assert isinstance(options, VlmPipelineOptions)
        assert options.enable_remote_services is True


class TestOllamaPipelineOptionsProvider:
    """Test OllamaPipelineOptionsProvider."""

    def test_validate_config_valid(self):
        """Test validation with valid config."""
        provider = OllamaPipelineOptionsProvider()
        config = {"api_base_url": "http://localhost:11434"}
        # Should not raise
        provider.validate_config(config=config)

    def test_validate_config_empty(self):
        """Test validation with empty config."""
        provider = OllamaPipelineOptionsProvider()
        config: dict[str, str] = {}
        # Should not raise - Ollama has minimal requirements
        provider.validate_config(config=config)

    def test_create_pipeline_options(self):
        """Test creating pipeline options."""
        provider = OllamaPipelineOptionsProvider()
        config = {"api_base_url": "http://localhost:11434"}

        options = provider.create_pipeline_options(preset="granite_docling", config=config)

        assert isinstance(options, VlmPipelineOptions)
        assert options.enable_remote_services is True


class TestLMStudioPipelineOptionsProvider:
    """Test LMStudioPipelineOptionsProvider."""

    def test_validate_config_valid(self):
        """Test validation with valid config."""
        provider = LMStudioPipelineOptionsProvider()
        config = {"api_base_url": "http://localhost:1234/v1/chat/completions"}
        # Should not raise
        provider.validate_config(config=config)

    def test_validate_config_empty(self):
        """Test validation with empty config."""
        provider = LMStudioPipelineOptionsProvider()
        config: dict[str, str] = {}
        # Should not raise - LMStudio has minimal requirements
        provider.validate_config(config=config)

    def test_create_pipeline_options(self):
        """Test creating pipeline options."""
        provider = LMStudioPipelineOptionsProvider()
        config = {"api_base_url": "http://localhost:1234/v1/chat/completions"}

        options = provider.create_pipeline_options(preset="granite_docling", config=config)

        assert isinstance(options, VlmPipelineOptions)
        assert options.enable_remote_services is True


class TestGenericApiPipelineOptionsProvider:
    """Test GenericApiPipelineOptionsProvider."""

    def test_validate_config_valid(self):
        """Test validation with valid config."""
        provider = GenericApiPipelineOptionsProvider()
        config = {"api_base": "https://api.example.com"}
        # Should not raise
        provider.validate_config(config=config)

    def test_create_pipeline_options_with_api_key(self):
        """Test creating pipeline options with api_key."""
        provider = GenericApiPipelineOptionsProvider()
        config = {
            "api_key": "test_key",  # pragma: allowlist secret
            "api_base": "https://api.example.com",
        }

        options = provider.create_pipeline_options(preset="granite_docling", config=config)

        assert isinstance(options, VlmPipelineOptions)
        assert options.enable_remote_services is True

    def test_create_pipeline_options_with_custom_headers(self):
        """Test creating pipeline options with custom headers."""
        provider = GenericApiPipelineOptionsProvider()
        config = {
            "api_base": "https://api.example.com",
            "headers": {"X-Custom-Header": "custom_value"},
        }

        options = provider.create_pipeline_options(preset="granite_docling", config=config)

        assert isinstance(options, VlmPipelineOptions)
        assert options.enable_remote_services is True


class TestTransformersPipelineOptionsProvider:
    """Test TransformersPipelineOptionsProvider."""

    def test_validate_config_empty(self):
        """Test validation with empty config."""
        provider = TransformersPipelineOptionsProvider()
        config: dict[str, str] = {}
        # Should not raise - Transformers has no required config
        provider.validate_config(config=config)

    def test_create_pipeline_options(self):
        """Test creating pipeline options."""
        provider = TransformersPipelineOptionsProvider()
        config: dict[str, str] = {}

        options = provider.create_pipeline_options(preset="granite_docling", config=config)

        assert isinstance(options, VlmPipelineOptions)
        assert options.enable_remote_services is False


class TestMlxPipelineOptionsProvider:
    """Test MlxPipelineOptionsProvider."""

    def test_validate_config_empty(self):
        """Test validation with empty config."""
        provider = MlxPipelineOptionsProvider()
        config: dict[str, str] = {}
        # Should not raise - MLX has no required config
        provider.validate_config(config=config)

    def test_create_pipeline_options(self):
        """Test creating pipeline options."""
        provider = MlxPipelineOptionsProvider()
        config: dict[str, str] = {}

        options = provider.create_pipeline_options(preset="granite_docling", config=config)

        assert isinstance(options, VlmPipelineOptions)
        assert options.enable_remote_services is False
def test_api_provider_does_not_mutate_global_preset():
    provider = OpenAIPipelineOptionsProvider()
    config = {"api_key": "test_key", "model_id": "gpt-4-vision-preview", "api_base": "https://api.openai.com/v1"}  # pragma: allowlist secret
        options = provider.create_pipeline_options(preset="granite_docling", config=config)
            assert options.vlm_options.model_spec.response_format == ResponseFormat.MARKDOWN
            assert VlmConvertOptions.from_preset("granite_docling").model_spec.response_format == ResponseFormat.DOCTAGS
def test_transformers_provider_applies_model_id():
    options = TransformersPipelineOptionsProvider().create_pipeline_options(preset="granite_docling", config={"model_id": "custom/vlm-model"})
    assert options.vlm_options.model_spec.default_repo_id == "custom/vlm-model"
    assert VlmConvertOptions.from_preset("granite_docling").model_spec.default_repo_id != "custom/vlm-model"
    
