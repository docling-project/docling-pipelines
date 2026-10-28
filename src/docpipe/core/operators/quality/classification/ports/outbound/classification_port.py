"""Outbound port interface for document classification adapters."""

from abc import ABC, abstractmethod
from typing import Any, Self

from docpipe.core.operators.quality.classification.domain.models import ClassificationResponse


class ClassificationPort(ABC):
    """Outbound port that every classification adapter must implement.

    Concrete adapters extend this ABC and are resolved at runtime by
    :class:`~docpipe.core.operators.quality.classification.adapters.outbound.factories.classification_adapter_factory.ClassificationAdapterFactory`.

    Class attributes:
        ADAPTER_NAME: Machine-readable short name registered in the factory
            (e.g. ``"standard"``).  The factory's ``register()`` call uses this
            value as the registry key.
        ADAPTER_DISPLAY_NAME: Human-readable label for logs and UI.

    The port defines the contract only.  Each adapter parses the config values
    it needs (e.g. ``confidence_threshold``) in its own ``from_config`` /
    constructor.  Document types are supplied per call to
    :meth:`classify_document`, so adapters never depend on where the classes
    came from.
    """

    ADAPTER_NAME: str
    ADAPTER_DISPLAY_NAME: str

    @classmethod
    @abstractmethod
    def from_config(cls, config: dict[str, Any]) -> Self:
        """Validate *config*, build any dependencies, and return a ready instance.

        Each adapter subclass owns its own config-validation and dependency-
        construction logic here.  The factory delegates entirely to this method,
        keeping itself as a pure dispatcher.

        Typical implementation pattern::

            @classmethod
            def from_config(cls, config):
                provider_config = config.get("provider_config") or {}
                model_id = provider_config.get("model_id", "")
                if not model_id:
                    raise ValueError("provider_config.model_id is required")
                llm_adapter = LLMAdapterFactory.create_inference_adapter(
                    provider=..., model_id=model_id, provider_config=provider_config
                )
                return cls(llm_adapter=llm_adapter, config=config)

        Args:
            config: Full operator config dictionary from the flow JSON.

        Returns:
            A fully initialised concrete :class:`ClassificationPort` instance.

        Raises:
            ValueError: When required config keys are absent or invalid.
        """
        ...

    @abstractmethod
    def classify_document(
        self,
        *,
        doc_name: str,
        binary_content: bytes | None,
        existing_text: str | None,
        document_types: list[str] | dict[str, str],
    ) -> ClassificationResponse:
        """Classify a single document and return a structured response.

        Implementations must populate all ``ClassificationResponse`` fields.

        Args:
            doc_name: Document file name (used for format detection and logging).
            binary_content: Raw bytes of the document.  May be ``None`` when
                ``existing_text`` is already available.
            existing_text: Pre-extracted text content.  When supplied, adapters
                that support a text path should prefer it over re-extracting
                from ``binary_content``.
            document_types: Document types to classify into, as a list of names
                or a ``name → description`` mapping.  Resolved by the caller
                (typically via a ``DocumentClassProvider``).

        Returns:
            :class:`ClassificationResponse` with ``document_type``,
            ``confidence``, ``reasoning``, ``success``, and optionally
            ``error``.  Adapters that had to extract text themselves may also
            set ``extracted_content`` and ``extraction_metadata`` so the
            operator can reuse them downstream; adapters that do not extract
            text leave both ``None``.
        """
        ...
