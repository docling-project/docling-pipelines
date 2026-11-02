# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for PIIAndHAPDetectionFactory — registration, creation, error handling."""

from unittest.mock import MagicMock

import pytest

from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.factories.pii_and_hap_detection_factory import (
    PIIAndHAPDetectionFactory,
    register_pii_and_hap_detection_adapter,
)
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_and_hap_detection_port import (
    PIIAndHAPDetectionPort,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter_class(name: str) -> type[PIIAndHAPDetectionPort]:
    """Return a minimal concrete adapter class with the given ADAPTER_NAME."""

    class _Adapter(PIIAndHAPDetectionPort):
        ADAPTER_NAME = name
        ADAPTER_DISPLAY_NAME = name.title()

        def __init__(self, *, model_id: str, provider_config: dict) -> None:
            self.model_id = model_id
            self.provider_config = provider_config

        @staticmethod
        def get_config_schema():  # type: ignore[override]
            from pydantic import BaseModel

            return BaseModel

        def detect(self, *, payload):  # type: ignore[override]
            return MagicMock()

        def validate(self):
            return {"valid": True, "errors": [], "warnings": []}

    _Adapter.__name__ = f"_{name.title()}Adapter"
    return _Adapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshot the factory registry before each test and restore it after."""
    original = dict(PIIAndHAPDetectionFactory._registry)
    yield
    PIIAndHAPDetectionFactory._registry.clear()
    PIIAndHAPDetectionFactory._registry.update(original)


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


def test_register_stores_adapter():
    cls = _make_adapter_class("testprovider")
    PIIAndHAPDetectionFactory.register(cls)
    assert "testprovider" in PIIAndHAPDetectionFactory._registry


def test_register_normalises_name_to_lowercase():
    cls = _make_adapter_class("UPPERCASE")
    PIIAndHAPDetectionFactory.register(cls)
    assert "uppercase" in PIIAndHAPDetectionFactory._registry


def test_register_raises_when_adapter_name_missing():
    class _Bad(PIIAndHAPDetectionPort):
        def detect(self, *, payload):  # type: ignore[override]
            ...

        def validate(self): ...

    with pytest.raises(ValueError, match="must define ADAPTER_NAME"):
        PIIAndHAPDetectionFactory.register(_Bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# @register_pii_and_hap_detection_adapter decorator
# ---------------------------------------------------------------------------


def test_decorator_registers_adapter():
    @register_pii_and_hap_detection_adapter
    class _Dec(PIIAndHAPDetectionPort):
        ADAPTER_NAME = "decorated"
        ADAPTER_DISPLAY_NAME = "Decorated"

        def __init__(self, *, model_id, provider_config):
            pass

        def detect(self, *, payload):  # type: ignore[override]
            return MagicMock()

        def validate(self):
            return {"valid": True, "errors": [], "warnings": []}

    assert "decorated" in PIIAndHAPDetectionFactory._registry


def test_decorator_returns_class_unchanged():
    @register_pii_and_hap_detection_adapter
    class _R(PIIAndHAPDetectionPort):
        ADAPTER_NAME = "returncheck"
        ADAPTER_DISPLAY_NAME = "R"

        def __init__(self, *, model_id, provider_config):
            pass

        def detect(self, *, payload):  # type: ignore[override]
            return MagicMock()

        def validate(self):
            return {"valid": True, "errors": [], "warnings": []}

    assert _R.ADAPTER_NAME == "returncheck"


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------


def test_create_returns_adapter_instance():
    PIIAndHAPDetectionFactory.register(_make_adapter_class("myprovider"))
    adapter = PIIAndHAPDetectionFactory.create("myprovider", model_id="m", provider_config={})
    assert isinstance(adapter, PIIAndHAPDetectionPort)


def test_create_passes_model_id_and_config():
    PIIAndHAPDetectionFactory.register(_make_adapter_class("cfgprovider"))
    adapter = PIIAndHAPDetectionFactory.create(
        "cfgprovider",
        model_id="my-model",
        provider_config={"api_key": "k"},  # pragma: allowlist secret
    )
    assert adapter.model_id == "my-model"
    assert adapter.provider_config == {"api_key": "k"}  # pragma: allowlist secret


def test_create_is_case_insensitive():
    PIIAndHAPDetectionFactory.register(_make_adapter_class("caseprovider"))
    adapter = PIIAndHAPDetectionFactory.create("CASEProvider", model_id="m", provider_config={})
    assert isinstance(adapter, PIIAndHAPDetectionPort)


def test_create_unknown_provider_raises_value_error():
    with pytest.raises(ValueError, match="Unknown PII/HAP detection provider: 'unknown'"):
        PIIAndHAPDetectionFactory.create("unknown", model_id="m", provider_config={})


def test_create_error_message_lists_registered_providers():
    PIIAndHAPDetectionFactory.register(_make_adapter_class("listed"))
    with pytest.raises(ValueError, match="listed"):
        PIIAndHAPDetectionFactory.create("notfound", model_id="m", provider_config={})


# ---------------------------------------------------------------------------
# list_adapters()
# ---------------------------------------------------------------------------


def test_list_adapters_returns_sorted_names():
    PIIAndHAPDetectionFactory.register(_make_adapter_class("zzz"))
    PIIAndHAPDetectionFactory.register(_make_adapter_class("aaa"))
    names = PIIAndHAPDetectionFactory.list_adapters()
    assert names == sorted(names)
    assert "aaa" in names
    assert "zzz" in names


# ---------------------------------------------------------------------------
# Both built-in adapters are registered after importing the outbound package
# ---------------------------------------------------------------------------


def test_both_builtin_adapters_are_registered():
    import docpipe.core.operators.quality.pii_and_hap.adapters.outbound  # noqa: F401

    assert "watsonx" in PIIAndHAPDetectionFactory._registry
    assert "litellm" in PIIAndHAPDetectionFactory._registry
