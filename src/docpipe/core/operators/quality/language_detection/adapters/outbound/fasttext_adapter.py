"""FastText adapter for language detection.

This adapter wraps Facebook's FastText model to provide language detection for 176+ languages.
It implements efficient memory management through reference counting for parallel flow execution.
"""

from docpipe.core.operators.quality.language_detection.adapters.outbound.factories.language_adapter_factory import (
    register_language_adapter,
)
from docpipe.core.operators.quality.language_detection.domain.models import LanguageDetectionResult
from docpipe.core.operators.quality.language_detection.ports.outbound.language_service import LanguageServicePort
from docpipe.exceptions.docpipe_exceptions import ExternalServiceError
from docpipe.utils.infrastructure.fasttext_model_manager import FastTextModelManager
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@register_language_adapter
class FastTextAdapter(LanguageServicePort):
    """Adapter for FastText language detection model.

    This adapter provides language detection using Facebook's FastText model.
    FastTextModelManager handles the infrastructure concerns (model lifecycle,
    memory management, thread safety) while this adapter focuses on the
    language detection interface.

    Features:
        - High accuracy for both long and short texts
        - Memory-efficient singleton model with reference counting
        - Thread-safe model management
        - Automatic model download on first use

    Limitations:
        - Requires model download (~131MB) on first use
        - Slightly slower than langdetect for very short texts
        - Requires fasttext library installation
    """

    ADAPTER_NAME = "fasttext"
    ADAPTER_DISPLAY_NAME = "FastText"

    def __init__(self, **adapter_config):
        """Initialize FastText adapter.

        Args:
            **adapter_config: Additional configuration (currently unused)
        """
        self.model_manager = FastTextModelManager()
        self.fasttext_model = None

        try:
            self.fasttext_model = self.model_manager.acquire_model()
            ref_count = self.model_manager.get_ref_count()
            logger.info("FastText model acquired successfully. Reference count: %s", ref_count)
        except Exception as e:
            logger.error("Failed to acquire FastText model: %s", e)
            self.fasttext_model = None
            raise ExternalServiceError(f"Failed to initialize FastText model: {e}") from e

    def cleanup(self) -> None:
        """Explicitly release FastText model resources.

        This method is called by the operator's cleanup() to ensure proper
        resource cleanup.
        """
        if self.fasttext_model is not None:
            try:
                self.model_manager.release_model()
                ref_count = self.model_manager.get_ref_count()
                logger.info("FastText model released. Reference count: %s", ref_count)
                self.fasttext_model = None
            except Exception as e:
                logger.warning("Error releasing FastText model: %s", e)

    def detect_language(self, text: str) -> LanguageDetectionResult:
        """Detect language using FastText model.

        Args:
            text: Input text to detect language for

        Returns:
            LanguageDetectionResult containing language code and confidence score

        Raises:
            ValueError: If text is empty or detection fails
            ExternalServiceError: If FastText model is not available
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        if self.fasttext_model is None:
            raise ExternalServiceError("FastText model not available")

        try:
            # Clean text for better detection
            cleaned_text = text.replace("\n", " ").strip()

            # FastText returns predictions in format: (('__label__en',), array([0.99]))
            predictions = self.fasttext_model.predict(cleaned_text, k=1)

            # Extract language code (remove '__label__' prefix)
            # predictions[0] is a tuple of labels, predictions[1] is array of probabilities
            if len(predictions) >= 2 and predictions[0] and predictions[1]:
                language_code = predictions[0][0].replace("__label__", "")
                confidence = float(predictions[1][0])
                return LanguageDetectionResult(language_code=language_code, confidence=confidence)
            raise ValueError("FastText returned invalid predictions")

        except ValueError:
            # Re-raise ValueError as-is
            raise
        except Exception as e:
            logger.error("FastText language detection failed: %s", e)
            raise ExternalServiceError(f"FastText language detection failed: {e}") from e
