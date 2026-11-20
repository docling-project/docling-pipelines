# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pydantic config model for the Docling Serve text extraction adapter."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from docpipe.core.operators.extract.adapters.outbound.text_extraction.ocr_config import OcrConfig

ADAPTER_NAME = "docling_serve"


class DoclingServeConfig(BaseModel):
    """User-facing provider_config for the docling_serve text extraction provider.

    Describes the fields the user writes inside ``text_extraction.provider_config``
    when selecting the ``docling_serve`` provider in an Extract operator node.
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "api_key",
        "base_url",
    )

    model_config = ConfigDict(extra="ignore")

    base_url: str = Field(
        default="http://0.0.0.0:5001",
        description="Base URL of the Docling Serve API (e.g., http://0.0.0.0:5001).",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for authenticating with the Docling Serve endpoint (if required).",
    )
    timeout: int = Field(
        default=300,
        description="Request timeout in seconds.",
    )
    poll_interval: int = Field(
        default=2,
        description="Polling interval in seconds when waiting for async extraction results.",
    )
    max_retries: int = Field(
        default=3,
        description="Maximum number of retries on transient failures.",
    )
    verify_ssl: bool = Field(
        default=True,
        description="Whether to verify the server's SSL certificate.",
    )
    ocr: OcrConfig | None = Field(
        default=None,
        description="OCR configuration block. When present, overrides the deprecated do_ocr/ocr_engine/ocr_languages fields.",
    )
    do_ocr: bool = Field(
        default=True,
        description="Deprecated: use ocr.enabled instead. Whether to run OCR on document pages.",
    )
    pdf_backend: Literal["dlparse_v2", "pypdfium2"] = Field(
        default="dlparse_v2",
        description="PDF parsing backend.",
    )
    ocr_engine: str | None = Field(
        default=None,
        description="Deprecated: use ocr.engine instead. OCR engine override (leave unset to use the server default).",
    )
    ocr_languages: list[str] | None = Field(
        default=None,
        description="Deprecated: use ocr.engine_options.lang instead. List of language codes for OCR (e.g., ['en', 'fr']).",
    )
    table_mode: str | None = Field(
        default=None,
        description="Table extraction mode override (leave unset to use the server default).",
    )
    image_export_mode: Literal["placeholder", "embedded"] = Field(
        default="placeholder",
        description="How to export images found in the document.",
    )
