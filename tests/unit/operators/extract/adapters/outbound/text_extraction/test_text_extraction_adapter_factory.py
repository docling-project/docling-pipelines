"""Tests for text extraction adapter configuration."""

from docling.datamodel.pipeline_options import VlmConvertOptions

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.extract.adapters.outbound.factories.text_extraction_adapter_factory import (
    TextExtractionAdapterFactory,
)
from docpipe.core.operators.extract.domain.models import TextExtractionMode


def _build_config(provider_config: dict[str, object] | None = None) -> dict[str, object]:
    text_extraction_config = {}
    if provider_config is not None:
        text_extraction_config[OperatorConstants.Config.PROVIDER_CONFIG] = provider_config
    return TextExtractionAdapterFactory.build_adapter_config(
        mode=TextExtractionMode.DOCLING_LIBRARY,
        text_extraction_config=text_extraction_config,
    )


def test_pipeline_blocks_omitted() -> None:
    result = _build_config()

    assert result[OperatorConstants.Config.USE_VLM_PIPELINE] is False
    assert result[OperatorConstants.Config.USE_ASR_PIPELINE] is False


def test_empty_pipeline_blocks_enable_defaults() -> None:
    result = _build_config(
        {
            OperatorConstants.Config.VLM_PIPELINE: {},
            OperatorConstants.Config.ASR_PIPELINE: {},
        }
    )

    assert result[OperatorConstants.Config.USE_VLM_PIPELINE] is True
    preset = result[OperatorConstants.Config.VLM_PRESET]
    assert preset == OperatorConstants.Config.VLM_PRESET_DEFAULT
    assert isinstance(preset, str)
    VlmConvertOptions.from_preset(preset)
    assert result[OperatorConstants.Config.VLM_ENGINE_TYPE] == OperatorConstants.Config.VLM_ENGINE_TRANSFORMERS
    assert result[OperatorConstants.Config.VLM_PROVIDER_CONFIG] is None
    assert result[OperatorConstants.Config.USE_ASR_PIPELINE] is True
    assert result[OperatorConstants.Config.ASR_MODEL_NAME] == OperatorConstants.Config.ASR_MODEL_DEFAULT


def test_null_pipeline_blocks_are_disabled() -> None:
    result = _build_config(
        {
            OperatorConstants.Config.VLM_PIPELINE: None,
            OperatorConstants.Config.ASR_PIPELINE: None,
        }
    )

    assert result[OperatorConstants.Config.USE_VLM_PIPELINE] is False
    assert result[OperatorConstants.Config.USE_ASR_PIPELINE] is False


def test_populated_pipeline_blocks_preserve_values() -> None:
    engine_options = {"api_base": "https://example.com", "model_id": "example-model"}
    result = _build_config(
        {
            OperatorConstants.Config.VLM_PIPELINE: {
                OperatorConstants.Config.PRESET: "custom",
                OperatorConstants.Config.ENGINE: "api_openai",
                OperatorConstants.Config.ENGINE_OPTIONS: engine_options,
            },
            OperatorConstants.Config.ASR_PIPELINE: {
                OperatorConstants.Config.MODEL_ID: "whisper_small",
            },
        }
    )

    assert result[OperatorConstants.Config.USE_VLM_PIPELINE] is True
    assert result[OperatorConstants.Config.VLM_PRESET] == "custom"
    assert result[OperatorConstants.Config.VLM_ENGINE_TYPE] == "api_openai"
    assert result[OperatorConstants.Config.VLM_PROVIDER_CONFIG] == engine_options
    assert result[OperatorConstants.Config.USE_ASR_PIPELINE] is True
    assert result[OperatorConstants.Config.ASR_MODEL_NAME] == "whisper_small"
