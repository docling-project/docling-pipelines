# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for capability-aware registration, validation and creation in PIIAndHAPDetectionFactory."""

from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel

import docpipe.core.operators.quality.pii_and_hap.adapters.outbound  # noqa: F401  (registers built-ins)
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.factories.pii_and_hap_detection_factory import (
    PIIAndHAPDetectionFactory,
)
from docpipe.core.operators.quality.pii_and_hap.domain.models import (
    DetectionCapability,
    PIIHAPDetectionResponse,
    ProviderSelection,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.hap_detection_port import HAPDetectionPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_and_hap_detection_port import (
    PIIAndHAPDetectionPort,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_detection_port import PIIDetectionPort

# ---------------------------------------------------------------------------
# Test adapters
# ---------------------------------------------------------------------------


class _BaseTestAdapter:
    """Mixin with the boilerplate every test adapter needs."""

    def __init__(self, *, model_id: str, provider_config: dict[str, Any]) -> None:
        self.model_id = model_id
        self.provider_config = provider_config

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        return BaseModel

    def validate(self) -> dict[str, Any]:
        return {"valid": True, "errors": [], "warnings": []}


class _PIIOnlyAdapter(_BaseTestAdapter, PIIDetectionPort):
    ADAPTER_NAME = "piionly"
    ADAPTER_DISPLAY_NAME = "PII only"
    SUPPORTS_PII = True
    SUPPORTS_HAP = False

    def detect_pii(self, *, text: str, threshold: float) -> PIIHAPDetectionResponse:
        return PIIHAPDetectionResponse(detections=[], input_text=text)


class _HAPOnlyAdapter(_BaseTestAdapter, HAPDetectionPort):
    ADAPTER_NAME = "haponly"
    ADAPTER_DISPLAY_NAME = "HAP only"
    SUPPORTS_PII = False
    SUPPORTS_HAP = True

    def detect_hap(self, *, text: str, threshold: float) -> PIIHAPDetectionResponse:
        return PIIHAPDetectionResponse(detections=[], input_text=text)


class _DualAdapter(_BaseTestAdapter, PIIAndHAPDetectionPort):
    ADAPTER_NAME = "dual"
    ADAPTER_DISPLAY_NAME = "Dual"
    SUPPORTS_PII = True
    SUPPORTS_HAP = True

    def detect(self, *, payload: dict[str, Any]) -> PIIHAPDetectionResponse:
        return PIIHAPDetectionResponse(detections=[], input_text=payload["input"])


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Register the test adapters for one test and restore the registry afterwards."""
    original = dict(PIIAndHAPDetectionFactory._registry)
    for adapter_class in (_PIIOnlyAdapter, _HAPOnlyAdapter, _DualAdapter):
        PIIAndHAPDetectionFactory.register(adapter_class)
    yield
    PIIAndHAPDetectionFactory._registry.clear()
    PIIAndHAPDetectionFactory._registry.update(original)


# ---------------------------------------------------------------------------
# register() capability checks
# ---------------------------------------------------------------------------


def test_single_capability_adapters_register_with_their_capability():
    assert PIIAndHAPDetectionFactory.get_adapter_class("piionly").get_capabilities() == ["pii"]
    assert PIIAndHAPDetectionFactory.get_adapter_class("haponly").get_capabilities() == ["hap"]
    assert PIIAndHAPDetectionFactory.get_adapter_class("dual").get_capabilities() == ["pii", "hap"]


def test_register_rejects_flag_without_port():
    class _Liar(_PIIOnlyAdapter):
        ADAPTER_NAME = "liar"
        SUPPORTS_HAP = True

    with pytest.raises(ValueError, match="SUPPORTS_HAP is True but the class does not implement HAPDetectionPort"):
        PIIAndHAPDetectionFactory.register(_Liar)


def test_register_rejects_port_without_flag():
    class _Undeclared(_HAPOnlyAdapter):
        ADAPTER_NAME = "undeclared"
        SUPPORTS_HAP = False

    with pytest.raises(ValueError, match="implements HAPDetectionPort but does not declare SUPPORTS_HAP = True"):
        PIIAndHAPDetectionFactory.register(_Undeclared)


# ---------------------------------------------------------------------------
# Capability lookups
# ---------------------------------------------------------------------------


def test_list_adapters_filters_by_capability():
    pii_providers = PIIAndHAPDetectionFactory.list_adapters(capability=DetectionCapability.PII)
    hap_providers = PIIAndHAPDetectionFactory.list_adapters(capability=DetectionCapability.HAP)
    assert {"piionly", "dual"} <= set(pii_providers)
    assert "haponly" not in pii_providers
    assert {"haponly", "dual"} <= set(hap_providers)
    assert "piionly" not in hap_providers


def test_builtin_adapter_capabilities():
    assert PIIAndHAPDetectionFactory.supports("watsonx", capability=DetectionCapability.PII)
    assert PIIAndHAPDetectionFactory.supports("watsonx", capability=DetectionCapability.HAP)
    assert PIIAndHAPDetectionFactory.supports("litellm", capability=DetectionCapability.PII)
    assert PIIAndHAPDetectionFactory.supports("litellm", capability=DetectionCapability.HAP)
    assert PIIAndHAPDetectionFactory.supports("presidio", capability=DetectionCapability.PII)
    assert not PIIAndHAPDetectionFactory.supports("presidio", capability=DetectionCapability.HAP)
    assert not PIIAndHAPDetectionFactory.supports("unknown", capability=DetectionCapability.PII)


# ---------------------------------------------------------------------------
# validate_selection()
# ---------------------------------------------------------------------------


def test_validate_selection_rejects_pii_only_provider_for_hap():
    errors = PIIAndHAPDetectionFactory.validate_selection(
        capability=DetectionCapability.HAP,
        selection=ProviderSelection(provider="piionly", provider_key="hap_provider"),
    )
    assert len(errors) == 1
    assert "Provider 'piionly' (set via 'hap_provider') does not support HAP detection" in errors[0]
    assert "dual" in errors[0]  # lists the providers that do support HAP


def test_validate_selection_accepts_supported_provider():
    selection = ProviderSelection(provider="PIIONLY")
    assert PIIAndHAPDetectionFactory.validate_selection(capability=DetectionCapability.PII, selection=selection) == []


def test_validate_selection_unknown_provider():
    errors = PIIAndHAPDetectionFactory.validate_selection(
        capability=DetectionCapability.PII, selection=ProviderSelection(provider="nope")
    )
    assert len(errors) == 1
    assert "Unknown PII/HAP detection provider: 'nope'" in errors[0]


# ---------------------------------------------------------------------------
# create() / create_adapters()
# ---------------------------------------------------------------------------


def test_create_with_unsupported_capability_raises():
    with pytest.raises(ValueError, match="does not support PII detection"):
        PIIAndHAPDetectionFactory.create("haponly", model_id="", provider_config={}, capability=DetectionCapability.PII)


def test_create_adapters_shares_instance_for_identical_selection():
    selection = ProviderSelection(provider="dual", provider_config={"model_id": "m"})
    pii_adapter, hap_adapter = PIIAndHAPDetectionFactory.create_adapters(pii=selection, hap=selection)
    assert pii_adapter is hap_adapter
    assert isinstance(pii_adapter, _DualAdapter)
    assert pii_adapter.model_id == "m"


def test_create_adapters_builds_separate_instances_for_different_configs():
    pii_adapter, hap_adapter = PIIAndHAPDetectionFactory.create_adapters(
        pii=ProviderSelection(provider="dual", provider_config={"model_id": "a"}),
        hap=ProviderSelection(provider="dual", provider_config={"model_id": "b"}),
    )
    assert pii_adapter is not hap_adapter


def test_create_adapters_mixes_single_capability_providers():
    pii_adapter, hap_adapter = PIIAndHAPDetectionFactory.create_adapters(
        pii=ProviderSelection(provider="piionly"),
        hap=ProviderSelection(provider="haponly"),
    )
    assert isinstance(pii_adapter, _PIIOnlyAdapter)
    assert isinstance(hap_adapter, _HAPOnlyAdapter)


def test_create_adapters_skips_capability_not_needed():
    pii_adapter, hap_adapter = PIIAndHAPDetectionFactory.create_adapters(
        pii=ProviderSelection(provider="piionly"), hap=None
    )
    assert isinstance(pii_adapter, _PIIOnlyAdapter)
    assert hap_adapter is None


def test_create_adapters_fails_fast_before_building_anything():
    with (
        patch.object(PIIAndHAPDetectionFactory, "create") as mock_create,
        pytest.raises(ValueError, match="does not support HAP detection"),
    ):
        PIIAndHAPDetectionFactory.create_adapters(
            pii=ProviderSelection(provider="piionly"),
            hap=ProviderSelection(provider="piionly", provider_key="hap_provider"),
        )
    mock_create.assert_not_called()
