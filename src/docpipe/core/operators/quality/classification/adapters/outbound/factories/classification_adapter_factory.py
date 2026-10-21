"""Registry-based factory that resolves a provider string to a ClassificationPort adapter.

Design
------
The factory is a **pure dispatcher**.  It holds a class-level registry that maps
``ADAPTER_NAME`` strings to adapter classes.  All validation and dependency
construction (e.g. building an :class:`~docpipe.core.ports.llm_inference_port.LLMInferencePort`)
live in each adapter's own :meth:`~docpipe.core.operators.quality.classification.ports.outbound.classification_port.ClassificationPort.from_config`
classmethod.

Provider aliases
----------------
Some provider strings used in flow JSON (``"litellm"``, ``"watsonx"``) map to
the ``"standard"`` adapter.  The alias table lives here as ``_PROVIDER_ALIASES``
and is the single source of truth for those mappings.
"""

from typing import Any, ClassVar

from docpipe.core.operators.quality.classification.ports.outbound.classification_port import ClassificationPort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class ClassificationAdapterFactory:
    """Registry-based factory: resolves a ``provider`` string → :class:`ClassificationPort`.

    Registry
    --------
    Adapters self-register via the ``@register_classification_adapter``
    decorator (same pattern as ``@register_entity_extraction_adapter``).
    The key is each adapter's ``ADAPTER_NAME`` class attribute.

    Aliases
    -------
    ``_PROVIDER_ALIASES`` is the only list of valid flow-JSON provider strings.
    Each maps to the ``ADAPTER_NAME`` it resolves to.  For example ``"litellm"``
    and ``"watsonx"`` both resolve to ``"standard"``.  ``ADAPTER_NAME`` is an
    internal registry key and is not itself a valid provider string.
    """

    # Registry: ADAPTER_NAME → adapter class
    _REGISTRY: ClassVar[dict[str, type[ClassificationPort]]] = {}

    # Alias table: flow-JSON provider string → ADAPTER_NAME
    # Add an entry here for every provider string a new adapter accepts.
    _PROVIDER_ALIASES: ClassVar[dict[str, str]] = {
        "litellm": "standard",
        "watsonx": "standard",
    }

    @classmethod
    def register(cls, adapter_class: type[ClassificationPort]) -> None:
        """Register *adapter_class* under its ``ADAPTER_NAME``.

        Normally invoked through the ``@register_classification_adapter`` decorator.

        Args:
            adapter_class: A concrete subclass of :class:`ClassificationPort`
                with ``ADAPTER_NAME`` set.
        """
        cls._REGISTRY[adapter_class.ADAPTER_NAME] = adapter_class
        logger.debug("ClassificationAdapterFactory: registered adapter=%s", adapter_class.ADAPTER_NAME)

    @classmethod
    def create_adapter(cls, *, provider: str, config: dict[str, Any]) -> ClassificationPort:
        """Resolve *provider* and return a ready :class:`ClassificationPort`.

        Resolution order:

        1. Normalise to lower-case.
        2. Reject deprecated providers with migration guidance.
        3. Apply alias table (``"litellm"`` → ``"standard"``, etc.).
        4. Look up the resolved name in the registry.
        5. Delegate to ``adapter_class.from_config(config)`` — all validation
           and dependency construction happen there.

        Args:
            provider: Provider name from the flow config (e.g. ``"litellm"``).
            config: Full operator config dictionary forwarded to
                ``from_config``.

        Returns:
            A concrete :class:`ClassificationPort` instance.

        Raises:
            ValueError: When *provider* is deprecated, unrecognised, or when
                the adapter's ``from_config`` raises.
        """
        normalised = provider.lower()
        logger.debug("ClassificationAdapterFactory: resolving provider=%s", normalised)

        # Resolve alias → canonical ADAPTER_NAME.
        resolved = cls._PROVIDER_ALIASES.get(normalised)

        adapter_class = cls._REGISTRY.get(resolved) if resolved is not None else None
        if adapter_class is None:
            supported = sorted(cls.get_supported_providers())
            raise ValueError(f"Unknown classification provider: {provider!r}. Supported values: {supported}")

        logger.debug(
            "ClassificationAdapterFactory: dispatching to %s.from_config() for provider=%s",
            adapter_class.__name__,
            normalised,
        )
        return adapter_class.from_config(config)

    @classmethod
    def get_deprecation_message(cls, provider: str) -> str | None:
        """Return the migration message for a deprecated *provider*, or ``None`` if it is not deprecated."""
        return cls._DEPRECATED.get(provider.lower())

    @classmethod
    def get_supported_providers(cls) -> set[str]:
        """Return all valid provider strings (the alias table keys).

        Deprecated providers are excluded.

        Returns:
            Set of valid provider name strings accepted by :meth:`create_adapter`.
        """
        return set(cls._PROVIDER_ALIASES)


def register_classification_adapter(adapter_class: type[ClassificationPort]) -> type[ClassificationPort]:
    """Decorator to register a classification adapter with ``ClassificationAdapterFactory``.

    Args:
        adapter_class: Concrete subclass of :class:`ClassificationPort`.

    Returns:
        The adapter class (unchanged).

    Example::

        @register_classification_adapter
        class MyAdapter(ClassificationPort):
            ADAPTER_NAME = "my_adapter"
            ADAPTER_DISPLAY_NAME = "My Adapter"
            ...
    """
    ClassificationAdapterFactory.register(adapter_class)
    return adapter_class
