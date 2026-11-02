"""Factory for creating text extraction adapters.

This factory creates appropriate text extraction adapter instances based on the
extraction provider and configuration. It supports multiple extraction strategies:
- DOCLING_LIBRARY: Local Docling extraction with optional VLM support
- DOCLING_SERVE: Remote extraction via Docling Serve API
"""

import logging
from typing import Any, ClassVar

import re2 as re

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.extract.domain.models import DoclingServeConfig, TextExtractionMode
from docpipe.core.operators.extract.ports.outbound.text_extraction import TextExtractionPort
from docpipe.utils.infrastructure.logging import get_logger

logger: logging.Logger = get_logger()


class TextExtractionAdapterFactory:
    """Factory for creating text extraction adapters.

    This factory creates appropriate adapter instances based on extraction provider
    and validates configuration requirements for each adapter type.

    It also maintains a class registry so that third-party adapters can
    self-register via ``@register_text_extraction_adapter``.  The operator uses
    this registry in ``get_metadata()`` to auto-discover provider config schemas
    without needing manual imports.

    Supported Providers:
        - TextExtractionMode.DOCLING_LIBRARY: Local Docling extraction with optional VLM
        - TextExtractionMode.DOCLING_SERVE: Remote Docling Serve API extraction

    Example Usage:
        # Create Docling adapter (standard extraction)
        config = {
            "doc_column": "document"
        }
        adapter = TextExtractionAdapterFactory.create_adapter(
            mode=TextExtractionMode.DOCLING_LIBRARY,
            config=config,
            max_workers=4
        )

        # Create Docling adapter with VLM enabled
        vlm_config = {
            "doc_column": "document",
            "provider_config": {
                "vlm_pipeline": {
                    "preset": "granite_docling",
                    "engine": "api_ollama",
                    "engine_options": {
                        "api_base": "http://localhost:11434",
                        "model_id": "ibm/granite-docling:258m"
                    }
                }
            }
        }
        vlm_adapter = TextExtractionAdapterFactory.create_adapter(
            mode=TextExtractionMode.DOCLING_LIBRARY,
            text_extraction_config=vlm_config,
            global_config={},
            max_workers=2
        )

        # Create Docling Serve adapter
        serve_config = {
            "docling_serve_config": {
                "base_url": "http://localhost:5001",
                "timeout": 300,
                "do_ocr": True
            },
            "doc_column": "document"
        }
        serve_adapter = TextExtractionAdapterFactory.create_adapter(
            mode=TextExtractionMode.DOCLING_SERVE,
            config=serve_config
        )
    """

    # Registry of adapter classes keyed by ADAPTER_NAME (populated via @register_text_extraction_adapter).
    _registry: ClassVar[dict[str, type[TextExtractionPort]]] = {}

    @classmethod
    def register(cls, adapter_class: type[TextExtractionPort]) -> type[TextExtractionPort]:
        """Register an adapter class in the schema-discovery registry.

        Called automatically by the ``@register_text_extraction_adapter`` decorator.

        Args:
            adapter_class: Concrete subclass of ``TextExtractionPort``.

        Returns:
            The adapter class (for decorator chaining).

        Raises:
            ValueError: If the class does not define ``ADAPTER_NAME``.
        """
        if not hasattr(adapter_class, "ADAPTER_NAME") or not adapter_class.ADAPTER_NAME:
            msg = f"Adapter {adapter_class.__name__} must define ADAPTER_NAME"
            raise ValueError(msg)

        name = adapter_class.ADAPTER_NAME.lower()
        cls._registry[name] = adapter_class
        return adapter_class

    @classmethod
    def list_adapters(cls) -> list[str]:
        """Return names of all registered adapters.

        Returns:
            List of registered adapter names.
        """
        return list(cls._registry.keys())

    @staticmethod
    def build_adapter_config(*, mode: TextExtractionMode, text_extraction_config: dict[str, Any]) -> dict[str, Any]:
        """Build adapter-specific configuration from nested text_extraction config.

        This method extracts and transforms the nested text_extraction configuration into
        adapter-specific configuration, handling provider-specific requirements.

        Args:
            mode: Text extraction provider (DOCLING_LIBRARY, DOCLING_SERVE)
            text_extraction_config: Nested text_extraction configuration dictionary

        Returns:
            Adapter-specific configuration dictionary

        Raises:
            ValueError: If provider is unsupported or configuration is invalid
        """
        # Extract provider_config from nested structure
        provider_config = text_extraction_config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})

        # Schema checks: standard_pipeline and accelerator must be dicts when present
        standard_pipeline_raw = provider_config.get(OperatorConstants.Extraction.STANDARD_PIPELINE)
        if standard_pipeline_raw is not None and not isinstance(standard_pipeline_raw, dict):
            msg = f"provider_config.standard_pipeline must be a JSON object, got {type(standard_pipeline_raw).__name__}"
            raise ValueError(msg)
        accelerator_raw = (
            (standard_pipeline_raw or {}).get(OperatorConstants.Extraction.ACCELERATOR)
            if isinstance(standard_pipeline_raw, dict)
            else None
        )
        if accelerator_raw is not None and not isinstance(accelerator_raw, dict):
            msg = (
                "provider_config.standard_pipeline.accelerator must be a JSON object, "
                f"got {type(accelerator_raw).__name__}"
            )
            raise ValueError(msg)
        if isinstance(accelerator_raw, dict):
            allowed_accel_keys = {OperatorConstants.Extraction.DEVICE, OperatorConstants.Extraction.NUM_THREADS}
            unknown_keys = set(accelerator_raw.keys()) - allowed_accel_keys
            if unknown_keys:
                msg = (
                    f"Unknown accelerator key(s): {sorted(unknown_keys)}. Only 'device' and 'num_threads' are accepted."
                )
                raise ValueError(msg)

        # Common configuration for all text providers
        adapter_config: dict[str, Any] = {
            OperatorConstants.Config.DOC_COLUMN: text_extraction_config.get(
                OperatorConstants.Config.DOC_COLUMN, OperatorConstants.Columns.DOC_COLUMN_DEFAULT
            ),
            OperatorConstants.Extraction.ADDITIONAL_FORMATS: provider_config.get(
                OperatorConstants.Extraction.ADDITIONAL_FORMATS, []
            ),
            OperatorConstants.Config.COMMON_LOG_ARGUMENTS: text_extraction_config.get(
                OperatorConstants.Config.COMMON_LOG_ARGUMENTS, {}
            ),
        }

        # Add mode-specific configuration from provider_config
        if mode == TextExtractionMode.DOCLING_LIBRARY:
            # VLM configuration comes from provider_config.vlm_pipeline
            vlm_pipeline = provider_config.get(OperatorConstants.Config.VLM_PIPELINE)
            vlm_pipeline_config = vlm_pipeline if vlm_pipeline is not None else {}

            adapter_config.update(
                {
                    OperatorConstants.Config.USE_VLM_PIPELINE: vlm_pipeline is not None,
                    OperatorConstants.Config.VLM_PRESET: vlm_pipeline_config.get(
                        OperatorConstants.Config.PRESET, OperatorConstants.Config.VLM_PRESET_DEFAULT
                    ),
                    OperatorConstants.Config.VLM_ENGINE_TYPE: vlm_pipeline_config.get(
                        OperatorConstants.Config.ENGINE, OperatorConstants.Config.VLM_ENGINE_TRANSFORMERS
                    ),
                    OperatorConstants.Config.VLM_PROVIDER_CONFIG: vlm_pipeline_config.get(
                        OperatorConstants.Config.ENGINE_OPTIONS
                    ),
                }
            )

            # ASR configuration comes from provider_config.asr_pipeline
            asr_pipeline = provider_config.get(OperatorConstants.Config.ASR_PIPELINE)
            asr_pipeline_config = asr_pipeline if asr_pipeline is not None else {}

            adapter_config.update(
                {
                    OperatorConstants.Config.USE_ASR_PIPELINE: asr_pipeline is not None,
                    OperatorConstants.Config.ASR_MODEL_NAME: asr_pipeline_config.get(
                        OperatorConstants.Config.MODEL_ID, OperatorConstants.Config.ASR_MODEL_DEFAULT
                    ),
                }
            )

            # GPU / standard pipeline accelerator config from provider_config.standard_pipeline
            standard_pipeline = provider_config.get(OperatorConstants.Extraction.STANDARD_PIPELINE, {})
            accelerator = standard_pipeline.get(OperatorConstants.Extraction.ACCELERATOR, {})
            gpu_device = accelerator.get(OperatorConstants.Extraction.DEVICE)
            gpu_num_threads = accelerator.get(OperatorConstants.Extraction.NUM_THREADS)

            # If the user included an accelerator block but omitted device, auto-detect
            # the best available GPU so they don't have to specify it explicitly.
            if accelerator and gpu_device is None:
                gpu_device = TextExtractionAdapterFactory._auto_detect_device()
                if gpu_device is not None:
                    logger.info("No accelerator device specified - auto-detected: %s", gpu_device)
                else:
                    logger.warning(
                        "Accelerator block present but no GPU device found via torch. "
                        "Falling back to standard CPU extraction."
                    )

            if gpu_device is not None:
                adapter_config[OperatorConstants.Extraction.DEVICE] = gpu_device
            if gpu_num_threads is not None:
                adapter_config[OperatorConstants.Extraction.NUM_THREADS] = gpu_num_threads

            # OCR configuration from provider_config.ocr
            ocr_raw = provider_config.get(OperatorConstants.Config.OCR_BLOCK)
            if ocr_raw is not None:
                if not isinstance(ocr_raw, dict):
                    msg = f"provider_config.ocr must be a JSON object, got {type(ocr_raw).__name__}"
                    raise ValueError(msg)
                TextExtractionAdapterFactory._validate_ocr_config(ocr_raw)
                adapter_config[OperatorConstants.Config.OCR_BLOCK] = ocr_raw

        elif mode == TextExtractionMode.DOCLING_SERVE:
            # Build docling_serve_config dictionary from provider_config
            docling_serve_config = {
                OperatorConstants.Config.BASE_URL: provider_config.get(
                    OperatorConstants.Config.BASE_URL, "http://localhost:5001"
                ),
                OperatorConstants.Processing.TIMEOUT: provider_config.get(OperatorConstants.Processing.TIMEOUT, 300),
                OperatorConstants.Processing.POLL_INTERVAL: provider_config.get(
                    OperatorConstants.Processing.POLL_INTERVAL, 2
                ),
                OperatorConstants.Processing.MAX_RETRIES: provider_config.get(
                    OperatorConstants.Processing.MAX_RETRIES, 3
                ),
                OperatorConstants.Processing.VERIFY_SSL: provider_config.get(
                    OperatorConstants.Processing.VERIFY_SSL, True
                ),
                OperatorConstants.Config.DO_OCR: provider_config.get(OperatorConstants.Config.DO_OCR, True),
                OperatorConstants.Config.PDF_BACKEND: provider_config.get(
                    OperatorConstants.Config.PDF_BACKEND, "dlparse_v2"
                ),
                OperatorConstants.Config.IMAGE_EXPORT_MODE: provider_config.get(
                    OperatorConstants.Config.IMAGE_EXPORT_MODE, "placeholder"
                ),
            }

            # Add optional parameters if provided
            if provider_config.get(OperatorConstants.Config.API_KEY):
                docling_serve_config[OperatorConstants.Config.API_KEY] = provider_config[
                    OperatorConstants.Config.API_KEY
                ]

            if provider_config.get(OperatorConstants.Config.OCR_ENGINE):
                docling_serve_config[OperatorConstants.Config.OCR_ENGINE] = provider_config[
                    OperatorConstants.Config.OCR_ENGINE
                ]

            if provider_config.get(OperatorConstants.Config.TABLE_MODE):
                docling_serve_config[OperatorConstants.Config.TABLE_MODE] = provider_config[
                    OperatorConstants.Config.TABLE_MODE
                ]

            if provider_config.get(OperatorConstants.Config.OCR_LANGUAGES):
                docling_serve_config[OperatorConstants.Config.OCR_LANGUAGES] = provider_config[
                    OperatorConstants.Config.OCR_LANGUAGES
                ]

            # Forward new canonical ocr block if present
            ocr_raw = provider_config.get(OperatorConstants.Config.OCR_BLOCK)
            if ocr_raw is not None:
                if not isinstance(ocr_raw, dict):
                    msg = f"provider_config.ocr must be a JSON object, got {type(ocr_raw).__name__}"
                    raise ValueError(msg)
                TextExtractionAdapterFactory._validate_ocr_config(ocr_raw)
                docling_serve_config[OperatorConstants.Config.OCR_BLOCK] = ocr_raw

            adapter_config[OperatorConstants.Config.DOCLING_SERVE_CONFIG] = docling_serve_config

        else:
            msg = (
                f"Unsupported extraction provider: {mode}. Supported providers: {[m.value for m in TextExtractionMode]}"
            )
            raise ValueError(msg)

        return adapter_config

    @staticmethod
    def create_adapter(
        *,
        mode: TextExtractionMode,
        text_extraction_config: dict[str, Any],
        global_config: dict[str, Any],
        max_workers: int = 4,
        use_processes: bool = False,
    ) -> TextExtractionPort:
        """Create appropriate text extraction adapter based on provider.

        Args:
            mode: Extraction provider (DOCLING_LIBRARY, DOCLING_SERVE)
            text_extraction_config: Nested text_extraction configuration dictionary
            global_config: Global operator configuration (for job tracking, etc.)
            max_workers: Number of parallel workers (default: 4)
            use_processes: Use ProcessPoolExecutor instead of ThreadPoolExecutor (default: False)

        Returns:
            Configured TextExtractionPort adapter instance

        Raises:
            ValueError: If provider is unsupported or config is invalid
        """
        # Build adapter-specific configuration from nested text_extraction config
        adapter_config = TextExtractionAdapterFactory.build_adapter_config(
            mode=mode, text_extraction_config=text_extraction_config
        )

        # Merge with global config for job tracking and other global settings
        # IMPORTANT: Merge global_config first to preserve keys like ingest_source
        full_config = {**global_config, **adapter_config, "max_workers": max_workers, "use_processes": use_processes}

        if mode == TextExtractionMode.DOCLING_LIBRARY:
            from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter import DoclingAdapter

            # Check if VLM is enabled
            use_vlm = adapter_config.get(OperatorConstants.Config.USE_VLM_PIPELINE, False)
            gpu_device = adapter_config.get(OperatorConstants.Extraction.DEVICE)

            if use_vlm:
                TextExtractionAdapterFactory._validate_vlm_config(adapter_config)
                logger.info(
                    "Creating DoclingAdapter with VLM enabled (preset: %s) and %s workers",
                    adapter_config.get(
                        OperatorConstants.Config.VLM_PRESET, OperatorConstants.Config.VLM_PRESET_DEFAULT
                    ),
                    max_workers,
                )
            elif gpu_device:
                TextExtractionAdapterFactory._validate_gpu_config(
                    adapter_config=adapter_config,
                    max_workers=max_workers,
                    use_processes=use_processes,
                )
                logger.info(
                    "Creating DoclingAdapter with GPU acceleration (device: %s) and %s workers",
                    gpu_device,
                    max_workers,
                )
            else:
                TextExtractionAdapterFactory._validate_docling_config(adapter_config)
                logger.info("Creating DoclingAdapter for provider: %s with %s workers", mode.value, max_workers)

            return DoclingAdapter(config=full_config)

        if mode == TextExtractionMode.DOCLING_SERVE:
            from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter import (
                DoclingServeAdapter,
            )

            TextExtractionAdapterFactory._validate_docling_serve_config(adapter_config)
            logger.info(
                "Creating DoclingServeAdapter with URL: %s",
                adapter_config.get(OperatorConstants.Config.DOCLING_SERVE_CONFIG, {}).get(
                    OperatorConstants.Config.BASE_URL, "http://0.0.0.0:5001"
                ),
            )
            return DoclingServeAdapter(config=full_config)

        msg = f"Unsupported extraction provider: {mode}. Supported providers: {[m.value for m in TextExtractionMode]}"
        raise ValueError(msg)

    @staticmethod
    def _validate_gpu_config(*, adapter_config: dict[str, Any], max_workers: int, use_processes: bool) -> None:
        """Validate configuration for GPU-accelerated standard pipeline extraction.

        GPU acceleration requires max_workers=1 and use_processes=False because
        Docling's standard pipeline with a GPU accelerator device is not safe to
        run across multiple threads or processes simultaneously.

        Additionally, VLM and GPU acceleration cannot be combined — the VLM
        pipeline has its own device management.

        Args:
            adapter_config: Adapter configuration dictionary (must contain 'device')
            max_workers: Number of parallel workers configured by the caller
            use_processes: Whether ProcessPoolExecutor was requested

        Raises:
            ValueError: If any GPU constraint is violated
        """
        gpu_device = adapter_config.get(OperatorConstants.Extraction.DEVICE)

        # Normalise and validate device string.
        # Accepted forms: mps, cuda, cuda:<non-negative integer index>, xpu
        if not isinstance(gpu_device, str):
            msg = f"Invalid GPU device {gpu_device!r}. Must be a string."
            raise ValueError(msg)

        normalised = gpu_device.strip().lower()
        base_devices = {
            OperatorConstants.Extraction.DEVICE_MPS,
            OperatorConstants.Extraction.DEVICE_CUDA,
            OperatorConstants.Extraction.DEVICE_XPU,
        }
        cuda_index_pattern = re.compile(r"^cuda:\d+$")
        if normalised not in base_devices and not cuda_index_pattern.match(normalised):
            msg = (
                f"Invalid GPU device '{gpu_device}'. "
                f"Supported forms: {sorted(base_devices)} or 'cuda:<index>' (e.g. 'cuda:0')."
            )
            raise ValueError(msg)

        if adapter_config.get(OperatorConstants.Config.USE_VLM_PIPELINE, False):
            msg = (
                "GPU acceleration (standard_pipeline.accelerator.device) cannot be combined "
                "with VLM pipeline. Use one or the other."
            )
            raise ValueError(msg)

        if max_workers != 1:
            msg = (
                f"GPU acceleration requires max_workers=1, got max_workers={max_workers}. "
                "Set max_workers to 1 in text_extraction config when using a GPU device."
            )
            raise ValueError(msg)

        if use_processes:
            msg = (
                "GPU acceleration requires use_processes=false. "
                "ProcessPoolExecutor cannot share a GPU-loaded model across processes."
            )
            raise ValueError(msg)

        num_threads = adapter_config.get(OperatorConstants.Extraction.NUM_THREADS)
        # isinstance(True, int) is True in Python — booleans must be rejected explicitly
        if num_threads is not None and (
            isinstance(num_threads, bool) or not isinstance(num_threads, int) or num_threads < 1
        ):
            msg = f"num_threads must be a positive integer, got: {num_threads!r}"
            raise ValueError(msg)

        # Runtime device availability checks — fail early before any model is loaded
        TextExtractionAdapterFactory._check_device_availability(normalised)

    @staticmethod
    def _auto_detect_device() -> str | None:
        """Detect the best available GPU device using torch.

        Probes torch backends in priority order: CUDA → MPS → XPU.
        Returns the device string (e.g. ``"cuda"``, ``"mps"``, ``"xpu"``) or
        ``None`` when torch is not installed or no supported GPU is found.
        """
        try:
            import torch
        except ImportError:
            return None

        if torch.cuda.is_available():
            return OperatorConstants.Extraction.DEVICE_CUDA
        if torch.backends.mps.is_built() and torch.backends.mps.is_available():
            return OperatorConstants.Extraction.DEVICE_MPS
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            return OperatorConstants.Extraction.DEVICE_XPU
        return None

    @staticmethod
    def _check_device_availability(normalised_device: str) -> None:
        """Check that the requested GPU device is available at runtime via torch.

        Args:
            normalised_device: Lowercase device string (e.g. 'mps', 'cuda', 'cuda:0', 'xpu')

        Raises:
            ValueError: If torch is not installed or the device is unavailable
        """
        try:
            import torch
        except ImportError as exc:
            msg = "GPU acceleration requires torch to be installed. Install with: uv pip install torch"
            raise ValueError(msg) from exc

        if normalised_device == OperatorConstants.Extraction.DEVICE_MPS:
            if not (torch.backends.mps.is_built() and torch.backends.mps.is_available()):
                msg = (
                    "GPU device 'mps' is not available in this environment. "
                    "MPS requires an Apple Silicon Mac with a compatible PyTorch build."
                )
                raise ValueError(msg)
        elif normalised_device.startswith(OperatorConstants.Extraction.DEVICE_CUDA):
            if not torch.cuda.is_available():
                msg = (
                    f"GPU device '{normalised_device}' is not available. "
                    "CUDA requires a compatible NVIDIA GPU and CUDA-enabled PyTorch."
                )
                raise ValueError(msg)
            if ":" in normalised_device:
                index = int(normalised_device.split(":")[1])
                device_count = torch.cuda.device_count()
                if index >= device_count:
                    msg = f"CUDA device index {index} is out of range (available devices: 0-{device_count - 1})."
                    raise ValueError(msg)
        elif normalised_device == OperatorConstants.Extraction.DEVICE_XPU:
            if not (hasattr(torch, "xpu") and torch.xpu.is_available()):
                msg = (
                    "GPU device 'xpu' is not available in this environment. "
                    "XPU requires Intel hardware and a compatible PyTorch build."
                )
                raise ValueError(msg)

    @staticmethod
    def _validate_docling_config(config: dict[str, Any]) -> None:
        """Validate configuration for DoclingAdapter.

        Args:
            config: Configuration dictionary to validate

        Raises:
            ValueError: If required configuration is missing or invalid
        """
        # Optional parameters - no strict validation needed
        # DoclingAdapter handles defaults internally
        use_template = config.get(OperatorConstants.Config.USE_TEMPLATE, False)

        if use_template:
            template = config.get(OperatorConstants.Config.TEMPLATE)
            if template is not None and not isinstance(template, dict):
                msg = "DoclingAdapter 'template' must be a dictionary when provided"
                raise ValueError(msg)

        # Validate boolean flags if present
        for flag in [
            OperatorConstants.Config.EXPAND_EXTRACTED_DATA,
        ]:
            if flag in config and not isinstance(config[flag], bool):
                msg = f"DoclingAdapter '{flag}' must be a boolean"
                raise ValueError(msg)

    @staticmethod
    def _validate_vlm_config(config: dict[str, Any]) -> None:
        """Validate configuration for DoclingAdapter with VLM enabled.

        Args:
            config: Configuration dictionary to validate

        Raises:
            ValueError: If required configuration is missing or invalid
        """
        # VLM preset is optional (defaults to "granite_docling")
        vlm_preset = config.get(OperatorConstants.Config.VLM_PRESET)
        if vlm_preset is not None and not isinstance(vlm_preset, str):
            msg = "DoclingAdapter 'vlm_preset' must be a string"
            raise ValueError(msg)

        # VLM engine type is optional
        vlm_engine_type = config.get(OperatorConstants.Config.VLM_ENGINE_TYPE)
        if vlm_engine_type is not None and not isinstance(vlm_engine_type, str):
            msg = "DoclingAdapter 'vlm_engine_type' must be a string"
            raise ValueError(msg)

        # VLM provider config is optional
        vlm_provider_config = config.get(OperatorConstants.Config.VLM_PROVIDER_CONFIG)
        if vlm_provider_config is not None and not isinstance(vlm_provider_config, dict):
            msg = "DoclingAdapter 'vlm_provider_config' must be a dictionary"
            raise ValueError(msg)

    @staticmethod
    def _validate_docling_serve_config(config: dict[str, Any]) -> None:
        """Validate configuration for DoclingServeAdapter.

        Args:
            config: Configuration dictionary to validate

        Raises:
            ValueError: If required configuration is missing or invalid
        """
        docling_serve_config = config.get(OperatorConstants.Config.DOCLING_SERVE_CONFIG)

        if not docling_serve_config:
            msg = "DoclingServeAdapter requires 'docling_serve_config' dictionary"
            raise ValueError(msg)

        if not isinstance(docling_serve_config, dict):
            msg = "DoclingServeAdapter 'docling_serve_config' must be a dictionary"
            raise ValueError(msg)

        # Validate base_url if present
        base_url = docling_serve_config.get(OperatorConstants.Config.BASE_URL)
        if base_url is not None and not isinstance(base_url, str):
            msg = "docling_serve_config 'base_url' must be a string"
            raise ValueError(msg)

        # Validate numeric parameters if present
        for param in [
            OperatorConstants.Processing.TIMEOUT,
            OperatorConstants.Processing.POLL_INTERVAL,
            OperatorConstants.Processing.MAX_RETRIES,
        ]:
            value = docling_serve_config.get(param)
            if value is not None and not isinstance(value, (int, float)):
                msg = f"docling_serve_config '{param}' must be a number"
                raise ValueError(msg)

        # Validate boolean flags if present
        do_ocr = docling_serve_config.get(OperatorConstants.Config.DO_OCR)
        if do_ocr is not None and not isinstance(do_ocr, bool):
            msg = "docling_serve_config 'do_ocr' must be a boolean"
            raise ValueError(msg)

    @staticmethod
    def _build_docling_serve_config(config: dict[str, Any]) -> DoclingServeConfig:
        """Build DoclingServeConfig from configuration dictionary.

        This helper method constructs a DoclingServeConfig dataclass instance
        from the configuration dictionary, applying defaults where needed.

        Args:
            config: Configuration dictionary containing docling_serve_config

        Returns:
            DoclingServeConfig instance

        Raises:
            ValueError: If required configuration is missing
        """
        docling_serve_config = config.get(OperatorConstants.Config.DOCLING_SERVE_CONFIG, {})

        return DoclingServeConfig(
            url=docling_serve_config.get(OperatorConstants.Config.BASE_URL, "http://localhost:8080"),
            timeout=docling_serve_config.get(OperatorConstants.Processing.TIMEOUT, 300),
            max_retries=docling_serve_config.get(OperatorConstants.Processing.MAX_RETRIES, 3),
            additional_params=docling_serve_config.get("additional_params", {}),
        )

    @staticmethod
    def _validate_ocr_config(ocr_block: dict[str, Any]) -> None:
        """Validate an OCR config block from provider_config.ocr.

        Args:
            ocr_block: The ocr sub-dict from provider_config.

        Raises:
            ValueError: If engine or mode values are invalid, or engine_options is not a dict.
        """
        from docpipe.core.operators.extract.adapters.outbound.text_extraction.ocr_config import OcrConfig

        valid_engines = set(OcrConfig.model_fields["engine"].annotation.__args__)
        valid_modes = set(OcrConfig.model_fields["mode"].annotation.__args__)

        engine = ocr_block.get("engine", "rapidocr")
        if engine not in valid_engines:
            msg = f"Invalid OCR engine '{engine}'. Valid engines: {sorted(valid_engines)}"
            raise ValueError(msg)

        mode = ocr_block.get("mode", "default")
        if mode not in valid_modes:
            msg = f"Invalid OCR mode '{mode}'. Valid modes: {sorted(valid_modes)}"
            raise ValueError(msg)

        engine_options = ocr_block.get("engine_options")
        if engine_options is not None and not isinstance(engine_options, dict):
            msg = f"ocr.engine_options must be a JSON object, got {type(engine_options).__name__}"
            raise ValueError(msg)

    @staticmethod
    def get_supported_modes() -> list[str]:
        """Get list of supported extraction providers.

        Returns:
            List of supported extraction provider values
        """
        return [mode.value for mode in TextExtractionMode]


def register_text_extraction_adapter(adapter_class: type[TextExtractionPort]) -> type[TextExtractionPort]:
    """Decorator to register a text extraction adapter for schema discovery.

    This decorator automatically registers the adapter class with
    ``TextExtractionAdapterFactory``.

    Args:
        adapter_class: Concrete subclass of ``TextExtractionPort``.

    Returns:
        The adapter class (unchanged).

    Example::

        @register_text_extraction_adapter
        class DoclingServeAdapter(TextExtractionPort):
            ADAPTER_NAME = "docling_serve"
            ADAPTER_DISPLAY_NAME = "Docling Serve"
            ...
    """
    return TextExtractionAdapterFactory.register(adapter_class)
