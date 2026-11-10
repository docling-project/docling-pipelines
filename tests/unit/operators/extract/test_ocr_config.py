"""Unit tests for OCR configuration — OcrConfig model, factory validation, and adapter wiring."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.extract.adapters.outbound.factories.text_extraction_adapter_factory import (
    TextExtractionAdapterFactory,
)
from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter import DoclingAdapter
from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter import DoclingServeAdapter
from docpipe.core.operators.extract.adapters.outbound.text_extraction.ocr_config import OcrConfig
from docpipe.core.operators.extract.domain.models import TextExtractionMode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lib_adapter(ocr_block: dict[str, Any] | None = None) -> DoclingAdapter:
    """Instantiate DoclingAdapter with a minimal config, patching GPU converter build."""
    cfg: dict[str, Any] = {
        "doc_column": "content",
        "additional_formats": [],
        "common_log_arguments": {},
    }
    if ocr_block is not None:
        cfg[OperatorConstants.Config.OCR_BLOCK] = ocr_block
    with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
        return DoclingAdapter(config=cfg)


def _make_serve_adapter(docling_serve_config: dict[str, Any]) -> DoclingServeAdapter:
    cfg: dict[str, Any] = {
        "docling_serve_config": docling_serve_config,
        "doc_column": "content",
        "additional_formats": [],
        "common_log_arguments": {},
    }
    return DoclingServeAdapter(config=cfg)


# ---------------------------------------------------------------------------
# OcrConfig model
# ---------------------------------------------------------------------------


def test_ocr_config_defaults() -> None:
    cfg = OcrConfig()
    assert cfg.enabled is True
    assert cfg.engine == "rapidocr"
    assert cfg.mode == "default"
    assert cfg.engine_options is None


def test_ocr_config_all_fields() -> None:
    cfg = OcrConfig(
        enabled=False,
        engine="easyocr",
        mode="pdf_aware_layout_regions",
        engine_options={"lang": ["en", "fr"], "use_gpu": True},
    )
    assert cfg.enabled is False
    assert cfg.engine == "easyocr"
    assert cfg.mode == "pdf_aware_layout_regions"
    assert cfg.engine_options == {"lang": ["en", "fr"], "use_gpu": True}


def test_ocr_config_extra_keys_ignored() -> None:
    # model_config = extra="ignore" — unknown keys must not raise
    cfg = OcrConfig.model_validate({"engine": "tesseract", "unknown_key": "value"})
    assert cfg.engine == "tesseract"


# ---------------------------------------------------------------------------
# TextExtractionAdapterFactory._validate_ocr_config
# ---------------------------------------------------------------------------


def test_validate_ocr_config_valid() -> None:
    # Must not raise
    TextExtractionAdapterFactory._validate_ocr_config(
        {"engine": "easyocr", "mode": "layout_regions", "engine_options": {"lang": ["en"]}}
    )


def test_validate_ocr_config_invalid_engine() -> None:
    with pytest.raises(ValueError, match="Invalid OCR engine 'magic_ocr'"):
        TextExtractionAdapterFactory._validate_ocr_config({"engine": "magic_ocr"})


def test_validate_ocr_config_invalid_mode() -> None:
    with pytest.raises(ValueError, match="Invalid OCR mode 'turbo_mode'"):
        TextExtractionAdapterFactory._validate_ocr_config({"mode": "turbo_mode"})


def test_validate_ocr_config_engine_options_not_dict() -> None:
    with pytest.raises(ValueError, match=r"ocr\.engine_options must be a JSON object"):
        TextExtractionAdapterFactory._validate_ocr_config({"engine_options": "en"})


def test_validate_ocr_config_default_engine_is_rapidocr() -> None:
    # Omitting 'engine' must default to 'rapidocr', not 'auto' or any other value.
    # This test will fail if the factory default drifts from OcrConfig.engine default.
    TextExtractionAdapterFactory._validate_ocr_config({})


# ---------------------------------------------------------------------------
# Factory: build_adapter_config — docling_library path
# ---------------------------------------------------------------------------


def _lib_extraction_config(ocr: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "doc_column": "content",
        "provider_config": {},
    }
    if ocr is not None:
        cfg["provider_config"]["ocr"] = ocr
    return cfg


def test_build_adapter_config_ocr_block_docling_library() -> None:
    ocr = {"engine": "tesseract", "mode": "full_page"}
    result = TextExtractionAdapterFactory.build_adapter_config(
        mode=TextExtractionMode.DOCLING_LIBRARY,
        text_extraction_config=_lib_extraction_config(ocr=ocr),
    )
    assert result[OperatorConstants.Config.OCR_BLOCK] == ocr


def test_build_adapter_config_no_ocr_block_docling_library() -> None:
    result = TextExtractionAdapterFactory.build_adapter_config(
        mode=TextExtractionMode.DOCLING_LIBRARY,
        text_extraction_config=_lib_extraction_config(),
    )
    assert OperatorConstants.Config.OCR_BLOCK not in result


def test_build_adapter_config_ocr_invalid_engine_raises() -> None:
    with pytest.raises(ValueError, match="Invalid OCR engine"):
        TextExtractionAdapterFactory.build_adapter_config(
            mode=TextExtractionMode.DOCLING_LIBRARY,
            text_extraction_config=_lib_extraction_config(ocr={"engine": "bogus"}),
        )


def test_build_adapter_config_ocr_invalid_mode_raises() -> None:
    with pytest.raises(ValueError, match="Invalid OCR mode"):
        TextExtractionAdapterFactory.build_adapter_config(
            mode=TextExtractionMode.DOCLING_LIBRARY,
            text_extraction_config=_lib_extraction_config(ocr={"mode": "bogus"}),
        )


def test_build_adapter_config_ocr_engine_options_not_dict_raises() -> None:
    with pytest.raises(ValueError, match=r"ocr\.engine_options must be a JSON object"):
        TextExtractionAdapterFactory.build_adapter_config(
            mode=TextExtractionMode.DOCLING_LIBRARY,
            text_extraction_config=_lib_extraction_config(ocr={"engine_options": "oops"}),
        )


# ---------------------------------------------------------------------------
# DoclingAdapter OCR attribute reading
# ---------------------------------------------------------------------------


def test_docling_adapter_default_ocr_when_no_block() -> None:
    adapter = _make_lib_adapter()
    assert adapter._ocr_enabled is True
    assert adapter._ocr_engine == "rapidocr"
    assert adapter._ocr_mode == "default"
    assert adapter._ocr_engine_options is None


def test_docling_adapter_ocr_disabled() -> None:
    adapter = _make_lib_adapter({"enabled": False, "engine": "auto"})
    assert adapter._ocr_enabled is False


def test_docling_adapter_ocr_engine_set() -> None:
    adapter = _make_lib_adapter({"engine": "tesseract", "mode": "full_page"})
    assert adapter._ocr_engine == "tesseract"
    assert adapter._ocr_mode == "full_page"


# ---------------------------------------------------------------------------
# DoclingAdapter._build_ocr_options — using mocked docling classes
# ---------------------------------------------------------------------------


def test_docling_adapter_builds_easyocr_options() -> None:
    fake_easyocr_cls = MagicMock(return_value=MagicMock())
    mock_pipeline_options = MagicMock()
    mock_pipeline_options.EasyOcrOptions = fake_easyocr_cls
    mock_pipeline_options.OcrAutoOptions = MagicMock(return_value=MagicMock())
    mock_pipeline_options.OcrMacOptions = MagicMock(return_value=MagicMock())
    mock_pipeline_options.RapidOcrOptions = MagicMock(return_value=MagicMock())
    mock_pipeline_options.TesseractCliOcrOptions = MagicMock(return_value=MagicMock())
    mock_pipeline_options.TesseractOcrOptions = MagicMock(return_value=MagicMock())

    adapter = _make_lib_adapter({"engine": "easyocr", "engine_options": {"lang": ["en", "de"]}})

    with patch.dict("sys.modules", {"docling.datamodel.pipeline_options": mock_pipeline_options}):
        result = adapter._build_ocr_options()

    fake_easyocr_cls.assert_called_once_with(lang=["en", "de"])
    assert result is not None


def test_docling_adapter_builds_tesseract_options() -> None:
    fake_tesseract_cls = MagicMock(return_value=MagicMock())
    mock_pipeline_options = MagicMock()
    mock_pipeline_options.TesseractCliOcrOptions = fake_tesseract_cls
    mock_pipeline_options.EasyOcrOptions = MagicMock(return_value=MagicMock())
    mock_pipeline_options.OcrAutoOptions = MagicMock(return_value=MagicMock())
    mock_pipeline_options.OcrMacOptions = MagicMock(return_value=MagicMock())
    mock_pipeline_options.RapidOcrOptions = MagicMock(return_value=MagicMock())
    mock_pipeline_options.TesseractOcrOptions = MagicMock(return_value=MagicMock())

    adapter = _make_lib_adapter({"engine": "tesseract", "engine_options": {"lang": ["eng"]}})

    with patch.dict("sys.modules", {"docling.datamodel.pipeline_options": mock_pipeline_options}):
        result = adapter._build_ocr_options()

    fake_tesseract_cls.assert_called_once_with(lang=["eng"])
    assert result is not None


def test_docling_adapter_build_ocr_options_unknown_engine_falls_back() -> None:
    fake_auto_cls = MagicMock(return_value=MagicMock())
    mock_pipeline_options = MagicMock()
    mock_pipeline_options.OcrAutoOptions = fake_auto_cls
    mock_pipeline_options.EasyOcrOptions = MagicMock()
    mock_pipeline_options.OcrMacOptions = MagicMock()
    mock_pipeline_options.RapidOcrOptions = MagicMock()
    mock_pipeline_options.TesseractCliOcrOptions = MagicMock()
    mock_pipeline_options.TesseractOcrOptions = MagicMock()

    # Force an unknown engine by directly setting the private attr
    adapter = _make_lib_adapter({"engine": "auto"})
    adapter._ocr_engine = "not_a_real_engine"

    with patch.dict("sys.modules", {"docling.datamodel.pipeline_options": mock_pipeline_options}):
        result = adapter._build_ocr_options()

    fake_auto_cls.assert_called_once()
    assert result is not None


# ---------------------------------------------------------------------------
# DoclingServeAdapter — OCR wiring
# ---------------------------------------------------------------------------


def test_docling_serve_adapter_new_ocr_block() -> None:
    adapter = _make_serve_adapter(
        {
            "base_url": "http://localhost:5001",
            "ocr": {"enabled": True, "engine": "tesseract", "mode": "layout_regions"},
        }
    )
    opts = adapter.processing_options
    assert opts["do_ocr"] is True
    assert opts["ocr_preset"] == "tesseract"
    assert opts["ocr_mode"] == "layout_regions"


def test_docling_serve_adapter_backward_compat() -> None:
    """Old ocr_engine / ocr_languages fields still work when new ocr block is absent."""
    adapter = _make_serve_adapter(
        {
            "base_url": "http://localhost:5001",
            "do_ocr": True,
            "ocr_engine": "easyocr",
            "ocr_languages": ["en", "fr"],
        }
    )
    opts = adapter.processing_options
    assert opts["do_ocr"] is True
    assert opts["ocr_preset"] == "easyocr"
    assert opts["ocr_languages"] == ["en", "fr"]


def test_docling_serve_adapter_new_overrides_old() -> None:
    """When both the new ocr block and old ocr_engine are present, the new block wins."""
    adapter = _make_serve_adapter(
        {
            "base_url": "http://localhost:5001",
            "ocr_engine": "easyocr",  # old field — should be ignored
            "ocr": {"enabled": True, "engine": "tesseract"},
        }
    )
    opts = adapter.processing_options
    assert opts["ocr_preset"] == "tesseract"


def test_ocr_mode_forwarded_to_serve() -> None:
    adapter = _make_serve_adapter(
        {
            "base_url": "http://localhost:5001",
            "ocr": {
                "enabled": True,
                "engine": "auto",
                "mode": "pdf_aware_layout_regions",
            },
        }
    )
    assert adapter.processing_options.get("ocr_mode") == "pdf_aware_layout_regions"


def test_ocr_default_mode_not_forwarded_to_serve() -> None:
    """mode='default' should not produce an ocr_mode key (let server decide)."""
    adapter = _make_serve_adapter(
        {
            "base_url": "http://localhost:5001",
            "ocr": {"enabled": True, "engine": "auto", "mode": "default"},
        }
    )
    assert "ocr_mode" not in adapter.processing_options


def test_docling_adapter_extract_handles_ocr_options_none() -> None:
    """Test that extract_single_document handles _build_ocr_options returning None gracefully."""
    adapter = _make_lib_adapter({"enabled": True, "engine": "rapidocr", "mode": "layout_regions"})

    mock_result = {
        OperatorConstants.Extraction.SUCCESS: True,
        OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "content",
        OperatorConstants.Metadata.METADATA: {},
    }

    with (
        patch.object(adapter, "_build_ocr_options", return_value=None) as mock_build_ocr,
        patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
            return_value=mock_result,
        ) as mock_extract,
    ):
        result = adapter.extract_single_document(file_path="doc.pdf", binary_content=b"PDF")

    assert mock_build_ocr.called
    assert result[OperatorConstants.Extraction.SUCCESS] is True

    # Verify that the converter configuration fallback occurred gracefully and the format options
    # were set with the default OCR options, not None.
    call_args = mock_extract.call_args
    assert call_args is not None
    converter_config = call_args.kwargs.get("converter_config")
    assert converter_config is not None

    from docling.datamodel.base_models import InputFormat

    format_opts = converter_config[OperatorConstants.Config.FORMAT_OPTIONS]
    pdf_opts = format_opts[InputFormat.PDF]
    assert pdf_opts.pipeline_options.ocr_options is not None
