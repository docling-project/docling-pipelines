"""Unit tests for StandardLLMClassificationAdapter."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter import (
    StandardLLMClassificationAdapter,
)
from docpipe.core.operators.quality.classification.domain.models import ClassificationResponse
from docpipe.core.ports.llm_inference_port import LLMInferencePort

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE_CONFIG: dict[str, Any] = {
    "provider": "litellm",
    "provider_config": {
        "model_id": "openai/test-model",
        "api_base": "http://localhost:11434/v1",
        "api_key": "test",  # pragma: allowlist secret
    },
    "document_types": ["invoice", "receipt"],
    "confidence_threshold": 7.0,
}

_GOOD_RESPONSE = ClassificationResponse(
    document_type="invoice",
    confidence=9,
    reasoning="Contains line items and totals",
    success=True,
)


def _make_mock_llm_adapter() -> MagicMock:
    """Return a mock LLMInferencePort that passes validation."""
    mock = MagicMock(spec=LLMInferencePort)
    mock.validate.return_value = {"valid": True, "errors": [], "warnings": []}
    return mock


def _make_adapter(config: dict[str, Any] | None = None) -> StandardLLMClassificationAdapter:
    """Return an adapter with a mocked _LLMClassificationService."""
    cfg = config or _BASE_CONFIG
    mock_llm = _make_mock_llm_adapter()
    with patch(
        "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter._LLMClassificationService"
    ) as mock_svc_cls:
        mock_svc = MagicMock()
        mock_svc.classify_document.return_value = _GOOD_RESPONSE
        mock_svc_cls.return_value = mock_svc
        adapter = StandardLLMClassificationAdapter(llm_adapter=mock_llm, config=cfg)
    adapter._service = mock_svc  # type: ignore[attr-defined]
    return adapter


# ---------------------------------------------------------------------------
# Tests — constructor / class attributes
# ---------------------------------------------------------------------------


class TestStandardLLMClassificationAdapterInit:
    def test_adapter_name(self) -> None:
        assert StandardLLMClassificationAdapter.ADAPTER_NAME == "standard"

    def test_has_no_provider_aliases_copy(self) -> None:
        """The factory's _PROVIDER_ALIASES is the single source of truth."""
        assert not hasattr(StandardLLMClassificationAdapter, "PROVIDER_ALIASES")

    def test_does_not_read_document_types_from_config(self) -> None:
        """Document types are a per-call argument, never read from config."""
        adapter = _make_adapter()
        assert not hasattr(adapter, "document_types")

    def test_does_not_hold_confidence_threshold(self) -> None:
        """The operator is the only place the confidence threshold is enforced."""
        adapter = _make_adapter()
        assert not hasattr(adapter, "confidence_threshold")

    def test_stores_max_content_length_default(self) -> None:
        adapter = _make_adapter()
        assert adapter.max_content_length == OperatorConstants.Classification.DEFAULT_MAX_CONTENT_LENGTH

    def test_stores_configured_max_content_length(self) -> None:
        config = {**_BASE_CONFIG, "max_content_length": 500}
        adapter = _make_adapter(config=config)
        assert adapter.max_content_length == 500

    def test_requires_llm_adapter_parameter(self) -> None:
        """Constructor requires llm_adapter; passing it builds successfully."""
        mock_llm = _make_mock_llm_adapter()
        with patch(
            "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter._LLMClassificationService"
        ):
            adapter = StandardLLMClassificationAdapter(llm_adapter=mock_llm, config=_BASE_CONFIG)
        assert adapter is not None

    def test_doc_format_defaults_to_markdown(self) -> None:
        assert _make_adapter().doc_format == "markdown"

    def test_doc_format_read_from_config(self) -> None:
        assert _make_adapter({**_BASE_CONFIG, "doc_format": "doclang"}).doc_format == "doclang"

    def test_strict_label_matching_defaults_to_false_and_is_forwarded(self) -> None:
        mock_llm = _make_mock_llm_adapter()
        adapter_module = "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter"
        with patch(f"{adapter_module}._LLMClassificationService") as mock_svc_cls:
            StandardLLMClassificationAdapter(llm_adapter=mock_llm, config=_BASE_CONFIG)
            assert mock_svc_cls.call_args.kwargs["strict_label_matching"] is False

            StandardLLMClassificationAdapter(
                llm_adapter=mock_llm, config={**_BASE_CONFIG, "strict_label_matching": True}
            )
            assert mock_svc_cls.call_args.kwargs["strict_label_matching"] is True


# ---------------------------------------------------------------------------
# Tests — from_config (canonical construction path)
# ---------------------------------------------------------------------------


class TestFromConfig:
    """from_config is the path the factory calls; test it end-to-end."""

    def test_returns_adapter_instance(self) -> None:
        """from_config returns a StandardLLMClassificationAdapter when config is valid."""
        mock_llm = _make_mock_llm_adapter()
        with (
            patch(
                "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter.LLMAdapterFactory"
            ) as mock_factory_cls,
            patch(
                "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter._LLMClassificationService"
            ),
        ):
            mock_factory_cls.create_inference_adapter.return_value = mock_llm
            mock_factory_cls.get_supported_providers.return_value = {"litellm", "watsonx"}
            adapter = StandardLLMClassificationAdapter.from_config(_BASE_CONFIG)
        assert isinstance(adapter, StandardLLMClassificationAdapter)

    def test_builds_llm_adapter_with_correct_provider(self) -> None:
        """from_config passes the resolved provider to LLMAdapterFactory."""
        mock_llm = _make_mock_llm_adapter()
        with (
            patch(
                "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter.LLMAdapterFactory"
            ) as mock_factory_cls,
            patch(
                "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter._LLMClassificationService"
            ),
        ):
            mock_factory_cls.create_inference_adapter.return_value = mock_llm
            mock_factory_cls.get_supported_providers.return_value = {"litellm", "watsonx"}
            StandardLLMClassificationAdapter.from_config(_BASE_CONFIG)

        mock_factory_cls.create_inference_adapter.assert_called_once_with(
            provider="litellm",
            model_id="openai/test-model",
            provider_config=_BASE_CONFIG["provider_config"],
        )

    def test_missing_provider_uses_default_provider(self) -> None:
        """An absent provider key resolves to the DEFAULT_PROVIDER (litellm), as the operator does."""
        config = {k: v for k, v in _BASE_CONFIG.items() if k != "provider"}
        mock_llm = _make_mock_llm_adapter()
        with (
            patch(
                "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter.LLMAdapterFactory"
            ) as mock_factory_cls,
            patch(
                "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter._LLMClassificationService"
            ),
        ):
            mock_factory_cls.create_inference_adapter.return_value = mock_llm
            mock_factory_cls.get_supported_providers.return_value = {"litellm", "watsonx"}
            StandardLLMClassificationAdapter.from_config(config)

        call_kwargs = mock_factory_cls.create_inference_adapter.call_args.kwargs
        assert call_kwargs["provider"] == OperatorConstants.Classification.DEFAULT_PROVIDER

    def test_standard_is_rejected_as_provider(self) -> None:
        """'standard' is not an LLM provider for LLMAdapterFactory; it must not fall back to litellm."""
        config = {**_BASE_CONFIG, "provider": "standard"}
        with pytest.raises(ValueError, match="Unsupported provider 'standard'"):
            StandardLLMClassificationAdapter.from_config(config)

    def test_unsupported_provider_raises_with_supported_list(self) -> None:
        """An unsupported provider no longer falls back silently to litellm."""
        config = {**_BASE_CONFIG, "provider": "bogus"}
        with pytest.raises(ValueError, match="Unsupported provider 'bogus'") as exc_info:
            StandardLLMClassificationAdapter.from_config(config)
        assert "litellm" in str(exc_info.value)
        assert "watsonx" in str(exc_info.value)

    def test_raises_when_provider_config_missing(self) -> None:
        config = {**_BASE_CONFIG, "provider_config": {}}
        with pytest.raises(ValueError, match="provider_config is required"):
            StandardLLMClassificationAdapter.from_config(config)

    def test_model_id_falls_back_to_default_when_omitted(self) -> None:
        """When provider_config.model_id is omitted, falls back to DEFAULT_MODEL."""
        config = {
            **_BASE_CONFIG,
            "provider_config": {"api_base": "http://localhost:11434/v1"},
        }
        mock_llm = _make_mock_llm_adapter()
        with (
            patch(
                "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter.LLMAdapterFactory"
            ) as mock_factory_cls,
            patch(
                "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter._LLMClassificationService"
            ),
        ):
            mock_factory_cls.create_inference_adapter.return_value = mock_llm
            mock_factory_cls.get_supported_providers.return_value = {"litellm", "watsonx"}
            StandardLLMClassificationAdapter.from_config(config)

        mock_factory_cls.create_inference_adapter.assert_called_once_with(
            provider="litellm",
            model_id=OperatorConstants.Classification.DEFAULT_MODEL,
            provider_config={"api_base": "http://localhost:11434/v1"},
        )

    def test_raises_when_llm_factory_fails(self) -> None:
        with (
            patch(
                "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter.LLMAdapterFactory"
            ) as mock_factory_cls,
        ):
            mock_factory_cls.get_supported_providers.return_value = {"litellm", "watsonx"}
            mock_factory_cls.create_inference_adapter.side_effect = RuntimeError("connection refused")
            with pytest.raises(ValueError, match="Failed to create LLM inference adapter"):
                StandardLLMClassificationAdapter.from_config(_BASE_CONFIG)


# ---------------------------------------------------------------------------
# Tests — injected LLM port (host-application construction path)
# ---------------------------------------------------------------------------


class TestInjectedLLMPort:
    def test_end_to_end_classification_uses_call_time_document_types(self) -> None:
        """A host-supplied LLMInferencePort works via the constructor, with types given per call."""
        mock_llm = _make_mock_llm_adapter()
        mock_llm.chat.return_value = '{"document_type": "pay_stub", "confidence": 9, "reasoning": "r"}'
        config = {"provider_config": {"model_id": "gw/model"}}  # no document_types in config
        adapter = StandardLLMClassificationAdapter(llm_adapter=mock_llm, config=config)
        response = adapter.classify_document(
            doc_name="a.pdf",
            binary_content=None,
            existing_text="Gross pay ...",
            document_types={"pay_stub": "A pay stub", "invoice": "An invoice"},
        )
        assert response.success is True
        assert response.document_type == "pay_stub"
        prompt = mock_llm.chat.call_args.kwargs["messages"][1]["content"]
        assert "pay_stub: A pay stub" in prompt  # call-time types reach the prompt


# ---------------------------------------------------------------------------
# Tests — classify_document with existing_text
# ---------------------------------------------------------------------------


class TestClassifyDocumentWithExistingText:
    def test_delegates_to_service_when_existing_text_given(self) -> None:
        """When existing_text is supplied the service receives it directly."""
        adapter = _make_adapter()
        response = adapter.classify_document(
            doc_name="doc.pdf",
            binary_content=None,
            existing_text="Invoice total: $100",
            document_types=["invoice", "receipt"],
        )
        assert response.success is True
        assert response.document_type == "invoice"
        adapter._service.classify_document.assert_called_once()  # type: ignore[attr-defined]

    def test_passes_call_time_document_types_to_service(self) -> None:
        adapter = _make_adapter()
        types = {"invoice": "An invoice"}
        adapter.classify_document(doc_name="doc.pdf", binary_content=None, existing_text="text", document_types=types)
        request = adapter._service.classify_document.call_args.kwargs["request"]  # type: ignore[attr-defined]
        assert request.document_types == types

    def test_returns_valid_classification_response(self) -> None:
        adapter = _make_adapter()
        response = adapter.classify_document(
            doc_name="doc.pdf",
            binary_content=None,
            existing_text="Some document content",
            document_types=["invoice"],
        )
        assert isinstance(response, ClassificationResponse)
        assert response.success is True

    def test_passes_configured_max_content_length_to_request(self) -> None:
        """The configured max_content_length is forwarded to ClassificationRequest."""
        config = {**_BASE_CONFIG, "max_content_length": 500}
        adapter = _make_adapter(config=config)
        adapter.classify_document(
            doc_name="doc.pdf",
            binary_content=None,
            existing_text="Some document content",
            document_types=["invoice"],
        )
        request = adapter._service.classify_document.call_args.kwargs["request"]  # type: ignore[attr-defined]
        assert request.max_content_length == 500

    def test_passes_default_max_content_length_to_request(self) -> None:
        """When max_content_length is unconfigured, DEFAULT_MAX_CONTENT_LENGTH is used."""
        adapter = _make_adapter()
        adapter.classify_document(
            doc_name="doc.pdf",
            binary_content=None,
            existing_text="Some document content",
            document_types=["invoice"],
        )
        request = adapter._service.classify_document.call_args.kwargs["request"]  # type: ignore[attr-defined]
        assert request.max_content_length == OperatorConstants.Classification.DEFAULT_MAX_CONTENT_LENGTH


# ---------------------------------------------------------------------------
# Tests — classify_document from binary_content (adapter owns Docling extraction)
# ---------------------------------------------------------------------------

_OPERATOR_UTILS = "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter.OperatorUtils"


class TestClassifyDocumentFromBinary:
    def test_extracts_then_classifies_and_reports_side_products(self) -> None:
        adapter = _make_adapter()
        with patch(_OPERATOR_UTILS) as mock_utils:
            mock_utils.extract_content.return_value = {
                "success": True,
                "content": "Extracted markdown text",
                "metadata": {"page_count": 3},
            }
            response = adapter.classify_document(
                doc_name="doc.pdf",
                binary_content=b"%PDF-fake",
                existing_text=None,
                document_types=["invoice"],
            )
        mock_utils.extract_content.assert_called_once_with(
            file_path="doc.pdf", binary_content=b"%PDF-fake", doc_format="markdown"
        )
        request = adapter._service.classify_document.call_args.kwargs["request"]  # type: ignore[attr-defined]
        assert request.content == "Extracted markdown text"
        assert response.success is True
        assert response.extracted_content == "Extracted markdown text"
        assert response.extraction_metadata == {"page_count": 3}

    def test_extraction_honors_doclang_doc_format(self) -> None:
        adapter = _make_adapter({**_BASE_CONFIG, "doc_format": "doclang"})
        with patch(_OPERATOR_UTILS) as mock_utils:
            mock_utils.extract_content.return_value = {"success": True, "content": "<doclang/>", "metadata": {}}
            response = adapter.classify_document(
                doc_name="doc.pdf",
                binary_content=b"%PDF-fake",
                existing_text=None,
                document_types=["invoice"],
            )
        mock_utils.extract_content.assert_called_once_with(
            file_path="doc.pdf", binary_content=b"%PDF-fake", doc_format="doclang"
        )
        assert response.extracted_content == "<doclang/>"

    def test_does_not_mutate_service_response(self) -> None:
        adapter = _make_adapter()
        with patch(_OPERATOR_UTILS) as mock_utils:
            mock_utils.extract_content.return_value = {"success": True, "content": "text", "metadata": {}}
            adapter.classify_document(
                doc_name="doc.pdf", binary_content=b"x", existing_text=None, document_types=["invoice"]
            )
        assert _GOOD_RESPONSE.extracted_content is None
        assert _GOOD_RESPONSE.extraction_metadata is None

    def test_existing_text_skips_extraction(self) -> None:
        adapter = _make_adapter()
        with patch(_OPERATOR_UTILS) as mock_utils:
            response = adapter.classify_document(
                doc_name="doc.pdf", binary_content=b"x", existing_text="already here", document_types=["invoice"]
            )
        mock_utils.extract_content.assert_not_called()
        assert response.extracted_content is None
        assert response.extraction_metadata is None

    def test_returns_failure_when_extraction_fails(self) -> None:
        adapter = _make_adapter()
        with patch(_OPERATOR_UTILS) as mock_utils:
            mock_utils.extract_content.return_value = {"success": False, "error": "Unsupported format"}
            response = adapter.classify_document(
                doc_name="doc.pdf", binary_content=b"bad", existing_text=None, document_types=["invoice"]
            )
        assert response.success is False
        assert response.error == "Unsupported format"
        assert response.extracted_content is None
        adapter._service.classify_document.assert_not_called()  # type: ignore[attr-defined]

    def test_blank_extraction_returns_failure_carrying_extracted_content(self) -> None:
        adapter = _make_adapter()
        with patch(_OPERATOR_UTILS) as mock_utils:
            mock_utils.extract_content.return_value = {"success": True, "content": "   \n", "metadata": {}}
            response = adapter.classify_document(
                doc_name="doc.pdf", binary_content=b"x", existing_text=None, document_types=["invoice"]
            )
        assert response.success is False
        assert response.error == "Empty content"
        assert response.extracted_content == "   \n"
        adapter._service.classify_document.assert_not_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Tests — no content
# ---------------------------------------------------------------------------


class TestClassifyDocumentNoContent:
    def test_returns_failure_when_both_none(self) -> None:
        adapter = _make_adapter()
        response = adapter.classify_document(
            doc_name="doc.pdf",
            binary_content=None,
            existing_text=None,
            document_types=["invoice"],
        )
        assert response.success is False
        assert response.error is not None
        assert "existing_text or binary_content" in response.error
