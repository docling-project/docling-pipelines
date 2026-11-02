#!/usr/bin/env python3
"""Unit tests for _LLMClassificationService and StandardLLMClassificationAdapter.from_config.

_LLMClassificationService is constructed with a pre-built LLMInferencePort;
provider validation and adapter construction live in
StandardLLMClassificationAdapter.from_config.
"""

import json
from unittest.mock import Mock, patch

import pytest

from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory
from docpipe.core.constants.constants import LLMConstants
from docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter import (
    StandardLLMClassificationAdapter,
    _LLMClassificationService,
)
from docpipe.core.operators.quality.classification.domain.models import ClassificationRequest
from docpipe.exceptions.docpipe_exceptions import DocpipeException


def _make_valid_llm_adapter(response_text: str = "") -> Mock:
    mock = Mock()
    mock.validate.return_value = {
        LLMConstants.ValidationKeys.VALID: True,
        LLMConstants.ValidationKeys.ERRORS: [],
        LLMConstants.ValidationKeys.WARNINGS: [],
    }
    mock.chat.return_value = response_text
    return mock


@pytest.mark.unit
class TestLLMClassificationServiceInjectedAdapter:
    """Tests for _LLMClassificationService with a pre-built LLMInferencePort."""

    def test_init_with_injected_adapter(self) -> None:
        adapter = _make_valid_llm_adapter()
        service = _LLMClassificationService(llm_adapter=adapter)
        assert service.llm_adapter is adapter

    def test_init_stores_temperature_and_max_tokens(self) -> None:
        adapter = _make_valid_llm_adapter()
        service = _LLMClassificationService(llm_adapter=adapter, temperature=0.5, max_tokens=1000)
        assert service.temperature == 0.5
        assert service.max_tokens == 1000

    def test_validate_called_on_init(self) -> None:
        adapter = _make_valid_llm_adapter()
        _LLMClassificationService(llm_adapter=adapter)
        adapter.validate.assert_called_once()

    def test_validation_failure_raises(self) -> None:
        adapter = Mock()
        adapter.validate.return_value = {
            LLMConstants.ValidationKeys.VALID: False,
            LLMConstants.ValidationKeys.ERRORS: ["Missing API key"],
            LLMConstants.ValidationKeys.WARNINGS: [],
        }
        with pytest.raises(DocpipeException, match="validation failed"):
            _LLMClassificationService(llm_adapter=adapter)

    def test_classify_document_success(self) -> None:
        response_json = json.dumps({"document_type": "invoice", "confidence": 9, "reasoning": "Has line items"})
        adapter = _make_valid_llm_adapter(response_json)
        service = _LLMClassificationService(llm_adapter=adapter)

        request = ClassificationRequest(content="Invoice content", document_types=["invoice", "receipt"])
        response = service.classify_document(request=request)

        assert response.success is True
        assert response.document_type == "invoice"
        assert response.confidence == 9
        assert response.reasoning == "Has line items"

    def test_classify_document_invalid_json_returns_failure(self) -> None:
        adapter = _make_valid_llm_adapter("Not valid JSON")
        service = _LLMClassificationService(llm_adapter=adapter)

        request = ClassificationRequest(content="Test content", document_types=["invoice"])
        response = service.classify_document(request=request)

        assert response.success is False
        assert response.document_type == "unknown"
        assert response.error is not None

    def test_classify_document_missing_fields_returns_failure(self) -> None:
        adapter = _make_valid_llm_adapter(json.dumps({"some_field": "value"}))
        service = _LLMClassificationService(llm_adapter=adapter)

        request = ClassificationRequest(content="Test", document_types=["invoice"])
        response = service.classify_document(request=request)

        assert response.success is False

    def test_classify_document_embedded_json(self) -> None:
        text = 'Here is the result: {"document_type": "report", "confidence": 7, "reasoning": "test"}'
        adapter = _make_valid_llm_adapter(text)
        service = _LLMClassificationService(llm_adapter=adapter)

        request = ClassificationRequest(content="Content", document_types=["report"])
        response = service.classify_document(request=request)

        assert response.success is True
        assert response.document_type == "report"
        assert response.confidence == 7

    def test_default_label_is_normalised_legacy_style(self) -> None:
        response_json = json.dumps({"document_type": "purchase_order", "confidence": 9, "reasoning": "r"})
        service = _LLMClassificationService(llm_adapter=_make_valid_llm_adapter(response_json))

        request = ClassificationRequest(content="PO", document_types=["Purchase Order"])
        response = service.classify_document(request=request)

        assert response.success is True
        assert response.document_type == "purchase_order"

    def test_default_accepts_label_that_differs_from_configured_type(self) -> None:
        response_json = json.dumps({"document_type": "Expense Report", "confidence": 8, "reasoning": "r"})
        service = _LLMClassificationService(llm_adapter=_make_valid_llm_adapter(response_json))

        request = ClassificationRequest(content="ER", document_types=["Expense Reports"])
        response = service.classify_document(request=request)

        assert response.success is True
        assert response.document_type == "expense_report"
        assert response.confidence == 8

    def test_default_accepts_unconfigured_label(self) -> None:
        response_json = json.dumps({"document_type": "Memo", "confidence": 9, "reasoning": "r"})
        service = _LLMClassificationService(llm_adapter=_make_valid_llm_adapter(response_json))

        request = ClassificationRequest(content="Memo", document_types=["invoice", "receipt"])
        response = service.classify_document(request=request)

        assert response.document_type == "memo"

    def test_strict_label_resolved_to_configured_spelling(self) -> None:
        response_json = json.dumps({"document_type": "purchase_order", "confidence": 9, "reasoning": "r"})
        service = _LLMClassificationService(
            llm_adapter=_make_valid_llm_adapter(response_json), strict_label_matching=True
        )

        request = ClassificationRequest(content="PO", document_types={"Purchase Order": "A PO"})
        response = service.classify_document(request=request)

        assert response.success is True
        assert response.document_type == "Purchase Order"

    def test_strict_label_not_in_document_types_yields_none_with_reasoning(self) -> None:
        response_json = json.dumps({"document_type": "memo", "confidence": 9, "reasoning": "r"})
        service = _LLMClassificationService(
            llm_adapter=_make_valid_llm_adapter(response_json), strict_label_matching=True
        )

        request = ClassificationRequest(content="Memo", document_types=["invoice", "receipt"])
        response = service.classify_document(request=request)

        assert response.success is True
        assert response.document_type is None
        assert "memo" in response.reasoning

    def test_get_model_info(self) -> None:
        adapter = _make_valid_llm_adapter()
        service = _LLMClassificationService(
            llm_adapter=adapter,
            model_id="my-model",
            provider_name="gateway",
            temperature=0.3,
            max_tokens=800,
        )
        info = service.get_model_info()
        assert info["model_id"] == "my-model"
        assert info["provider"] == "gateway"
        assert info["temperature"] == 0.3
        assert info["max_tokens"] == 800


@pytest.mark.unit
class TestStandardAdapterFromConfigProviderConfig:
    """provider_config is required for litellm but optional for watsonx (env-var credentials)."""

    def test_watsonx_with_empty_provider_config_does_not_raise(self) -> None:
        llm_adapter = _make_valid_llm_adapter()
        config = {"provider": "watsonx", "provider_config": {}}
        with patch.object(LLMAdapterFactory, "create_inference_adapter", return_value=llm_adapter) as mock_create:
            adapter = StandardLLMClassificationAdapter.from_config(config)
        assert isinstance(adapter, StandardLLMClassificationAdapter)
        assert mock_create.call_args.kwargs["provider"] == "watsonx"

    def test_watsonx_with_absent_provider_config_does_not_raise(self) -> None:
        llm_adapter = _make_valid_llm_adapter()
        with patch.object(LLMAdapterFactory, "create_inference_adapter", return_value=llm_adapter):
            adapter = StandardLLMClassificationAdapter.from_config({"provider": "watsonx"})
        assert isinstance(adapter, StandardLLMClassificationAdapter)

    def test_litellm_with_empty_provider_config_raises(self) -> None:
        with pytest.raises(ValueError, match="provider_config is required"):
            StandardLLMClassificationAdapter.from_config({"provider": "litellm", "provider_config": {}})

    def test_litellm_with_absent_provider_config_raises(self) -> None:
        with pytest.raises(ValueError, match="provider_config is required"):
            StandardLLMClassificationAdapter.from_config({"provider": "litellm"})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
