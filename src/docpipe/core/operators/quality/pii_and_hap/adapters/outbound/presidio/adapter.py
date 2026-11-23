# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Presidio adapter for PII detection (PII only, runs locally).

Reference single-capability adapter: it implements ``PIIDetectionPort`` only, so it
can be selected as ``pii_provider`` but is rejected as ``hap_provider``.

``presidio-analyzer`` is an optional dependency.  It is imported lazily so that the
adapter registers (and appears in operator metadata) even when the package is not
installed; ``validate()`` then fails with installation instructions before any
document is processed.
"""

import importlib
import threading
from typing import Any

from pydantic import BaseModel, ValidationError

from docpipe.core.constants.constants import LLMConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.factories.pii_and_hap_detection_factory import (
    register_pii_and_hap_detection_adapter,
)
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.presidio.config import (
    ADAPTER_NAME,
    DEFAULT_PRESIDIO_ENTITY_MAPPING,
    PresidioPIIConfig,
)
from docpipe.core.operators.quality.pii_and_hap.domain.models import DetectionResult, PIIHAPDetectionResponse
from docpipe.core.operators.quality.pii_and_hap.pii_and_hap_helper import DEFAULT_PII_TYPES_OF_CONCERN
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_detection_port import PIIDetectionPort
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

PRESIDIO_PACKAGE = "presidio_analyzer"
PRESIDIO_NLP_ENGINE_MODULE = "presidio_analyzer.nlp_engine"
PRESIDIO_INSTALL_HINT = (
    "The 'presidio' PII provider requires the optional 'presidio-analyzer' package, which is not installed. "
    "Install it with: pip install presidio-analyzer (or pip install 'docling-pipelines[presidio]'), "
    "then install a spaCy model, e.g.: python -m spacy download en_core_web_lg"
)
PRESIDIO_SOURCE = "presidio"


@register_pii_and_hap_detection_adapter
class PresidioPIIAdapter(PIIDetectionPort):
    """PII detection adapter backed by Microsoft Presidio's ``AnalyzerEngine``.

    Presidio entity types are translated to the operator's PII vocabulary
    (``EmailAddress``, ``PhoneNumber``, ...) via ``DEFAULT_PRESIDIO_ENTITY_MAPPING``
    plus optional ``provider_config.entity_mapping`` overrides.  Entities without a
    mapping are dropped.
    """

    ADAPTER_NAME = ADAPTER_NAME
    ADAPTER_DISPLAY_NAME = "Presidio (PII only)"
    SUPPORTS_PII = True
    SUPPORTS_HAP = False
    REQUIRES_MODEL_ID = False

    def __init__(self, *, model_id: str, provider_config: dict[str, Any]) -> None:
        """Initialise the adapter.  The Presidio engine itself is built lazily.

        Args:
            model_id: Ignored - Presidio does not use a model identifier.
            provider_config: Presidio config (``language``, ``spacy_model``, ``entity_mapping``).
        """
        super().__init__(model_id=model_id, provider_config=provider_config)
        self._config_errors: list[str] = []
        try:
            self._config = PresidioPIIConfig.model_validate(provider_config or {})
        except ValidationError as exc:
            self._config = PresidioPIIConfig()
            self._config_errors.append(f"Invalid Presidio provider_config: {exc}")
        self._config_errors.extend(PresidioPIIAdapter._check_entity_mapping(entity_mapping=self._config.entity_mapping))
        self._entity_mapping = {**DEFAULT_PRESIDIO_ENTITY_MAPPING, **(self._config.entity_mapping or {})}
        self._analyzer: Any = None
        self._init_lock = threading.Lock()
        # spaCy pipelines are not documented as thread-safe; serialise analyzer calls.
        self._analyze_lock = threading.Lock()
        logger.info("Initialised PresidioPIIAdapter (language=%s)", self._config.language)

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        return PresidioPIIConfig

    @classmethod
    def validate_provider_config(cls, *, provider_config: dict[str, Any], config_key: str) -> list[str]:
        """Check the Presidio config shape without importing Presidio."""
        try:
            config = PresidioPIIConfig.model_validate(provider_config or {})
        except ValidationError as exc:
            return [f"{config_key} is invalid for provider '{cls.ADAPTER_NAME}': {exc}"]
        return [
            f"{config_key}: {error}"
            for error in PresidioPIIAdapter._check_entity_mapping(entity_mapping=config.entity_mapping)
        ]

    @staticmethod
    def _check_entity_mapping(*, entity_mapping: dict[str, str] | None) -> list[str]:
        """Return errors for entity_mapping values outside the operator PII vocabulary."""
        if not entity_mapping:
            return []
        invalid = sorted({value for value in entity_mapping.values() if value not in DEFAULT_PII_TYPES_OF_CONCERN})
        if not invalid:
            return []
        return [
            f"entity_mapping values {invalid} are not valid PII types. Use values from {DEFAULT_PII_TYPES_OF_CONCERN}"
        ]

    def validate(self) -> dict[str, Any]:
        """Check config, the optional dependency and the spaCy model (fail-fast).

        Builds the Presidio ``AnalyzerEngine`` so that a missing package or spaCy
        model is reported at startup rather than on the first document.

        Returns:
            Validation result dict with ``valid``, ``errors`` and ``warnings`` keys.
        """
        if self._config_errors:
            return PresidioPIIAdapter._validation_result(errors=list(self._config_errors))
        try:
            self._get_analyzer()
        except ImportError:
            return PresidioPIIAdapter._validation_result(errors=[PRESIDIO_INSTALL_HINT])
        except Exception as exc:
            return PresidioPIIAdapter._validation_result(
                errors=[
                    f"Failed to initialise Presidio AnalyzerEngine (language='{self._config.language}', "
                    f"spacy_model='{self._config.spacy_model}'): {exc}. Make sure the spaCy model is installed: "
                    f"python -m spacy download {self._config.spacy_model}"
                ]
            )
        return PresidioPIIAdapter._validation_result(errors=[])

    @staticmethod
    def _validation_result(*, errors: list[str]) -> dict[str, Any]:
        """Build the standard validation result dict."""
        return {
            LLMConstants.ValidationKeys.VALID: not errors,
            LLMConstants.ValidationKeys.ERRORS: errors,
            LLMConstants.ValidationKeys.WARNINGS: [],
        }

    def _get_analyzer(self) -> Any:
        """Return the cached ``AnalyzerEngine``, building it on first use (thread-safe)."""
        if self._analyzer is None:
            with self._init_lock:
                if self._analyzer is None:
                    self._analyzer = PresidioPIIAdapter._build_analyzer(
                        language=self._config.language,
                        spacy_model=self._config.spacy_model,
                    )
        return self._analyzer

    @staticmethod
    def _build_analyzer(*, language: str, spacy_model: str) -> Any:
        """Import Presidio lazily and build an ``AnalyzerEngine`` for one language.

        Raises:
            ImportError: If ``presidio-analyzer`` is not installed.
        """
        analyzer_module = importlib.import_module(PRESIDIO_PACKAGE)
        nlp_engine_module = importlib.import_module(PRESIDIO_NLP_ENGINE_MODULE)
        nlp_configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": language, "model_name": spacy_model}],
        }
        nlp_engine = nlp_engine_module.NlpEngineProvider(nlp_configuration=nlp_configuration).create_engine()
        logger.info("Built Presidio AnalyzerEngine (language=%s, spacy_model=%s)", language, spacy_model)
        return analyzer_module.AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=[language])

    def detect_pii(self, *, text: str, threshold: float) -> PIIHAPDetectionResponse:
        """Detect PII with Presidio and translate entity types to operator PII labels.

        Args:
            text: Non-empty text to analyse (guaranteed by the calling service).
            threshold: Minimum Presidio score for a result to be reported.

        Returns:
            PIIHAPDetectionResponse with one detection per mapped Presidio result.

        Raises:
            DocpipeException: If Presidio is unavailable or analysis fails.
        """
        try:
            analyzer = self._get_analyzer()
            with self._analyze_lock:
                results = analyzer.analyze(text=text, language=self._config.language, score_threshold=threshold)
        except ImportError as exc:
            raise DocpipeException(message=PRESIDIO_INSTALL_HINT, status_code=500) from exc
        except Exception as exc:
            logger.error("Presidio analysis failed: %s", exc)
            raise DocpipeException(message=f"Presidio PII detection failed: {exc!s}", status_code=500) from exc

        return PIIHAPDetectionResponse(
            detections=PresidioPIIAdapter._to_detections(
                results=results, text=text, entity_mapping=self._entity_mapping
            ),
            input_text=text,
        )

    @staticmethod
    def _to_detections(*, results: list[Any], text: str, entity_mapping: dict[str, str]) -> list[DetectionResult]:
        """Convert Presidio ``RecognizerResult`` objects to ``DetectionResult`` (unmapped entities dropped)."""
        detections: list[DetectionResult] = []
        for result in results:
            label = entity_mapping.get(result.entity_type)
            if label is None:
                logger.debug("Skipping unmapped Presidio entity type %s", result.entity_type)
                continue
            start, end = int(result.start), int(result.end)
            detections.append(
                DetectionResult(
                    detection=label,
                    detection_type=OperatorConstants.PIIHAP.PII_FIELD_NAME,
                    score=float(result.score),
                    start=start,
                    end=end,
                    text=text[start:end],
                    evidences=[{"source": PRESIDIO_SOURCE, "entity_type": result.entity_type}],
                )
            )
        return detections
