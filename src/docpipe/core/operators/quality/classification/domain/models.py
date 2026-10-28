"""Domain models for document classification.

These models represent core domain concepts independent of any specific
LLM provider or infrastructure concerns.
"""

import re
from dataclasses import dataclass
from typing import Any

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.llm.json_parser import parse_llm_json_response


@dataclass
class ClassificationRequest:
    """Request for document classification.

    Attributes:
        content: Document content to classify
        document_types: List of document types or dict with type descriptions
        max_content_length: Maximum content length to send to LLM
        confidence_threshold: Minimum confidence score for classification (1-10)
    """

    content: str
    document_types: list[str] | dict[str, str]
    max_content_length: int = 2000
    confidence_threshold: float = 7.0


@dataclass
class ClassificationResponse:
    """Response from document classification.

    Attributes:
        document_type: Classified document type.  By default this is the model's
            label normalised with :func:`normalize_label` (lower-case, spaces
            replaced by underscores).  With strict label matching it is in the
            spelling of the configured document types, and ``None`` when the
            model returned a label that matches none of them (``reasoning`` then
            explains why).
        confidence: Confidence score (1-10 scale)
        reasoning: Explanation for the classification decision
        success: Whether classification was successful
        error: Error message if classification failed
        extracted_content: Optional text the adapter had to extract as a
            by-product of classification (e.g. via Docling).  ``None`` when the
            adapter did not extract anything or was given the text already.
        extraction_metadata: Optional metadata produced alongside
            ``extracted_content`` (e.g. Docling ``page_count``).
    """

    document_type: str | None
    confidence: float
    reasoning: str
    success: bool
    error: str | None = None
    extracted_content: str | None = None
    extraction_metadata: dict[str, Any] | None = None


@dataclass
class ModelInfo:
    """Information about a classification model.

    Attributes:
        name: Model name
        provider: Provider name (e.g., 'ollama', 'watsonx')
        supports_json_mode: Whether model supports JSON output format
        max_tokens: Maximum token limit for the model
    """

    name: str
    provider: str
    supports_json_mode: bool = True
    max_tokens: int = 4096


def normalize_label(label: str) -> str:
    """Return *label* in the legacy output form: lower-case with spaces replaced by underscores."""
    return label.lower().replace(" ", "_")


def _label_key(label: str) -> str:
    """Return *label* folded for comparison: lower-case, without whitespace or underscores."""
    return re.sub(r"[\s_]+", "", label.lower())


def resolve_document_type(*, label: str, document_types: list[str] | dict[str, str]) -> str | None:
    """Resolve an LLM-returned *label* to one of the configured document types.

    Matching is insensitive to case, whitespace and underscores, so
    ``"purchase order"`` resolves to ``"Purchase Order"``.  An exact match wins
    over a folded match.

    Args:
        label: Document type label returned by the LLM.
        document_types: Configured document types (names, or name -> description).

    Returns:
        The document type in its configured spelling, or ``None`` when *label*
        matches none of them.
    """
    names = list(document_types)
    if label in names:
        return label
    key = _label_key(label)
    for name in names:
        if _label_key(name) == key:
            return name
    return None


def parse_classification_response(*, response_text: str | None) -> ClassificationResponse:
    """Convert raw LLM text into a successful :class:`ClassificationResponse`.

    Parses the JSON object, checks the required fields and clamps the
    confidence to the 1-10 range.  The returned ``document_type`` is the label
    exactly as the LLM wrote it (whitespace-stripped); use
    :func:`resolve_document_type` to map it onto the configured types.

    Args:
        response_text: Raw text returned by the LLM.

    Returns:
        A ``ClassificationResponse`` with ``success=True``.

    Raises:
        ValueError: When the text is empty, is not valid JSON, lacks the
            required fields, or carries a non-numeric confidence.
    """
    if not response_text or not response_text.strip():
        raise ValueError("Empty response from LLM chat API")

    try:
        result = parse_llm_json_response(response_text, log_on_error=True)
    except DocpipeException as exc:
        raise ValueError(f"Invalid JSON response from LLM: {exc}") from exc

    type_key = OperatorConstants.Classification.FIELD_DOCUMENT_TYPE
    confidence_key = OperatorConstants.Classification.FIELD_CONFIDENCE

    if type_key not in result or confidence_key not in result:
        raise ValueError("Invalid response format from LLM - missing required fields")
    if result[type_key] is None or result[confidence_key] is None:
        raise ValueError("Invalid response format from LLM - null values in required fields")

    try:
        confidence = max(1, min(10, int(float(result[confidence_key]))))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid confidence value: {result[confidence_key]}") from exc

    return ClassificationResponse(
        document_type=str(result[type_key]).strip(),
        confidence=confidence,
        reasoning=result.get(OperatorConstants.Classification.FIELD_REASONING, ""),
        success=True,
        error=None,
    )


def build_classification_prompt(*, request: ClassificationRequest) -> str:
    """Build the classification prompt for the LLM.

    This function creates a standardized prompt format that works across
    all LLM providers (Ollama, OpenAI, Watsonx, etc.).

    Args:
        request: Classification request with content and document types

    Returns:
        Formatted prompt string
    """
    if isinstance(request.document_types, dict):
        types_desc = "\n".join([f"- {name}: {desc}" for name, desc in request.document_types.items()])
    else:
        types_desc = "\n".join([f"- {document_type}" for document_type in request.document_types])

    sanitized_content = request.content[: request.max_content_length] if request.content else ""

    return f"""Classify the following document into one of these types:

{types_desc}

Document content:
{sanitized_content}

Respond with a JSON object containing:
- {OperatorConstants.Classification.FIELD_DOCUMENT_TYPE}: The document type that best matches (must be one of the types listed above)
- {OperatorConstants.Classification.FIELD_CONFIDENCE}: Confidence score from 1-10 (10 = certain)
- {OperatorConstants.Classification.FIELD_REASONING}: Brief explanation for why this document type was chosen

Example response:
{{
  "{OperatorConstants.Classification.FIELD_DOCUMENT_TYPE}": "invoice",
  "{OperatorConstants.Classification.FIELD_CONFIDENCE}": 9,
  "{OperatorConstants.Classification.FIELD_REASONING}": "Contains line items, totals, and payment terms typical of invoices"
}}"""
