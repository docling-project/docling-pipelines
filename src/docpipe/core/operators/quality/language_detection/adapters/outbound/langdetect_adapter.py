"""Langdetect adapter for language detection.

This adapter wraps the langdetect library to provide language detection
following the hexagonal architecture pattern.
"""

from langdetect import LangDetectException, detect_langs

from docpipe.core.operators.quality.language_detection.adapters.outbound.factories.language_adapter_factory import (
    register_language_adapter,
)
from docpipe.core.operators.quality.language_detection.domain.models import LanguageDetectionResult
from docpipe.core.operators.quality.language_detection.ports.outbound.language_service import LanguageServicePort
from docpipe.exceptions.docpipe_exceptions import ExternalServiceError
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@register_language_adapter
class LangdetectAdapter(LanguageServicePort):
    """Adapter for langdetect library.

    This adapter provides language detection using the langdetect library,
    which supports 55+ languages with good accuracy for most common languages.

    Features:
        - Fast detection for common languages
        - Probabilistic approach
        - No external dependencies or model downloads
        - Good for general-purpose language detection

    Limitations:
        - Less accurate for short texts
        - Limited to 55 languages
        - May struggle with mixed-language content
    """

    ADAPTER_NAME = "langdetect"
    ADAPTER_DISPLAY_NAME = "langdetect"

    def __init__(self, **adapter_config):
        """Initialize langdetect adapter.

        Args:
            **adapter_config: Additional configuration (currently unused for langdetect)
        """
        # langdetect doesn't require initialization

    def detect_language(self, text: str) -> LanguageDetectionResult:
        """Detect language using langdetect library.

        Args:
            text: Input text to detect language for

        Returns:
            LanguageDetectionResult containing language code and confidence score

        Raises:
            ValueError: If text is empty or detection fails
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        try:
            # detect_langs returns a list of Language objects sorted by probability
            # Format: [Language(lang='en', prob=0.9999), ...]
            # Note: detect_langs raises LangDetectException if no language can be detected
            languages = detect_langs(text)

            # Get the most probable language
            top_language = languages[0]

            # Extract language code and probability using direct attribute access
            language_code = top_language.lang
            confidence = top_language.prob

            return LanguageDetectionResult(language_code=language_code, confidence=confidence)

        except LangDetectException as e:
            logger.error("Language detection failed (langdetect error): %s", e)
            raise ExternalServiceError(f"Language detection failed: {e}") from e
        except Exception as e:
            logger.error("Unexpected error during language detection: %s", e)
            raise ExternalServiceError(f"Unexpected error during language detection: {e}") from e
