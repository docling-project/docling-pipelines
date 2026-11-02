# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Factory for creating PII and HAP detection adapters.

Implements the registry pattern with decorator-based auto-registration.  Each
registered adapter declares which capabilities it supports (``SUPPORTS_PII`` /
``SUPPORTS_HAP``); the factory validates those declarations at registration time
and validates provider selections per capability before any adapter is built.
"""

from typing import Any, ClassVar, cast

from docpipe.core.operators.quality.pii_and_hap.domain.models import DetectionCapability, ProviderSelection
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.detection_adapter_port import DetectionAdapterPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.hap_detection_port import HAPDetectionPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_detection_port import PIIDetectionPort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

_CAPABILITY_PORTS: dict[DetectionCapability, type[DetectionAdapterPort]] = {
    DetectionCapability.PII: PIIDetectionPort,
    DetectionCapability.HAP: HAPDetectionPort,
}
_CAPABILITY_FLAGS: dict[DetectionCapability, str] = {
    DetectionCapability.PII: "SUPPORTS_PII",
    DetectionCapability.HAP: "SUPPORTS_HAP",
}


class PIIAndHAPDetectionFactory:
    """Factory for creating PII/HAP detection adapters.

    Maintains a registry of available adapters keyed by ``ADAPTER_NAME``.
    Adapters self-register at import time via the
    ``@register_pii_and_hap_detection_adapter`` decorator.  A single registry holds
    PII-only, HAP-only and dual-capability adapters; capability lookups filter it.

    Example::

        @register_pii_and_hap_detection_adapter
        class MyAdapter(PIIDetectionPort):
            ADAPTER_NAME = "myprovider"
            SUPPORTS_PII = True
            SUPPORTS_HAP = False
            ...

        pii_adapter, hap_adapter = PIIAndHAPDetectionFactory.create_adapters(
            pii=ProviderSelection(provider="myprovider", provider_config={}),
            hap=None,
        )
    """

    _registry: ClassVar[dict[str, type[DetectionAdapterPort]]] = {}

    @classmethod
    def register[AdapterClassT: type[DetectionAdapterPort]](cls, adapter_class: AdapterClassT) -> AdapterClassT:
        """Register an adapter class.

        Args:
            adapter_class: Adapter class to register.  Must define ``ADAPTER_NAME`` and
                declare capability flags that match the ports it implements.

        Returns:
            The adapter class unchanged (allows use as a decorator).

        Raises:
            ValueError: If ``ADAPTER_NAME`` is missing, no capability is declared, or a
                capability flag does not match the implemented port.
        """
        if not hasattr(adapter_class, "ADAPTER_NAME") or not adapter_class.ADAPTER_NAME:
            raise ValueError(f"Adapter {adapter_class.__name__} must define ADAPTER_NAME")

        errors = cls._check_capability_declarations(adapter_class=adapter_class)
        if errors:
            raise ValueError(
                f"Adapter {adapter_class.__name__} has invalid capability declarations: {'; '.join(errors)}"
            )

        name = adapter_class.ADAPTER_NAME.lower()
        cls._registry[name] = adapter_class
        logger.debug(
            "Registered PII/HAP detection adapter: %s (capabilities: %s)", name, adapter_class.get_capabilities()
        )
        return adapter_class

    @staticmethod
    def _check_capability_declarations(*, adapter_class: type[DetectionAdapterPort]) -> list[str]:
        """Return errors when ``SUPPORTS_*`` flags disagree with the implemented ports."""
        errors: list[str] = []
        for capability, port in _CAPABILITY_PORTS.items():
            flag_name = _CAPABILITY_FLAGS[capability]
            declared = bool(getattr(adapter_class, flag_name, False))
            implemented = issubclass(adapter_class, port)
            if declared and not implemented:
                errors.append(f"{flag_name} is True but the class does not implement {port.__name__}")
            elif implemented and not declared:
                errors.append(f"implements {port.__name__} but does not declare {flag_name} = True")
        if not errors and not adapter_class.get_capabilities():
            errors.append("must implement PIIDetectionPort and/or HAPDetectionPort")
        return errors

    @classmethod
    def get_adapter_class(cls, provider: str) -> type[DetectionAdapterPort] | None:
        """Return the registered adapter class for ``provider`` (case-insensitive), or None."""
        return cls._registry.get(provider.lower())

    @classmethod
    def supports(cls, provider: str, *, capability: DetectionCapability) -> bool:
        """Return True when ``provider`` is registered and supports ``capability``."""
        adapter_class = cls.get_adapter_class(provider)
        return adapter_class is not None and capability.value in adapter_class.get_capabilities()

    @classmethod
    def list_adapters(cls, *, capability: DetectionCapability | None = None) -> list[str]:
        """Return sorted registered provider names, optionally filtered by capability."""
        if capability is None:
            return sorted(cls._registry.keys())
        return sorted(name for name in cls._registry if cls.supports(name, capability=capability))

    @classmethod
    def validate_selection(cls, *, capability: DetectionCapability, selection: ProviderSelection) -> list[str]:
        """Check that ``selection`` names a registered provider supporting ``capability``.

        Pure registry lookup; no adapter is instantiated and no network call is made.

        Args:
            capability: Capability the provider is selected for.
            selection: Provider selection resolved from the operator config.

        Returns:
            List of error messages (empty when the selection is valid).
        """
        adapter_class = cls.get_adapter_class(selection.provider)
        if adapter_class is None:
            available = ", ".join(cls.list_adapters())
            return [
                f"Unknown PII/HAP detection provider: '{selection.provider}' "
                f"(set via '{selection.provider_key}'). Registered providers: {available}"
            ]
        if capability.value not in adapter_class.get_capabilities():
            capable = ", ".join(cls.list_adapters(capability=capability)) or "none"
            return [
                f"Provider '{selection.provider}' (set via '{selection.provider_key}') does not support "
                f"{capability.value.upper()} detection. Providers supporting {capability.value.upper()}: {capable}. "
                f"Set '{capability.value}_provider' to one of them, or remove '{capability.value.upper()}' "
                "from expected_redactions."
            ]
        return []

    @classmethod
    def create(
        cls,
        provider: str,
        *,
        model_id: str,
        provider_config: dict[str, Any],
        capability: DetectionCapability | None = None,
    ) -> DetectionAdapterPort:
        """Create a detection adapter instance.

        Args:
            provider: Provider name - must match an adapter's ``ADAPTER_NAME``.
            model_id: Model identifier forwarded to the adapter.
            provider_config: Provider-specific configuration dict.
            capability: When given, the provider must support this capability.

        Returns:
            Initialised adapter.

        Raises:
            ValueError: If ``provider`` is not registered (the message lists all
                registered names) or does not support ``capability``.
        """
        key = provider.lower()
        adapter_class = cls._registry.get(key)
        if not adapter_class:
            available = ", ".join(sorted(cls._registry.keys()))
            raise ValueError(f"Unknown PII/HAP detection provider: '{provider}'. Registered providers: {available}")
        if capability is not None and capability.value not in adapter_class.get_capabilities():
            capable = ", ".join(cls.list_adapters(capability=capability)) or "none"
            raise ValueError(
                f"Provider '{provider}' does not support {capability.value.upper()} detection. "
                f"Providers supporting {capability.value.upper()}: {capable}"
            )

        logger.debug("Creating PII/HAP detection adapter: %s", key)
        return adapter_class(model_id=model_id, provider_config=provider_config)

    @classmethod
    def create_adapters(
        cls,
        *,
        pii: ProviderSelection | None,
        hap: ProviderSelection | None,
    ) -> tuple[PIIDetectionPort | None, HAPDetectionPort | None]:
        """Validate selections and build one adapter per required capability.

        Pass ``None`` for a capability that is not needed; no adapter is built for it.
        When both capabilities select the same provider with an identical config, a
        single adapter instance is shared so dual-capability providers can serve both
        in one call.

        Args:
            pii: Provider selection for PII detection, or None if PII is not needed.
            hap: Provider selection for HAP detection, or None if HAP is not needed.

        Returns:
            ``(pii_adapter, hap_adapter)``; an entry is None when its selection is None.

        Raises:
            ValueError: If any selection is invalid (all errors are reported together).
        """
        errors: list[str] = []
        if pii is not None:
            errors.extend(cls.validate_selection(capability=DetectionCapability.PII, selection=pii))
        if hap is not None:
            errors.extend(cls.validate_selection(capability=DetectionCapability.HAP, selection=hap))
        if errors:
            raise ValueError("; ".join(errors))

        # Capabilities were verified above, so the casts below are safe.
        pii_adapter: PIIDetectionPort | None = None
        hap_adapter: HAPDetectionPort | None = None
        if pii is not None:
            pii_adapter = cast(
                PIIDetectionPort,
                cls.create(pii.provider, model_id=pii.model_id, provider_config=dict(pii.provider_config)),
            )
        if hap is not None:
            if pii is not None and cls._is_same_selection(first=pii, second=hap):
                hap_adapter = cast(HAPDetectionPort, pii_adapter)
            else:
                hap_adapter = cast(
                    HAPDetectionPort,
                    cls.create(hap.provider, model_id=hap.model_id, provider_config=dict(hap.provider_config)),
                )
        return pii_adapter, hap_adapter

    @staticmethod
    def _is_same_selection(*, first: ProviderSelection, second: ProviderSelection) -> bool:
        """Return True when two selections would build an identical adapter."""
        return first.provider.lower() == second.provider.lower() and first.provider_config == second.provider_config


def register_pii_and_hap_detection_adapter[AdapterClassT: type[DetectionAdapterPort]](
    adapter_class: AdapterClassT,
) -> AdapterClassT:
    """Decorator that registers a PII and/or HAP detection adapter with the factory.

    Usage::

        @register_pii_and_hap_detection_adapter
        class WatsonxPIIAndHAPAdapter(PIIAndHAPDetectionPort):
            ADAPTER_NAME = "watsonx"
            SUPPORTS_PII = True
            SUPPORTS_HAP = True
            ...

    Args:
        adapter_class: The adapter class to register.

    Returns:
        The adapter class unchanged (allows decorator chaining).
    """
    return PIIAndHAPDetectionFactory.register(adapter_class)
