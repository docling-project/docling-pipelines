# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for WatsonxPIIAndHAPAdapter."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory
from docpipe.core.constants.constants import ServiceConstants
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.watsonx.adapter import WatsonxPIIAndHAPAdapter
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.watsonx.config import (
    ADAPTER_NAME,
    WatsonxPIIAndHAPConfig,
)
from docpipe.core.operators.quality.pii_and_hap.domain.models import PIIHAPDetectionResponse
from docpipe.exceptions.docpipe_exceptions import DocpipeException

_MODEL_ID = "ibm/granite-guardian-3-8b"
_API_KEY = "test-watsonx-api-key"  # pragma: allowlist secret
_URL = "https://us-south.ml.cloud.ibm.com"
_PROJECT_ID = "3f2b8c1e-5d4a-4e7b-9a60-1c2d3e4f5a6b"

_FULL_CONFIG: dict[str, Any] = {
    "api_key": _API_KEY,
    "url": _URL,
    "container_kind": "project",
    "container_id": _PROJECT_ID,
}
_CONFIG_WITHOUT_CONTAINER_KIND: dict[str, Any] = {k: v for k, v in _FULL_CONFIG.items() if k != "container_kind"}


@pytest.fixture
def mock_text_detection_adapter() -> MagicMock:
    mock = MagicMock()
    mock.validate.return_value = {"valid": True, "errors": [], "warnings": []}
    mock.detect.return_value = {"success": True, "detections": []}
    return mock


def _build_adapter(
    *, provider_config: dict[str, Any], inner_adapter: MagicMock
) -> tuple[WatsonxPIIAndHAPAdapter, MagicMock]:
    """Build the adapter with the text-detection factory patched.

    Returns the adapter and the patched ``create_text_detection_adapter`` so tests can inspect the
    ``provider_config`` the adapter resolved and handed to the factory.
    """
    with patch.object(LLMAdapterFactory, "create_text_detection_adapter", return_value=inner_adapter) as factory:
        adapter = WatsonxPIIAndHAPAdapter(model_id=_MODEL_ID, provider_config=provider_config)
    return adapter, factory


@pytest.fixture
def adapter(mock_text_detection_adapter: MagicMock) -> WatsonxPIIAndHAPAdapter:
    built, _ = _build_adapter(provider_config=_FULL_CONFIG, inner_adapter=mock_text_detection_adapter)
    return built


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_adapter_name_constant_is_watsonx() -> None:
    assert ADAPTER_NAME == "watsonx"


def test_adapter_name_attribute_is_watsonx() -> None:
    assert WatsonxPIIAndHAPAdapter.ADAPTER_NAME == "watsonx"


def test_adapter_get_config_schema_returns_watsonx_config_model() -> None:
    assert WatsonxPIIAndHAPAdapter.get_config_schema() is WatsonxPIIAndHAPConfig


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


def test_validate_delegates_to_inner_adapter(
    adapter: WatsonxPIIAndHAPAdapter, mock_text_detection_adapter: MagicMock
) -> None:
    result = adapter.validate()

    assert result["valid"] is True
    mock_text_detection_adapter.validate.assert_called_once()


def test_validate_fails_when_all_credentials_missing(mock_text_detection_adapter: MagicMock) -> None:
    inst, _ = _build_adapter(provider_config={}, inner_adapter=mock_text_detection_adapter)

    result = inst.validate()

    assert result["valid"] is False
    assert any("missing required keys" in error for error in result["errors"])


def test_validate_fails_when_url_missing(mock_text_detection_adapter: MagicMock) -> None:
    config = {k: v for k, v in _FULL_CONFIG.items() if k != "url"}
    inst, _ = _build_adapter(provider_config=config, inner_adapter=mock_text_detection_adapter)

    result = inst.validate()

    assert result["valid"] is False
    assert any("url" in error for error in result["errors"])


def test_validate_succeeds_when_container_kind_omitted(mock_text_detection_adapter: MagicMock) -> None:
    inst, _ = _build_adapter(provider_config=_CONFIG_WITHOUT_CONTAINER_KIND, inner_adapter=mock_text_detection_adapter)

    assert inst.validate()["valid"] is True


def test_validate_fails_when_schema_rejects_values_without_raising_in_init(
    mock_text_detection_adapter: MagicMock,
) -> None:
    inst, _ = _build_adapter(
        provider_config={**_FULL_CONFIG, "timeout": "not-a-number"}, inner_adapter=mock_text_detection_adapter
    )

    result = inst.validate()

    assert result["valid"] is False
    assert any("is invalid for provider 'watsonx'" in error for error in result["errors"])


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------


def test_detect_returns_response_on_success(
    adapter: WatsonxPIIAndHAPAdapter, mock_text_detection_adapter: MagicMock
) -> None:
    mock_text_detection_adapter.detect.return_value = {
        "success": True,
        "detections": [
            {
                "detection": "EmailAddress",
                "detection_type": "pii",
                "score": 0.95,
                "start": 0,
                "end": 15,
                "text": "test@example.com",
            }
        ],
    }

    response = adapter.detect(payload={"input": "test@example.com", "detectors": {}})

    assert isinstance(response, PIIHAPDetectionResponse)
    assert [d.detection for d in response.detections] == ["EmailAddress"]


def test_detect_raises_docpipe_exception_on_api_error(
    adapter: WatsonxPIIAndHAPAdapter, mock_text_detection_adapter: MagicMock
) -> None:
    mock_text_detection_adapter.detect.return_value = {"success": False, "error": "API failure"}

    with pytest.raises(DocpipeException, match="Text detection failed: API failure"):
        adapter.detect(payload={"input": "some text", "detectors": {}})


def test_detect_empty_detections_returns_empty_response(
    adapter: WatsonxPIIAndHAPAdapter, mock_text_detection_adapter: MagicMock
) -> None:
    mock_text_detection_adapter.detect.return_value = {"success": True, "detections": []}

    response = adapter.detect(payload={"input": "clean text", "detectors": {}})

    assert response.detections == []
    assert response.input_text == "clean text"


# ---------------------------------------------------------------------------
# Capability-scoped detection (PIIDetectionPort / HAPDetectionPort)
# ---------------------------------------------------------------------------

_MIXED_DETECTIONS = {
    "success": True,
    "detections": [
        {"detection": "EmailAddress", "detection_type": "pii", "score": 0.9, "start": 0, "end": 16},
        {"detection": "has_HAP", "detection_type": "hap", "score": 0.9, "start": 17, "end": 30},
    ],
}


def test_adapter_declares_pii_and_hap_capabilities() -> None:
    assert (WatsonxPIIAndHAPAdapter.SUPPORTS_PII, WatsonxPIIAndHAPAdapter.SUPPORTS_HAP) == (True, True)


def test_detect_pii_sends_only_pii_detector(
    adapter: WatsonxPIIAndHAPAdapter, mock_text_detection_adapter: MagicMock
) -> None:
    mock_text_detection_adapter.detect.return_value = _MIXED_DETECTIONS

    adapter.detect_pii(text="some text", threshold=0.6)

    mock_text_detection_adapter.detect.assert_called_once_with(text="some text", detectors={"pii": {"threshold": 0.6}})


def test_detect_pii_returns_only_pii_detections(
    adapter: WatsonxPIIAndHAPAdapter, mock_text_detection_adapter: MagicMock
) -> None:
    mock_text_detection_adapter.detect.return_value = _MIXED_DETECTIONS

    response = adapter.detect_pii(text="some text", threshold=0.6)

    assert [d.detection for d in response.detections] == ["EmailAddress"]


def test_detect_hap_sends_only_hap_detector(
    adapter: WatsonxPIIAndHAPAdapter, mock_text_detection_adapter: MagicMock
) -> None:
    mock_text_detection_adapter.detect.return_value = _MIXED_DETECTIONS

    adapter.detect_hap(text="some text", threshold=0.7)

    mock_text_detection_adapter.detect.assert_called_once_with(text="some text", detectors={"hap": {"threshold": 0.7}})


def test_detect_hap_returns_only_hap_detections(
    adapter: WatsonxPIIAndHAPAdapter, mock_text_detection_adapter: MagicMock
) -> None:
    mock_text_detection_adapter.detect.return_value = _MIXED_DETECTIONS

    response = adapter.detect_hap(text="some text", threshold=0.7)

    assert [d.detection for d in response.detections] == ["has_HAP"]


# ---------------------------------------------------------------------------
# validate_provider_config()
# ---------------------------------------------------------------------------


def test_validate_provider_config_reports_missing_watsonx_keys() -> None:
    errors = WatsonxPIIAndHAPAdapter.validate_provider_config(
        provider_config={"model_id": _MODEL_ID, "api_key": _API_KEY},
        config_key="hap_provider_config",
    )

    assert errors == [
        "WatsonX provider requires api_key, url, container_id in hap_provider_config. Missing: url, container_id"
    ]


def test_validate_provider_config_accepts_config_without_container_kind() -> None:
    errors = WatsonxPIIAndHAPAdapter.validate_provider_config(
        provider_config={"model_id": _MODEL_ID, **_CONFIG_WITHOUT_CONTAINER_KIND},
        config_key="provider_config",
    )

    assert errors == []


@pytest.mark.parametrize(
    "invalid_override",
    [
        pytest.param({"container_kind": "catalog"}, id="unsupported-container-kind"),
        pytest.param({"timeout": "not-a-number"}, id="non-numeric-timeout"),
        pytest.param({"timeout": 0}, id="non-positive-timeout"),
    ],
)
def test_validate_provider_config_reports_schema_violation_for_invalid_values(
    invalid_override: dict[str, Any],
) -> None:
    errors = WatsonxPIIAndHAPAdapter.validate_provider_config(
        provider_config={"model_id": _MODEL_ID, **_FULL_CONFIG, **invalid_override},
        config_key="provider_config",
    )

    assert len(errors) == 1
    assert "provider_config is invalid for provider 'watsonx'" in errors[0]


# ---------------------------------------------------------------------------
# Config defaults: the schema is authoritative for what runs use
# ---------------------------------------------------------------------------


def test_config_timeout_default_equals_shared_watsonx_request_timeout() -> None:
    default = WatsonxPIIAndHAPConfig.model_fields["timeout"].default

    assert default == ServiceConstants.DEFAULT_WATSONX_REQUEST_TIMEOUT_SECONDS


def test_config_timeout_default_is_120_seconds() -> None:
    assert WatsonxPIIAndHAPConfig.model_fields["timeout"].default == 120


def test_init_passes_schema_default_timeout_to_factory_when_timeout_omitted(
    mock_text_detection_adapter: MagicMock,
) -> None:
    _, factory = _build_adapter(provider_config=_FULL_CONFIG, inner_adapter=mock_text_detection_adapter)

    passed = factory.call_args.kwargs["provider_config"]
    assert passed["timeout"] == WatsonxPIIAndHAPConfig.model_fields["timeout"].default


def test_init_passes_explicit_timeout_to_factory_unchanged(mock_text_detection_adapter: MagicMock) -> None:
    _, factory = _build_adapter(
        provider_config={**_FULL_CONFIG, "timeout": 45}, inner_adapter=mock_text_detection_adapter
    )

    assert factory.call_args.kwargs["provider_config"]["timeout"] == 45


def test_init_passes_project_container_kind_to_factory_when_container_kind_omitted(
    mock_text_detection_adapter: MagicMock,
) -> None:
    _, factory = _build_adapter(
        provider_config=_CONFIG_WITHOUT_CONTAINER_KIND, inner_adapter=mock_text_detection_adapter
    )

    assert factory.call_args.kwargs["provider_config"]["container_kind"] == "project"


def test_init_passes_explicit_space_container_kind_to_factory_unchanged(
    mock_text_detection_adapter: MagicMock,
) -> None:
    _, factory = _build_adapter(
        provider_config={**_FULL_CONFIG, "container_kind": "space"}, inner_adapter=mock_text_detection_adapter
    )

    assert factory.call_args.kwargs["provider_config"]["container_kind"] == "space"


@pytest.mark.parametrize(
    ("alias_key", "alias_value"),
    [
        pytest.param("project_id", _PROJECT_ID, id="project_id-alias"),
        pytest.param("api_base", _URL, id="api_base-alias"),
    ],
)
def test_init_preserves_factory_alias_keys_not_modelled_by_schema(
    mock_text_detection_adapter: MagicMock, alias_key: str, alias_value: str
) -> None:
    _, factory = _build_adapter(
        provider_config={"api_key": _API_KEY, alias_key: alias_value}, inner_adapter=mock_text_detection_adapter
    )

    assert factory.call_args.kwargs["provider_config"][alias_key] == alias_value
