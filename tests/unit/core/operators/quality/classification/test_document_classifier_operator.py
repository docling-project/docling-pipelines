"""Unit tests for DocumentClassifierOperator — factory wiring and injection seams.

Tests verify that:
- ``provider="litellm"`` → factory is called correctly and operator holds the result
- Output columns are present and correct
- Validate() does not flag valid providers
- ``DocumentClassProvider`` / ``ClassificationPort`` can be injected (hexagonal seams)
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.operators.quality.classification.adapters.outbound.factories.classification_adapter_factory import (
    ClassificationAdapterFactory,
)
from docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter import (
    StandardLLMClassificationAdapter,
)
from docpipe.core.operators.quality.classification.document_classifier import DocumentClassifierOperator
from docpipe.core.operators.quality.classification.domain.models import ClassificationResponse
from docpipe.core.operators.quality.classification.ports.outbound.classification_port import ClassificationPort
from docpipe.core.ports.document_class_provider import DocumentClassProvider, StaticDocumentClassProvider

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

_GOOD_RESPONSE = ClassificationResponse(
    document_type="invoice",
    confidence=9,
    reasoning="Has line items",
    success=True,
)


def _make_operator(config: dict[str, Any], mock_adapter: MagicMock):
    """Build a DocumentClassifierOperator with adapter replaced by *mock_adapter*."""
    from docpipe.core.operators.quality.classification.document_classifier import DocumentClassifierOperator

    with patch(
        "docpipe.core.operators.quality.classification.document_classifier.ClassificationAdapterFactory"
    ) as mock_factory:
        mock_factory.create_adapter.return_value = mock_adapter
        op = DocumentClassifierOperator(config=config)
    op.adapter = mock_adapter
    return op


# ---------------------------------------------------------------------------
# Tests — factory resolution
# ---------------------------------------------------------------------------


class TestOperatorFactoryWiring:
    def test_litellm_provider_uses_factory(self) -> None:
        """Factory is called when provider=litellm; operator holds its result."""
        mock_adapter = MagicMock(spec=StandardLLMClassificationAdapter)
        mock_adapter.classify_document.return_value = _GOOD_RESPONSE

        from docpipe.core.operators.quality.classification.document_classifier import DocumentClassifierOperator

        with patch(
            "docpipe.core.operators.quality.classification.document_classifier.ClassificationAdapterFactory"
        ) as mock_factory:
            mock_factory.create_adapter.return_value = mock_adapter
            op = DocumentClassifierOperator(config=_LITELLM_CONFIG)

        mock_factory.create_adapter.assert_called_once_with(provider="litellm", config=_LITELLM_CONFIG)
        assert op.adapter is mock_adapter


# ---------------------------------------------------------------------------
# Tests — output columns correct
# ---------------------------------------------------------------------------


class TestOutputColumns:
    def _run_transform(self, config: dict[str, Any]) -> pa.Table:
        """Run transform with a mocked adapter and return the output table."""
        mock_adapter = MagicMock()
        mock_adapter.classify_document.return_value = _GOOD_RESPONSE

        op = _make_operator(config, mock_adapter)

        table = pa.table(
            {
                "id": ["doc_1"],
                "name": ["test.pdf"],
                "content": ["Invoice total: $500"],
            }
        )

        output_tables, _ = op.transform(table)
        return output_tables[0]

    def test_document_type_column_present(self) -> None:
        result = self._run_transform(_LITELLM_CONFIG)
        assert "document_type" in result.column_names

    def test_confidence_column_present_when_enabled(self) -> None:
        config = {**_LITELLM_CONFIG, "include_confidence": True}
        result = self._run_transform(config)
        assert "document_type_confidence" in result.column_names

    def test_no_is_scanned_column_emitted(self) -> None:
        """is_scanned must never appear in the output table."""
        result = self._run_transform(_LITELLM_CONFIG)
        assert "is_scanned" not in result.column_names


# ---------------------------------------------------------------------------
# Tests — validate()
# ---------------------------------------------------------------------------


class TestValidate:
    def test_valid_provider_produces_no_provider_error(self) -> None:
        mock_adapter = MagicMock(spec=StandardLLMClassificationAdapter)

        from docpipe.core.operators.quality.classification.document_classifier import DocumentClassifierOperator

        with patch(
            "docpipe.core.operators.quality.classification.document_classifier.ClassificationAdapterFactory"
        ) as mock_factory:
            mock_factory.create_adapter.return_value = mock_adapter
            mock_factory.get_supported_providers.return_value = {"litellm", "watsonx"}
            op = DocumentClassifierOperator(config=_LITELLM_CONFIG)

            errors: list[str] = []
            warnings: list[str] = []
            op.validate(errors, warnings, ["content", "id", "name"])

        provider_errors = [e for e in errors if "provider" in e.lower() and "litellm" in e.lower()]
        assert provider_errors == [], "validate() should not flag 'litellm' as invalid provider"


class TestValidateProviderMessages:
    def test_deprecated_ollama_reports_migration_message(self) -> None:
        op = DocumentClassifierOperator(_LITELLM_CONFIG, classification_adapter=MagicMock(spec=ClassificationPort))
        op.provider = "ollama"
        errors: list[str] = []
        op.validate(errors, [], ["content", "id", "name"])
        assert any("Ollama provider is no longer supported" in e for e in errors)

    def test_unknown_provider_reports_supported_list(self) -> None:
        op = DocumentClassifierOperator(_LITELLM_CONFIG, classification_adapter=MagicMock(spec=ClassificationPort))
        op.provider = "bogus"
        errors: list[str] = []
        op.validate(errors, [], ["content", "id", "name"])
        assert any("provider must be one of" in e for e in errors)

    def test_provider_config_is_not_flagged_required(self) -> None:
        """watsonx may omit provider_config (WATSONX_* env vars); the adapter enforces the litellm rule."""
        attributes = DocumentClassifierOperator.get_metadata()["attributes"]
        assert attributes["provider_config"]["required"] is False

    def test_strict_label_matching_declared_in_metadata(self) -> None:
        attribute = DocumentClassifierOperator.get_metadata()["attributes"]["strict_label_matching"]
        assert attribute["default"] is False
        assert attribute["required"] is False


class TestCustomAdapterSelectedByProvider:
    """A registered adapter is selectable via ``provider: "<ADAPTER_NAME>"`` through the real factory."""

    @staticmethod
    def _register_custom() -> type[ClassificationPort]:
        class _CustomAdapter(ClassificationPort):
            ADAPTER_NAME = "_operator_test_custom"
            ADAPTER_DISPLAY_NAME = "Custom"

            @classmethod
            def from_config(cls, config: dict[str, Any]) -> "_CustomAdapter":
                return cls()

            def classify_document(self, *, doc_name, binary_content, existing_text, document_types):  # type: ignore[override]
                return _GOOD_RESPONSE

        ClassificationAdapterFactory.register(_CustomAdapter)
        return _CustomAdapter

    def test_custom_provider_passes_validate_and_constructs_via_factory(self) -> None:
        adapter_class = self._register_custom()
        try:
            op = DocumentClassifierOperator({"provider": "_operator_test_custom", "document_types": ["invoice"]})
            errors: list[str] = []
            op.validate(errors, [], ["content", "id", "name"])
        finally:
            ClassificationAdapterFactory._REGISTRY.pop("_operator_test_custom", None)

        assert isinstance(op.adapter, adapter_class)
        assert [e for e in errors if "provider" in e.lower()] == []


# ---------------------------------------------------------------------------
# Tests — DocumentClassProvider / ClassificationPort injection
# ---------------------------------------------------------------------------

_CONFIG_NO_TYPES: dict[str, Any] = {
    "provider": "litellm",
    "provider_config": {
        "model_id": "openai/test",
        "api_base": "http://localhost:11434/v1",
        "api_key": "x",
    },  # pragma: allowlist secret
}


class _FakeProvider(DocumentClassProvider):
    def __init__(self, types: dict[str, str]) -> None:
        self._types = types
        self.calls = 0

    def get_document_types(self) -> dict[str, str]:
        self.calls += 1
        return dict(self._types)

    def get_schema_templates(self, *, document_types: list[str]) -> dict[str, dict]:
        return {}


class _FakeAdapter(ClassificationPort):
    ADAPTER_NAME = "_fake"
    ADAPTER_DISPLAY_NAME = "Fake"

    def __init__(self) -> None:
        self.received_types: Any = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "_FakeAdapter":
        return cls()

    def classify_document(self, *, doc_name, binary_content, existing_text, document_types):  # type: ignore[override]
        self.received_types = document_types
        return ClassificationResponse(document_type="Pay Stub", confidence=9, reasoning="r", success=True)


@pytest.mark.unit
class TestDocumentClassProviderInjection:
    def test_defaults_to_static_provider(self) -> None:
        with patch("docpipe.core.operators.quality.classification.document_classifier.ClassificationAdapterFactory"):
            op = DocumentClassifierOperator(_CONFIG_NO_TYPES)
        assert isinstance(op._document_class_provider, StaticDocumentClassProvider)

    def test_injected_provider_supplies_types(self) -> None:
        provider = _FakeProvider({"Pay Stub": "A pay stub"})
        op = DocumentClassifierOperator(
            _CONFIG_NO_TYPES, document_class_provider=provider, classification_adapter=_FakeAdapter()
        )
        assert op.document_types == {"Pay Stub": "A pay stub"}

    def test_provider_not_called_during_construction(self) -> None:
        provider = _FakeProvider({"a": "b"})
        DocumentClassifierOperator(
            _CONFIG_NO_TYPES, document_class_provider=provider, classification_adapter=_FakeAdapter()
        )
        assert provider.calls == 0

    def test_provider_result_is_cached(self) -> None:
        provider = _FakeProvider({"a": "b"})
        op = DocumentClassifierOperator(
            _CONFIG_NO_TYPES, document_class_provider=provider, classification_adapter=_FakeAdapter()
        )
        _ = op.document_types
        _ = op.document_types
        assert provider.calls == 1

    def test_config_document_types_override_provider(self) -> None:
        provider = _FakeProvider({"from_provider": "x"})
        config = {**_CONFIG_NO_TYPES, "document_types": ["from_config"]}
        op = DocumentClassifierOperator(config, document_class_provider=provider, classification_adapter=_FakeAdapter())
        assert op.document_types == ["from_config"]
        assert provider.calls == 0

    def test_validate_reports_provider_failure_as_error(self) -> None:
        provider = MagicMock(spec=DocumentClassProvider)
        provider.get_document_types.side_effect = RuntimeError("provider unavailable")
        op = DocumentClassifierOperator(
            _CONFIG_NO_TYPES, document_class_provider=provider, classification_adapter=_FakeAdapter()
        )
        errors: list[str] = []
        op.validate(errors, [], ["content"])
        assert any("provider unavailable" in e for e in errors)


@pytest.mark.unit
class TestClassificationAdapterInjection:
    def test_injected_adapter_bypasses_factory(self) -> None:
        adapter = _FakeAdapter()
        with patch(
            "docpipe.core.operators.quality.classification.document_classifier.ClassificationAdapterFactory"
        ) as factory:
            op = DocumentClassifierOperator(
                _CONFIG_NO_TYPES,
                document_class_provider=_FakeProvider({"Pay Stub": "d"}),
                classification_adapter=adapter,
            )
        factory.create_adapter.assert_not_called()
        assert op.adapter is adapter

    def test_end_to_end_with_fake_ports_only(self) -> None:
        """Provider + adapter fakes: no litellm / watsonx / filesystem involved."""
        adapter = _FakeAdapter()
        op = DocumentClassifierOperator(
            _CONFIG_NO_TYPES,
            document_class_provider=_FakeProvider({"Pay Stub": "A pay stub"}),
            classification_adapter=adapter,
        )
        table = pa.table({"id": ["1"], "name": ["a.pdf"], "content": ["Gross pay 100"]})
        out, _ = op.transform(table)
        assert out[0]["document_type"].to_pylist() == ["Pay Stub"]
        assert adapter.received_types == {"Pay Stub": "A pay stub"}

    def test_document_types_resolved_once_for_whole_batch(self) -> None:
        provider = _FakeProvider({"Pay Stub": "A pay stub"})
        op = DocumentClassifierOperator(
            _CONFIG_NO_TYPES, document_class_provider=provider, classification_adapter=_FakeAdapter()
        )
        table = pa.table({"id": ["1", "2", "3"], "name": ["a.pdf", "b.pdf", "c.pdf"], "content": ["x", "y", "z"]})
        op.transform(table)
        assert provider.calls == 1
