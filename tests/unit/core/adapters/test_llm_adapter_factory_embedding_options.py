"""Tests that LLMAdapterFactory threads batch_size / max_concurrent_requests into embedding adapters."""

from unittest.mock import patch

import pytest

from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory

_LITELLM_CLIENT = "docpipe.core.adapters.litellm.litellm_adapter.LiteLLMLLMClient"
_WATSONX_CLIENT = "docpipe.core.adapters.watsonx.watsonx_adapter.WatsonXClient"
_WATSONX_REST_CLIENT = "docpipe.core.adapters.watsonx.watsonx_adapter.WatsonxRestEmbeddingClient"
_HF_CLIENT = "docpipe.core.adapters.huggingface.huggingface_adapter.HuggingFaceLLMClient"

_WATSONX_CONFIG = {
    "api_key": "<test-api-key>",  # pragma: allowlist secret
    "url": "https://us-south.ml.cloud.ibm.com",
    "project_id": "proj",
    "container_kind": "project",
}


class TestLiteLLMEmbeddingOptions:
    def test_options_are_passed_to_adapter_and_client(self):
        with patch(_LITELLM_CLIENT) as client_cls:
            client_cls.return_value.batch_size = 64
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider="litellm",
                model_id="openai/text-embedding-3-small",
                provider_config={"api_key": "k", "batch_size": 64, "max_concurrent_requests": 6},
            )

        assert client_cls.call_args.kwargs["batch_size"] == 64
        assert "max_concurrent_requests" not in client_cls.call_args.kwargs
        assert adapter.get_embedding_batch_size() == 64
        assert adapter.get_max_concurrent_requests() == 6

    def test_defaults(self):
        with patch(_LITELLM_CLIENT) as client_cls:
            client_cls.return_value.batch_size = 32
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider="litellm",
                model_id="openai/text-embedding-3-small",
                provider_config={"api_key": "k"},
            )

        assert client_cls.call_args.kwargs["batch_size"] == 32
        assert adapter.get_max_concurrent_requests() == 4

    @pytest.mark.parametrize("bad_value", [0, -3, "16", True, 1.5])
    def test_invalid_values_fall_back_to_defaults(self, bad_value):
        with patch(_LITELLM_CLIENT) as client_cls:
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider="litellm",
                model_id="openai/text-embedding-3-small",
                provider_config={"api_key": "k", "batch_size": bad_value, "max_concurrent_requests": bad_value},
            )

        assert client_cls.call_args.kwargs["batch_size"] == 32
        assert adapter.get_max_concurrent_requests() == 4


class TestWatsonxEmbeddingOptions:
    def test_options_are_passed_to_embedding_client(self):
        with patch(_WATSONX_CLIENT), patch(_WATSONX_REST_CLIENT) as rest_cls:
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider="watsonx",
                model_id="ibm/slate-125m-english-rtrvr",
                provider_config={**_WATSONX_CONFIG, "batch_size": 100, "max_concurrent_requests": 2},
            )
            _ = adapter.embedding_client

        assert rest_cls.call_args.kwargs["batch_size"] == 100
        assert adapter.get_embedding_batch_size() == 100
        assert adapter.get_max_concurrent_requests() == 2

    def test_defaults(self):
        with patch(_WATSONX_CLIENT), patch(_WATSONX_REST_CLIENT) as rest_cls:
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider="watsonx",
                model_id="ibm/slate-125m-english-rtrvr",
                provider_config=dict(_WATSONX_CONFIG),
            )
            _ = adapter.embedding_client

        assert rest_cls.call_args.kwargs["batch_size"] == 800
        assert adapter.get_embedding_batch_size() == 800
        assert adapter.get_max_concurrent_requests() == 1


class TestHuggingFaceEmbeddingOptions:
    def test_batch_size_passed_and_concurrency_stays_serial(self):
        with patch(_HF_CLIENT) as client_cls:
            client_cls.return_value.batch_size = 16
            adapter = LLMAdapterFactory.create_embedding_adapter(
                provider="huggingface",
                model_id="sentence-transformers/all-MiniLM-L6-v2",
                provider_config={"batch_size": 16, "max_concurrent_requests": 8},
            )

        assert client_cls.call_args.kwargs["batch_size"] == 16
        assert adapter.get_embedding_batch_size() == 16
        assert adapter.get_max_concurrent_requests() == 1
