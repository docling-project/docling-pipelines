# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""PIIAndHAPAnnotator tests for per-capability provider selection (issue #77).

Covers provider/config resolution (including the legacy ``provider`` /
``provider_config`` shorthand), fail-fast capability validation, conditional
adapter injection, operator metadata, and an end-to-end run mixing a PII-only
provider (Presidio, analyzer mocked) with a HAP-only provider.
"""

from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest
from pydantic import BaseModel

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.factories.pii_and_hap_detection_factory import (
    PIIAndHAPDetectionFactory,
)
from docpipe.core.operators.quality.pii_and_hap.domain.models import (
    DetectionCapability,
    DetectionResult,
    PIIHAPDetectionResponse,
    ProviderSelection,
)
from docpipe.core.operators.quality.pii_and_hap.pii_and_hap_annotator import PIIAndHAPAnnotator
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.hap_detection_port import HAPDetectionPort

_ANNOTATOR_MODULE = "docpipe.core.operators.quality.pii_and_hap.pii_and_hap_annotator"
_BUILD_ANALYZER = (
    "docpipe.core.operators.quality.pii_and_hap.adapters.outbound.presidio.adapter.PresidioPIIAdapter._build_analyzer"
)

_LITELLM_CONFIG = {
    "model_id": "openai/granite4",
    "api_base": "http://localhost:11434/v1",
    "api_key": "<ollama>",  # pragma: allowlist secret
}
_WATSONX_CONFIG = {
    "model_id": "ibm/granite-guardian",
    "api_key": "key",  # pragma: allowlist secret
    "url": "https://watsonx.example",
    "container_kind": "project",
    "container_id": "pid",
}


@pytest.fixture
def mocked_wiring():
    """Patch adapter creation and the service so no provider is contacted."""
    with (
        patch(
            f"{_ANNOTATOR_MODULE}.PIIAndHAPDetectionFactory.create", side_effect=lambda *a, **k: MagicMock()
        ) as create,
        patch(f"{_ANNOTATOR_MODULE}.PIIHAPService") as service_cls,
    ):
        yield SimpleNamespace(create=create, service_cls=service_cls)


def _validate(operator: PIIAndHAPAnnotator) -> list[str]:
    errors: list[str] = []
    operator.validate(errors, [], [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
    return errors


# ---------------------------------------------------------------------------
# Provider / config resolution
# ---------------------------------------------------------------------------


def test_legacy_shorthand_sets_both_capabilities():
    config = {"provider": "watsonx", "provider_config": _WATSONX_CONFIG}
    pii = PIIAndHAPAnnotator._resolve_provider_selection(config=config, capability=DetectionCapability.PII)
    hap = PIIAndHAPAnnotator._resolve_provider_selection(config=config, capability=DetectionCapability.HAP)
    expected = ProviderSelection(provider="watsonx", provider_config=_WATSONX_CONFIG)
    assert pii == expected
    assert hap == expected


def test_default_provider_is_litellm():
    pii = PIIAndHAPAnnotator._resolve_provider_selection(config={}, capability=DetectionCapability.PII)
    assert pii.provider == "litellm"
    assert pii.provider_key == "provider"
    assert pii.provider_config == {}


def test_capability_provider_overrides_legacy_provider():
    config = {"provider": "watsonx", "provider_config": _WATSONX_CONFIG, "pii_provider": "presidio"}
    pii = PIIAndHAPAnnotator._resolve_provider_selection(config=config, capability=DetectionCapability.PII)
    hap = PIIAndHAPAnnotator._resolve_provider_selection(config=config, capability=DetectionCapability.HAP)
    # The legacy config belongs to watsonx, so it is NOT handed to presidio
    assert pii == ProviderSelection(
        provider="presidio",
        provider_config={},
        provider_key="pii_provider",
        provider_config_key="pii_provider_config",
    )
    assert hap.provider == "watsonx"
    assert hap.provider_config == _WATSONX_CONFIG


def test_capability_config_wins_over_legacy_config():
    config = {
        "provider": "litellm",
        "provider_config": _LITELLM_CONFIG,
        "hap_provider": "watsonx",
        "hap_provider_config": _WATSONX_CONFIG,
    }
    hap = PIIAndHAPAnnotator._resolve_provider_selection(config=config, capability=DetectionCapability.HAP)
    assert hap == ProviderSelection(
        provider="watsonx",
        provider_config=_WATSONX_CONFIG,
        provider_key="hap_provider",
        provider_config_key="hap_provider_config",
    )


def test_legacy_config_is_shared_when_provider_key_absent():
    config = {"hap_provider": "litellm", "provider_config": _LITELLM_CONFIG}
    hap = PIIAndHAPAnnotator._resolve_provider_selection(config=config, capability=DetectionCapability.HAP)
    assert hap.provider == "litellm"
    assert hap.provider_config == _LITELLM_CONFIG
    assert hap.provider_config_key == "provider_config"


def test_empty_capability_values_fall_back_to_legacy():
    # The UI stamps attribute defaults ({} / no value) - these must not shadow the legacy keys.
    config = {
        "provider": "litellm",
        "provider_config": _LITELLM_CONFIG,
        "pii_provider": None,
        "pii_provider_config": {},
    }
    pii = PIIAndHAPAnnotator._resolve_provider_selection(config=config, capability=DetectionCapability.PII)
    assert pii == ProviderSelection(provider="litellm", provider_config=_LITELLM_CONFIG)


# ---------------------------------------------------------------------------
# Conditional adapter injection
# ---------------------------------------------------------------------------


def test_legacy_flow_builds_one_shared_adapter(mocked_wiring):
    operator = PIIAndHAPAnnotator({"provider": "litellm", "provider_config": _LITELLM_CONFIG})

    mocked_wiring.create.assert_called_once()
    kwargs = mocked_wiring.service_cls.call_args.kwargs
    assert kwargs["pii_adapter"] is kwargs["hap_adapter"]
    assert operator.provider == "litellm"
    assert operator.model_name == "openai/granite4"


def test_pii_only_redactions_inject_no_hap_adapter(mocked_wiring):
    operator = PIIAndHAPAnnotator({"provider": "presidio", "expected_redactions": ["PII"]})

    assert operator.hap_selection is None
    assert operator.pii_selection.provider == "presidio"
    kwargs = mocked_wiring.service_cls.call_args.kwargs
    assert kwargs["pii_adapter"] is not None
    assert kwargs["hap_adapter"] is None
    mocked_wiring.create.assert_called_once()
    assert mocked_wiring.create.call_args.args == ("presidio",)


def test_hap_only_redactions_ignore_pii_provider(mocked_wiring):
    # pii_provider names a HAP-incapable provider, but PII is not expected, so it is never resolved.
    operator = PIIAndHAPAnnotator(
        {
            "pii_provider": "presidio",
            "provider": "watsonx",
            "provider_config": _WATSONX_CONFIG,
            "expected_redactions": ["hap"],
        }
    )
    assert operator.pii_selection is None
    assert operator.hap_selection.provider == "watsonx"
    assert mocked_wiring.service_cls.call_args.kwargs["pii_adapter"] is None


def test_mixed_providers_build_two_adapters(mocked_wiring):
    PIIAndHAPAnnotator(
        {
            "pii_provider": "presidio",
            "hap_provider": "watsonx",
            "hap_provider_config": _WATSONX_CONFIG,
        }
    )
    assert [c.args[0] for c in mocked_wiring.create.call_args_list] == ["presidio", "watsonx"]
    kwargs = mocked_wiring.service_cls.call_args.kwargs
    assert kwargs["pii_adapter"] is not kwargs["hap_adapter"]


# ---------------------------------------------------------------------------
# Fail-fast capability validation
# ---------------------------------------------------------------------------


def test_pii_only_provider_as_hap_provider_fails_fast(mocked_wiring):
    with pytest.raises(ValueError, match="Provider 'presidio' \\(set via 'hap_provider'\\) does not support HAP"):
        PIIAndHAPAnnotator({"provider": "litellm", "provider_config": _LITELLM_CONFIG, "hap_provider": "presidio"})
    mocked_wiring.create.assert_not_called()


def test_pii_only_legacy_provider_with_hap_expected_fails_fast(mocked_wiring):
    with pytest.raises(ValueError, match="does not support HAP detection") as exc_info:
        PIIAndHAPAnnotator({"provider": "presidio"})  # default expected_redactions = pii + hap
    assert "hap_provider" in str(exc_info.value)
    mocked_wiring.create.assert_not_called()


def test_unknown_provider_fails_fast(mocked_wiring):
    with pytest.raises(ValueError, match="Unknown PII/HAP detection provider: 'nope'"):
        PIIAndHAPAnnotator({"pii_provider": "nope"})


def test_capability_errors_reported_by_validate_during_flow_validation(mocked_wiring):
    operator = PIIAndHAPAnnotator(
        {
            "provider": "litellm",
            "provider_config": _LITELLM_CONFIG,
            "hap_provider": "presidio",
            DocpipeConstants.VALIDATING_FLOW: True,
        }
    )
    assert operator.pii_hap_service is None
    mocked_wiring.service_cls.assert_not_called()
    errors = _validate(operator)
    assert any("does not support HAP detection" in e for e in errors)


# ---------------------------------------------------------------------------
# validate(): per-provider config checks
# ---------------------------------------------------------------------------


# "redaction" and "hap_redaction" are required attributes in the operator metadata
_REQUIRED = {"redaction": False, "hap_redaction": False}


def test_validate_presidio_needs_no_model_id(mocked_wiring):
    operator = PIIAndHAPAnnotator(
        {**_REQUIRED, "pii_provider": "presidio", "hap_provider": "litellm", "hap_provider_config": _LITELLM_CONFIG}
    )
    assert _validate(operator) == []


def test_validate_reports_errors_against_the_capability_config_key(mocked_wiring):
    operator = PIIAndHAPAnnotator(
        {**_REQUIRED, "pii_provider": "presidio", "hap_provider": "watsonx", "hap_provider_config": {"model_id": "m"}}
    )
    errors = _validate(operator)
    assert len(errors) == 1
    assert "WatsonX provider requires" in errors[0]
    assert "hap_provider_config" in errors[0]


def test_validate_legacy_errors_reported_once(mocked_wiring):
    operator = PIIAndHAPAnnotator({**_REQUIRED, "provider": "litellm"})
    errors = _validate(operator)
    assert errors == ["provider_config is required for provider 'litellm'"]


def test_validate_rejects_non_dict_capability_config(mocked_wiring):
    operator = PIIAndHAPAnnotator(
        {"provider": "litellm", "provider_config": _LITELLM_CONFIG, "hap_provider_config": "oops"}
    )
    errors = _validate(operator)
    assert "hap_provider_config must be a dictionary, got str" in errors


# ---------------------------------------------------------------------------
# Metadata (schema the UI reads)
# ---------------------------------------------------------------------------


def test_metadata_exposes_capability_provider_attributes():
    attributes = PIIAndHAPAnnotator.get_metadata()[OperatorConstants.Config.ATTRIBUTES]
    valid_values = OperatorConstants.Config.VALID_VALUES
    providers = OperatorConstants.Config.PROVIDERS

    assert {"litellm", "presidio", "watsonx"} <= set(attributes["provider"][valid_values])
    assert {"litellm", "presidio", "watsonx"} <= set(attributes["pii_provider"][valid_values])
    assert "presidio" not in attributes["hap_provider"][valid_values]
    assert {"litellm", "watsonx"} <= set(attributes["hap_provider"][valid_values])

    assert "presidio" in attributes["pii_provider_config"][providers]
    assert "presidio" not in attributes["hap_provider_config"][providers]
    assert attributes["pii_provider_config"][OperatorConstants.Config.PROVIDER_FIELD] == "pii_provider"
    assert attributes["hap_provider_config"][OperatorConstants.Config.PROVIDER_FIELD] == "hap_provider"
    assert attributes["pii_provider_config"][OperatorConstants.Config.DEFAULT] == {}
    # No default for the capability providers, so the UI never stamps one that would shadow "provider"
    assert OperatorConstants.Config.DEFAULT not in attributes["pii_provider"]


def test_metadata_provider_schemas_list_capabilities():
    attributes = PIIAndHAPAnnotator.get_metadata()[OperatorConstants.Config.ATTRIBUTES]
    schemas = attributes["provider_config"][OperatorConstants.Config.PROVIDERS]
    assert schemas["presidio"]["capabilities"] == ["pii"]
    assert schemas["watsonx"]["capabilities"] == ["pii", "hap"]
    assert schemas["litellm"]["capabilities"] == ["pii", "hap"]
    assert {"language", "spacy_model", "entity_mapping"} <= set(
        schemas["presidio"][OperatorConstants.Config.PROPERTIES]
    )


# ---------------------------------------------------------------------------
# End-to-end: Presidio (PII only, analyzer mocked) + HAP-only provider
# ---------------------------------------------------------------------------


class _KeywordHAPAdapter(HAPDetectionPort):
    """HAP-only test adapter flagging the word 'idiot'."""

    ADAPTER_NAME = "keyword_hap"
    ADAPTER_DISPLAY_NAME = "Keyword HAP"
    SUPPORTS_PII = False
    SUPPORTS_HAP = True
    REQUIRES_MODEL_ID = False
    calls: ClassVar[list[tuple[str, float]]] = []

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        return BaseModel

    def validate(self) -> dict[str, Any]:
        return {"valid": True, "errors": [], "warnings": []}

    def detect_hap(self, *, text: str, threshold: float) -> PIIHAPDetectionResponse:
        _KeywordHAPAdapter.calls.append((text, threshold))
        start = text.find("idiot")
        detections = (
            [DetectionResult(detection="has_HAP", detection_type="hap", score=0.99, start=start, end=start + 5)]
            if start >= 0
            else []
        )
        return PIIHAPDetectionResponse(detections=detections, input_text=text)


def _presidio_analyzer() -> MagicMock:
    """Fake Presidio analyzer that reports e-mail addresses and an unmapped DATE_TIME."""

    def _analyze(*, text: str, language: str, score_threshold: float) -> list[SimpleNamespace]:
        results = []
        start = text.find("bob@example.com")
        if start >= 0:
            results.append(SimpleNamespace(entity_type="EMAIL_ADDRESS", start=start, end=start + 15, score=1.0))
        results.append(SimpleNamespace(entity_type="DATE_TIME", start=0, end=1, score=0.9))
        return results

    analyzer = MagicMock()
    analyzer.analyze.side_effect = _analyze
    return analyzer


@pytest.fixture
def keyword_hap_registered():
    original = dict(PIIAndHAPDetectionFactory._registry)
    PIIAndHAPDetectionFactory.register(_KeywordHAPAdapter)
    _KeywordHAPAdapter.calls = []
    yield
    PIIAndHAPDetectionFactory._registry.clear()
    PIIAndHAPDetectionFactory._registry.update(original)


def _input_table() -> pa.Table:
    return pa.Table.from_arrays(
        [
            pa.array(["1", "2"]),
            pa.array(["Mail bob@example.com please", "You idiot, stop it"]),
            pa.array(["doc1", "doc2"]),
        ],
        names=["id", "content", "name"],
    )


def test_end_to_end_presidio_pii_with_hap_only_provider(keyword_hap_registered):
    with patch(_BUILD_ANALYZER, return_value=_presidio_analyzer()):
        operator = PIIAndHAPAnnotator(
            {
                "pii_provider": "presidio",
                "hap_provider": "keyword_hap",
                "pii_list": ["EmailAddress"],
                "redaction": True,
                "hap_redaction": True,
                "hap_redaction_character": "#",
                "hap_threshold": 0.7,
            }
        )
        tables, metadata = operator.transform(_input_table())

    table = tables[0]
    assert metadata["processed_docs"] == 2
    assert table["pii_email_address"].to_pylist() == [1, 0]
    assert table["hap"].to_pylist() == [0, 1]
    assert table["content"].to_pylist() == ["Mail *************** please", "You #####, stop it"]
    assert {threshold for _, threshold in _KeywordHAPAdapter.calls} == {0.7}


def test_end_to_end_hap_adapter_not_called_when_only_pii_expected(keyword_hap_registered):
    with patch(_BUILD_ANALYZER, return_value=_presidio_analyzer()):
        operator = PIIAndHAPAnnotator(
            {"pii_provider": "presidio", "hap_provider": "keyword_hap", "expected_redactions": ["pii"]}
        )
        tables, _ = operator.transform(_input_table())

    assert _KeywordHAPAdapter.calls == []
    assert "hap" not in tables[0].column_names
    assert tables[0]["pii_email_address"].to_pylist() == [1, 0]
