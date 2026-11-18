# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for VLM pipeline options providers: URL handling, guards and the IAM exchange.

Complements ``tests/unit/common/clients/test_vlm_pipeline_options_provider.py``. No model
is loaded and no network is used: presets only build option objects, and the IBM IAM
token exchange goes through a fake ``RestClient``.
"""

import logging
from typing import Any, ClassVar

import pytest
from docling.datamodel.pipeline_options import VlmPipelineOptions
from docling.datamodel.vlm_engine_options import VlmEngineType

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.integrations.docling import vlm_pipeline_options_provider as vpp
from docpipe.integrations.docling.vlm_pipeline_options_provider import (
    GenericApiPipelineOptionsProvider,
    OllamaPipelineOptionsProvider,
    OpenAIPipelineOptionsProvider,
    TransformersPipelineOptionsProvider,
    VlmPipelineOptionsProvider,
    VlmPipelineOptionsProviderFactory,
    WatsonxPipelineOptionsProvider,
)

PRESET = "granite_docling"
WATSONX_CONFIG = {
    "api_key": "fake-ibm-cloud-key",  # pragma: allowlist secret
    "container_id": "project-123",
    "model_id": "ibm/granite-vision",
}


class _FakeRestClient:
    """Records how the IAM exchange calls the REST client and replays a canned answer."""

    instances: ClassVar[list["_FakeRestClient"]] = []
    response: ClassVar[Any] = None

    def __init__(self, *, config: Any) -> None:
        self.config = config
        self.calls: list[dict[str, Any]] = []
        _FakeRestClient.instances.append(self)

    def call_rest_json(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(_FakeRestClient.response, Exception):
            raise _FakeRestClient.response
        return _FakeRestClient.response


@pytest.fixture
def fake_rest_client(monkeypatch):
    """Replace the module's RestClient with a recording fake."""
    _FakeRestClient.instances = []
    _FakeRestClient.response = {"access_token": "iam-token"}
    monkeypatch.setattr(vpp, "RestClient", _FakeRestClient)
    return _FakeRestClient


def _lenient(provider_cls: type[VlmPipelineOptionsProvider]) -> VlmPipelineOptionsProvider:
    """Instance of ``provider_cls`` whose ``validate_config`` accepts anything.

    The providers re-check their required keys inside ``create_pipeline_options``; a
    subclass that relaxes ``validate_config`` must still hit those guards.
    """

    class _Lenient(provider_cls):  # type: ignore[valid-type,misc]
        def validate_config(self, *, config: dict[str, Any]) -> None:
            return None

    return _Lenient()


class TestNormalizeOpenAiCompatibleUrl:
    """URL normalisation shared by the OpenAI-compatible providers."""

    @pytest.mark.parametrize(
        ("api_base", "expected"),
        [
            ("http://host:1234", "http://host:1234/v1/chat/completions"),
            ("http://host:1234/", "http://host:1234/v1/chat/completions"),
            ("http://host:1234/v1/chat/completions", "http://host:1234/v1/chat/completions"),
            ("http://host:1234/v1/chat/completions/", "http://host:1234/v1/chat/completions"),
            (None, "http://default/v1/chat/completions"),
            ("", "http://default/v1/chat/completions"),
        ],
    )
    def test_normalization(self, api_base, expected):
        """The completions path is appended once; missing bases fall back to the default."""
        result = VlmPipelineOptionsProvider._normalize_openai_compatible_url(
            api_base=api_base, default_url="http://default/v1/chat/completions"
        )
        assert result == expected


class TestWatsonxProvider:
    """watsonx.ai configuration checks and IAM token exchange."""

    def test_validate_config_missing_model_id(self):
        """A missing model id is rejected."""
        config = {k: v for k, v in WATSONX_CONFIG.items() if k != "model_id"}
        with pytest.raises(ValueError, match="'model_id' is required"):
            WatsonxPipelineOptionsProvider().validate_config(config=config)

    def test_validate_config_rejects_plain_http_api_base(self):
        """A non-HTTPS api_base is rejected so the bearer token never travels in clear text."""
        config = {**WATSONX_CONFIG, "api_base": "http://us-south.ml.cloud.ibm.com/ml/v1/text/chat"}
        with pytest.raises(ValueError, match="must use HTTPS"):
            WatsonxPipelineOptionsProvider().validate_config(config=config)

    def test_create_pipeline_options_builds_watsonx_request(self, fake_rest_client):
        """The IAM token, container, model and defaults end up in the engine options."""
        options = WatsonxPipelineOptionsProvider().create_pipeline_options(
            preset=PRESET, config={**WATSONX_CONFIG, "container_kind": "space", "max_new_tokens": 512}
        )

        engine = options.vlm_options.engine_options
        assert isinstance(options, VlmPipelineOptions)
        assert options.enable_remote_services is True
        assert engine.engine_type == VlmEngineType.API
        assert engine.headers == {"Authorization": "Bearer iam-token"}
        assert engine.params == {
            "space_id": "project-123",
            "model_id": "ibm/granite-vision",
            "parameters": {"max_new_tokens": 512, "temperature": 0.0},
        }
        assert str(engine.url).startswith("https://us-south.ml.cloud.ibm.com/ml/v1/text/chat")
        assert engine.timeout == 90

        (client,) = fake_rest_client.instances
        (call,) = client.calls
        assert call["url"] == vpp.IBM_CLOUD_IAM_TOKEN_URL
        assert call["form_data"]["apikey"] == WATSONX_CONFIG["api_key"]
        assert client.config.timeout == vpp.IAM_TOKEN_REQUEST_TIMEOUT

    def test_iam_response_without_token_is_an_authentication_error(self, fake_rest_client):
        """A token response without ``access_token`` fails with a clear error."""
        fake_rest_client.response = {"errorMessage": "nope"}
        with pytest.raises(ValueError, match="Failed to authenticate with watsonx: Invalid IAM token response"):
            WatsonxPipelineOptionsProvider._get_iam_access_token(api_key="k")

    def test_iam_transport_error_is_wrapped_without_leaking_the_key(self, fake_rest_client, caplog):
        """Errors from the token endpoint become ValueError; the log does not contain the key."""
        fake_rest_client.response = ConnectionError("iam unreachable")
        with caplog.at_level(logging.ERROR), pytest.raises(ValueError, match="iam unreachable") as excinfo:
            WatsonxPipelineOptionsProvider._get_iam_access_token(api_key="super-secret-key")  # pragma: allowlist secret
        assert isinstance(excinfo.value.__cause__, ConnectionError)
        assert "IAM token exchange failed" in caplog.text
        assert "super-secret-key" not in caplog.text

    @pytest.mark.parametrize(
        ("missing", "message"),
        [
            ("api_key", "'api_key' is required"),
            ("container_id", "'container_id' is required"),
            ("model_id", "'model_id' is required"),
        ],
    )
    def test_create_guards_required_keys_even_with_lenient_validation(self, fake_rest_client, missing, message):
        """``create_pipeline_options`` re-checks required keys after ``validate_config``."""
        config = {k: v for k, v in WATSONX_CONFIG.items() if k != missing}
        with pytest.raises(ValueError, match=message):
            _lenient(WatsonxPipelineOptionsProvider).create_pipeline_options(preset=PRESET, config=config)


class TestOpenAIProvider:
    """OpenAI provider guards and request settings."""

    @pytest.mark.parametrize(
        ("config", "message"),
        [
            ({"model_id": "gpt"}, "'api_key' is required"),
            ({"api_key": "k"}, "'model_id' is required"),
        ],  # pragma: allowlist secret
    )
    def test_create_guards_required_keys_even_with_lenient_validation(self, config, message):
        """``create_pipeline_options`` re-checks required keys after ``validate_config``."""
        with pytest.raises(ValueError, match=message):
            _lenient(OpenAIPipelineOptionsProvider).create_pipeline_options(preset=PRESET, config=config)

    def test_create_uses_key_model_base_and_timeout(self):
        """The API key becomes a bearer header; base URL and timeout are honoured."""
        options = OpenAIPipelineOptionsProvider().create_pipeline_options(
            preset=PRESET,
            config={
                "api_key": "sk-test",  # pragma: allowlist secret
                "model_id": "gpt-4o",
                "api_base": "https://proxy.example/",
                "request_timeout": 15,
            },
        )
        engine = options.vlm_options.engine_options
        assert engine.engine_type == VlmEngineType.API_OPENAI
        assert engine.headers == {"Authorization": "Bearer sk-test"}
        assert engine.params == {OperatorConstants.Config.MODEL_NAME: "gpt-4o"}
        assert str(engine.url) == "https://proxy.example/v1/chat/completions"
        assert engine.timeout == 15


class TestOllamaProvider:
    """Ollama model selection."""

    def test_model_id_is_sent_as_model_param(self):
        """A configured model id is passed as the OpenAI-compatible ``model`` parameter."""
        options = OllamaPipelineOptionsProvider().create_pipeline_options(
            preset=PRESET, config={"model_id": "llava:13b", "api_base": "http://ollama:11434"}
        )
        engine = options.vlm_options.engine_options
        assert engine.params == {"model": "llava:13b"}
        assert str(engine.url) == "http://ollama:11434/v1/chat/completions"

    def test_without_model_id_no_model_param_is_set(self):
        """Without a model id the preset's own model choice is left alone."""
        options = OllamaPipelineOptionsProvider().create_pipeline_options(preset=PRESET, config={})
        assert options.vlm_options.engine_options.params == {}


class TestGenericApiProvider:
    """Generic API endpoint configuration."""

    def test_validate_config_requires_api_base(self):
        """``validate_config`` rejects a config without ``api_base``."""
        with pytest.raises(ValueError, match="api_base is required for generic API"):
            GenericApiPipelineOptionsProvider().validate_config(config={})

    def test_create_guards_api_base_even_with_lenient_validation(self):
        """``create_pipeline_options`` re-checks ``api_base`` after ``validate_config``."""
        with pytest.raises(ValueError, match="api_base is required for generic API"):
            _lenient(GenericApiPipelineOptionsProvider).create_pipeline_options(preset=PRESET, config={})

    def test_custom_params_are_copied_not_shared(self):
        """Custom params reach the engine options without aliasing the caller's dict."""
        params = {"temperature": 0.1}
        options = GenericApiPipelineOptionsProvider().create_pipeline_options(
            preset=PRESET, config={"api_base": "https://vlm.example/v1/chat", "parameters": params}
        )
        engine = options.vlm_options.engine_options
        assert engine.params == {"temperature": 0.1}
        assert engine.params is not params
        assert engine.headers == {}


class TestTransformersProvider:
    """Local Transformers inference."""

    def test_model_id_is_logged(self, caplog):
        """A configured model id is reported in the log; local inference stays local."""
        with caplog.at_level(logging.INFO):
            options = TransformersPipelineOptionsProvider().create_pipeline_options(
                preset=PRESET, config={"model_id": "my-org/my-vlm"}
            )
        assert isinstance(options, VlmPipelineOptions)
        assert options.enable_remote_services is False
        assert "my-org/my-vlm" in caplog.text


class TestProviderFactory:
    """Factory defaults and registration."""

    @pytest.mark.parametrize("engine_type", [None, ""])
    def test_missing_engine_type_defaults_to_transformers(self, engine_type):
        """No engine type selects local Transformers inference."""
        provider = VlmPipelineOptionsProviderFactory.get_provider(engine_type=engine_type)
        assert isinstance(provider, TransformersPipelineOptionsProvider)

    def test_registered_provider_is_returned(self, monkeypatch):
        """A custom provider registered for an engine type is instantiated by the factory."""
        monkeypatch.setattr(
            VlmPipelineOptionsProviderFactory, "_providers", dict(VlmPipelineOptionsProviderFactory._providers)
        )

        class _Custom(OllamaPipelineOptionsProvider):
            pass

        VlmPipelineOptionsProviderFactory.register_provider(engine_type="custom", provider_class=_Custom)

        assert isinstance(VlmPipelineOptionsProviderFactory.get_provider(engine_type="custom"), _Custom)
        assert isinstance(
            VlmPipelineOptionsProviderFactory.get_provider(engine_type=OperatorConstants.Config.VLM_ENGINE_API_OLLAMA),
            OllamaPipelineOptionsProvider,
        )
