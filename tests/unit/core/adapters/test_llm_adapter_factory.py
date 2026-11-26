# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for LLMAdapterFactory provider dispatch and argument mapping."""

from unittest.mock import patch

import pytest

from docpipe.core.adapters.huggingface import HuggingFaceAdapter
from docpipe.core.adapters.litellm import LiteLLMAdapter
from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory
from docpipe.core.adapters.watsonx import WatsonXAdapter

_LITELLM_CLIENT = "docpipe.core.adapters.litellm.litellm_adapter.LiteLLMLLMClient"
_WATSONX_CLIENT = "docpipe.core.adapters.watsonx.watsonx_adapter.WatsonXClient"
_HF_CLIENT = "docpipe.core.adapters.huggingface.huggingface_adapter.HuggingFaceLLMClient"

_WATSONX_CONFIG = {
    "api_key": "<test-api-key>",  # pragma: allowlist secret
    "url": "https://us-south.ml.cloud.ibm.com",
    "project_id": "proj",
    "container_kind": "project",
}


class TestCreateInferenceAdapter:
    """Test suite for LLMAdapterFactory.create_inference_adapter."""

    def test_unsupported_provider_raises(self):
        """Unknown inference providers are rejected with a helpful message."""
        with pytest.raises(ValueError, match="Unsupported inference provider: huggingface"):
            LLMAdapterFactory.create_inference_adapter(provider="huggingface", model_id="m")

    def test_watsonx_provider_is_case_insensitive(self):
        """Provider names are normalised and watsonx config keys are mapped."""
        with patch(_WATSONX_CLIENT) as client_cls:
            adapter = LLMAdapterFactory.create_inference_adapter(
                provider="WatsonX",
                model_id="ibm/granite-13b-chat-v2",
                provider_config=_WATSONX_CONFIG,
            )

        assert isinstance(adapter, WatsonXAdapter)
        client_cls.assert_called_once_with(
            model_name="ibm/granite-13b-chat-v2",
            api_key="<test-api-key>",  # pragma: allowlist secret
            container_id="proj",
            api_base="https://us-south.ml.cloud.ibm.com",
            container_kind="project",
            timeout=120,
        )

    def test_litellm_forwards_connection_options(self):
        """stream and timeout are forwarded to the LiteLLM client; other keys are not."""
        with patch(_LITELLM_CLIENT) as client_cls:
            adapter = LLMAdapterFactory.create_inference_adapter(
                provider="litellm",
                model_id="openai/llama2",
                provider_config={
                    "api_key": "ollama",  # pragma: allowlist secret
                    "api_base": "http://localhost:11434/v1",
                    "stream": True,
                    "timeout": 30,
                    "unrelated": "ignored",
                },
            )

        assert isinstance(adapter, LiteLLMAdapter)
        kwargs = client_cls.call_args.kwargs
        assert kwargs["model_name"] == "openai/llama2"
        assert kwargs["api_base"] == "http://localhost:11434/v1"
        assert kwargs["stream"] is True
        assert kwargs["timeout"] == 30
        assert "unrelated" not in kwargs

    def test_litellm_without_config(self):
        """A missing provider_config is treated as empty."""
        with patch(_LITELLM_CLIENT) as client_cls:
            LLMAdapterFactory.create_inference_adapter(provider="litellm", model_id="gpt-4")

        kwargs = client_cls.call_args.kwargs
        assert kwargs["api_key"] is None
        assert kwargs["api_base"] is None
        assert "stream" not in kwargs
        assert "timeout" not in kwargs


class TestCreateEmbeddingAdapter:
    """Test suite for LLMAdapterFactory.create_embedding_adapter provider dispatch."""

    def test_unsupported_provider_raises(self):
        """Unknown embedding providers are rejected."""
        with pytest.raises(ValueError, match="Unsupported embedding provider: cohere"):
            LLMAdapterFactory.create_embedding_adapter(provider="cohere", model_id="m")

    def test_huggingface_api_key_fallback(self):
        """api_key is used as the HuggingFace api_token when api_token is absent."""
        with patch(_HF_CLIENT) as client_cls:
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider="huggingface",
                model_id="sentence-transformers/all-MiniLM-L6-v2",
                provider_config={"use_local": False, "api_key": "hf-key"},  # pragma: allowlist secret
            )
            adapter.validate_embedding()

        assert isinstance(adapter, HuggingFaceAdapter)
        assert client_cls.call_args.kwargs["use_local"] is False
        assert client_cls.call_args.kwargs["api_token"] == "hf-key"  # pragma: allowlist secret

    def test_huggingface_embedding_adapter_gets_no_hap_defaults(self):
        """The embedding branch keeps the caller's model and sets no detection defaults."""
        adapter = LLMAdapterFactory.create_embedding_adapter(
            provider="huggingface", model_id="sentence-transformers/all-MiniLM-L6-v2", provider_config={}
        )

        assert isinstance(adapter, HuggingFaceAdapter)
        assert adapter.model_name == "sentence-transformers/all-MiniLM-L6-v2"
        assert adapter.toxic_labels == ()
        assert adapter.revision is None


class TestCreateTextDetectionAdapter:
    """Test suite for LLMAdapterFactory.create_text_detection_adapter."""

    def test_unsupported_provider_raises(self):
        """Providers without text detection are rejected."""
        with pytest.raises(ValueError, match="Unsupported text detection provider: litellm"):
            LLMAdapterFactory.create_text_detection_adapter(
                provider="litellm", model_id="m", provider_config={"api_key": "k"}
            )

    def test_empty_model_id_raises(self):
        """An empty model_id is rejected."""
        with pytest.raises(ValueError, match="model_id cannot be empty"):
            LLMAdapterFactory.create_text_detection_adapter(
                provider="watsonx", model_id="", provider_config=_WATSONX_CONFIG
            )

    def test_empty_provider_config_raises(self):
        """An empty provider_config is rejected."""
        with pytest.raises(ValueError, match="provider_config cannot be empty"):
            LLMAdapterFactory.create_text_detection_adapter(provider="watsonx", model_id="m", provider_config={})

    def test_watsonx_adapter_created(self):
        """Watsonx detection adapters accept container_id/api_base aliases."""
        config = {
            "api_key": "<test-api-key>",  # pragma: allowlist secret
            "api_base": "https://eu-de.ml.cloud.ibm.com",
            "container_id": "space-1",
            "container_kind": "space",
            "timeout": 45,
        }
        with patch(_WATSONX_CLIENT):
            adapter = LLMAdapterFactory.create_text_detection_adapter(
                provider="WATSONX", model_id="ibm/granite-guardian", provider_config=config
            )

        assert isinstance(adapter, WatsonXAdapter)
        assert adapter.model_name == "ibm/granite-guardian"
        assert adapter.api_base == "https://eu-de.ml.cloud.ibm.com"
        assert adapter.container_id == "space-1"
        assert adapter.container_kind == "space"
        assert adapter.timeout == 45

    def test_huggingface_adapter_created_from_explicit_options(self):
        """Hugging Face detection options are mapped onto the adapter without loading a model."""
        adapter = LLMAdapterFactory.create_text_detection_adapter(
            provider="HuggingFace",
            model_id="unitary/unbiased-toxic-roberta",
            provider_config={
                "toxic_labels": ["toxicity", "insult"],
                "revision": "abc123",
                "activation": "sigmoid",
                "max_length": 256,
                "batch_size": 8,
                "device": "cpu",
                "local_files_only": True,
            },
        )

        assert isinstance(adapter, HuggingFaceAdapter)
        assert adapter.model_name == "unitary/unbiased-toxic-roberta"
        assert adapter.toxic_labels == ("toxicity", "insult")
        assert adapter.revision == "abc123"
        assert adapter.activation == "sigmoid"
        assert adapter.max_length == 256
        assert adapter.batch_size == 8
        assert adapter.device == "cpu"
        assert adapter.local_files_only is True
        assert adapter.detection_client is None

    def test_huggingface_optional_options_fall_back_without_hap_model_defaults(self):
        """Omitted options use generic fallbacks; the model, revision and labels are never defaulted."""
        adapter = LLMAdapterFactory.create_text_detection_adapter(
            provider="huggingface",
            model_id="org/classifier",
            provider_config={"toxic_labels": ["toxic"], "batch_size": 0},
        )

        assert isinstance(adapter, HuggingFaceAdapter)
        assert adapter.model_name == "org/classifier"
        assert adapter.revision is None
        assert adapter.activation == "auto"
        assert adapter.max_length == 512
        assert adapter.batch_size == 32
        assert adapter.device is None
        assert adapter.local_files_only is False

    def test_huggingface_empty_model_id_raises(self):
        """The factory does not pick a default Hugging Face model."""
        with pytest.raises(ValueError, match="model_id cannot be empty"):
            LLMAdapterFactory.create_text_detection_adapter(
                provider="huggingface", model_id="", provider_config={"toxic_labels": ["LABEL_1"]}
            )

    @pytest.mark.parametrize("provider_config", [{}, {"toxic_labels": []}])
    def test_huggingface_missing_toxic_labels_raises_with_id2label_hint(self, provider_config):
        """toxic_labels are required and the error points to the model's id2label."""
        with pytest.raises(ValueError, match="'toxic_labels' is required for model 'org/classifier'") as error:
            LLMAdapterFactory.create_text_detection_adapter(
                provider="huggingface", model_id="org/classifier", provider_config=provider_config
            )

        assert "config.json id2label" in str(error.value)


class TestGetSupportedProviders:
    """Test suite for LLMAdapterFactory.get_supported_providers."""

    @pytest.mark.parametrize(
        ("capability", "expected"),
        [
            ("inference", {"watsonx", "litellm"}),
            ("Embedding", {"watsonx", "litellm", "huggingface"}),
            ("embeddings", {"watsonx", "litellm", "huggingface"}),
            ("text_detection", {"watsonx", "huggingface"}),
            ("detection", {"watsonx", "huggingface"}),
        ],
    )
    def test_supported_providers(self, capability, expected):
        """Each capability alias maps to its provider set."""
        assert LLMAdapterFactory.get_supported_providers(capability=capability) == expected

    def test_default_capability_is_inference(self):
        """Without an argument the inference providers are returned."""
        assert LLMAdapterFactory.get_supported_providers() == {"watsonx", "litellm"}

    def test_returns_copy(self):
        """Mutating the returned set does not affect the factory."""
        providers = LLMAdapterFactory.get_supported_providers(capability="detection")
        providers.add("other")

        assert LLMAdapterFactory.TEXT_DETECTION_PROVIDERS == {"watsonx", "huggingface"}

    def test_unknown_capability_raises(self):
        """Unknown capabilities are rejected."""
        with pytest.raises(ValueError, match="Unknown capability: vision"):
            LLMAdapterFactory.get_supported_providers(capability="vision")
