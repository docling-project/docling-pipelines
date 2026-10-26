"""Standard LLM classification adapter.

Implements :class:`ClassificationPort` for the ``litellm`` and ``watsonx``
providers by handling the full LLM round-trip internally via
:class:`_LLMClassificationService`, a private helper that manages the LLM
interaction.

:class:`StandardLLMClassificationAdapter` owns its own config validation and
LLM adapter construction in :meth:`~StandardLLMClassificationAdapter.from_config`.
The factory is a pure dispatcher and never contains adapter-specific logic.
"""

from dataclasses import replace
from typing import Any, Self

from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory
from docpipe.core.constants.constants import LLMConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.core.operators.quality.classification.adapters.outbound.factories.classification_adapter_factory import (
    register_classification_adapter,
)
from docpipe.core.operators.quality.classification.domain.models import (
    ClassificationRequest,
    ClassificationResponse,
    build_classification_prompt,
    normalize_label,
    parse_classification_response,
    resolve_document_type,
)
from docpipe.core.operators.quality.classification.ports.outbound.classification_port import ClassificationPort
from docpipe.core.ports.llm_inference_port import LLMInferencePort
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Private implementation detail — not part of the public adapter contract
# ---------------------------------------------------------------------------


class _LLMClassificationService:
    """LLM-backed classification worker used exclusively by
    :class:`StandardLLMClassificationAdapter`.

    Accepts a pre-built :class:`~docpipe.core.ports.llm_inference_port.LLMInferencePort`
    injected by :meth:`StandardLLMClassificationAdapter.from_config`.  All
    provider validation and adapter construction belong in ``from_config``, not
    here.

    Attributes:
        llm_adapter: Active :class:`LLMInferencePort` instance.
        model_id: Model identifier (for logging/metadata only).
        provider_name: Provider name (for logging/metadata only).
        temperature: Sampling temperature forwarded to the LLM.
        max_tokens: Token budget forwarded to the LLM.
        strict_label_matching: When ``True`` the returned label is resolved to a
            configured document type and unknown labels are rejected.  When
            ``False`` the label is only normalised with :func:`normalize_label`.
    """

    def __init__(
        self,
        *,
        llm_adapter: LLMInferencePort,
        temperature: float = OperatorConstants.Classification.DEFAULT_TEMPERATURE,
        max_tokens: int = OperatorConstants.Classification.DEFAULT_MAX_TOKENS,
        model_id: str = "",
        provider_name: str = "",
        strict_label_matching: bool = OperatorConstants.Classification.DEFAULT_STRICT_LABEL_MATCHING,
    ) -> None:
        """Initialise the service with a pre-built LLM adapter.

        Args:
            llm_adapter: Pre-built :class:`LLMInferencePort` instance.
            temperature: Sampling temperature
                (default ``OperatorConstants.Classification.DEFAULT_TEMPERATURE``).
            max_tokens: Maximum tokens for LLM response
                (default ``OperatorConstants.Classification.DEFAULT_MAX_TOKENS``).
            model_id: Model identifier stored for logging/metadata only.
            provider_name: Provider name stored for logging/metadata only.
            strict_label_matching: Resolve labels to configured spellings and
                reject unknown labels (default ``False``).

        Raises:
            DocpipeException: When adapter validation fails.
        """
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.model_id = model_id
        self.provider_name = provider_name
        self.strict_label_matching = strict_label_matching
        self.llm_adapter: LLMInferencePort = llm_adapter

        validation_result = self.llm_adapter.validate()
        if not validation_result.get(LLMConstants.ValidationKeys.VALID, False):
            errors = validation_result.get(LLMConstants.ValidationKeys.ERRORS, [])
            raise DocpipeException(
                error_code=ErrorCode.INVALID_CONFIGURATION,
                message=f"Injected adapter validation failed: {'; '.join(errors)}",
            )
        for warning in validation_result.get(LLMConstants.ValidationKeys.WARNINGS, []):
            logger.warning("Adapter configuration warning: %s", warning)

        logger.info(
            "_LLMClassificationService: initialised adapter=%s temperature=%s max_tokens=%s",
            type(llm_adapter).__name__,
            temperature,
            max_tokens,
        )

    def classify_document(self, *, request: ClassificationRequest) -> ClassificationResponse:
        """Classify a document and return a structured response.

        Args:
            request: :class:`ClassificationRequest` carrying content and
                document-type options.

        Returns:
            :class:`ClassificationResponse` with type, confidence, and
            reasoning populated.

        Raises:
            DocpipeException: When the LLM API call fails.
        """
        try:
            prompt = build_classification_prompt(request=request)
            messages = [
                {
                    "role": "system",
                    "content": "You are a document classification expert. Always respond only with valid JSON.",
                },
                {"role": "user", "content": prompt},
            ]

            total_len = sum(len(msg.get("content", "")) for msg in messages)
            logger.debug("_LLMClassificationService: total message content length=%s chars", total_len)
            logger.debug("_LLMClassificationService: calling LLM adapter")

            result_text = self.llm_adapter.chat(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            logger.debug(
                "_LLMClassificationService: received response (len=%s)", len(result_text) if result_text else 0
            )

            parsed = parse_classification_response(response_text=result_text)
            if not self.strict_label_matching:
                return replace(parsed, document_type=normalize_label(parsed.document_type or ""))

            resolved_type = resolve_document_type(
                label=parsed.document_type or "", document_types=request.document_types
            )

            logger.debug(
                "_LLMClassificationService: parsed result - label=%s resolved=%s confidence=%s",
                parsed.document_type,
                resolved_type,
                parsed.confidence,
            )

            if resolved_type is None:
                logger.warning(
                    "_LLMClassificationService: LLM returned label %r that is not a configured document type",
                    parsed.document_type,
                )
                return replace(
                    parsed,
                    document_type=None,
                    reasoning=f"Returned label {parsed.document_type!r} is not a configured document type",
                )
            return replace(parsed, document_type=resolved_type)

        except ValueError as exc:
            logger.error("_LLMClassificationService: failed to parse LLM response: %s", exc)
            return ClassificationResponse(
                document_type=OperatorConstants.Classification.UNKNOWN_TYPE,
                confidence=0,
                reasoning="",
                success=False,
                error=f"Invalid response format: {exc}",
            )
        except DocpipeException:
            raise
        except Exception as exc:
            logger.exception("_LLMClassificationService: LLM call failed: %s", exc)
            raise DocpipeException(
                error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                message=f"LLM API call failed: {exc}",
            ) from exc

    def get_model_info(self) -> dict[str, Any]:
        """Return model metadata as a plain dictionary."""
        return {
            "model_id": self.model_id,
            "provider": self.provider_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


# ---------------------------------------------------------------------------
# Public adapter
# ---------------------------------------------------------------------------


@register_classification_adapter
class StandardLLMClassificationAdapter(ClassificationPort):
    """Implements :class:`ClassificationPort` for ``litellm`` and ``watsonx``
    providers by delegating to :class:`_LLMClassificationService`.

    Config validation, LLM adapter construction, and provider normalisation all
    live in :meth:`from_config`, making the factory a pure dispatcher.

    Class attributes:
        ADAPTER_NAME: ``"standard"`` — the key under which this adapter is
            registered in :class:`ClassificationAdapterFactory`.  Like every
            registered ``ADAPTER_NAME`` it is also accepted as a ``provider``
            value in a flow.
        ADAPTER_DISPLAY_NAME: Human-readable label.
    """

    ADAPTER_NAME = "standard"
    ADAPTER_DISPLAY_NAME = "Standard LLM Classifier"

    def __init__(self, *, llm_adapter: LLMInferencePort, config: dict[str, Any]) -> None:
        """Build the adapter with a pre-built LLM port.

        Prefer :meth:`from_config` over calling this constructor directly.
        The constructor assumes all validation has already been performed.

        Args:
            llm_adapter: Pre-built and validated :class:`LLMInferencePort`.
            config: Full operator config dictionary (used for
                max_content_length, temperature, max_tokens).  The confidence
                threshold is enforced by the operator, not by this adapter.
        """
        self.config = config
        self.doc_format: str = config.get(OperatorConstants.DOC_FORMAT_KEY, OperatorConstants.DOC_FORMAT_DEFAULT)
        self.max_content_length: int = config.get(
            OperatorConstants.Config.MAX_CONTENT_LENGTH,
            OperatorConstants.Classification.DEFAULT_MAX_CONTENT_LENGTH,
        )
        provider_config: dict[str, Any] = config.get(OperatorConstants.Config.PROVIDER_CONFIG) or {}
        temperature: float = provider_config.get(
            OperatorConstants.LLM.TEMPERATURE, OperatorConstants.Classification.DEFAULT_TEMPERATURE
        )
        max_tokens: int = provider_config.get(
            OperatorConstants.LLM.MAX_TOKENS, OperatorConstants.Classification.DEFAULT_MAX_TOKENS
        )
        model_id: str = (
            provider_config.get(OperatorConstants.Config.MODEL_ID) or OperatorConstants.Classification.DEFAULT_MODEL
        )
        provider: str = config.get(OperatorConstants.Config.PROVIDER, "").lower()

        self._service = _LLMClassificationService(
            llm_adapter=llm_adapter,
            temperature=temperature,
            max_tokens=max_tokens,
            model_id=model_id,
            provider_name=provider,
            strict_label_matching=config.get(
                OperatorConstants.Config.STRICT_LABEL_MATCHING,
                OperatorConstants.Classification.DEFAULT_STRICT_LABEL_MATCHING,
            ),
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Self:
        """Validate *config*, build the :class:`LLMInferencePort`, return a ready adapter.

        This is the canonical construction path used by
        :class:`~docpipe.core.operators.quality.classification.adapters.outbound.factories.classification_adapter_factory.ClassificationAdapterFactory`.
        All provider validation and LLM adapter construction happen here so
        that the factory remains a pure dispatcher.

        Args:
            config: Full operator config dictionary.  Must contain:

                * ``provider`` — one of ``"litellm"`` or ``"watsonx"``.  Defaults
                  to ``"litellm"`` when absent.
                * ``provider_config`` — dict with optional model_id and connection parameters.
                  Required for ``litellm``; optional for ``watsonx``, which falls
                  back to the ``WATSONX_*`` environment variables.

        Returns:
            A ready :class:`StandardLLMClassificationAdapter` instance.

        Raises:
            ValueError: When ``provider`` is not supported by
                :class:`~docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory`.
            ValueError: When ``provider_config`` is absent for a provider that requires it (``litellm``).
            ValueError: When :class:`~docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory`
                fails to build the inference adapter.
        """
        provider_config: dict[str, Any] = config.get(OperatorConstants.Config.PROVIDER_CONFIG) or {}

        # A missing provider selects the default provider (same default the operator applies).
        llm_provider: str = (
            config.get(OperatorConstants.Config.PROVIDER) or OperatorConstants.Classification.DEFAULT_PROVIDER
        ).lower()
        supported_providers = LLMAdapterFactory.get_supported_providers(capability="inference")
        if llm_provider not in supported_providers:
            raise ValueError(
                f"Unsupported provider '{llm_provider}' for StandardLLMClassificationAdapter. "
                f"Supported providers: {sorted(supported_providers)}"
            )

        # watsonx may rely on WATSONX_* environment variables, so an empty provider_config is valid there.
        if llm_provider == OperatorConstants.Classification.PROVIDER_LITELLM and not provider_config:
            raise ValueError(
                "provider_config is required for StandardLLMClassificationAdapter. "
                "Must include at minimum: {'api_base': '...'}"
            )

        model_id: str = (
            provider_config.get(OperatorConstants.Config.MODEL_ID) or OperatorConstants.Classification.DEFAULT_MODEL
        )

        logger.debug(
            "StandardLLMClassificationAdapter.from_config: building LLMInferencePort provider=%s model=%s",
            llm_provider,
            model_id,
        )
        try:
            llm_adapter = LLMAdapterFactory.create_inference_adapter(
                provider=llm_provider,
                model_id=model_id,
                provider_config=provider_config,
            )
        except Exception as exc:
            raise ValueError(f"Failed to create LLM inference adapter for provider '{llm_provider}': {exc}") from exc

        return cls(llm_adapter=llm_adapter, config=config)

    @staticmethod
    def _failure_response(
        *,
        error: str,
        extracted_content: str | None = None,
        extraction_metadata: dict[str, Any] | None = None,
    ) -> ClassificationResponse:
        """Build a failed :class:`ClassificationResponse`, optionally carrying extraction side products."""
        return ClassificationResponse(
            document_type=OperatorConstants.Classification.UNKNOWN_TYPE,
            confidence=0,
            reasoning="",
            success=False,
            error=error,
            extracted_content=extracted_content,
            extraction_metadata=extraction_metadata,
        )

    def classify_document(
        self,
        *,
        doc_name: str,
        binary_content: bytes | None,
        existing_text: str | None,
        document_types: list[str] | dict[str, str],
    ) -> ClassificationResponse:
        """Classify a document using :class:`_LLMClassificationService`.

        This adapter classifies from text.  When *existing_text* is given it is
        used directly.  Otherwise the text is extracted from *binary_content*
        with Docling, and the extracted text plus its extraction metadata are
        returned on the response (``extracted_content`` / ``extraction_metadata``)
        so the operator can hand them to downstream operators without a second
        extraction.

        Args:
            doc_name: File name (used for Docling format detection when
                *existing_text* is absent).
            binary_content: Raw document bytes.  Required when *existing_text*
                is ``None``.
            existing_text: Pre-extracted text.  When given, Docling extraction
                is skipped entirely.
            document_types: Document types to classify into. Supplied by the
                operator, which resolved them via a ``DocumentClassProvider``.

        Returns:
            :class:`ClassificationResponse` populated by
            :class:`_LLMClassificationService`.  ``extracted_content`` and
            ``extraction_metadata`` are set only when this adapter extracted
            the text itself.
        """
        extracted_content: str | None = None
        extraction_metadata: dict[str, Any] | None = None

        if existing_text is not None:
            logger.debug(
                "StandardLLMAdapter: classifying %s using existing_text (len=%s)",
                doc_name,
                len(existing_text),
            )
            content = existing_text
        elif binary_content is not None:
            logger.debug(
                "StandardLLMAdapter: extracting text from %s with Docling (binary_size=%s bytes)",
                doc_name,
                len(binary_content),
            )
            result = OperatorUtils.extract_content(
                file_path=doc_name, binary_content=binary_content, doc_format=self.doc_format
            )
            if not result.get(OperatorConstants.Extraction.SUCCESS):
                error = result.get(OperatorConstants.Extraction.ERROR, "Extraction failed")
                logger.warning("StandardLLMAdapter: Docling extraction failed for %s: %s", doc_name, error)
                return self._failure_response(error=error)

            content = result.get(OperatorConstants.Columns.DOC_COLUMN_DEFAULT) or ""
            extracted_content = content
            extraction_metadata = result.get(OperatorConstants.Metadata.METADATA) or {}
            logger.debug(
                "StandardLLMAdapter: Docling extraction succeeded for %s (content_len=%s)",
                doc_name,
                len(content),
            )
            if not content.strip():
                return self._failure_response(
                    error="Empty content",
                    extracted_content=extracted_content,
                    extraction_metadata=extraction_metadata,
                )
        else:
            logger.warning(
                "StandardLLMAdapter: no content available for %s (both binary_content and existing_text are None)",
                doc_name,
            )
            return self._failure_response(
                error="StandardLLMClassificationAdapter requires existing_text or binary_content"
            )

        request = ClassificationRequest(
            content=content,
            document_types=document_types,
            max_content_length=self.max_content_length,
        )
        logger.debug(
            "StandardLLMAdapter: invoking _LLMClassificationService for %s (content_len=%s, types=%s)",
            doc_name,
            len(content),
            len(document_types),
        )
        response = self._service.classify_document(request=request)
        if extracted_content is None:
            return response
        # Copy rather than mutate: the service may return a shared/cached object.
        return replace(response, extracted_content=extracted_content, extraction_metadata=extraction_metadata)
