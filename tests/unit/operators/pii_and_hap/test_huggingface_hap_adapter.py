# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for HuggingFaceHAPConfig and HuggingFaceHAPAdapter (core adapter mocked; no model loaded)."""

import typing
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from docpipe.core.constants.constants import ServiceConstants
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.factories.pii_and_hap_detection_factory import (
    PIIAndHAPDetectionFactory,
)
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.huggingface import adapter as adapter_module
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.huggingface.adapter import HuggingFaceHAPAdapter
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.huggingface.config import HuggingFaceHAPConfig
from docpipe.core.operators.quality.pii_and_hap.domain.models import DetectionCapability, DetectionResult
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.hap_detection_port import HAPDetectionPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_detection_port import PIIDetectionPort
from docpipe.exceptions.docpipe_exceptions import DocpipeException

_DEFAULT_MODEL = ServiceConstants.DEFAULT_HUGGINGFACE_HAP_MODEL_ID
_DEFAULT_REVISION = ServiceConstants.DEFAULT_HUGGINGFACE_HAP_REVISION
_OTHER_MODEL = "unitary/unbiased-toxic-roberta"
_ACCEPTED_KEYS = [
    "activation",
    "batch_size",
    "device",
    "local_files_only",
    "max_length",
    "model_id",
    "revision",
    "toxic_labels",
]


@pytest.fixture
def core_adapter() -> Generator[MagicMock, None, None]:
    """Patch the factory so the adapter gets a mock core TextDetectionPort."""
    core = MagicMock()
    core.validate_detection.return_value = {"valid": True, "context": "detection", "errors": [], "warnings": []}
    with patch.object(
        adapter_module.LLMAdapterFactory, "create_text_detection_adapter", return_value=core
    ) as create_adapter:
        core.create_adapter = create_adapter
        yield core


# ---------------------------------------------------------------------- HuggingFaceHAPConfig


class TestHuggingFaceHAPConfig:
    """Default resolution and validation of hap_provider_config."""

    def test_empty_config_resolves_default_model_revision_and_labels(self) -> None:
        """An empty config yields the default model at the pinned revision with its toxic label."""
        assert HuggingFaceHAPConfig.model_validate({}).model_dump() == {
            "model_id": _DEFAULT_MODEL,
            "revision": _DEFAULT_REVISION,
            "toxic_labels": ["LABEL_1"],
            "activation": "auto",
            "max_length": 512,
            "batch_size": 32,
            "device": None,
            "local_files_only": False,
        }

    @pytest.mark.parametrize("model_id", ["", "   ", None])
    def test_blank_model_id_means_default_model(self, model_id: str | None) -> None:
        """An empty, blank or null model_id selects the default model and its defaults."""
        config = HuggingFaceHAPConfig.model_validate({"model_id": model_id})

        assert config.model_id == _DEFAULT_MODEL
        assert config.revision == _DEFAULT_REVISION

    def test_explicit_revision_and_labels_override_default_model_defaults(self) -> None:
        """Explicit values win over the default model's pinned revision and labels."""
        config = HuggingFaceHAPConfig.model_validate({"revision": "main", "toxic_labels": ["LABEL_0", "LABEL_1"]})

        assert config.revision == "main"
        assert config.toxic_labels == ["LABEL_0", "LABEL_1"]

    def test_non_default_model_keeps_labels_and_gets_no_pinned_revision(self) -> None:
        """Another model uses its own labels and the Hub's default branch unless a revision is set."""
        config = HuggingFaceHAPConfig.model_validate({"model_id": _OTHER_MODEL, "toxic_labels": ["toxicity"]})

        assert config.revision is None
        assert config.toxic_labels == ["toxicity"]

    @pytest.mark.parametrize("toxic_labels", [None, []])
    def test_non_default_model_without_toxic_labels_fails_with_id2label_hint(self, toxic_labels: Any) -> None:
        """A non-default model must name its toxic labels; the error points to id2label."""
        with pytest.raises(ValidationError) as error:
            HuggingFaceHAPConfig.model_validate({"model_id": _OTHER_MODEL, "toxic_labels": toxic_labels})

        message = str(error.value)
        assert f"toxic_labels is required for model '{_OTHER_MODEL}'" in message
        assert "config.json id2label on Hugging Face" in message

    @pytest.mark.parametrize(
        ("config", "field"),
        [
            ({"batch_size": 0}, "batch_size"),
            ({"max_length": -1}, "max_length"),
            ({"batch_size": True}, "batch_size"),
            ({"batch_size": "8"}, "batch_size"),
            ({"activation": "relu"}, "activation"),
            ({"device": "tpu"}, "device"),
            ({"local_files_only": "maybe"}, "local_files_only"),
        ],
    )
    def test_invalid_option_value_fails_naming_the_field(self, config: dict[str, Any], field: str) -> None:
        """Wrong types, non-positive sizes and unknown enum values fail validation for that field."""
        with pytest.raises(ValidationError) as error:
            HuggingFaceHAPConfig.model_validate(config)

        assert [item["loc"][0] for item in error.value.errors()] == [field]

    def test_unknown_key_is_rejected(self) -> None:
        """A misspelled key is not ignored."""
        with pytest.raises(ValidationError) as error:
            HuggingFaceHAPConfig.model_validate({"local_file_only": True})

        assert [(item["type"], item["loc"]) for item in error.value.errors()] == [
            ("extra_forbidden", ("local_file_only",))
        ]

    def test_literal_values_match_shared_constants(self) -> None:
        """The Literal types in the schema match the values the client accepts."""
        fields = HuggingFaceHAPConfig.model_fields
        activation_values = typing.get_args(fields["activation"].annotation)
        device_values = tuple(
            value for option in typing.get_args(fields["device"].annotation) for value in typing.get_args(option)
        )

        assert activation_values == ServiceConstants.HUGGINGFACE_ACTIVATIONS
        assert device_values == ServiceConstants.HUGGINGFACE_DEVICES


# ---------------------------------------------------------------------- HuggingFaceHAPAdapter


class TestHuggingFaceHAPAdapter:
    """Capability, construction, validation and result mapping of the operator adapter."""

    def test_adapter_is_registered_for_hap_only(self) -> None:
        """The adapter implements HAPDetectionPort only and registers under 'huggingface'."""
        assert issubclass(HuggingFaceHAPAdapter, HAPDetectionPort)
        assert not issubclass(HuggingFaceHAPAdapter, PIIDetectionPort)
        assert HuggingFaceHAPAdapter.get_capabilities() == ["hap"]
        assert HuggingFaceHAPAdapter.REQUIRES_MODEL_ID is False
        assert PIIAndHAPDetectionFactory.get_adapter_class("huggingface") is HuggingFaceHAPAdapter
        assert "huggingface" in PIIAndHAPDetectionFactory.list_adapters(capability=DetectionCapability.HAP)
        assert "huggingface" not in PIIAndHAPDetectionFactory.list_adapters(capability=DetectionCapability.PII)

    def test_get_config_schema_returns_config_model(self) -> None:
        """Operator metadata publishes HuggingFaceHAPConfig for this provider."""
        assert HuggingFaceHAPAdapter.get_config_schema() is HuggingFaceHAPConfig

    def test_empty_config_builds_core_adapter_with_resolved_defaults(self, core_adapter: MagicMock) -> None:
        """The factory receives the default model and the resolved defaults, not an empty config."""
        HuggingFaceHAPAdapter(model_id="", provider_config={})

        core_adapter.create_adapter.assert_called_once_with(
            provider="huggingface",
            model_id=_DEFAULT_MODEL,
            provider_config=HuggingFaceHAPConfig.model_validate({}).model_dump(),
        )

    def test_validate_runs_detection_validation_of_core_adapter(self, core_adapter: MagicMock) -> None:
        """validate() calls validate_detection(), not the embedding-resolving validate()."""
        result = HuggingFaceHAPAdapter(model_id="", provider_config={}).validate()

        assert result["valid"] is True
        core_adapter.validate_detection.assert_called_once_with()
        core_adapter.validate.assert_not_called()

    def test_invalid_config_fails_validation_without_building_core_adapter(self, core_adapter: MagicMock) -> None:
        """Config errors are reported by validate() and no core adapter or model is created."""
        adapter = HuggingFaceHAPAdapter(model_id="", provider_config={"model_id": _OTHER_MODEL})

        result = adapter.validate()

        assert result["valid"] is False
        assert "toxic_labels is required" in result["errors"][0]
        core_adapter.create_adapter.assert_not_called()
        with pytest.raises(DocpipeException, match="toxic_labels is required"):
            adapter.detect_hap(text="Some text.", threshold=0.8)

    def test_validate_provider_config_accepts_valid_config(self) -> None:
        """A valid config yields no errors."""
        assert (
            HuggingFaceHAPAdapter.validate_provider_config(provider_config={}, config_key="hap_provider_config") == []
        )

    def test_validate_provider_config_leaves_unknown_keys_to_metadata_check(self) -> None:
        """Unknown keys are reported once, by validate_config_from_metadata, not again here."""
        assert (
            HuggingFaceHAPAdapter.validate_provider_config(
                provider_config={"local_file_only": True}, config_key="hap_provider_config"
            )
            == []
        )

    def test_constructor_reports_unknown_keys_when_flow_validation_was_skipped(self, core_adapter: MagicMock) -> None:
        """At run time, validate() still names unknown keys and the accepted ones."""
        adapter = HuggingFaceHAPAdapter(model_id="", provider_config={"local_file_only": True, "batch_size": 0})

        assert adapter.validate()["errors"] == [
            "Provider config for 'huggingface' is invalid: "
            f"unknown key(s) ['local_file_only']; accepted keys: {_ACCEPTED_KEYS}; "
            "batch_size: Input should be greater than or equal to 1"
        ]
        core_adapter.create_adapter.assert_not_called()

    def test_validate_provider_config_reports_value_errors(self) -> None:
        """Value errors name the key."""
        (error,) = HuggingFaceHAPAdapter.validate_provider_config(
            provider_config={"batch_size": 0}, config_key="hap_provider_config"
        )

        assert error.startswith("hap_provider_config is invalid for provider 'huggingface': batch_size:")

    def test_detect_hap_forwards_threshold_and_maps_detections(self, core_adapter: MagicMock) -> None:
        """detect_hap passes the threshold as detectors and maps detection dicts to DetectionResult."""
        text = "Thanks.\nYou are a worthless idiot."
        core_adapter.detect.return_value = {
            "success": True,
            "detections": [
                {
                    "detection": "has_HAP",
                    "detection_type": "hap",
                    "score": 0.97,
                    "start": 8,
                    "end": 34,
                    "text": "You are a worthless idiot.",
                    "evidences": [{"source": "huggingface", "model_id": _DEFAULT_MODEL, "label": "LABEL_1"}],
                }
            ],
            "error": None,
        }

        response = HuggingFaceHAPAdapter(model_id="", provider_config={}).detect_hap(text=text, threshold=0.6)

        core_adapter.detect.assert_called_once_with(text=text, detectors={"hap": {"threshold": 0.6}})
        assert response.input_text == text
        assert response.detections == [
            DetectionResult(
                detection="has_HAP",
                detection_type="hap",
                score=0.97,
                start=8,
                end=34,
                text="You are a worthless idiot.",
                evidences=[{"source": "huggingface", "model_id": _DEFAULT_MODEL, "label": "LABEL_1"}],
            )
        ]

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            ("ValueError while scoring with model 'm'", "Hugging Face HAP detection failed: ValueError while scoring"),
            (None, "Hugging Face HAP detection failed: Unknown error"),
        ],
    )
    def test_detect_hap_raises_on_scoring_failure(
        self, core_adapter: MagicMock, error: str | None, expected: str
    ) -> None:
        """A success False result becomes a DocpipeException so the annotator records the document as failed."""
        core_adapter.detect.return_value = {"success": False, "detections": [], "error": error}

        with pytest.raises(DocpipeException, match=expected):
            HuggingFaceHAPAdapter(model_id="", provider_config={}).detect_hap(text="Some text.", threshold=0.8)
