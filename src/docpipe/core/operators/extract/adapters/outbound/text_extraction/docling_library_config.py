"""Pydantic config model for the Docling Library text extraction adapter."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from docpipe.core.operators.extract.adapters.outbound.text_extraction.ocr_config import OcrConfig

ADAPTER_NAME = "docling_library"


class VlmPipelineConfig(BaseModel):
    """User-facing VLM pipeline configuration nested inside DoclingLibraryConfig."""

    model_config = ConfigDict(extra="ignore")

    preset: str = Field(
        default="granite_docling",
        description="VLM preset name (e.g., 'granite_docling', 'fast'). Defaults to 'granite_docling'.",
    )
    engine: Literal["transformers", "mlx", "api", "api_ollama", "api_openai", "api_watsonx", "api_lmstudio"] = Field(
        default="transformers",
        description="VLM engine.",
    )
    engine_options: dict[str, Any] | None = Field(
        default=None,
        description="Engine-specific configuration (e.g., api_base, model_id, api_key).",
    )


class AsrPipelineConfig(BaseModel):
    """User-facing ASR pipeline configuration nested inside DoclingLibraryConfig."""

    model_config = ConfigDict(extra="ignore")

    model_id: str | None = Field(
        default=None,
        description="ASR model name (e.g., whisper_turbo, whisper_small, whisper_medium). Valid values: whisper_tiny, whisper_small, whisper_medium, whisper_base, whisper_large, whisper_turbo, and their _mlx/_native variants.",
    )


class AcceleratorConfig(BaseModel):
    """GPU accelerator options nested inside StandardPipelineConfig.

    Only 'device' and 'num_threads' are accepted — the factory rejects any
    additional keys at runtime, so this model is intentionally strict.
    """

    model_config = ConfigDict(extra="forbid")

    device: str | None = Field(
        default=None,
        description=(
            "GPU device for acceleration. Accepted values: 'mps' (Apple Silicon), 'cuda' (NVIDIA), "
            "'cuda:<index>' (e.g. 'cuda:0'), 'xpu' (Intel). "
            "When omitted, the best available device is auto-detected via torch (CUDA -> MPS -> XPU)."
        ),
    )
    num_threads: int | None = Field(
        default=None,
        description="Number of CPU-side pipeline threads. Must be a positive integer. Defaults to 4 when not set.",
    )


class StandardPipelineConfig(BaseModel):
    """Standard pipeline acceleration block nested inside DoclingLibraryConfig."""

    model_config = ConfigDict(extra="forbid")

    accelerator: AcceleratorConfig | None = Field(
        default=None,
        description=(
            "GPU accelerator options for PDF and image processing. When present, the GPU DocumentConverter "
            "is pooled process-wide and reused across documents and micro-batches. "
            "Requires max_workers=1 and use_processes=false. Cannot be combined with vlm_pipeline."
        ),
    )


class DoclingLibraryConfig(BaseModel):
    """User-facing provider_config for the Docling Library text extraction provider.

    Describes the fields the user writes inside ``text_extraction.provider_config``
    when selecting the ``docling_library`` provider in an Extract operator node.
    """

    model_config = ConfigDict(extra="ignore")

    vlm_pipeline: VlmPipelineConfig | None = Field(
        default=None,
        description="Vision-Language Model pipeline configuration for enhanced document extraction. Provide an empty object {} to enable with defaults, or omit to disable.",
    )
    asr_pipeline: AsrPipelineConfig | None = Field(
        default=None,
        description="Automatic Speech Recognition pipeline configuration for audio/video extraction. Provide an empty object {} to enable with defaults, or omit to disable.",
    )
    additional_formats: list[Literal["markdown", "html", "json", "text", "doctags", "doclang"]] = Field(
        default_factory=list,
        description=(
            "Additional output formats to generate beyond the primary format. "
            "When doc_format=markdown (default), markdown is already the primary format so including "
            "it here is a no-op. When doc_format=doclang, add 'markdown' here to also produce a "
            "markdown column alongside the primary DocLang content column."
        ),
    )
    standard_pipeline: StandardPipelineConfig | None = Field(
        default=None,
        description=(
            "Standard pipeline acceleration configuration. Omit entirely for default CPU behaviour. "
            "When present, enables GPU-accelerated extraction via the accelerator block."
        ),
    )
    ocr: OcrConfig | None = Field(
        default=None,
        description=(
            "OCR configuration block. Omit to use defaults (OCR enabled, rapidocr engine, default mode). "
            "Provide an empty object {} to enable OCR explicitly with defaults. "
            "Not applied when vlm_pipeline is active — VLM replaces OCR."
        ),
    )
