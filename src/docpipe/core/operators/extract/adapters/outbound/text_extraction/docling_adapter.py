"""Docling library text extraction adapter.

This adapter implements the unified docling_library provider for document extraction.
It handles both standard Docling extraction and VLM (Vision Language Model) extraction
when use_vlm_pipeline is enabled. The adapter uses Docling's DocumentExtractor for
extraction and supports template-based structured extraction.

GPU acceleration is supported for the standard pipeline via the ``device`` configuration
key (mps, cuda, xpu). When a GPU device is specified the adapter builds the GPU format
options once at init time; the matching DocumentConverter is leased from the process-wide
converter pool, so model weights are loaded onto the GPU once per configuration and reused
across documents, micro-batches and operator instances.
"""

import logging
from typing import Any

from pydantic import BaseModel

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.extract.adapters.outbound.factories.text_extraction_adapter_factory import (
    register_text_extraction_adapter,
)
from docpipe.core.operators.extract.adapters.outbound.text_extraction.ocr_config import OcrConfig
from docpipe.core.operators.extract.ports.outbound.text_extraction import TextExtractionPort
from docpipe.core.operators.operator_utils import OperatorUtils, is_asr_available
from docpipe.integrations.docling.vlm_pipeline_options_provider import VlmPipelineOptionsProviderFactory
from docpipe.utils.infrastructure.logging import get_logger

logger: logging.Logger = get_logger()

_DOCLING_PIPELINE_OPTIONS_MODULE = "docling.datamodel.pipeline_options"

# ASR availability is resolved lazily: the probe imports docling (and transitively torch/transformers),
# which must not happen at module import time (e.g. for --list-operators).
_ASR_AVAILABLE: bool | None = None


def _asr_available() -> bool:
    """Return whether ASR dependencies are installed, probing once on first use."""
    global _ASR_AVAILABLE
    if _ASR_AVAILABLE is None:
        _ASR_AVAILABLE = is_asr_available()
        if not _ASR_AVAILABLE:
            logger.debug("ASR dependencies not available. Install with: uv pip install -e '.[asr]'")
    return _ASR_AVAILABLE


@register_text_extraction_adapter
class DoclingAdapter(TextExtractionPort):
    """Adapter for unified Docling library document extraction.

    This adapter implements the docling_library provider, which handles both standard
    Docling extraction and VLM (Vision Language Model) extraction. When use_vlm_pipeline
    is enabled, it uses Docling's VLM pipeline for enhanced extraction.

    The adapter provides:
    - Standard Docling extraction using DocumentExtractor
    - VLM pipeline support for advanced document understanding
    - Template-based structured extraction for structured data
    - Page-level extraction results

    Configuration:
        use_vlm_pipeline: Enable VLM extraction (default: False)
        vlm_preset: VLM preset name when VLM is enabled (default: "granite_docling")
        vlm_engine_type: VLM engine type (optional, uses Docling defaults if not set)
        vlm_provider_config: Provider-specific configuration (optional)

    Attributes:
        ADAPTER_NAME: Short identifier "docling_library"
        ADAPTER_DISPLAY_NAME: Human-readable name "Docling Library Extractor"
    """

    ADAPTER_NAME = "docling_library"
    ADAPTER_DISPLAY_NAME = "Docling Library Extractor"

    def __init__(self, *, config: dict[str, Any]) -> None:
        """Initialize the adapter with configuration.

        Args:
            config: Configuration dictionary
        """
        super().__init__(config=config)

    def _init_adapter_config(self, *, config: dict[str, Any]) -> None:
        """Initialize Docling-specific configuration.

        Args:
            config: Configuration dictionary containing:
                - use_vlm_pipeline: Enable VLM extraction (default: False)
                - vlm_preset: VLM preset name (default: "granite_docling")
                - vlm_engine_type: Engine type (optional)
                - vlm_provider_config: Provider-specific configuration (optional)
                - additional_formats: List of additional output formats beyond markdown (default: [])
                - use_asr_pipeline: Enable ASR extraction for audio/video (default: False)
                - asr_model_name: ASR model name (optional)
                - device: GPU device for standard pipeline acceleration ("mps", "cuda", "xpu") (optional)
                - num_threads: Thread count for GPU pipeline operations (optional)
        """
        self.use_vlm_pipeline = config.get(OperatorConstants.Config.USE_VLM_PIPELINE, False)
        self.vlm_preset = config.get(OperatorConstants.Config.VLM_PRESET, OperatorConstants.Config.VLM_PRESET_DEFAULT)
        self.vlm_engine_type = config.get(OperatorConstants.Config.VLM_ENGINE_TYPE)
        self.vlm_provider_config = config.get(OperatorConstants.Config.VLM_PROVIDER_CONFIG)
        self.additional_formats = config.get(OperatorConstants.Extraction.ADDITIONAL_FORMATS, [])
        self.use_asr_pipeline = config.get(OperatorConstants.Config.USE_ASR_PIPELINE, False) and _asr_available()
        # Always use string default for ASR model name
        self.asr_model_name = config.get(
            OperatorConstants.Config.ASR_MODEL_NAME, OperatorConstants.Config.ASR_MODEL_DEFAULT
        )

        # GPU acceleration config (standard pipeline only — incompatible with VLM)
        self.gpu_device: str | None = config.get(OperatorConstants.Extraction.DEVICE)
        self.gpu_num_threads: int | None = config.get(OperatorConstants.Extraction.NUM_THREADS)

        # OCR configuration (standard pipeline only — OCR is not applicable when VLM is active)
        ocr_block = config.get(OperatorConstants.Config.OCR_BLOCK)
        self._ocr_enabled: bool = True
        self._ocr_engine: str = "rapidocr"
        self._ocr_mode: str = "default"
        self._ocr_engine_options: dict[str, Any] | None = None

        if ocr_block:
            ocr_cfg = OcrConfig.model_validate(ocr_block)
            self._ocr_enabled = ocr_cfg.enabled
            self._ocr_engine = ocr_cfg.engine
            self._ocr_mode = ocr_cfg.mode
            self._ocr_engine_options = ocr_cfg.engine_options

        # Pre-build the GPU converter configuration once. The converter itself is leased
        # from the process-wide pool (keyed by these options) so its model weights are
        # loaded once and reused across documents, batches and operator instances.
        # ``None`` means GPU acceleration is unavailable; ``{}`` means the default converter.
        self._gpu_converter_config: dict[str, Any] | None = None
        if self.gpu_device:
            self._gpu_converter_config = self._build_gpu_converter_config()

        self._log_init_mode(config=config, ocr_block=ocr_block)

    def _log_init_mode(self, *, config: dict[str, Any], ocr_block: Any) -> None:
        """Log the active extraction mode chosen during adapter initialisation."""
        if self.use_vlm_pipeline:
            logger.info(
                "Initialized DoclingAdapter with VLM enabled - preset: %s, engine: %s, additional formats: %s",
                self.vlm_preset,
                self.vlm_engine_type or "default",
                self.additional_formats,
            )
        elif self.gpu_device:
            logger.info(
                "Initialized DoclingAdapter with GPU acceleration - device: %s, num_threads: %s, "
                "additional formats: %s",
                self.gpu_device,
                self.gpu_num_threads,
                self.additional_formats,
            )

        if self.use_asr_pipeline:
            logger.info("Initialized DoclingAdapter with ASR enabled - model: %s", self.asr_model_name or "default")
        elif config.get(OperatorConstants.Config.USE_ASR_PIPELINE, False) and not _asr_available():
            logger.warning(
                "ASR pipeline requested but dependencies not available. Install with: uv pip install -e '.[asr]'"
            )

        if ocr_block:
            logger.info(
                "OCR config - enabled: %s, engine: %s, mode: %s",
                self._ocr_enabled,
                self._ocr_engine,
                self._ocr_mode,
            )

        if not self.use_vlm_pipeline and not self.use_asr_pipeline and not self.gpu_device:
            logger.info(
                "Initialized DoclingAdapter with standard extraction, additional formats: %s", self.additional_formats
            )

    def _build_gpu_converter_config(self) -> dict[str, Any] | None:
        """Build the converter configuration for GPU-accelerated standard pipeline extraction.

        Uses the Docling 2105 mapping: AcceleratorOptions -> ThreadedPdfPipelineOptions ->
        PdfFormatOption + ImageFormatOption (+ AudioFormatOption when ASR is enabled).

        The configuration is built once at adapter init. The DocumentConverter for it is
        leased from the process-wide converter pool, so model weights are loaded onto the
        GPU only once per configuration and process rather than once per adapter.

        Returns:
            ``{"format_options": ...}`` with AcceleratorOptions set, ``{}`` (default
            converter) for an unrecognised device, or None if docling is not available.
        """
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import (
                AcceleratorDevice,
                AcceleratorOptions,
                ThreadedPdfPipelineOptions,
            )
            from docling.document_converter import ImageFormatOption, PdfFormatOption

            # Normalise device string — validation already passed by factory, but cuda:N
            # must map to the bare CUDA enum value (device index is handled at torch level).
            normalised = (self.gpu_device or "").strip().lower()  # type: ignore[arg-type]
            base_device_map = {
                OperatorConstants.Extraction.DEVICE_MPS: AcceleratorDevice.MPS,
                OperatorConstants.Extraction.DEVICE_CUDA: AcceleratorDevice.CUDA,
                OperatorConstants.Extraction.DEVICE_XPU: AcceleratorDevice.XPU,
            }
            # cuda:N -> AcceleratorDevice.CUDA (index handled by torch runtime)
            device_key = (
                OperatorConstants.Extraction.DEVICE_CUDA
                if normalised.startswith(OperatorConstants.Extraction.DEVICE_CUDA)
                else normalised
            )
            accelerator_device = base_device_map.get(device_key)
            if accelerator_device is None:
                logger.warning("Unrecognised GPU device '%s' - falling back to default converter", self.gpu_device)
                return {}

            accelerator_options = AcceleratorOptions(
                num_threads=self.gpu_num_threads if self.gpu_num_threads is not None else 4,
                device=accelerator_device,
            )
            # Docling 2105 mapping: ThreadedPdfPipelineOptions carries AcceleratorOptions;
            # both PDF and IMAGE format options share the same pipeline options instance.
            threaded_options = ThreadedPdfPipelineOptions(accelerator_options=accelerator_options)

            format_options: dict[Any, Any] = {
                InputFormat.PDF: PdfFormatOption(pipeline_options=threaded_options),
                InputFormat.IMAGE: ImageFormatOption(pipeline_options=threaded_options),
            }

            # Include AudioFormatOption only when ASR is enabled and installed
            if self.use_asr_pipeline and _asr_available():
                try:
                    from docling.document_converter import AudioFormatOption
                    from docling.pipeline.asr_pipeline import AsrPipeline

                    asr_opts = self._configure_asr_engine()
                    format_options[InputFormat.AUDIO] = AudioFormatOption(
                        pipeline_cls=AsrPipeline,
                        pipeline_options=asr_opts,
                    )
                except ImportError as asr_exc:
                    logger.warning("Could not add ASR to GPU converter: %s", asr_exc)

            logger.info(
                "Built GPU-accelerated DocumentConverter options (device=%s, num_threads=%s)",
                self.gpu_device,
                accelerator_options.num_threads,
            )
            return {OperatorConstants.Config.FORMAT_OPTIONS: format_options}
        except ImportError as exc:
            logger.warning("Docling GPU acceleration unavailable (%s). Falling back to standard converter.", exc)
            return None

    def _build_ocr_options(self) -> Any:
        """Build a Docling OcrOptions instance from adapter OCR config.

        Each engine's optional dependency is imported independently so that a missing
        dep for one engine does not prevent other engines from loading.

        Returns:
            Configured OcrOptions subclass instance, or None to use Docling defaults.
        """
        import importlib

        _engine_imports: dict[str, tuple[str, str]] = {
            "auto": (_DOCLING_PIPELINE_OPTIONS_MODULE, "OcrAutoOptions"),
            "easyocr": (_DOCLING_PIPELINE_OPTIONS_MODULE, "EasyOcrOptions"),
            "tesserocr": (_DOCLING_PIPELINE_OPTIONS_MODULE, "TesseractOcrOptions"),
            "tesseract": (_DOCLING_PIPELINE_OPTIONS_MODULE, "TesseractCliOcrOptions"),
            "rapidocr": (_DOCLING_PIPELINE_OPTIONS_MODULE, "RapidOcrOptions"),
            "ocrmac": (_DOCLING_PIPELINE_OPTIONS_MODULE, "OcrMacOptions"),
            "kserve_v2_ocr": (_DOCLING_PIPELINE_OPTIONS_MODULE, "KserveV2OcrOptions"),
            "nemotron-ocr": (_DOCLING_PIPELINE_OPTIONS_MODULE, "NemotronOcrOptions"),
        }

        entry = _engine_imports.get(self._ocr_engine)
        if entry is None:
            logger.warning(
                "Unknown OCR engine '%s' - falling back to OcrAutoOptions. Valid engines: %s",
                self._ocr_engine,
                sorted(_engine_imports.keys()),
            )
            self._ocr_engine = "auto"
            entry = _engine_imports["auto"]

        module_name, cls_name = entry
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, cls_name)
        except (ImportError, AttributeError) as exc:
            logger.warning(
                "Could not import OCR options for engine '%s': %s - using Docling defaults",
                self._ocr_engine,
                exc,
            )
            return None

        opts = self._ocr_engine_options or {}
        try:
            return cls(**opts) if opts else cls()
        except Exception as exc:
            logger.warning(
                "Failed to build OCR options for engine '%s': %s - using Docling defaults",
                self._ocr_engine,
                exc,
            )
            return None

    def _configure_vlm_engine(self) -> Any:
        """Configure VLM pipeline options based on engine type.

        Returns:
            VlmPipelineOptions configured for the engine, or None to use Docling defaults

        Raises:
            ValueError: If required parameters are missing for the selected engine
        """
        # If no engine type and no provider config, return None to use Docling's defaults
        if not self.vlm_engine_type and not self.vlm_provider_config:
            logger.info("No VLM engine configuration provided - using Docling defaults")
            return None

        # Get pipeline options provider for the specified engine type
        provider = VlmPipelineOptionsProviderFactory.get_provider(engine_type=self.vlm_engine_type)

        # Create complete pipeline options using the provider
        provider_config = self.vlm_provider_config or {}
        return provider.create_pipeline_options(preset=self.vlm_preset, config=provider_config)

    def _configure_asr_engine(self) -> Any:
        """Configure ASR pipeline options based on model configuration.
        Returns:
            AsrPipelineOptions configured for the model, or None to use Docling defaults
        Raises:
            ValueError: If required parameters are missing for ASR
        """
        # If no model name specified, return None to use Docling's defaults
        if not self.asr_model_name:
            logger.info("No ASR model specified - using Docling defaults (whisper_turbo)")
            return None

        try:
            # Import the asr_model_specs module to access pre-configured model specs
            from docling.datamodel import asr_model_specs
            from docling.datamodel.pipeline_options import AsrPipelineOptions

            # Convert model name to uppercase constant name (e.g., "whisper_turbo" -> "WHISPER_TURBO")
            model_constant_name = self.asr_model_name.upper()

            # Get the pre-configured model spec from the module
            if hasattr(asr_model_specs, model_constant_name):
                asr_options = getattr(asr_model_specs, model_constant_name)
                logger.info("Using ASR model: %s (repo_id: %s)", self.asr_model_name, asr_options.repo_id)
            else:
                logger.warning(
                    "Invalid ASR model name: %s. Using default WHISPER_TURBO. "
                    "Valid options: whisper_tiny, whisper_small, whisper_medium, whisper_base, "
                    "whisper_large, whisper_turbo, and their _mlx/_native variants",
                    self.asr_model_name,
                )
                asr_options = asr_model_specs.WHISPER_TURBO

            return AsrPipelineOptions(asr_options=asr_options)

        except ImportError as e:
            logger.warning("ASR pipeline dependencies not available: %s", str(e))
            return None

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_library_config import (
            DoclingLibraryConfig,
        )

        return DoclingLibraryConfig

    def extract_single_document(self, *, file_path: str, binary_content: bytes, **kwargs: Any) -> dict[str, Any]:
        """Extract content from a single document using Docling.

        Performs template-based extraction if a template is provided, otherwise
        falls back to basic extraction. Extracts structured data, tables, and
        images based on configuration. Uses VLM pipeline if enabled.

        Args:
            file_path: Path to the document file (used for logging and temp file)
            binary_content: Binary content of the document
            **kwargs: Additional parameters:
                - template: Optional template dictionary for structured extraction

        Returns:
            Dictionary containing:
                - success: True if extraction succeeded
                - doc_content: Extracted content as JSON string (template mode) or markdown
                - structured_data: List of page-level structured data (template mode)
                - metadata: Extraction metadata (page_count, etc.)
                - error: Error message if extraction failed
        """
        if self.use_vlm_pipeline:
            logger.info(
                "Processing file with VLM pipeline (preset: %s, engine: %s): %s",
                self.vlm_preset,
                self.vlm_engine_type or OperatorConstants.Config.DEFAULT,
                file_path,
            )
        elif self.gpu_device:
            logger.info(
                "Processing file with GPU-accelerated standard pipeline (device: %s): %s", self.gpu_device, file_path
            )
        else:
            logger.info("Processing file with standard extraction: %s", file_path)

        try:
            from docling.datamodel.base_models import InputFormat
            from docling.document_converter import ImageFormatOption, PdfFormatOption
            from docling.pipeline.vlm_pipeline import VlmPipeline

            # Prepare converter configuration
            converter_config = None
            format_options: dict[InputFormat, Any] = {}

            if self.use_vlm_pipeline:
                # Configure VLM pipeline options
                pipeline_options = self._configure_vlm_engine()

                # Set up VLM pipeline for PDF and image formats
                format_options[InputFormat.PDF] = PdfFormatOption(
                    pipeline_cls=VlmPipeline,
                    pipeline_options=pipeline_options,
                )
                format_options[InputFormat.IMAGE] = ImageFormatOption(
                    pipeline_cls=VlmPipeline,
                    pipeline_options=pipeline_options,
                )

            if self.use_asr_pipeline and _asr_available():
                # Import ASR classes only when needed
                from docling.document_converter import AudioFormatOption
                from docling.pipeline.asr_pipeline import AsrPipeline

                # Configure ASR pipeline options
                asr_options = self._configure_asr_engine()

                # Set up ASR pipeline for audio and video formats
                # Note: Docling does not have a separate VIDEO InputFormat or VideoFormatOption
                # Video files are handled through AUDIO format with ASR pipeline
                format_options[InputFormat.AUDIO] = AudioFormatOption(
                    pipeline_cls=AsrPipeline,
                    pipeline_options=asr_options,
                )

            # Apply OCR configuration for standard (non-VLM) pipeline
            if not self.use_vlm_pipeline and (
                not self._ocr_enabled or self._ocr_engine != "rapidocr" or self._ocr_mode != "default"
            ):
                from docling.datamodel.pipeline_options import OcrMode, PdfPipelineOptions

                pdf_pipeline_opts = PdfPipelineOptions()
                pdf_pipeline_opts.do_ocr = self._ocr_enabled
                if self._ocr_enabled:
                    ocr_options = self._build_ocr_options()
                    if ocr_options is not None:
                        pdf_pipeline_opts.ocr_options = ocr_options
                    if self._ocr_mode != "default" and pdf_pipeline_opts.ocr_options is not None:
                        pdf_pipeline_opts.ocr_options.mode = OcrMode(self._ocr_mode)

                format_options[InputFormat.PDF] = PdfFormatOption(pipeline_options=pdf_pipeline_opts)
                format_options[InputFormat.IMAGE] = ImageFormatOption(pipeline_options=pdf_pipeline_opts)

            # Only set converter_config if we have format options
            if format_options:
                converter_config = {OperatorConstants.Config.FORMAT_OPTIONS: format_options}

            # When GPU acceleration is active use the pre-built GPU configuration; the
            # pooled converter for it keeps its model weights loaded across documents.
            if self.gpu_device and self._gpu_converter_config is not None:
                result = OperatorUtils.extract_content(
                    file_path=file_path,
                    binary_content=binary_content,
                    converter_config=self._gpu_converter_config or None,
                    additional_formats=self.additional_formats,
                    doc_format=self.global_config.get(
                        OperatorConstants.DOC_FORMAT_KEY, OperatorConstants.DOC_FORMAT_DEFAULT
                    ),
                )
            else:
                # Use common extraction method with output_formats
                result = OperatorUtils.extract_content(
                    file_path=file_path,
                    binary_content=binary_content,
                    converter_config=converter_config,
                    additional_formats=self.additional_formats,
                    doc_format=self.global_config.get(
                        OperatorConstants.DOC_FORMAT_KEY, OperatorConstants.DOC_FORMAT_DEFAULT
                    ),
                )

            # Add GPU-specific metadata if extraction succeeded and GPU was used
            if self.gpu_device and result.get(OperatorConstants.Extraction.SUCCESS):
                result[OperatorConstants.Metadata.METADATA][OperatorConstants.Extraction.DEVICE] = self.gpu_device

            # Add VLM-specific metadata if extraction succeeded and VLM was used
            if self.use_vlm_pipeline and result.get(OperatorConstants.Extraction.SUCCESS):
                result[OperatorConstants.Metadata.METADATA][OperatorConstants.Config.VLM_PRESET] = self.vlm_preset
                result[OperatorConstants.Metadata.METADATA][OperatorConstants.Config.VLM_ENGINE_TYPE] = (
                    self.vlm_engine_type or OperatorConstants.Config.VLM_ENGINE_TRANSFORMERS
                )
            # Add ASR-specific metadata if extraction succeeded and ASR was used
            if self.use_asr_pipeline and result.get(OperatorConstants.Extraction.SUCCESS):
                result[OperatorConstants.Metadata.METADATA][OperatorConstants.Config.ASR_MODEL_NAME] = (
                    self.asr_model_name or OperatorConstants.Config.ASR_MODEL_DEFAULT
                )
            return result

        except ImportError as e:
            if self.use_vlm_pipeline:
                logger.error("VLM pipeline dependencies not available. Install with: pip install docling[vlm]")
                logger.error("Error: %s", str(e))
                return {
                    OperatorConstants.Extraction.SUCCESS: False,
                    OperatorConstants.Extraction.ERROR: "VLM pipeline dependencies not available. Install docling[vlm]",
                    OperatorConstants.Columns.DOC_COLUMN_DEFAULT: None,
                }
            raise
        except Exception as e:
            logger.error("Error during text extraction: %s", str(e))
            return {
                OperatorConstants.Extraction.SUCCESS: False,
                OperatorConstants.Extraction.ERROR: str(e),
                OperatorConstants.Columns.DOC_COLUMN_DEFAULT: None,
            }
