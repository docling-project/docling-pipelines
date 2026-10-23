"""Tests for WatsonX adapter embeddings, configuration validation and detection guards."""

from unittest.mock import Mock, patch

import pytest

from docpipe.core.adapters import WatsonXAdapter
from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort
from docpipe.exceptions.docpipe_exceptions import DocpipeException

_WATSONX_CLIENT = "docpipe.core.adapters.watsonx.watsonx_adapter.WatsonXClient"
_WATSONX_REST_CLIENT = "docpipe.core.adapters.watsonx.watsonx_adapter.WatsonxRestEmbeddingClient"
_IAM_TOKEN = "docpipe.core.adapters.watsonx.watsonx_adapter.WatsonxPipelineOptionsProvider._get_iam_access_token"

_FULL_CONFIG = {
    "api_key": "watsonx-test-credential",  # pragma: allowlist secret
    "api_base": "https://us-south.ml.cloud.ibm.com",
    "container_id": "test-project-id",
    "container_kind": "project",
}


class TestWatsonXConstruction:
    """Test suite for WatsonX adapter construction details."""

    def test_project_id_is_used_as_container_id_alias(self):
        """project_id is accepted as a backwards compatible alias for container_id."""
        with patch(_WATSONX_CLIENT) as client_cls:
            adapter = WatsonXAdapter(model_name="m", project_id="legacy-project")

        assert adapter.container_id == "legacy-project"
        assert client_cls.call_args.kwargs["container_id"] == "legacy-project"

    def test_container_id_takes_precedence_over_project_id(self):
        """An explicit container_id wins over the project_id alias."""
        with patch(_WATSONX_CLIENT):
            adapter = WatsonXAdapter(model_name="m", container_id="explicit", project_id="legacy")

        assert adapter.container_id == "explicit"

    def test_chat_passes_response_format(self):
        """response_format is forwarded to the client's chat call."""
        with patch(_WATSONX_CLIENT) as client_cls:
            client = client_cls.return_value
            client.chat.return_value = "{}"
            adapter = WatsonXAdapter(model_name="m")

            result = adapter.chat(model_name="other", messages=[], response_format={"type": "json_object"})

        assert result == "{}"
        assert client.model_name == "other"
        client.chat.assert_called_once_with(messages=[], response_format={"type": "json_object"})

    def test_generate_passes_response_format(self):
        """response_format is forwarded to the client's generate call."""
        with patch(_WATSONX_CLIENT) as client_cls:
            client = client_cls.return_value
            client.generate.return_value = "{}"
            adapter = WatsonXAdapter(model_name="m")

            result = adapter.generate(prompt="p", response_format={"type": "json_object"})

        assert result == "{}"
        client.generate.assert_called_once_with(prompt="p", response_format={"type": "json_object"})


class TestWatsonXEmbeddings:
    """Test suite for WatsonX embedding capabilities."""

    @pytest.fixture
    def rest_client_class(self):
        """Patch the WatsonX client and the REST embedding client class."""
        with patch(_WATSONX_CLIENT), patch(_WATSONX_REST_CLIENT) as rest_cls:
            rest_cls.return_value = Mock()
            yield rest_cls

    @pytest.fixture
    def adapter(self, rest_client_class):
        """Create a fully configured WatsonX adapter for embeddings."""
        return WatsonXAdapter(model_name="ibm/slate-125m-english-rtrvr", timeout=30, **_FULL_CONFIG)

    def test_implements_llm_embedding_port(self, adapter):
        """Adapter implements the LLMEmbeddingPort interface."""
        assert isinstance(adapter, LLMEmbeddingPort)

    def test_embedding_client_is_lazy_and_cached(self, adapter, rest_client_class):
        """The REST embedding client is only built on first access and then reused."""
        rest_client_class.assert_not_called()

        first = adapter.embedding_client
        second = adapter.embedding_client

        assert first is second
        rest_client_class.assert_called_once_with(
            api_key="watsonx-test-credential",  # pragma: allowlist secret
            url="https://us-south.ml.cloud.ibm.com",
            container_id="test-project-id",
            container_kind="project",
            model_name="ibm/slate-125m-english-rtrvr",
            timeout=30,
            batch_size=800,
        )

    @pytest.mark.parametrize("missing", ["api_key", "api_base", "container_id", "container_kind"])
    def test_embedding_client_requires_parameter(self, rest_client_class, missing):
        """Accessing the embedding client without a required parameter raises DocpipeException."""
        config = {**_FULL_CONFIG, missing: None}
        adapter = WatsonXAdapter(model_name="m", **config)

        with pytest.raises(DocpipeException, match=f"requires {missing}"):
            _ = adapter.embedding_client
        rest_client_class.assert_not_called()

    def test_generate_embeddings_uses_default_model(self, adapter, rest_client_class):
        """Single-text embeddings use the adapter's default model."""
        rest_client = rest_client_class.return_value
        rest_client.generate_embeddings.return_value = [0.1, 0.2]

        result = adapter.generate_embeddings(text="hello")

        assert result == [0.1, 0.2]
        assert rest_client.model_name == "ibm/slate-125m-english-rtrvr"
        rest_client.generate_embeddings.assert_called_once_with(text="hello")

    def test_generate_embeddings_overrides_model(self, adapter, rest_client_class):
        """An explicit model_name is applied to the embedding client."""
        rest_client = rest_client_class.return_value
        rest_client.generate_embeddings.return_value = [0.3]

        adapter.generate_embeddings(model_name="ibm/granite-embedding", text="hello")

        assert rest_client.model_name == "ibm/granite-embedding"

    def test_generate_embeddings_batch(self, adapter, rest_client_class):
        """Batch embeddings are delegated to the embedding client."""
        rest_client = rest_client_class.return_value
        rest_client.generate_embeddings_batch.return_value = [[0.1], [0.2]]

        result = adapter.generate_embeddings_batch(model_name="ibm/granite-embedding", texts=["a", "b"])

        assert result == [[0.1], [0.2]]
        assert rest_client.model_name == "ibm/granite-embedding"
        rest_client.generate_embeddings_batch.assert_called_once_with(texts=["a", "b"])

    def test_generate_embeddings_batch_without_config_raises(self, rest_client_class):
        """Batch embeddings fail fast when the adapter lacks embedding configuration."""
        adapter = WatsonXAdapter(model_name="m")

        with pytest.raises(DocpipeException, match="requires api_key"):
            adapter.generate_embeddings_batch(texts=["a"])

    def test_get_embedding_dimension_is_detected_and_cached(self, adapter, rest_client_class):
        """Dimension is detected from one sample embedding and then cached."""
        rest_client = rest_client_class.return_value
        rest_client.generate_embeddings.return_value = [0.0] * 384

        assert adapter.get_embedding_dimension() == 384
        assert adapter.get_embedding_dimension() == 384
        rest_client.generate_embeddings.assert_called_once_with(text="test")


class TestWatsonXValidation:
    """Test suite for WatsonX configuration validation."""

    @staticmethod
    def _make_adapter(*, model_name: str | None = "m", **client_attrs) -> WatsonXAdapter:
        """Build an adapter whose mocked client exposes the given configuration attributes."""
        attrs = {**_FULL_CONFIG, **client_attrs}
        with patch(_WATSONX_CLIENT) as client_cls:
            client = client_cls.return_value
            for name, value in attrs.items():
                setattr(client, name, value)
            return WatsonXAdapter(model_name=model_name)

    def test_valid_configuration(self):
        """A complete configuration passes validation for every context."""
        adapter = self._make_adapter()

        for result, context in (
            (adapter.validate_inference(), "inference"),
            (adapter.validate_embedding(), "embedding"),
            (adapter.validate_detection(), "detection"),
        ):
            assert result == {"valid": True, "context": context, "errors": [], "warnings": []}

    def test_missing_values_are_reported(self):
        """Missing or blank values each produce a validation error."""
        adapter = self._make_adapter(api_key="  ", api_base=None, container_id="", container_kind=None)

        result = adapter.validate_embedding()

        assert result["valid"] is False
        assert result["errors"] == [
            "api_key is missing or empty",
            "api_base is missing or empty",
            "container_id is missing or empty",
            "container_kind is missing",
        ]

    def test_invalid_container_kind(self):
        """An unsupported container kind is rejected."""
        adapter = self._make_adapter(container_kind="catalog")

        result = adapter.validate_detection()

        assert result["valid"] is False
        assert result["context"] == "detection"
        assert result["errors"] == ["container_kind must be one of ['project', 'space'], got: catalog"]

    def test_missing_model_name_is_a_warning(self):
        """A missing default model name only produces a warning."""
        adapter = self._make_adapter(model_name=None)

        result = adapter.validate_inference()

        assert result["valid"] is True
        assert result["warnings"] == ["model_name is not set - will need to be provided per method call"]


class TestWatsonXDetectionGuards:
    """Test suite for WatsonX detection API precondition checks."""

    @staticmethod
    def _make_adapter(**overrides) -> WatsonXAdapter:
        """Create an adapter with the full detection config, overridden as requested."""
        with patch(_WATSONX_CLIENT):
            return WatsonXAdapter(model_name="m", **{**_FULL_CONFIG, **overrides})

    def test_detect_entities_batch_empty_prompt_raises_error(self):
        """An empty prompt is rejected before any detection call."""
        adapter = self._make_adapter()

        with pytest.raises(ValueError, match="Detection prompt cannot be empty"):
            adapter.detect_entities_batch(texts=["text"], prompt="  ")

    def test_missing_api_key_raises_on_token_request(self):
        """Requesting an access token without an api_key raises ValueError."""
        adapter = self._make_adapter(api_key=None)

        with pytest.raises(ValueError, match="API key is required"):
            adapter._get_access_token()

    def test_access_token_is_cached(self):
        """The IAM token is fetched once and reused."""
        adapter = self._make_adapter()

        with patch(_IAM_TOKEN, return_value="token-1") as token_mock:
            assert adapter._get_access_token() == "token-1"
            assert adapter._get_access_token() == "token-1"

        token_mock.assert_called_once_with(api_key="watsonx-test-credential")  # pragma: allowlist secret

    def test_detect_reports_missing_api_base(self):
        """detect() reports a missing API base URL as a failed result."""
        adapter = self._make_adapter(api_base=None)

        result = adapter.detect(text="some text")

        assert result["success"] is False
        assert result["error"] == "WatsonX API base URL is required for text detection"

    @pytest.mark.parametrize("missing", ["container_id", "container_kind"])
    def test_detect_entities_reports_missing_container(self, missing):
        """detect_entities() wraps a missing container setting in a ValueError."""
        adapter = self._make_adapter(**{missing: None})

        with pytest.raises(ValueError, match="container id/ container kind is required"):
            adapter.detect_entities(text="some text", prompt="Detect PII")
