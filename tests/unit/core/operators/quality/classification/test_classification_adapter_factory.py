"""Unit tests for ClassificationAdapterFactory (registry-based dispatcher)."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.quality.classification.adapters.outbound.factories.classification_adapter_factory import (
    ClassificationAdapterFactory,
)
from docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter import (
    StandardLLMClassificationAdapter,
)
from docpipe.core.operators.quality.classification.ports.outbound.classification_port import ClassificationPort

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_LITELLM_CONFIG: dict[str, Any] = {
    "provider": "litellm",
    "provider_config": {
        "model_id": "openai/test-model",
        "api_base": "http://localhost:11434/v1",
        "api_key": "test",  # pragma: allowlist secret
    },
    "document_types": ["invoice", "report"],
}

_WATSONX_CONFIG: dict[str, Any] = {
    "provider": "watsonx",
    "provider_config": {
        "model_id": "ibm/granite-3-8b-instruct",
        "api_base": "https://us-south.ml.cloud.ibm.com",
    },
    "document_types": ["invoice", "report"],
}


# ---------------------------------------------------------------------------
# Tests — registry mechanics
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_standard_adapter_is_registered(self) -> None:
        """StandardLLMClassificationAdapter is registered under 'standard' at import time."""
        assert "standard" in ClassificationAdapterFactory._REGISTRY
        assert ClassificationAdapterFactory._REGISTRY["standard"] is StandardLLMClassificationAdapter

    def test_register_adds_to_registry(self) -> None:
        """register() stores the adapter class under its ADAPTER_NAME."""

        class _FakeAdapter(ClassificationPort):
            ADAPTER_NAME = "_fake_test_adapter"
            ADAPTER_DISPLAY_NAME = "Fake"

            @classmethod
            def from_config(cls, config: dict[str, Any]) -> "_FakeAdapter":
                return cls()

            def classify_document(self, *, doc_name, binary_content, existing_text, document_types):  # type: ignore[override]
                ...

        ClassificationAdapterFactory.register(_FakeAdapter)
        assert ClassificationAdapterFactory._REGISTRY.get("_fake_test_adapter") is _FakeAdapter
        # clean up so other tests aren't affected
        del ClassificationAdapterFactory._REGISTRY["_fake_test_adapter"]

    def test_get_supported_providers_are_the_alias_keys(self) -> None:
        supported = ClassificationAdapterFactory.get_supported_providers()
        assert supported == {"litellm", "watsonx"}
        assert "standard" not in supported

    def test_get_supported_providers_excludes_deprecated(self) -> None:
        supported = ClassificationAdapterFactory.get_supported_providers()
        for deprecated in ClassificationAdapterFactory._DEPRECATED:
            assert deprecated not in supported


# ---------------------------------------------------------------------------
# Tests — alias resolution
# ---------------------------------------------------------------------------


class TestAliasResolution:
    def test_litellm_resolves_to_standard_adapter(self) -> None:
        """'litellm' is an alias for 'standard'; from_config is called on StandardLLMClassificationAdapter."""
        with patch.object(StandardLLMClassificationAdapter, "from_config") as mock_fc:
            mock_fc.return_value = MagicMock(spec=StandardLLMClassificationAdapter)
            ClassificationAdapterFactory.create_adapter(provider="litellm", config=_LITELLM_CONFIG)
        mock_fc.assert_called_once_with(_LITELLM_CONFIG)

    def test_watsonx_resolves_to_standard_adapter(self) -> None:
        """'watsonx' is an alias for 'standard'; from_config is called on StandardLLMClassificationAdapter."""
        with patch.object(StandardLLMClassificationAdapter, "from_config") as mock_fc:
            mock_fc.return_value = MagicMock(spec=StandardLLMClassificationAdapter)
            ClassificationAdapterFactory.create_adapter(provider="watsonx", config=_WATSONX_CONFIG)
        mock_fc.assert_called_once_with(_WATSONX_CONFIG)

    def test_standard_is_not_a_valid_provider(self) -> None:
        """'standard' is the internal ADAPTER_NAME, not a provider string."""
        with patch.object(StandardLLMClassificationAdapter, "from_config") as mock_fc:
            with pytest.raises(ValueError, match="Unknown classification provider"):
                ClassificationAdapterFactory.create_adapter(provider="standard", config=_LITELLM_CONFIG)
        mock_fc.assert_not_called()

    def test_provider_string_is_case_insensitive(self) -> None:
        """Provider strings are normalised to lower-case before resolution."""
        with patch.object(StandardLLMClassificationAdapter, "from_config") as mock_fc:
            mock_fc.return_value = MagicMock(spec=StandardLLMClassificationAdapter)
            ClassificationAdapterFactory.create_adapter(provider="LiteLLM", config=_LITELLM_CONFIG)
        mock_fc.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — deprecated and unknown providers
# ---------------------------------------------------------------------------


class TestInvalidProviders:
    def test_ollama_raises_with_migration_message(self) -> None:
        with pytest.raises(ValueError, match="litellm"):
            ClassificationAdapterFactory.create_adapter(
                provider="ollama",
                config={"provider": "ollama", "provider_config": {}, "document_types": []},
            )

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown classification provider"):
            ClassificationAdapterFactory.create_adapter(
                provider="openai",
                config={"provider": "openai", "provider_config": {}, "document_types": []},
            )

    def test_error_message_lists_supported_providers(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            ClassificationAdapterFactory.create_adapter(
                provider="openai",
                config={"provider": "openai", "provider_config": {}, "document_types": []},
            )
        # Error message should name at least one known provider
        assert "litellm" in str(exc_info.value)
        assert "watsonx" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests — from_config delegation
# ---------------------------------------------------------------------------


class TestFromConfigDelegation:
    def test_create_adapter_delegates_to_from_config(self) -> None:
        """Factory calls adapter_class.from_config(config), not the constructor."""
        with patch.object(StandardLLMClassificationAdapter, "from_config") as mock_fc:
            mock_result = MagicMock(spec=StandardLLMClassificationAdapter)
            mock_fc.return_value = mock_result
            result = ClassificationAdapterFactory.create_adapter(provider="litellm", config=_LITELLM_CONFIG)
        assert result is mock_result
        mock_fc.assert_called_once_with(_LITELLM_CONFIG)

    def test_validation_errors_from_from_config_propagate(self) -> None:
        """Errors raised inside from_config bubble up through create_adapter."""
        with patch.object(StandardLLMClassificationAdapter, "from_config", side_effect=ValueError("bad config")):
            with pytest.raises(ValueError, match="bad config"):
                ClassificationAdapterFactory.create_adapter(provider="litellm", config=_LITELLM_CONFIG)


class TestDeprecationMessage:
    def test_returns_message_for_deprecated_provider(self) -> None:
        message = ClassificationAdapterFactory.get_deprecation_message("Ollama")
        assert message is not None
        assert "litellm" in message

    def test_returns_none_for_supported_provider(self) -> None:
        assert ClassificationAdapterFactory.get_deprecation_message("litellm") is None
