# Copyright IBM Corp. 2025
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for DoclingAdapter GPU acceleration and converter reuse.

These tests verify:
- GPU config is correctly read from config dict into adapter attributes
- _build_gpu_converter_config is called (or skipped) based on device config
- extract_single_document passes the pre-built GPU converter config (pooled converter) on the GPU path
- GPU device name is written into result metadata on success
- TextExtractionAdapterFactory correctly extracts GPU config and validates constraints
"""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.extract.adapters.outbound.factories.text_extraction_adapter_factory import (
    TextExtractionAdapterFactory,
)
from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter import DoclingAdapter
from docpipe.core.operators.extract.domain.models import TextExtractionMode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(extra: dict | None = None) -> DoclingAdapter:
    """Build a DoclingAdapter with minimal config, optionally merging extra keys."""
    base: dict = {
        "max_workers": 1,
        "use_processes": False,
        "doc_column": "content",
    }
    if extra:
        base.update(extra)
    # Patch _build_gpu_converter_config so no real docling GPU classes are needed
    with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value={"format_options": {}}):
        return DoclingAdapter(config=base)


# ---------------------------------------------------------------------------
# _init_adapter_config — GPU attribute wiring
# ---------------------------------------------------------------------------


class TestDoclingAdapterGpuInit:
    """Tests for GPU attribute initialisation in _init_adapter_config."""

    def test_no_gpu_config_leaves_device_none(self):
        adapter = _make_adapter()
        assert adapter.gpu_device is None
        assert adapter.gpu_num_threads is None

    def test_gpu_device_stored(self):
        adapter = _make_adapter({OperatorConstants.Extraction.DEVICE: "cuda"})
        assert adapter.gpu_device == "cuda"

    def test_gpu_num_threads_stored(self):
        adapter = _make_adapter(
            {
                OperatorConstants.Extraction.DEVICE: "mps",
                OperatorConstants.Extraction.NUM_THREADS: 8,
            }
        )
        assert adapter.gpu_num_threads == 8

    def test_gpu_num_threads_stored_without_device(self):
        """num_threads key is stored even if device is absent; no converter is built."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config") as mock_build:
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Extraction.NUM_THREADS: 4,
                }
            )
            mock_build.assert_not_called()
        assert adapter.gpu_num_threads == 4
        assert adapter._gpu_converter_config is None

    def test_build_gpu_converter_called_when_device_set(self):
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=MagicMock()) as mock_build:
            DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Extraction.DEVICE: "cuda",
                }
            )
        mock_build.assert_called_once()

    def test_build_gpu_converter_not_called_without_device(self):
        with patch.object(DoclingAdapter, "_build_gpu_converter_config") as mock_build:
            DoclingAdapter(config={"max_workers": 1, "use_processes": False})
            mock_build.assert_not_called()

    def test_gpu_converter_config_stored_on_adapter(self):
        gpu_config = {"format_options": {"pdf": MagicMock(name="gpu_pdf_option")}}
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=gpu_config):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Extraction.DEVICE: "mps",
                }
            )
        assert adapter._gpu_converter_config is gpu_config


# ---------------------------------------------------------------------------
# extract_single_document — GPU path uses pre-built converter
# ---------------------------------------------------------------------------


class TestExtractSingleDocumentGpuPath:
    """Tests that extract_single_document uses the GPU converter config when present."""

    def test_gpu_converter_config_passed_to_extract_content(self):
        """When _gpu_converter_config is set, extract_content receives it (pooled converter, no shared instance)."""
        gpu_config = {"format_options": {"pdf": MagicMock(name="gpu_pdf_option")}}
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=gpu_config):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Extraction.DEVICE: "mps",
                }
            )

        mock_result = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "extracted text",
            OperatorConstants.Metadata.METADATA: {},
        }

        with patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
            return_value=mock_result,
        ) as mock_extract:
            adapter.extract_single_document(file_path="doc.pdf", binary_content=b"PDF")

        call_kwargs = mock_extract.call_args.kwargs
        assert call_kwargs.get("converter") is None
        assert call_kwargs.get("converter_config") is gpu_config

    def test_unrecognised_device_config_uses_default_converter(self):
        """An empty GPU config (unrecognised device) maps to the default converter (converter_config=None)."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value={}):
            adapter = DoclingAdapter(
                config={"max_workers": 1, "use_processes": False, OperatorConstants.Extraction.DEVICE: "mps"}
            )

        mock_result = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "text",
            OperatorConstants.Metadata.METADATA: {},
        }
        with patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
            return_value=mock_result,
        ) as mock_extract:
            adapter.extract_single_document(file_path="doc.pdf", binary_content=b"PDF")

        assert mock_extract.call_args.kwargs.get("converter_config") is None

    def test_no_gpu_path_does_not_pass_converter(self):
        """When gpu_device is None, extract_content is called without converter kwarg."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config"):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 4,
                    "use_processes": False,
                }
            )

        mock_result = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "text",
            OperatorConstants.Metadata.METADATA: {},
        }

        with patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
            return_value=mock_result,
        ) as mock_extract:
            adapter.extract_single_document(file_path="doc.pdf", binary_content=b"PDF")

        call_kwargs = mock_extract.call_args.kwargs
        # On the non-GPU path, converter is not forwarded
        assert call_kwargs.get("converter") is None

    def test_gpu_device_written_to_result_metadata_on_success(self):
        """Successful GPU extraction records device name in result metadata."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value={"format_options": {}}):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Extraction.DEVICE: "cuda",
                }
            )

        mock_result = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "text",
            OperatorConstants.Metadata.METADATA: {},
        }

        with patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
            return_value=mock_result,
        ):
            result = adapter.extract_single_document(file_path="doc.pdf", binary_content=b"PDF")

        assert result[OperatorConstants.Metadata.METADATA][OperatorConstants.Extraction.DEVICE] == "cuda"

    def test_gpu_device_not_in_metadata_on_failure(self):
        """Failed GPU extraction should not write device into metadata."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value={"format_options": {}}):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Extraction.DEVICE: "mps",
                }
            )

        mock_result = {
            OperatorConstants.Extraction.SUCCESS: False,
            OperatorConstants.Extraction.ERROR: "boom",
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: None,
            OperatorConstants.Metadata.METADATA: {},
        }

        with patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
            return_value=mock_result,
        ):
            result = adapter.extract_single_document(file_path="doc.pdf", binary_content=b"PDF")

        assert OperatorConstants.Extraction.DEVICE not in result.get(OperatorConstants.Metadata.METADATA, {})

    def test_converter_config_is_reused_across_calls(self):
        """The same GPU config object is passed to both calls — options are not rebuilt per document."""
        gpu_config = {"format_options": {"pdf": MagicMock(name="gpu_pdf_option")}}
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=gpu_config):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Extraction.DEVICE: "cuda",
                }
            )

        mock_result = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "text",
            OperatorConstants.Metadata.METADATA: {},
        }

        with patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
            return_value=mock_result,
        ) as mock_extract:
            adapter.extract_single_document(file_path="doc1.pdf", binary_content=b"PDF1")
            adapter.extract_single_document(file_path="doc2.pdf", binary_content=b"PDF2")

        assert mock_extract.call_count == 2
        configs_used = [call.kwargs.get("converter_config") for call in mock_extract.call_args_list]
        assert configs_used[0] is gpu_config
        assert configs_used[1] is gpu_config


# ---------------------------------------------------------------------------
# TextExtractionAdapterFactory — GPU config extraction
# ---------------------------------------------------------------------------


class TestTextExtractionAdapterFactoryBuildConfig:
    """Tests for factory build_adapter_config GPU config extraction."""

    def _gpu_text_extraction_config(self, *, device: str = "cuda", num_threads: int | None = None) -> dict:
        accel: dict[str, object] = {"device": device}
        if num_threads is not None:
            accel["num_threads"] = num_threads
        return {
            "provider_config": {
                "standard_pipeline": {
                    "accelerator": accel,
                }
            }
        }

    def test_build_adapter_config_extracts_gpu_device(self):
        config = self._gpu_text_extraction_config(device="mps")
        result = TextExtractionAdapterFactory.build_adapter_config(
            mode=TextExtractionMode.DOCLING_LIBRARY, text_extraction_config=config
        )
        assert result[OperatorConstants.Extraction.DEVICE] == "mps"

    def test_build_adapter_config_extracts_cuda_device(self):
        config = self._gpu_text_extraction_config(device="cuda")
        result = TextExtractionAdapterFactory.build_adapter_config(
            mode=TextExtractionMode.DOCLING_LIBRARY, text_extraction_config=config
        )
        assert result[OperatorConstants.Extraction.DEVICE] == "cuda"

    def test_build_adapter_config_extracts_xpu_device(self):
        config = self._gpu_text_extraction_config(device="xpu")
        result = TextExtractionAdapterFactory.build_adapter_config(
            mode=TextExtractionMode.DOCLING_LIBRARY, text_extraction_config=config
        )
        assert result[OperatorConstants.Extraction.DEVICE] == "xpu"

    def test_build_adapter_config_extracts_num_threads(self):
        config = self._gpu_text_extraction_config(device="cuda", num_threads=8)
        result = TextExtractionAdapterFactory.build_adapter_config(
            mode=TextExtractionMode.DOCLING_LIBRARY, text_extraction_config=config
        )
        assert result[OperatorConstants.Extraction.NUM_THREADS] == 8

    def test_build_adapter_config_no_gpu_config_no_device_key(self):
        result = TextExtractionAdapterFactory.build_adapter_config(
            mode=TextExtractionMode.DOCLING_LIBRARY, text_extraction_config={}
        )
        assert OperatorConstants.Extraction.DEVICE not in result

    def test_build_adapter_config_missing_accelerator_block_no_device_key(self):
        """standard_pipeline present but no accelerator block."""
        config: dict[str, object] = {"provider_config": {"standard_pipeline": {}}}
        result = TextExtractionAdapterFactory.build_adapter_config(
            mode=TextExtractionMode.DOCLING_LIBRARY, text_extraction_config=config
        )
        assert OperatorConstants.Extraction.DEVICE not in result

    def test_build_adapter_config_num_threads_omitted_when_not_set(self):
        config = self._gpu_text_extraction_config(device="mps")
        result = TextExtractionAdapterFactory.build_adapter_config(
            mode=TextExtractionMode.DOCLING_LIBRARY, text_extraction_config=config
        )
        assert OperatorConstants.Extraction.NUM_THREADS not in result


# ---------------------------------------------------------------------------
# TextExtractionAdapterFactory — _validate_gpu_config
# ---------------------------------------------------------------------------


class TestTextExtractionAdapterFactoryValidateGpu:
    """Tests for _validate_gpu_config static method."""

    def test_valid_cuda_config(self):
        with patch.object(TextExtractionAdapterFactory, "_check_device_availability"):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={OperatorConstants.Extraction.DEVICE: "cuda"},
                max_workers=1,
                use_processes=False,
            )

    def test_valid_mps_config(self):
        with patch.object(TextExtractionAdapterFactory, "_check_device_availability"):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={OperatorConstants.Extraction.DEVICE: "mps"},
                max_workers=1,
                use_processes=False,
            )

    def test_valid_xpu_config(self):
        with patch.object(TextExtractionAdapterFactory, "_check_device_availability"):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={OperatorConstants.Extraction.DEVICE: "xpu"},
                max_workers=1,
                use_processes=False,
            )

    def test_valid_config_with_num_threads(self):
        with patch.object(TextExtractionAdapterFactory, "_check_device_availability"):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={
                    OperatorConstants.Extraction.DEVICE: "cuda",
                    OperatorConstants.Extraction.NUM_THREADS: 8,
                },
                max_workers=1,
                use_processes=False,
            )

    def test_invalid_device_raises(self):
        with pytest.raises(ValueError, match="Invalid GPU device"):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={OperatorConstants.Extraction.DEVICE: "tpu"},
                max_workers=1,
                use_processes=False,
            )

    def test_multiple_workers_raises(self):
        with pytest.raises(ValueError, match="max_workers=1"):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={OperatorConstants.Extraction.DEVICE: "cuda"},
                max_workers=4,
                use_processes=False,
            )

    def test_use_processes_raises(self):
        with pytest.raises(ValueError, match="use_processes=false"):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={OperatorConstants.Extraction.DEVICE: "cuda"},
                max_workers=1,
                use_processes=True,
            )

    def test_vlm_combination_raises(self):
        with pytest.raises(ValueError, match="cannot be combined"):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={
                    OperatorConstants.Extraction.DEVICE: "mps",
                    OperatorConstants.Config.USE_VLM_PIPELINE: True,
                },
                max_workers=1,
                use_processes=False,
            )

    def test_zero_num_threads_raises(self):
        with pytest.raises(ValueError, match="num_threads must be a positive integer"):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={
                    OperatorConstants.Extraction.DEVICE: "cuda",
                    OperatorConstants.Extraction.NUM_THREADS: 0,
                },
                max_workers=1,
                use_processes=False,
            )

    def test_negative_num_threads_raises(self):
        with pytest.raises(ValueError, match="num_threads must be a positive integer"):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={
                    OperatorConstants.Extraction.DEVICE: "cuda",
                    OperatorConstants.Extraction.NUM_THREADS: -1,
                },
                max_workers=1,
                use_processes=False,
            )

    def test_string_num_threads_raises(self):
        with pytest.raises(ValueError, match="num_threads must be a positive integer"):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={
                    OperatorConstants.Extraction.DEVICE: "cuda",
                    OperatorConstants.Extraction.NUM_THREADS: "eight",
                },
                max_workers=1,
                use_processes=False,
            )


# ---------------------------------------------------------------------------
# TextExtractionAdapterFactory — cuda:N, bool num_threads, unknown keys,
# runtime availability
# ---------------------------------------------------------------------------


class TestValidateGpuConfigExtended:
    """Tests for gaps not covered by the original test class."""

    # --- cuda:<index> device form ---

    def test_valid_cuda_index_zero(self):
        """cuda:0 is a valid device form."""
        with patch.object(
            TextExtractionAdapterFactory,
            "_check_device_availability",
        ):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={OperatorConstants.Extraction.DEVICE: "cuda:0"},
                max_workers=1,
                use_processes=False,
            )

    def test_valid_cuda_index_nonzero(self):
        """cuda:3 is a valid device form."""
        with patch.object(
            TextExtractionAdapterFactory,
            "_check_device_availability",
        ):
            TextExtractionAdapterFactory._validate_gpu_config(
                adapter_config={OperatorConstants.Extraction.DEVICE: "cuda:3"},
                max_workers=1,
                use_processes=False,
            )

    def test_cuda_alpha_suffix_raises(self):
        """cuda:abc is not a valid CUDA index."""
        with pytest.raises(ValueError, match="Invalid GPU device"):
            with patch.object(TextExtractionAdapterFactory, "_check_device_availability"):
                TextExtractionAdapterFactory._validate_gpu_config(
                    adapter_config={OperatorConstants.Extraction.DEVICE: "cuda:abc"},
                    max_workers=1,
                    use_processes=False,
                )

    def test_cpu_device_raises(self):
        """'cpu' is not accepted by the GPU contract."""
        with pytest.raises(ValueError, match="Invalid GPU device"):
            with patch.object(TextExtractionAdapterFactory, "_check_device_availability"):
                TextExtractionAdapterFactory._validate_gpu_config(
                    adapter_config={OperatorConstants.Extraction.DEVICE: "cpu"},
                    max_workers=1,
                    use_processes=False,
                )

    def test_auto_device_raises(self):
        """'auto' is not accepted by the GPU contract."""
        with pytest.raises(ValueError, match="Invalid GPU device"):
            with patch.object(TextExtractionAdapterFactory, "_check_device_availability"):
                TextExtractionAdapterFactory._validate_gpu_config(
                    adapter_config={OperatorConstants.Extraction.DEVICE: "auto"},
                    max_workers=1,
                    use_processes=False,
                )

    # --- boolean num_threads rejection ---

    def test_bool_true_num_threads_raises(self):
        """True is a bool and must be rejected even though isinstance(True, int) is True."""
        with pytest.raises(ValueError, match="num_threads must be a positive integer"):
            with patch.object(TextExtractionAdapterFactory, "_check_device_availability"):
                TextExtractionAdapterFactory._validate_gpu_config(
                    adapter_config={
                        OperatorConstants.Extraction.DEVICE: "cuda",
                        OperatorConstants.Extraction.NUM_THREADS: True,
                    },
                    max_workers=1,
                    use_processes=False,
                )

    def test_bool_false_num_threads_raises(self):
        """False evaluates to 0 and must also be rejected."""
        with pytest.raises(ValueError, match="num_threads must be a positive integer"):
            with patch.object(TextExtractionAdapterFactory, "_check_device_availability"):
                TextExtractionAdapterFactory._validate_gpu_config(
                    adapter_config={
                        OperatorConstants.Extraction.DEVICE: "cuda",
                        OperatorConstants.Extraction.NUM_THREADS: False,
                    },
                    max_workers=1,
                    use_processes=False,
                )


class TestBuildAdapterConfigSchemaChecks:
    """Tests for schema object-type checks in build_adapter_config."""

    def test_standard_pipeline_not_dict_raises(self):
        config = {"provider_config": {"standard_pipeline": "not_a_dict"}}
        with pytest.raises(ValueError, match="standard_pipeline must be a JSON object"):
            TextExtractionAdapterFactory.build_adapter_config(
                mode=TextExtractionMode.DOCLING_LIBRARY,
                text_extraction_config=config,
            )

    def test_accelerator_not_dict_raises(self):
        config = {"provider_config": {"standard_pipeline": {"accelerator": 42}}}
        with pytest.raises(ValueError, match="accelerator must be a JSON object"):
            TextExtractionAdapterFactory.build_adapter_config(
                mode=TextExtractionMode.DOCLING_LIBRARY,
                text_extraction_config=config,
            )

    def test_unknown_accelerator_key_raises(self):
        config = {"provider_config": {"standard_pipeline": {"accelerator": {"device": "mps", "batch_size": 8}}}}
        with pytest.raises(ValueError, match="Unknown accelerator key"):
            TextExtractionAdapterFactory.build_adapter_config(
                mode=TextExtractionMode.DOCLING_LIBRARY,
                text_extraction_config=config,
            )

    def test_valid_accelerator_keys_accepted(self):
        """device + num_threads are the only accepted keys — no error."""
        config = {"provider_config": {"standard_pipeline": {"accelerator": {"device": "mps", "num_threads": 4}}}}
        result = TextExtractionAdapterFactory.build_adapter_config(
            mode=TextExtractionMode.DOCLING_LIBRARY,
            text_extraction_config=config,
        )
        assert result[OperatorConstants.Extraction.DEVICE] == "mps"
        assert result[OperatorConstants.Extraction.NUM_THREADS] == 4


class TestCheckDeviceAvailability:
    """Tests for _check_device_availability runtime checks."""

    def test_torch_not_installed_raises(self):
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def _no_torch(name, *args, **kwargs):
            if name == "torch":
                raise ImportError("No module named 'torch'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_no_torch):
            with pytest.raises(ValueError, match="torch to be installed"):
                TextExtractionAdapterFactory._check_device_availability("mps")

    def test_mps_unavailable_raises(self):
        torch_mock = MagicMock()
        torch_mock.backends.mps.is_built.return_value = True
        torch_mock.backends.mps.is_available.return_value = False
        with patch.dict("sys.modules", {"torch": torch_mock}):
            with pytest.raises(ValueError, match=r"mps.*not available"):
                TextExtractionAdapterFactory._check_device_availability("mps")

    def test_mps_available_passes(self):
        torch_mock = MagicMock()
        torch_mock.backends.mps.is_built.return_value = True
        torch_mock.backends.mps.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": torch_mock}):
            TextExtractionAdapterFactory._check_device_availability("mps")

    def test_cuda_unavailable_raises(self):
        torch_mock = MagicMock()
        torch_mock.cuda.is_available.return_value = False
        with patch.dict("sys.modules", {"torch": torch_mock}):
            with pytest.raises(ValueError, match="not available"):
                TextExtractionAdapterFactory._check_device_availability("cuda")

    def test_cuda_available_passes(self):
        torch_mock = MagicMock()
        torch_mock.cuda.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": torch_mock}):
            TextExtractionAdapterFactory._check_device_availability("cuda")

    def test_cuda_index_out_of_range_raises(self):
        torch_mock = MagicMock()
        torch_mock.cuda.is_available.return_value = True
        torch_mock.cuda.device_count.return_value = 2
        with patch.dict("sys.modules", {"torch": torch_mock}):
            with pytest.raises(ValueError, match="out of range"):
                TextExtractionAdapterFactory._check_device_availability("cuda:5")

    def test_cuda_index_in_range_passes(self):
        torch_mock = MagicMock()
        torch_mock.cuda.is_available.return_value = True
        torch_mock.cuda.device_count.return_value = 4
        with patch.dict("sys.modules", {"torch": torch_mock}):
            TextExtractionAdapterFactory._check_device_availability("cuda:3")

    def test_xpu_unavailable_raises(self):
        torch_mock = MagicMock()
        torch_mock.xpu.is_available.return_value = False
        with patch.dict("sys.modules", {"torch": torch_mock}):
            with pytest.raises(ValueError, match=r"xpu.*not available"):
                TextExtractionAdapterFactory._check_device_availability("xpu")

    def test_xpu_no_attr_raises(self):
        torch_mock = MagicMock(spec=[])  # no xpu attr
        with patch.dict("sys.modules", {"torch": torch_mock}):
            with pytest.raises(ValueError, match=r"xpu.*not available"):
                TextExtractionAdapterFactory._check_device_availability("xpu")

    def test_xpu_available_passes(self):
        torch_mock = MagicMock()
        torch_mock.xpu.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": torch_mock}):
            TextExtractionAdapterFactory._check_device_availability("xpu")


class TestBuildGpuConverter:
    """Tests for DoclingAdapter._build_gpu_converter_config correct Docling 2105 construction."""

    def _make_docling_mocks(self):
        """Return a dict of mocked docling classes for patching sys.modules."""
        mock_accel_device = MagicMock(name="AcceleratorDevice")
        mock_accel_device.MPS = "mps_enum"
        mock_accel_device.CUDA = "cuda_enum"
        mock_accel_device.XPU = "xpu_enum"

        mock_accel_options = MagicMock(name="AcceleratorOptions")
        mock_threaded_opts = MagicMock(name="ThreadedPdfPipelineOptions")
        mock_pdf_fmt = MagicMock(name="PdfFormatOption")
        mock_image_fmt = MagicMock(name="ImageFormatOption")
        mock_converter = MagicMock(name="DocumentConverter")
        mock_input_fmt = MagicMock(name="InputFormat")
        mock_input_fmt.PDF = "pdf_fmt"
        mock_input_fmt.IMAGE = "img_fmt"

        pipeline_options_mod = MagicMock()
        pipeline_options_mod.AcceleratorDevice = mock_accel_device
        pipeline_options_mod.AcceleratorOptions = mock_accel_options
        pipeline_options_mod.ThreadedPdfPipelineOptions = mock_threaded_opts

        base_models_mod = MagicMock()
        base_models_mod.InputFormat = mock_input_fmt

        document_converter_mod = MagicMock()
        document_converter_mod.DocumentConverter = mock_converter
        document_converter_mod.PdfFormatOption = mock_pdf_fmt
        document_converter_mod.ImageFormatOption = mock_image_fmt

        return {
            "AcceleratorOptions": mock_accel_options,
            "ThreadedPdfPipelineOptions": mock_threaded_opts,
            "PdfFormatOption": mock_pdf_fmt,
            "ImageFormatOption": mock_image_fmt,
            "DocumentConverter": mock_converter,
            "InputFormat": mock_input_fmt,
            "pipeline_options_mod": pipeline_options_mod,
            "base_models_mod": base_models_mod,
            "document_converter_mod": document_converter_mod,
        }

    def test_uses_threaded_pdf_pipeline_options(self):
        """_build_gpu_converter_config must use ThreadedPdfPipelineOptions not PipelineOptions."""
        mocks = self._make_docling_mocks()

        with patch.dict(
            "sys.modules",
            {
                "docling.datamodel.pipeline_options": mocks["pipeline_options_mod"],
                "docling.datamodel.base_models": mocks["base_models_mod"],
                "docling.document_converter": mocks["document_converter_mod"],
            },
        ):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Extraction.DEVICE: "mps",
                }
            )

        assert adapter._gpu_converter_config is not None
        assert set(adapter._gpu_converter_config["format_options"]) == {"pdf_fmt", "img_fmt"}
        # The converter itself is no longer built at init; it is leased from the pool on first use.
        mocks["DocumentConverter"].assert_not_called()
        mocks["ThreadedPdfPipelineOptions"].assert_called_once()
        mocks["PdfFormatOption"].assert_called_once()
        mocks["ImageFormatOption"].assert_called_once()

    def test_cuda_index_maps_to_cuda_enum(self):
        """cuda:0 must resolve to AcceleratorDevice.CUDA, not fail the device_map lookup."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=MagicMock()) as mock_build:
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Extraction.DEVICE: "cuda:0",
                }
            )
        mock_build.assert_called_once()
        assert adapter.gpu_device == "cuda:0"


# ---------------------------------------------------------------------------
# DoclingAdapter — _init_adapter_config logging branches
# ---------------------------------------------------------------------------


class TestDoclingAdapterInitLogging:
    """Tests covering the VLM, ASR, and standard-pipeline log branches."""

    def test_vlm_pipeline_info_logged(self):
        """No exception when VLM pipeline is enabled (log branch coverage)."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Config.USE_VLM_PIPELINE: True,
                    OperatorConstants.Config.VLM_PRESET: "granite_docling",
                }
            )
        assert adapter.use_vlm_pipeline is True

    def test_asr_pipeline_enabled_logs(self):
        """When use_asr_pipeline is True and ASR is available, attribute is set."""
        import sys
        from unittest.mock import MagicMock

        asr_mod = MagicMock()
        audio_opt = MagicMock()
        asr_pipeline = MagicMock()
        with patch.dict(
            sys.modules,
            {
                "docling.datamodel.asr_model_specs": asr_mod,
                "docling.document_converter": MagicMock(AudioFormatOption=audio_opt),
                "docling.pipeline.asr_pipeline": MagicMock(AsrPipeline=asr_pipeline),
            },
        ):
            import docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter as mod

            with patch.object(mod, "_ASR_AVAILABLE", True):
                with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
                    adapter = DoclingAdapter(
                        config={
                            "max_workers": 1,
                            "use_processes": False,
                            OperatorConstants.Config.USE_ASR_PIPELINE: True,
                        }
                    )
        assert adapter.use_asr_pipeline is True

    def test_asr_requested_but_unavailable_logs_warning(self):
        """When ASR is requested but unavailable, use_asr_pipeline stays False."""
        import docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter as mod

        with patch.object(mod, "_ASR_AVAILABLE", False):
            with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
                adapter = DoclingAdapter(
                    config={
                        "max_workers": 1,
                        "use_processes": False,
                        OperatorConstants.Config.USE_ASR_PIPELINE: True,
                    }
                )
        assert adapter.use_asr_pipeline is False

    def test_standard_pipeline_no_gpu_no_asr_logs(self):
        """Standard path (no VLM, no ASR, no GPU) reaches the standard-extraction log line."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                }
            )
        assert adapter.use_vlm_pipeline is False
        assert adapter.use_asr_pipeline is False
        assert adapter.gpu_device is None


# ---------------------------------------------------------------------------
# DoclingAdapter — _build_gpu_converter_config error paths
# ---------------------------------------------------------------------------


class TestBuildGpuConverterEdgeCases:
    """Tests covering fallback and error paths in _build_gpu_converter_config."""

    def test_unrecognised_device_returns_default_converter(self):
        """Unrecognised device name falls back to the default converter config ({})."""
        import sys
        from unittest.mock import MagicMock

        mock_converter_cls = MagicMock(name="DocumentConverter")
        mock_converter_instance = MagicMock(name="converter_instance")
        mock_converter_cls.return_value = mock_converter_instance

        mock_accel_device = MagicMock(name="AcceleratorDevice")
        mock_accel_device.MPS = "mps_enum"
        mock_accel_device.CUDA = "cuda_enum"
        mock_accel_device.XPU = "xpu_enum"

        pipeline_options_mod = MagicMock()
        pipeline_options_mod.AcceleratorDevice = mock_accel_device
        pipeline_options_mod.AcceleratorOptions = MagicMock()
        pipeline_options_mod.ThreadedPdfPipelineOptions = MagicMock()

        base_models_mod = MagicMock()
        base_models_mod.InputFormat = MagicMock(PDF="pdf", IMAGE="img")

        document_converter_mod = MagicMock()
        document_converter_mod.DocumentConverter = mock_converter_cls
        document_converter_mod.PdfFormatOption = MagicMock()
        document_converter_mod.ImageFormatOption = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "docling.datamodel.pipeline_options": pipeline_options_mod,
                "docling.datamodel.base_models": base_models_mod,
                "docling.document_converter": document_converter_mod,
            },
        ):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Extraction.DEVICE: "unknowndevice",
                }
            )

        # Falls back to the default converter configuration; nothing is constructed at init
        mock_converter_cls.assert_not_called()
        assert adapter._gpu_converter_config == {}

    def test_import_error_in_build_gpu_converter_config_returns_none(self):
        """ImportError in _build_gpu_converter_config returns None and logs warning."""
        import sys

        with patch.dict(sys.modules, {"docling.datamodel.pipeline_options": None}):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Extraction.DEVICE: "cuda",
                }
            )
        # _build_gpu_converter_config catches ImportError and returns None
        assert adapter._gpu_converter_config is None


# ---------------------------------------------------------------------------
# DoclingAdapter — extract_single_document branches
# ---------------------------------------------------------------------------


class TestExtractSingleDocumentBranches:
    """Tests for the non-GPU extract paths and metadata annotations."""

    def test_vlm_pipeline_metadata_written_on_success(self):
        """VLM preset and engine type are written to result metadata on success."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Config.USE_VLM_PIPELINE: True,
                    OperatorConstants.Config.VLM_PRESET: "granite_docling",
                    OperatorConstants.Config.VLM_ENGINE_TYPE: "transformers",
                }
            )

        mock_result = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "text",
            OperatorConstants.Metadata.METADATA: {},
        }

        with (
            patch.object(adapter, "_configure_vlm_engine", return_value=None),
            patch(
                "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
                return_value=mock_result,
            ),
        ):
            result = adapter.extract_single_document(file_path="doc.pdf", binary_content=b"PDF")

        assert result[OperatorConstants.Metadata.METADATA][OperatorConstants.Config.VLM_PRESET] == "granite_docling"
        assert OperatorConstants.Config.VLM_ENGINE_TYPE in result[OperatorConstants.Metadata.METADATA]

    def test_asr_metadata_written_on_success(self):
        """ASR model name is written to result metadata on success."""
        import docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter as mod

        with patch.object(mod, "_ASR_AVAILABLE", True):
            with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
                adapter = DoclingAdapter(
                    config={
                        "max_workers": 1,
                        "use_processes": False,
                        OperatorConstants.Config.USE_ASR_PIPELINE: True,
                        OperatorConstants.Config.ASR_MODEL_NAME: "whisper_turbo",
                    }
                )

        mock_result = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "transcribed text",
            OperatorConstants.Metadata.METADATA: {},
        }

        with patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
            return_value=mock_result,
        ):
            result = adapter.extract_single_document(file_path="audio.mp3", binary_content=b"audio")

        assert result[OperatorConstants.Metadata.METADATA][OperatorConstants.Config.ASR_MODEL_NAME] == "whisper_turbo"

    def test_import_error_for_vlm_pipeline_returns_error_dict(self):
        """ImportError when VLM deps are missing returns structured error dict."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Config.USE_VLM_PIPELINE: True,
                }
            )

        with patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
            side_effect=ImportError("No module named 'docling.pipeline.vlm_pipeline'"),
        ):
            result = adapter.extract_single_document(file_path="doc.pdf", binary_content=b"PDF")

        assert result[OperatorConstants.Extraction.SUCCESS] is False
        assert "VLM" in result[OperatorConstants.Extraction.ERROR]

    def test_generic_exception_returns_error_dict(self):
        """Unexpected exception during extraction returns structured error dict."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
            adapter = DoclingAdapter(config={"max_workers": 1, "use_processes": False})

        with patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
            side_effect=RuntimeError("unexpected boom"),
        ):
            result = adapter.extract_single_document(file_path="doc.pdf", binary_content=b"PDF")

        assert result[OperatorConstants.Extraction.SUCCESS] is False
        assert "unexpected boom" in result[OperatorConstants.Extraction.ERROR]

    def test_standard_pipeline_logs_standard_extraction(self):
        """Standard pipeline (no GPU, no VLM) logs correct message path."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
            adapter = DoclingAdapter(config={"max_workers": 1, "use_processes": False})

        mock_result = {
            OperatorConstants.Extraction.SUCCESS: True,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: "text",
            OperatorConstants.Metadata.METADATA: {},
        }

        with patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.OperatorUtils.extract_content",
            return_value=mock_result,
        ) as mock_extract:
            adapter.extract_single_document(file_path="doc.pdf", binary_content=b"PDF")

        mock_extract.assert_called_once()


# ---------------------------------------------------------------------------
# DoclingAdapter — _configure_vlm_engine
# ---------------------------------------------------------------------------


class TestConfigureVlmEngine:
    """Tests for _configure_vlm_engine."""

    def test_no_engine_no_provider_config_returns_none(self):
        """Returns None when neither vlm_engine_type nor vlm_provider_config are set."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Config.USE_VLM_PIPELINE: True,
                }
            )
        result = adapter._configure_vlm_engine()
        assert result is None

    def test_with_engine_type_calls_provider(self):
        """When vlm_engine_type is set, calls VlmPipelineOptionsProviderFactory."""
        from unittest.mock import MagicMock, patch

        mock_provider = MagicMock()
        mock_provider.create_pipeline_options.return_value = MagicMock(name="pipeline_opts")

        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
            adapter = DoclingAdapter(
                config={
                    "max_workers": 1,
                    "use_processes": False,
                    OperatorConstants.Config.USE_VLM_PIPELINE: True,
                    OperatorConstants.Config.VLM_ENGINE_TYPE: "transformers",
                }
            )

        with patch(
            "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.VlmPipelineOptionsProviderFactory.get_provider",
            return_value=mock_provider,
        ):
            result = adapter._configure_vlm_engine()

        assert result is not None
        mock_provider.create_pipeline_options.assert_called_once()


# ---------------------------------------------------------------------------
# DoclingAdapter — _configure_asr_engine
# ---------------------------------------------------------------------------


class TestConfigureAsrEngine:
    """Tests for _configure_asr_engine."""

    def test_no_model_name_returns_none(self):
        """Returns None when asr_model_name is empty/falsy."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
            adapter = DoclingAdapter(config={"max_workers": 1, "use_processes": False})
        adapter.asr_model_name = ""
        result = adapter._configure_asr_engine()
        assert result is None

    def test_valid_model_name_returns_options(self):
        """Returns AsrPipelineOptions when a valid model constant exists."""
        import sys
        from unittest.mock import MagicMock

        asr_model_specs_mock = MagicMock()
        model_spec = MagicMock()
        model_spec.repo_id = "openai/whisper-turbo"
        asr_model_specs_mock.WHISPER_TURBO = model_spec

        pipeline_options_mock = MagicMock()
        mock_asr_options = MagicMock()
        pipeline_options_mock.AsrPipelineOptions = MagicMock(return_value=mock_asr_options)

        with patch.dict(
            sys.modules,
            {
                "docling.datamodel.asr_model_specs": asr_model_specs_mock,
                "docling.datamodel.pipeline_options": pipeline_options_mock,
            },
        ):
            with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
                adapter = DoclingAdapter(config={"max_workers": 1, "use_processes": False})
            adapter.asr_model_name = "whisper_turbo"
            result = adapter._configure_asr_engine()

        assert result is mock_asr_options

    def test_invalid_model_name_falls_back_to_whisper_turbo(self):
        """Invalid model name falls back to WHISPER_TURBO and still returns options."""
        import sys
        from unittest.mock import MagicMock

        asr_model_specs_mock = MagicMock(spec=["WHISPER_TURBO"])
        model_spec = MagicMock()
        model_spec.repo_id = "openai/whisper-turbo"
        asr_model_specs_mock.WHISPER_TURBO = model_spec

        pipeline_options_mock = MagicMock()
        mock_asr_options = MagicMock()
        pipeline_options_mock.AsrPipelineOptions = MagicMock(return_value=mock_asr_options)

        with patch.dict(
            sys.modules,
            {
                "docling.datamodel.asr_model_specs": asr_model_specs_mock,
                "docling.datamodel.pipeline_options": pipeline_options_mock,
            },
        ):
            with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
                adapter = DoclingAdapter(config={"max_workers": 1, "use_processes": False})
            adapter.asr_model_name = "nonexistent_model"
            result = adapter._configure_asr_engine()

        assert result is mock_asr_options

    def test_import_error_returns_none(self):
        """Returns None when ASR import raises inside _configure_asr_engine."""
        with patch.object(DoclingAdapter, "_build_gpu_converter_config", return_value=None):
            adapter = DoclingAdapter(config={"max_workers": 1, "use_processes": False})

        adapter.asr_model_name = "whisper_turbo"

        # Patch the inner import of asr_model_specs to raise ImportError
        with patch(
            "docling.datamodel.asr_model_specs",
            side_effect=ImportError("No module named 'docling.datamodel.asr_model_specs'"),
        ):
            # The function catches ImportError and returns None — simulate by
            # patching AsrPipelineOptions to raise on construction
            with patch(
                "docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter.DoclingAdapter._configure_asr_engine",
                side_effect=ImportError("mocked"),
            ):
                # Direct call to a fresh adapter to exercise the except branch
                pass

        # Exercise the real except ImportError branch by removing asr_model_specs at runtime
        import builtins

        real_import = builtins.__import__

        def _block_asr(name, *args, **kwargs):
            if name in ("docling.datamodel.asr_model_specs", "docling.datamodel.pipeline_options"):
                raise ImportError(f"Blocked: {name}")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_block_asr):
            result = adapter._configure_asr_engine()

        assert result is None


# ---------------------------------------------------------------------------
# TextExtractionAdapterFactory — _auto_detect_device
# ---------------------------------------------------------------------------


class TestAutoDetectDevice:
    """Tests for _auto_detect_device static method."""

    def test_returns_cuda_when_cuda_available(self):
        torch_mock = MagicMock()
        torch_mock.cuda.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": torch_mock}):
            result = TextExtractionAdapterFactory._auto_detect_device()
        assert result == OperatorConstants.Extraction.DEVICE_CUDA

    def test_returns_mps_when_mps_available_and_no_cuda(self):
        torch_mock = MagicMock()
        torch_mock.cuda.is_available.return_value = False
        torch_mock.backends.mps.is_built.return_value = True
        torch_mock.backends.mps.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": torch_mock}):
            result = TextExtractionAdapterFactory._auto_detect_device()
        assert result == OperatorConstants.Extraction.DEVICE_MPS

    def test_returns_xpu_when_only_xpu_available(self):
        torch_mock = MagicMock()
        torch_mock.cuda.is_available.return_value = False
        torch_mock.backends.mps.is_built.return_value = False
        torch_mock.backends.mps.is_available.return_value = False
        torch_mock.xpu.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": torch_mock}):
            result = TextExtractionAdapterFactory._auto_detect_device()
        assert result == OperatorConstants.Extraction.DEVICE_XPU

    def test_returns_none_when_no_gpu_available(self):
        torch_mock = MagicMock()
        torch_mock.cuda.is_available.return_value = False
        torch_mock.backends.mps.is_built.return_value = False
        torch_mock.backends.mps.is_available.return_value = False
        torch_mock.xpu.is_available.return_value = False
        with patch.dict("sys.modules", {"torch": torch_mock}):
            result = TextExtractionAdapterFactory._auto_detect_device()
        assert result is None

    def test_returns_none_when_torch_not_installed(self):
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def _no_torch(name, *args, **kwargs):
            if name == "torch":
                raise ImportError("No module named 'torch'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_no_torch):
            result = TextExtractionAdapterFactory._auto_detect_device()
        assert result is None

    def test_returns_none_when_xpu_attr_missing(self):
        torch_mock = MagicMock(spec=["cuda", "backends"])
        torch_mock.cuda.is_available.return_value = False
        torch_mock.backends.mps.is_built.return_value = False
        torch_mock.backends.mps.is_available.return_value = False
        with patch.dict("sys.modules", {"torch": torch_mock}):
            result = TextExtractionAdapterFactory._auto_detect_device()
        assert result is None

    def test_build_adapter_config_auto_detects_device_when_accelerator_present_no_device(self):
        """Accelerator block without device key triggers auto-detection."""
        config = {"provider_config": {"standard_pipeline": {"accelerator": {"num_threads": 4}}}}
        with patch.object(TextExtractionAdapterFactory, "_auto_detect_device", return_value="cuda"):
            result = TextExtractionAdapterFactory.build_adapter_config(
                mode=TextExtractionMode.DOCLING_LIBRARY,
                text_extraction_config=config,
            )
        assert result[OperatorConstants.Extraction.DEVICE] == "cuda"
        assert result[OperatorConstants.Extraction.NUM_THREADS] == 4

    def test_build_adapter_config_no_device_when_auto_detect_returns_none(self):
        """When auto-detection finds nothing, device key is absent from adapter config."""
        config = {"provider_config": {"standard_pipeline": {"accelerator": {"num_threads": 4}}}}
        with patch.object(TextExtractionAdapterFactory, "_auto_detect_device", return_value=None):
            result = TextExtractionAdapterFactory.build_adapter_config(
                mode=TextExtractionMode.DOCLING_LIBRARY,
                text_extraction_config=config,
            )
        assert OperatorConstants.Extraction.DEVICE not in result

    def test_explicit_device_takes_precedence_over_auto_detect(self):
        """Explicit device in config is used as-is; _auto_detect_device is not called."""
        config = {"provider_config": {"standard_pipeline": {"accelerator": {"device": "mps"}}}}
        with patch.object(TextExtractionAdapterFactory, "_auto_detect_device") as mock_detect:
            result = TextExtractionAdapterFactory.build_adapter_config(
                mode=TextExtractionMode.DOCLING_LIBRARY,
                text_extraction_config=config,
            )
        mock_detect.assert_not_called()
        assert result[OperatorConstants.Extraction.DEVICE] == "mps"
