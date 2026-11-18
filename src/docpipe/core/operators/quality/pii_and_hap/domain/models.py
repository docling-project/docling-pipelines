"""Domain models for PII and HAP detection.

This module contains the core domain models used in PII and HAP detection operations.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# Label fragment that identifies a HAP detection (e.g. ``"has_HAP"``) when an adapter
# does not set ``detection_type``.
_HAP_LABEL_MARKER = "hap"


class DetectionCapability(StrEnum):
    """Detection capabilities a provider adapter can offer.

    The values match the lowercase ``expected_redactions`` entries and the keys used
    in the ``detectors`` section of a detection payload.
    """

    PII = "pii"
    HAP = "hap"


@dataclass(frozen=True)
class ProviderSelection:
    """Provider chosen for one detection capability, resolved from operator config.

    Attributes:
        provider: Registered adapter name (e.g. ``'watsonx'``, ``'presidio'``).
        provider_config: Provider-specific configuration dict passed to the adapter.
        provider_key: Config key the provider name was read from (for error messages).
        provider_config_key: Config key the provider config was read from (for error messages).
    """

    provider: str
    provider_config: dict[str, Any] = field(default_factory=dict)
    provider_key: str = "provider"
    provider_config_key: str = "provider_config"

    @property
    def model_id(self) -> str:
        """Return ``provider_config['model_id']`` or an empty string when absent."""
        model_id = self.provider_config.get("model_id")
        return model_id if isinstance(model_id, str) else ""


@dataclass
class DetectionResult:
    """Base result for PII/HAP detection operation.

    Attributes:
        detection: Type of detection (e.g., 'email', 'ssn', 'hate', 'abuse')
        detection_type: Category of detection (e.g., 'pii', 'hap')
        score: Confidence score between 0.0 and 1.0
        start: Start position in text
        end: End position in text
        text: Detected text snippet (optional, for display purposes)
        evidences: Additional evidence or context (optional)
    """

    detection: str
    detection_type: str
    score: float
    start: int
    end: int
    text: str | None = None
    evidences: list[dict[str, Any]] | None = None


@dataclass
class PIIHAPDetectionResponse:
    """Response containing all detections for a document.

    Attributes:
        detections: List of all detected PII/HAP instances
        input_text: Original input text (optional, for reference)
    """

    detections: list[DetectionResult]
    input_text: str | None = None


def get_detection_capability(detection: DetectionResult) -> DetectionCapability:
    """Classify a detection as PII or HAP.

    Uses ``detection_type`` when the adapter set it to ``'pii'`` or ``'hap'``; otherwise
    falls back to the label (HAP labels such as ``'has_HAP'`` contain ``'hap'``).

    Args:
        detection: Detection to classify.

    Returns:
        The capability the detection belongs to.
    """
    detection_type = (detection.detection_type or "").lower()
    if detection_type in (DetectionCapability.PII, DetectionCapability.HAP):
        return DetectionCapability(detection_type)
    if _HAP_LABEL_MARKER in (detection.detection or "").lower():
        return DetectionCapability.HAP
    return DetectionCapability.PII


def filter_detections_by_capability(
    *, detections: list[DetectionResult], capability: DetectionCapability
) -> list[DetectionResult]:
    """Return only the detections that belong to ``capability``.

    Args:
        detections: Detections returned by an adapter.
        capability: Capability to keep.

    Returns:
        Filtered list, original order preserved.
    """
    return [d for d in detections if get_detection_capability(d) == capability]


def convert_detection_dicts_to_results(detection_dicts: list[dict[str, Any]]) -> list[DetectionResult]:
    """Convert list of detection dictionaries to DetectionResult objects.

    Args:
        detection_dicts: List of dictionaries containing detection data

    Returns:
        List of DetectionResult objects
    """
    results = []
    for detection_dict in detection_dicts:
        detection = DetectionResult(
            detection=detection_dict.get("detection", ""),
            detection_type=detection_dict.get("detection_type", ""),
            score=detection_dict.get("score", 0.0),
            start=detection_dict.get("start", 0),
            end=detection_dict.get("end", 0),
            text=detection_dict.get("text"),
            evidences=detection_dict.get("evidences"),
        )
        results.append(detection)
    return results
