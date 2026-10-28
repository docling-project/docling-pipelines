# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Common base for PII and HAP detection adapter ports.

Holds the contract shared by every detection adapter regardless of capability:
registration metadata, capability flags, config schema and validation.  The
capability-scoped ports (``PIIDetectionPort``, ``HAPDetectionPort``) extend it.
"""

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel

from docpipe.core.constants.operator_constants import OperatorConstants


class DetectionAdapterPort(ABC):
    """Shared contract for all PII/HAP detection adapters.

    Class attributes:
        ADAPTER_NAME: Unique identifier used for factory registration (e.g. ``'watsonx'``).
        ADAPTER_DISPLAY_NAME: Human-readable name for UI display.
        SUPPORTS_PII: ``True`` when the adapter implements ``PIIDetectionPort``.
        SUPPORTS_HAP: ``True`` when the adapter implements ``HAPDetectionPort``.
        REQUIRES_MODEL_ID: ``True`` when ``provider_config.model_id`` is mandatory.

    Concrete adapters must declare ``SUPPORTS_PII`` / ``SUPPORTS_HAP`` explicitly; the
    factory rejects adapters whose flags do not match the ports they implement.
    """

    ADAPTER_NAME: str
    ADAPTER_DISPLAY_NAME: str
    SUPPORTS_PII: ClassVar[bool] = False
    SUPPORTS_HAP: ClassVar[bool] = False
    REQUIRES_MODEL_ID: ClassVar[bool] = True

    def __init__(self, *, model_id: str, provider_config: dict[str, Any]) -> None:
        """Store the common constructor arguments.

        Args:
            model_id: Model identifier (may be empty for adapters that do not use one).
            provider_config: Provider-specific configuration dict.
        """
        self._model_id = model_id
        self._provider_config = provider_config

    @staticmethod
    @abstractmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter.

        Used by ``PIIAndHAPAnnotator.get_metadata()`` to publish the per-provider
        ``provider_config`` schema without hard-coding adapter names.
        """
        ...

    @abstractmethod
    def validate(self) -> dict[str, Any]:
        """Validate adapter configuration before any documents are processed.

        Called during service initialisation so credential, dependency or config
        errors surface at startup (fail-fast) rather than mid-run.

        Returns:
            Validation result dictionary with at minimum:
                - valid (bool): True if configuration is valid.
                - errors (list[str]): Error messages when valid is False.
                - warnings (list[str]): Non-fatal warnings.
        """
        ...

    @classmethod
    def get_capabilities(cls) -> list[str]:
        """Return the capability names (``'pii'``, ``'hap'``) this adapter supports."""
        capabilities: list[str] = []
        if cls.SUPPORTS_PII:
            capabilities.append(OperatorConstants.PIIHAP.PII_FIELD_NAME)
        if cls.SUPPORTS_HAP:
            capabilities.append(OperatorConstants.PIIHAP.HAP_FIELD_NAME)
        return capabilities

    @classmethod
    def validate_provider_config(cls, *, provider_config: dict[str, Any], config_key: str) -> list[str]:
        """Statically check ``provider_config`` without instantiating the adapter.

        Used by ``PIIAndHAPAnnotator.validate()`` during flow validation.  The default
        implementation enforces ``model_id`` when ``REQUIRES_MODEL_ID`` is set; adapters
        override it to add provider-specific required keys.

        Args:
            provider_config: The provider configuration to check.
            config_key: Name of the config key the dict came from, used in messages.

        Returns:
            List of error messages (empty when the config looks valid).
        """
        if not cls.REQUIRES_MODEL_ID:
            return []
        if not provider_config:
            return [f"{config_key} is required for provider '{cls.ADAPTER_NAME}'"]
        model_id = provider_config.get(OperatorConstants.Config.MODEL_ID)
        if not model_id or not isinstance(model_id, str):
            return [f"{config_key}.model_id is required and must be a non-empty string"]
        return []
