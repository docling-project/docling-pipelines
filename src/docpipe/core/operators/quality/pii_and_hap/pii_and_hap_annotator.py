# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
PII and HAP Detection Annotator.

Detects Personally Identifiable Information (PII) and Hate, Abuse, and Profanity (HAP)
content in documents.  PII and HAP detection are served by independently selectable
providers (``pii_provider`` / ``hap_provider``): multi-capable providers such as WatsonX
and LiteLLM (Ollama, OpenAI-compatible APIs) can serve both, while single-capability
providers such as Presidio (PII only) serve one.  The legacy ``provider`` /
``provider_config`` keys remain supported and select the provider for both.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pyarrow as pa

# Import adapters package to trigger self-registration with PIIAndHAPDetectionFactory
import docpipe.core.operators.quality.pii_and_hap.adapters.outbound  # noqa: F401
from docpipe.core.constants.constants import (
    AttributeDataTypes,
    DocpipeConstants,
    ExecutionStatus,
    Metrics,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.factories.pii_and_hap_detection_factory import (
    PIIAndHAPDetectionFactory,
)
from docpipe.core.operators.quality.pii_and_hap.domain.models import DetectionCapability, ProviderSelection
from docpipe.core.operators.quality.pii_and_hap.pii_and_hap_helper import (
    DEFAULT_HAP_THRESHOLD_VALUE,
    DEFAULT_PII_THRESHOLD_VALUE,
    DEFAULT_PII_TYPES_OF_CONCERN,
    DEFAULT_REDACTIONS,
    METADATA_HAP_FIELD_NAME,
    GuardRailsPIIAndHAPExtractor,
    get_detected_field,
    get_fields_to_redact,
    initialize_table_columns,
    update_table,
)
from docpipe.core.operators.quality.pii_and_hap.services.pii_hap_service import PIIHAPService
from docpipe.utils.core.strings import split_text_into_chunks
from docpipe.utils.infrastructure.concurrency import submit_task_with_context_propagation
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Chunking configuration defaults
DEFAULT_MIN_CHUNK_SIZE_IN_KB = 50 * 1024  # 50 KB
DEFAULT_MAX_CHUNK_SIZE_IN_KB = 100 * 1024  # 100 KB
DEFAULT_BATCH_SIZE = 4

# Provider types
PROVIDER = "provider"
PROVIDER_DEFAULT = "litellm"  # Default to LiteLLM (can access Ollama via api_base)
PROVIDER_WATSONX = "watsonx"
PROVIDER_LITELLM = "litellm"

# Per-capability provider config keys: capability -> (provider key, provider config key)
CAPABILITY_PROVIDER_KEYS: dict[DetectionCapability, tuple[str, str]] = {
    DetectionCapability.PII: (
        OperatorConstants.PIIHAP.PII_PROVIDER_KEY,
        OperatorConstants.PIIHAP.PII_PROVIDER_CONFIG_KEY,
    ),
    DetectionCapability.HAP: (
        OperatorConstants.PIIHAP.HAP_PROVIDER_KEY,
        OperatorConstants.PIIHAP.HAP_PROVIDER_CONFIG_KEY,
    ),
}
# Key added to each entry of the "providers" metadata map listing its capabilities
PROVIDER_CAPABILITIES_KEY = "capabilities"

# Configuration keys
DISPLAY_PII_KEY = "display_pii"
BATCH_SIZE_KEY = "batch_size"
MIN_CHUNK_SIZE_KEY = "min_chunk_size_kb"
MAX_CHUNK_SIZE_KEY = "max_chunk_size_kb"


class PIIAndHAPAnnotator(AbstractOperator):  # type: ignore[misc]
    """
    Extract PII and HAP information from ingested documents.

    PII and HAP detection are delegated to independently injected adapters
    (``PIIDetectionPort`` / ``HAPDetectionPort``).  Only the capabilities listed in
    ``expected_redactions`` are configured, validated and invoked.

    Attributes:
        provider (str): Legacy shorthand provider; used for any capability without
            its own ``pii_provider`` / ``hap_provider`` (default ``litellm``)
        pii_selection (ProviderSelection | None): Resolved PII provider (None if PII not expected)
        hap_selection (ProviderSelection | None): Resolved HAP provider (None if HAP not expected)
        provider_config (dict): Legacy shorthand provider configuration
            - model_id (str): Model identifier for the provider
            - api_base (str): API endpoint URL (for litellm)
            - api_key (str): Authentication key
        doc_column_name (str): Column containing document content
        redaction (bool): Enable PII redaction
        redaction_character (str): Character used to mask PII
        hap_redaction (bool): Enable HAP redaction
        hap_redaction_character (str): Character used to mask HAP
        pii_threshold (float): Confidence threshold for PII detection (0.0-1.0)
        hap_threshold (float): Confidence threshold for HAP detection (0.0-1.0)
        display_pii (bool): Include actual PII values in output for debugging
        pii_list (list): List of PII types to detect/redact
        expected_redactions (set): Set of redactions to perform
    """

    short_name: str = "pii_and_hap"
    category: OperatorCategory = OperatorCategory.Quality
    owner = DocpipeConstants.OWNER_DOCPIPE

    # Type hints for instance attributes
    doc_column_name: str
    provider: str
    model_name: str
    redaction: bool
    redaction_character: str
    hap_redaction: bool
    hap_redaction_character: str
    pii_threshold: float
    hap_threshold: float
    display_pii: bool
    pii_list: list[str]
    expected_redactions: set[str]
    partial_ingest: bool
    batch_size: int
    min_chunk_size: int
    max_chunk_size: int
    provider_config: dict[str, Any]
    pii_selection: ProviderSelection | None
    hap_selection: ProviderSelection | None
    provider_selection_errors: list[str]
    extractor: GuardRailsPIIAndHAPExtractor
    common_log_arguments: dict[str, Any]
    pii_hap_service: PIIHAPService | None

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        # Configuration mapping: (attribute_name, config_key, default_value)
        config_mappings = [
            # Detection configuration
            ("provider", PROVIDER, PROVIDER_DEFAULT),
            # Redaction configuration
            (
                "redaction",
                OperatorConstants.PIIHAP.REDACTION_KEY,
                OperatorConstants.PIIHAP.DEFAULT_REDACTION_VALUE,
            ),
            (
                "redaction_character",
                OperatorConstants.PIIHAP.REDACTION_CHARACTER_KEY,
                OperatorConstants.PIIHAP.DEFAULT_REDACTION_CHARACTER_VALUE,
            ),
            (
                "hap_redaction",
                OperatorConstants.PIIHAP.HAP_REDACTION_KEY,
                OperatorConstants.PIIHAP.DEFAULT_REDACTION_VALUE,
            ),
            (
                "hap_redaction_character",
                OperatorConstants.PIIHAP.HAP_REDACTION_CHARACTER_KEY,
                OperatorConstants.PIIHAP.DEFAULT_REDACTION_CHARACTER_VALUE,
            ),
            # Thresholds
            (
                "pii_threshold",
                OperatorConstants.PIIHAP.PII_THRESHOLD_KEY,
                DEFAULT_PII_THRESHOLD_VALUE,
            ),
            (
                "hap_threshold",
                OperatorConstants.PIIHAP.HAP_THRESHOLD_KEY,
                DEFAULT_HAP_THRESHOLD_VALUE,
            ),
            # PII types and redactions
            ("display_pii", DISPLAY_PII_KEY, False),
            ("pii_list", OperatorConstants.PIIHAP.PII_LIST, DEFAULT_PII_TYPES_OF_CONCERN),
            (
                "expected_redactions",
                OperatorConstants.PIIHAP.EXPECTED_REDACTIONS,
                DEFAULT_REDACTIONS,
            ),
            # Processing configuration
            ("partial_ingest", OperatorConstants.Config.PARTIAL_INGEST, False),
            ("batch_size", BATCH_SIZE_KEY, DEFAULT_BATCH_SIZE),
            # Chunking configuration - configurable for performance tuning
            ("min_chunk_size", MIN_CHUNK_SIZE_KEY, DEFAULT_MIN_CHUNK_SIZE_IN_KB),
            ("max_chunk_size", MAX_CHUNK_SIZE_KEY, DEFAULT_MAX_CHUNK_SIZE_IN_KB),
            # Provider-specific configuration (generic dictionary)
            ("provider_config", OperatorConstants.Config.PROVIDER_CONFIG, {}),
        ]

        # Apply all configurations
        for attr_name, config_key, default_value in config_mappings:
            setattr(self, attr_name, config.get(config_key, default_value))

        # Coerce numeric fields — global_config merging can inject them as strings
        self.batch_size = int(self.batch_size)
        self.min_chunk_size = int(self.min_chunk_size)
        self.max_chunk_size = int(self.max_chunk_size)
        self.pii_threshold = float(self.pii_threshold)
        self.hap_threshold = float(self.hap_threshold)

        # Read model_name directly from provider_config
        self.model_name = config.get(OperatorConstants.Config.PROVIDER_CONFIG, {}).get(
            OperatorConstants.Config.MODEL_ID
        )

        # Normalize expected_redactions to lowercase set for O(1) lookups
        self.expected_redactions = {r.lower() for r in self.expected_redactions}

        # Validate configuration
        self._validate_config()

        self.common_log_arguments = {
            DocpipeConstants.JOB_ID: self.job_id,
            DocpipeConstants.JOB_RUN_ID: self.job_run_id,
        }

        # Resolve one provider per capability actually needed by expected_redactions
        self.pii_selection = (
            PIIAndHAPAnnotator._resolve_provider_selection(config=config, capability=DetectionCapability.PII)
            if DetectionCapability.PII in self.expected_redactions
            else None
        )
        self.hap_selection = (
            PIIAndHAPAnnotator._resolve_provider_selection(config=config, capability=DetectionCapability.HAP)
            if DetectionCapability.HAP in self.expected_redactions
            else None
        )
        self.provider_selection_errors = PIIAndHAPAnnotator._get_provider_selection_errors(
            pii_selection=self.pii_selection, hap_selection=self.hap_selection
        )

        # Fail fast on provider/capability mismatches before any document is processed.
        # While validating a flow, the errors are reported through validate() instead.
        if self.provider_selection_errors and not self.validating_flow:
            raise ValueError("; ".join(self.provider_selection_errors))
        self.pii_hap_service = None if self.provider_selection_errors else self._initialize_pii_hap_service()

        # Initialize extractor
        self.extractor = GuardRailsPIIAndHAPExtractor(config)

    @staticmethod
    def _resolve_provider_selection(*, config: dict[str, Any], capability: DetectionCapability) -> ProviderSelection:
        """Resolve the provider and provider config used for one capability.

        Precedence:
            1. ``<capability>_provider`` when set, else the legacy ``provider``, else ``litellm``.
            2. ``<capability>_provider_config`` when non-empty; otherwise the legacy
               ``provider_config`` if ``provider`` is unset or names the same provider;
               otherwise an empty dict (the legacy config belongs to another provider).

        Args:
            config: Operator configuration.
            capability: Capability to resolve.

        Returns:
            The resolved provider selection.
        """
        provider_key, provider_config_key = CAPABILITY_PROVIDER_KEYS[capability]
        legacy_provider = config.get(PROVIDER) or None
        specific_provider = config.get(provider_key) or None

        if specific_provider:
            provider, used_provider_key = str(specific_provider), provider_key
        elif legacy_provider:
            provider, used_provider_key = str(legacy_provider), PROVIDER
        else:
            provider, used_provider_key = PROVIDER_DEFAULT, PROVIDER

        specific_config = config.get(provider_config_key) or None
        provider_config: Any
        if specific_config:
            provider_config, used_config_key = specific_config, provider_config_key
        elif legacy_provider is None or str(legacy_provider).lower() == provider.lower():
            provider_config = config.get(OperatorConstants.Config.PROVIDER_CONFIG) or {}
            used_config_key = OperatorConstants.Config.PROVIDER_CONFIG
        else:
            provider_config, used_config_key = {}, provider_config_key

        return ProviderSelection(
            provider=provider,
            provider_config=dict(provider_config) if isinstance(provider_config, dict) else {},
            provider_key=used_provider_key,
            provider_config_key=used_config_key,
        )

    @staticmethod
    def _get_provider_selection_errors(
        *, pii_selection: ProviderSelection | None, hap_selection: ProviderSelection | None
    ) -> list[str]:
        """Return registry/capability errors for the resolved selections (no adapter is built)."""
        errors: list[str] = []
        if pii_selection is not None:
            errors.extend(
                PIIAndHAPDetectionFactory.validate_selection(
                    capability=DetectionCapability.PII, selection=pii_selection
                )
            )
        if hap_selection is not None:
            errors.extend(
                PIIAndHAPDetectionFactory.validate_selection(
                    capability=DetectionCapability.HAP, selection=hap_selection
                )
            )
        return errors

    def _describe_providers(self) -> str:
        """Return a short 'pii=<provider>, hap=<provider>' description for logs."""
        parts = []
        if self.pii_selection is not None:
            parts.append(f"pii={self.pii_selection.provider}")
        if self.hap_selection is not None:
            parts.append(f"hap={self.hap_selection.provider}")
        return ", ".join(parts) if parts else "none"

    def _initialize_pii_hap_service(self) -> PIIHAPService:
        """Initialize the PII/HAP detection service.

        Calls ``PIIAndHAPDetectionFactory`` to build one adapter per required
        capability (shared when both resolve to the same provider and config), then
        injects them into ``PIIHAPService``, which validates them (fail-fast).

        Returns:
            PIIHAPService: Initialized detection service.

        Raises:
            ValueError: If a provider is not registered or lacks a required capability.
            DocpipeException: If adapter validation fails.
        """
        providers = self._describe_providers()
        try:
            pii_adapter, hap_adapter = PIIAndHAPDetectionFactory.create_adapters(
                pii=self.pii_selection,
                hap=self.hap_selection,
            )
            service = PIIHAPService(pii_adapter=pii_adapter, hap_adapter=hap_adapter)
            logger.info(
                "Successfully initialized PII/HAP service (%s)",
                providers,
                extra=self.common_log_arguments,
            )
            return service
        except Exception as e:
            logger.error(
                "Failed to initialize PII/HAP service (%s): %s",
                providers,
                e,
                extra=self.common_log_arguments,
            )
            raise

    def _validate_config(self) -> None:
        """Validate configuration values to ensure they are within acceptable ranges."""
        if not 0 <= self.pii_threshold <= 1:
            msg = f"pii_threshold must be between 0 and 1, got {self.pii_threshold}"
            raise ValueError(msg)
        if not 0 <= self.hap_threshold <= 1:
            msg = f"hap_threshold must be between 0 and 1, got {self.hap_threshold}"
            raise ValueError(msg)
        if self.batch_size <= 0:
            msg = f"batch_size must be positive, got {self.batch_size}"
            raise ValueError(msg)
        if self.min_chunk_size > self.max_chunk_size:
            msg = f"min_chunk_size ({self.min_chunk_size}) cannot exceed max_chunk_size ({self.max_chunk_size})"
            raise ValueError(msg)

    @staticmethod
    def _get_piihap_provider_schemas(*, capability: DetectionCapability | None = None) -> dict[str, Any]:
        """Return per-provider JSON Schema dicts for a provider config field.

        Iterates the ``PIIAndHAPDetectionFactory`` registry and calls
        ``get_config_schema()`` on each registered adapter class - adding a new
        provider requires only registering the adapter.  Each entry also lists the
        provider's ``capabilities`` (``['pii']``, ``['hap']`` or both).

        Args:
            capability: When given, only providers supporting it are included.
        """
        from docpipe.core.operators.operator_utils import OperatorUtils

        schemas: dict[str, Any] = {}
        for name in PIIAndHAPDetectionFactory.list_adapters(capability=capability):
            adapter_class = PIIAndHAPDetectionFactory.get_adapter_class(name)
            if adapter_class is None:
                continue
            schemas[name] = OperatorUtils.model_schema_to_docpipe(
                schema=adapter_class.get_config_schema().model_json_schema(),
                overrides={PROVIDER_CAPABILITIES_KEY: adapter_class.get_capabilities()},
            )
        return schemas

    @staticmethod
    def _get_capability_provider_attributes(*, capability: DetectionCapability) -> dict[str, Any]:
        """Return metadata for ``<capability>_provider`` and ``<capability>_provider_config``."""
        provider_key, provider_config_key = CAPABILITY_PROVIDER_KEYS[capability]
        label = capability.value.upper()
        capable_providers = PIIAndHAPDetectionFactory.list_adapters(capability=capability)
        return {
            provider_key: {
                OperatorConstants.Misc.NAME: f"{label} Provider",
                OperatorConstants.Config.DESCRIPTION: (
                    f"Provider used for {label} detection ({', '.join(capable_providers)}). "
                    f"Overrides '{PROVIDER}' for {label} only; when unset, '{PROVIDER}' is used."
                ),
                OperatorConstants.Config.REQUIRED: False,
                OperatorConstants.Config.VALID_VALUES: capable_providers,
                OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
            },
            provider_config_key: {
                OperatorConstants.Misc.NAME: f"{label} Provider Configuration",
                OperatorConstants.Config.DESCRIPTION: (
                    f"Configuration for the {label} provider. Fields vary by provider - see the 'providers' "
                    f"schema. When empty, '{OperatorConstants.Config.PROVIDER_CONFIG}' is used if '{PROVIDER}' "
                    f"is unset or names the same provider."
                ),
                OperatorConstants.Config.REQUIRED: False,
                OperatorConstants.Config.DEFAULT: {},
                OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                OperatorConstants.Config.PROVIDERS: PIIAndHAPAnnotator._get_piihap_provider_schemas(
                    capability=capability
                ),
                OperatorConstants.Config.PROVIDER_FIELD: provider_key,
            },
        }

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Return operator metadata for SDK."""
        return {
            OperatorConstants.Misc.SDK: True,
            OperatorConstants.Misc.CATEGORY: PIIAndHAPAnnotator.category.value,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: PIIAndHAPAnnotator.is_available(),
            OperatorConstants.Misc.LABEL: "PII and HAP Annotator",
            OperatorConstants.Config.DESCRIPTION: "Detect and optionally redact Personally Identifiable Information (PII) and Hate, Abuse, and Profanity (HAP) content in documents.",
            OperatorConstants.Config.FEATURES: {
                "pii_bank_account": {
                    OperatorConstants.Misc.NAME: "Bank Account Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of Bank Accounts found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "pii_credit_card": {
                    OperatorConstants.Misc.NAME: "Credit Card Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of Credit Cards found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "pii_email_address": {
                    OperatorConstants.Misc.NAME: "Email Address Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of Email Addresses found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "pii_ip_address": {
                    OperatorConstants.Misc.NAME: "IP Address Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of IP Addresses found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "pii_phone_number": {
                    OperatorConstants.Misc.NAME: "Phone Number Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of Phone Numbers found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "pii_ssn_details": {
                    OperatorConstants.Misc.NAME: "SSN Details Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of SSNs found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "pii_person_name": {
                    OperatorConstants.Misc.NAME: "Person Name Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of Person Names found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "pii_date_of_birth": {
                    OperatorConstants.Misc.NAME: "Date of Birth Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of Dates of Birth found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "pii_address": {
                    OperatorConstants.Misc.NAME: "Address Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of Addresses found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "pii_passport_number": {
                    OperatorConstants.Misc.NAME: "Passport Number Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of Passport Numbers found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "pii_driver_license": {
                    OperatorConstants.Misc.NAME: "Driver License Number Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of Driver License Numbers found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "pii_national_id": {
                    OperatorConstants.Misc.NAME: "National ID Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of National IDs found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "pii_medical_record": {
                    OperatorConstants.Misc.NAME: "Medical Record Number Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of Medical Record Numbers found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "hap": {
                    OperatorConstants.Misc.NAME: "HAP Count",
                    OperatorConstants.Config.DESCRIPTION: "Number of HAP instances found in document",
                    OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
            },
            OperatorConstants.Config.ATTRIBUTES: {
                # ------------------------
                # PII control
                # ------------------------
                OperatorConstants.PIIHAP.EXPECTED_REDACTIONS: {
                    OperatorConstants.Misc.NAME: "Expected Redactions",
                    OperatorConstants.Config.DESCRIPTION: "List of redactions to perform",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: [r.upper() for r in DEFAULT_REDACTIONS],
                    OperatorConstants.Config.VALID_VALUES: [r.upper() for r in DEFAULT_REDACTIONS],
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.LIST,
                },
                OperatorConstants.PIIHAP.PII_LIST: {
                    OperatorConstants.Misc.NAME: "PII List",
                    OperatorConstants.Config.DESCRIPTION: "List of PII types to detect/redact",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: DEFAULT_PII_TYPES_OF_CONCERN,
                    OperatorConstants.Config.VALID_VALUES: DEFAULT_PII_TYPES_OF_CONCERN,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.LIST,
                },
                DISPLAY_PII_KEY: {
                    OperatorConstants.Misc.NAME: "Display PII",
                    OperatorConstants.Config.DESCRIPTION: "Include actual PII values in output columns for debugging/analysis",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                },
                # ------------------------
                # Redaction configuration
                # ------------------------
                OperatorConstants.PIIHAP.REDACTION_KEY: {
                    OperatorConstants.Misc.NAME: "PII Redaction",
                    OperatorConstants.Config.DESCRIPTION: "Enable PII redaction",
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.PIIHAP.DEFAULT_REDACTION_VALUE,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                },
                OperatorConstants.PIIHAP.REDACTION_CHARACTER_KEY: {
                    OperatorConstants.Misc.NAME: "PII Masking Character",
                    OperatorConstants.Config.DESCRIPTION: "Character used to mask PII",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.PIIHAP.DEFAULT_REDACTION_CHARACTER_VALUE,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OperatorConstants.PIIHAP.HAP_REDACTION_KEY: {
                    OperatorConstants.Misc.NAME: "HAP Redaction",
                    OperatorConstants.Config.DESCRIPTION: "Enable HAP redaction",
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.PIIHAP.DEFAULT_REDACTION_VALUE,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                },
                OperatorConstants.PIIHAP.HAP_REDACTION_CHARACTER_KEY: {
                    OperatorConstants.Misc.NAME: "HAP Masking Character",
                    OperatorConstants.Config.DESCRIPTION: "Character used to mask HAP",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.PIIHAP.DEFAULT_REDACTION_CHARACTER_VALUE,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                # ------------------------
                # Thresholds
                # ------------------------
                OperatorConstants.PIIHAP.PII_THRESHOLD_KEY: {
                    OperatorConstants.Misc.NAME: "PII Threshold",
                    OperatorConstants.Config.DESCRIPTION: "Confidence threshold for PII detection (0.0 - 1.0)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: DEFAULT_PII_THRESHOLD_VALUE,
                    OperatorConstants.Filtering.MIN_VALUE: 0.0,
                    OperatorConstants.Filtering.MAX_VALUE: 1.0,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.FLOAT,
                },
                OperatorConstants.PIIHAP.HAP_THRESHOLD_KEY: {
                    OperatorConstants.Misc.NAME: "HAP Threshold",
                    OperatorConstants.Config.DESCRIPTION: "Confidence threshold for HAP detection (0.0 - 1.0)",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: DEFAULT_HAP_THRESHOLD_VALUE,
                    OperatorConstants.Filtering.MIN_VALUE: 0.0,
                    OperatorConstants.Filtering.MAX_VALUE: 1.0,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.FLOAT,
                },
                # ------------------------
                # Detection configuration
                # ------------------------
                PROVIDER: {
                    OperatorConstants.Misc.NAME: "Provider",
                    OperatorConstants.Config.DESCRIPTION: (
                        f"Detection provider for every expected redaction without its own "
                        f"'{OperatorConstants.PIIHAP.PII_PROVIDER_KEY}' / '{OperatorConstants.PIIHAP.HAP_PROVIDER_KEY}' "
                        f"({', '.join(PIIAndHAPDetectionFactory.list_adapters())}). It must support every expected "
                        f"redaction it serves - see 'capabilities' in the 'providers' schema (presidio is PII only). "
                        f"Note: Ollama can be accessed via {PROVIDER_LITELLM} with api_base='http://localhost:11434/v1'"
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: PROVIDER_DEFAULT,
                    OperatorConstants.Config.VALID_VALUES: PIIAndHAPDetectionFactory.list_adapters(),
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OperatorConstants.Config.PROVIDER_CONFIG: {
                    OperatorConstants.Misc.NAME: "Provider Configuration",
                    OperatorConstants.Config.DESCRIPTION: "Provider-specific configuration. Fields vary by provider — see the 'providers' schema for details.",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: {},
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Config.PROVIDERS: PIIAndHAPAnnotator._get_piihap_provider_schemas(),
                },
                # ------------------------
                # Per-capability providers (override provider / provider_config)
                # ------------------------
                **PIIAndHAPAnnotator._get_capability_provider_attributes(capability=DetectionCapability.PII),
                **PIIAndHAPAnnotator._get_capability_provider_attributes(capability=DetectionCapability.HAP),
            },
        }

    @staticmethod
    def get_required_features() -> list[str]:
        """Get required features."""
        return [OperatorConstants.Columns.DOC_COLUMN_DEFAULT]

    def get_payload_for_detections(self, doc_contents: Any) -> dict[str, Any]:
        """Build request payload for detection API."""
        contents = doc_contents if isinstance(doc_contents, str) else doc_contents.as_py()
        payload: dict[str, Any] = {"input": contents, "detectors": {}}
        if OperatorConstants.PIIHAP.PII_FIELD_NAME in self.expected_redactions:
            payload["detectors"][OperatorConstants.PIIHAP.PII_FIELD_NAME] = {"threshold": self.pii_threshold}
        if OperatorConstants.PIIHAP.HAP_FIELD_NAME in self.expected_redactions:
            payload["detectors"][OperatorConstants.PIIHAP.HAP_FIELD_NAME] = {"threshold": self.hap_threshold}
        return payload

    def populate_table_columns(
        self,
        table_columns: dict[str, list[Any]],
        columns_to_add: dict[str, Any],
        fields_to_redact: list[str],
    ) -> None:
        """Populate table columns with detection results."""
        from .pii_and_hap_helper import (
            COLUMN_NAME_SUFFIX,
            DEFAULT_PII_TO_COLUMN_MAPPING,
            DISPLAY_PII_COLUMN_SUFFIX,
            PII_COLUMN_PREFIX,
        )

        for field in fields_to_redact:
            if field == METADATA_HAP_FIELD_NAME:
                table_columns[OperatorConstants.PIIHAP.HAP_FIELD_NAME].append(
                    columns_to_add[OperatorConstants.PIIHAP.HAP_FIELD_NAME]
                )
            else:
                column_name = DEFAULT_PII_TO_COLUMN_MAPPING.get(field)
                if not column_name:
                    continue

                pii_column_name = PII_COLUMN_PREFIX + column_name + COLUMN_NAME_SUFFIX
                table_columns[pii_column_name].append(columns_to_add[column_name])

                if self.display_pii:
                    display_pii_column_name = (
                        PII_COLUMN_PREFIX + column_name + DISPLAY_PII_COLUMN_SUFFIX + COLUMN_NAME_SUFFIX
                    )
                    table_columns[display_pii_column_name].append(
                        columns_to_add[column_name + DISPLAY_PII_COLUMN_SUFFIX]
                    )

    def _perform_detections_for_single_document(self, doc_info: dict[str, Any]) -> dict[str, Any]:
        """Perform PII/HAP detection for a single document using the configured adapters."""
        try:
            if self.pii_hap_service is None:
                raise ValueError("PII/HAP service is not initialized: " + "; ".join(self.provider_selection_errors))
            providers = self._describe_providers()
            all_detections: list[Any] = []
            doc_content_chunks = split_text_into_chunks(
                text=doc_info["doc_contents"].as_py(),
                min_size=self.min_chunk_size,
                max_size=self.max_chunk_size,
            )

            for doc_content_chunk in doc_content_chunks:
                payload = self.get_payload_for_detections(doc_content_chunk)

                # Log detection processing
                logger.info(
                    "Processing PII/HAP detection with providers: %s",
                    providers,
                    extra=self.common_log_arguments,
                )

                # Use service for detection
                response = self.pii_hap_service.detect_pii_hap(payload=payload)

                # Log detection count for this chunk
                detection_count = len(response.detections) if response.detections else 0
                logger.debug(
                    "Chunk returned %s detections",
                    detection_count,
                    extra=self.common_log_arguments,
                )

                # Convert domain models back to dict format for compatibility with existing code
                for detection in response.detections:
                    detection_dict = {
                        "detection": detection.detection,
                        "detection_type": detection.detection_type,
                        "score": detection.score,
                        "start": detection.start,
                        "end": detection.end,
                    }
                    if detection.text:
                        detection_dict["text"] = detection.text
                    if detection.evidences:
                        detection_dict["evidences"] = detection.evidences
                    all_detections.append(detection_dict)

            processed_response = {"detections": all_detections}
            doc_info.update({"processed_response": processed_response, "success": True})
            return doc_info

        except Exception as exc:
            logger.error("PII/HAP detection failed: %s", exc, extra=self.common_log_arguments)
            doc_info.update({"status_code": 500, "error_detail": str(exc), "success": False})
            return doc_info

    def transform(self, table: pa.Table, file_name: str = "") -> tuple[list[pa.Table], dict[str, Any]]:
        """
        Extract PII and HAP information from documents.

        Parameters:
        -----------
        table : pyarrow.Table
            Input table containing documents to analyze

        Returns:
        --------
        tuple[list[pyarrow.Table], dict[str, Any]]:
            Output tables with PII/HAP columns and metadata
        """
        logger.info("Running PII and HAP detection", extra=self.common_log_arguments)

        from docpipe.core.operators.operator_utils import OperatorUtils

        OperatorUtils.validate_columns(
            table=table,
            required=PIIAndHAPAnnotator.get_required_features(),
            operator_name=self.short_name,
        )

        fields_to_redact = get_fields_to_redact(self.expected_redactions, self.pii_list)

        # Initialize metadata
        metadata = self.create_base_metadata(total_docs_count=OperatorUtils.find_doc_count(table=table))

        # Initialize table columns
        table_columns = initialize_table_columns(
            metadata=metadata,
            fields_to_redact=fields_to_redact,
            display_pii=self.display_pii,
        )

        remove_row_idx: list[int] = []
        remove_row_id: list[str] = []
        # LLM-based PII/HAP detection may benefit from structured DocLang XML; pass content as-is
        new_doc_content = table[self.doc_column].to_pylist()
        name_column = table[OperatorConstants.Misc.NAME].to_pylist()
        id_column = table[OperatorConstants.Columns.ID].to_pylist()

        doc_info_list = []

        for idx, doc_contents in enumerate(table[self.doc_column]):
            doc_info = {"idx": idx, "doc_contents": doc_contents}
            doc_info_list.append(doc_info)

        # Process documents in parallel
        with ThreadPoolExecutor(max_workers=self.batch_size, thread_name_prefix="PIIAndHAPExecutor") as executor:
            logger.info(
                "Submitting %s documents to executor in batches of %s",
                len(doc_info_list),
                self.batch_size,
                extra=self.common_log_arguments,
            )

            futures = [
                submit_task_with_context_propagation(executor, self._perform_detections_for_single_document, doc_info)
                for doc_info in doc_info_list
            ]

            _ = [future.result() for future in futures]

        logger.info(
            "Completed processing all documents for PII and HAP",
            extra=self.common_log_arguments,
        )

        # Process results
        for doc_info in doc_info_list:
            if not doc_info["success"]:
                e = doc_info["error_detail"]
                logger.error(
                    "PII and HAP detection failed with error: %s",
                    e,
                    extra=self.common_log_arguments,
                )
                idx = doc_info["idx"]
                actual_file_name = name_column[idx]
                _id = id_column[idx]
                logger.error(
                    "PII and HAP extraction failed. %s is removed",
                    actual_file_name,
                    extra=self.common_log_arguments,
                )
                self._populate_remove_row_id_and_index(
                    file_name=actual_file_name,
                    metadata=metadata,
                    remove_row_id=remove_row_id,
                    _id=_id,
                    remove_row_idx=remove_row_idx,
                    idx=idx,
                    e=Exception(e),
                )
                continue

            document_content = doc_info.get("doc_contents")

            try:
                columns_to_add = self.extractor.column_values(fields_to_redact)
                for detection_dict in doc_info["processed_response"]["detections"]:
                    logger.debug(
                        "Detection type: %s, score: %s, position: %s-%s",
                        detection_dict.get("detection"),
                        detection_dict.get("score"),
                        detection_dict.get("start"),
                        detection_dict.get("end"),
                        extra=self.common_log_arguments,
                    )
                    detected_field = get_detected_field(detection_dict, fields_to_redact)

                    if not detected_field:
                        logger.debug(
                            "Unknown detection label %s - not in mapping, skipping",
                            detection_dict.get("detection"),
                            extra=self.common_log_arguments,
                        )
                        continue

                    detection_dict.pop("evidences", None)
                    detection_dict.pop("detection_type", None)

                    # Redact if needed
                    input_to_redact = {
                        "table": table,
                        "updated_content_list": new_doc_content,
                        "doc_content": document_content,
                        "detection_dict": detection_dict,
                        "row_index": doc_info["idx"],
                    }
                    table, doc_contents = self.extractor.redact_if_needed(detected_field, input_to_redact)
                    document_content = doc_contents
                    metadata, columns_to_add = self.extractor.update_metadata_and_columns_to_add(
                        metadata, columns_to_add, detected_field, detection_dict
                    )

                self.populate_table_columns(table_columns, columns_to_add, fields_to_redact)
                metadata[Metrics.External.PROCESSED_DOCS] += 1

                logger.info(
                    "PII and HAP extraction completed for doc: %s",
                    table["name"][doc_info["idx"]],
                    extra=self.common_log_arguments,
                )
            except Exception as exc:
                logger.error(
                    "PII and HAP detection failed with error: %s",
                    exc,
                    extra=self.common_log_arguments,
                )
                idx = doc_info["idx"]
                actual_file_name = name_column[idx]
                _id = id_column[idx]
                logger.error(
                    "PII and HAP extraction failed. %s is removed",
                    actual_file_name,
                    extra=self.common_log_arguments,
                )
                self._populate_remove_row_id_and_index(
                    file_name=actual_file_name,
                    metadata=metadata,
                    remove_row_id=remove_row_id,
                    _id=_id,
                    remove_row_idx=remove_row_idx,
                    idx=idx,
                    e=exc,
                )
                continue

        # Remove failed documents
        if self.partial_ingest and len(remove_row_idx) > 0:
            table = OperatorUtils.remove_rows(table=table, remove_row_idx=remove_row_idx)
        elif not self.partial_ingest and len(remove_row_id) > 0:
            table = OperatorUtils.remove_all_rows(table=table, remove_row_id=remove_row_id)

        table = update_table(table, table_columns, fields_to_redact, self.display_pii)
        metadata[Metrics.External.PROCESSED_ROWS] = table.num_rows

        return [table], metadata

    def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
        """Validate."""
        from docpipe.utils.operators.config_validation import validate_config_from_metadata

        super().validate(errors, warnings, available_features)

        if self.should_validate_field(field_value=self.expected_redactions):
            if self.expected_redactions and not set(self.expected_redactions).issubset(set(DEFAULT_REDACTIONS)):
                errors.append(
                    f"Invalid list of redaction types. The value provided, "
                    f"'{self.expected_redactions}' is not supported. "
                    f"Please use values from {DEFAULT_REDACTIONS}."
                )

        if self.should_validate_field(field_value=self.pii_list):
            if self.pii_list and not set(self.pii_list).issubset(set(DEFAULT_PII_TYPES_OF_CONCERN)):
                errors.append(
                    f"Invalid list of fields for redaction. The fields provided, "
                    f"'{self.pii_list}' have values which are not supported. "
                    f"Please use values from {DEFAULT_PII_TYPES_OF_CONCERN}."
                )

        # Use generic validation for provider_config
        metadata = self.get_metadata()
        attributes = metadata.get(OperatorConstants.Config.ATTRIBUTES, {})
        validate_config_from_metadata(config=self.config, attributes=attributes, errors=errors)

        # Provider/capability checks are structural (registry lookup only), so they run
        # in both the flow-validation and execution phases.
        errors.extend(self.provider_selection_errors)

        # Validate provider-specific requirements of each selected provider's config
        if self.should_validate_field(field_value=self.provider_config):
            self._validate_provider_configs(errors=errors)

        if len(errors) > 0:
            logger.error("PII/HAP operator validation failed: %s", errors)

    def _validate_provider_configs(self, *, errors: list[str]) -> None:
        """Append per-provider config errors for every selected capability provider.

        When PII and HAP resolve to the same provider and config key (e.g. the legacy
        ``provider`` / ``provider_config`` shorthand) the config is checked only once.
        """
        config_keys = (
            OperatorConstants.Config.PROVIDER_CONFIG,
            OperatorConstants.PIIHAP.PII_PROVIDER_CONFIG_KEY,
            OperatorConstants.PIIHAP.HAP_PROVIDER_CONFIG_KEY,
        )
        for key in config_keys:
            value = self.config.get(key)
            if value is not None and not isinstance(value, dict):
                errors.append(f"{key} must be a dictionary, got {type(value).__name__}")

        if self.provider_selection_errors:
            return
        checked: set[tuple[str, str]] = set()
        for selection in (self.pii_selection, self.hap_selection):
            if selection is None:
                continue
            signature = (selection.provider.lower(), selection.provider_config_key)
            if signature in checked:
                continue
            checked.add(signature)
            adapter_class = PIIAndHAPDetectionFactory.get_adapter_class(selection.provider)
            if adapter_class is not None:
                errors.extend(
                    adapter_class.validate_provider_config(
                        provider_config=selection.provider_config,
                        config_key=selection.provider_config_key,
                    )
                )

    def _populate_remove_row_id_and_index(
        self,
        *,
        file_name: str,
        metadata: dict[str, Any],
        remove_row_id: list[Any],
        _id: str,
        remove_row_idx: list[Any],
        idx: int,
        e: Exception,
    ) -> None:
        """Record failed document and update tracking lists."""
        from docpipe.core.operators.operator_utils import OperatorUtils

        reason = f"Error: {getattr(e, 'message', str(e)) if getattr(e, 'message', str(e)) else repr(e)}"
        self.record_failed_document(metadata=metadata, doc_id=_id, doc_name=file_name, reason=reason)

        current_status = metadata[Metrics.External.NODE_STATUS]
        metadata[Metrics.External.NODE_STATUS] = OperatorUtils.merge_status(
            current_status if isinstance(current_status, ExecutionStatus) else ExecutionStatus(current_status),
            ExecutionStatus.COMPLETED_WITH_ERRORS,
        ).value

        remove_row_idx.append(idx)
        if _id not in remove_row_id:
            remove_row_id.append(_id)
