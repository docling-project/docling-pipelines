"""Factory for creating entity extraction adapters.

This factory creates appropriate entity extraction adapter instances based on the
extraction mode and configuration. It supports multiple extraction strategies:
- LLM: Unified LLM-based entity extraction using shared infrastructure (watsonx, litellm)
- DOCLING: Template-based entity extraction using Docling templates

Adapter classes self-register via ``@register_entity_extraction_adapter``.
``create_adapter`` routes through ``_registry``.
To add a new provider, create a subclass with
``ADAPTER_NAME``, ``get_config_schema()``, ``build_provider_config()``, and the
``@register_entity_extraction_adapter`` decorator; no factory changes required.
"""

import logging
from typing import Any, ClassVar

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.extract.domain import EntityExtractionMode
from docpipe.core.operators.extract.ports.outbound.entity_extraction import EntityExtractionPort
from docpipe.utils.infrastructure.logging import get_logger

logger: logging.Logger = get_logger()


class EntityExtractionAdapterFactory:
    """Factory for creating entity extraction adapters.

    This factory creates appropriate adapter instances based on extraction mode
    and validates configuration requirements for each adapter type.

    It also maintains a class registry so that third-party adapters can
    self-register via ``@register_entity_extraction_adapter``.

    Supported Modes:
        - "litellm": LLM-based extraction using LiteLLM (supports multiple providers)
        - "watsonx": LLM-based extraction using IBM watsonx
        - "docling": Template-based extraction using Docling templates
        - "none": No entity extraction

    Example Usage:
        # Create LiteLLM adapter
        config = {
            OperatorConstants.Config.MODEL_NAME: "openai/granite4:latest",
            OperatorConstants.LLM.TEMPERATURE: 0.0,
            OperatorConstants.LLM.MAX_TOKENS: 4096,
            OperatorConstants.LLM.MAX_DOC_CHARS: 8000,
            "entity_provider_config": {
                "api_base": "http://localhost:11434/v1",
                "api_key": "<ollama_key>"
            },
            "doc_column": "doc_content",
            "output_column": "entities",
            "expand_extracted_data": False
        }
        adapter = EntityExtractionAdapterFactory.create_adapter(
            mode="litellm",
            config=config,
            max_workers=4
        )

        # Create Docling adapter
        docling_config = {
            "doc_column": "doc_content",
            "output_column": "entities"
        }
        docling_adapter = EntityExtractionAdapterFactory.create_adapter(
            mode="docling",
            config=docling_config,
            max_workers=4
        )
    """

    # Registry of adapter classes keyed by ADAPTER_NAME (populated via @register_entity_extraction_adapter).
    # NONE mode is intentionally absent — it is handled by an explicit guard in create_adapter
    # and build_adapter_config rather than by a registered class.
    _registry: ClassVar[dict[str, type[EntityExtractionPort]]] = {}

    @staticmethod
    def build_common_config(*, entity_extraction_config: dict[str, Any], doc_column: str) -> dict[str, Any]:
        """Build the config fields shared by every entity extraction adapter.

        Args:
            entity_extraction_config: Nested entity_extraction configuration dictionary
            doc_column: Document column name from text_extraction config

        Returns:
            Dictionary with common adapter config keys
        """
        return {
            "doc_column": doc_column,
            OperatorConstants.Columns.OUTPUT_COLUMN: entity_extraction_config.get(
                OperatorConstants.Columns.OUTPUT_COLUMN, OperatorConstants.Misc.ENTITIES
            ),
            "expand_extracted_data": entity_extraction_config.get(
                OperatorConstants.Config.EXPAND_EXTRACTED_DATA, False
            ),
            "custom_schema": entity_extraction_config.get(OperatorConstants.Config.CUSTOM_SCHEMA, {}),
            "common_log_arguments": entity_extraction_config.get("common_log_arguments", {}),
            # Job-tracking fields (job_run_id, node_id, node_name, batch_id) are NOT read
            # from entity_extraction_config — they are never present there (they come from
            # the orchestrator via global_config). Reading them here would produce None values
            # that overwrite the real values already in global_config.
        }

    @classmethod
    def register(cls, adapter_class: type[EntityExtractionPort]) -> type[EntityExtractionPort]:
        """Register an adapter class in the schema-discovery registry.

        Called automatically by the ``@register_entity_extraction_adapter`` decorator.

        Args:
            adapter_class: Concrete subclass of ``EntityExtractionPort``.

        Returns:
            The adapter class (for decorator chaining).

        Raises:
            ValueError: If the class does not define ``ADAPTER_NAME``.
        """
        if not hasattr(adapter_class, "ADAPTER_NAME") or not adapter_class.ADAPTER_NAME:
            raise ValueError(f"Adapter {adapter_class.__name__} must define ADAPTER_NAME")

        name = adapter_class.ADAPTER_NAME.lower()
        cls._registry[name] = adapter_class
        return adapter_class

    @classmethod
    def list_adapters(cls) -> list[str]:
        """Return names of all registered adapters.

        Returns:
            List of registered adapter names.
        """
        return list(cls._registry.keys())

    @classmethod
    def get_registry_items(cls) -> list[tuple[str, type[EntityExtractionPort]]]:
        """Return (name, adapter_class) pairs for all registered adapters.

        Returns:
            List of (adapter_name, adapter_class) tuples.
        """
        return list(cls._registry.items())

    @classmethod
    def create_adapter(
        cls,
        *,
        mode: EntityExtractionMode,
        entity_extraction_config: dict[str, Any],
        global_config: dict[str, Any],
        doc_column: str,
        max_workers: int = 4,
    ) -> EntityExtractionPort | None:
        """Create appropriate entity extraction adapter based on mode.

        Routes instantiation through the registry. NONE is handled by an explicit
        early-return guard — it is intentionally absent from the registry.

        Args:
            mode: Extraction mode ("litellm", "watsonx", "docling", or "none")
            entity_extraction_config: Nested entity_extraction configuration dictionary
            global_config: Global operator configuration (for job tracking, etc.)
            doc_column: Document column name from text_extraction config
            max_workers: Number of parallel workers (default: 4)

        Returns:
            Configured EntityExtractionPort adapter instance, or None if mode is "none"

        Raises:
            ValueError: If mode is unsupported or config is invalid
        """
        if mode == EntityExtractionMode.NONE:
            logger.info("Entity extraction disabled (mode='none')")
            return None

        adapter_cls = cls._registry.get(mode.value)
        if adapter_cls is None:
            raise ValueError(
                f"Unsupported entity extraction mode: {mode}. Supported modes: {cls.get_supported_modes()}"
            )

        adapter_config = adapter_cls.build_provider_config(
            entity_extraction_config=entity_extraction_config, doc_column=doc_column
        )

        # Merge with global config for job tracking and other global settings.
        # IMPORTANT: Merge global_config first to preserve keys like ingest_source.
        full_config = {**global_config, **adapter_config, "max_workers": max_workers}

        logger.info("Creating %s with %s workers", adapter_cls.__name__, max_workers)
        return adapter_cls(config=full_config)

    @classmethod
    def get_supported_modes(cls) -> list[str]:
        """Get list of supported extraction modes.

        Derived from the adapter registry so externally registered adapters are
        automatically included. NONE is appended explicitly since it is a valid
        mode but has no registered adapter class.

        Returns:
            List of supported extraction mode values
        """
        return [*cls._registry.keys(), EntityExtractionMode.NONE.value]


def register_entity_extraction_adapter(adapter_class: type[EntityExtractionPort]) -> type[EntityExtractionPort]:
    """Decorator to register an entity extraction adapter for schema discovery.

    This decorator automatically registers the adapter class with
    ``EntityExtractionAdapterFactory``.

    Args:
        adapter_class: Concrete subclass of ``EntityExtractionPort``.

    Returns:
        The adapter class (unchanged).

    Example::

        @register_entity_extraction_adapter
        class LLMEntityAdapter(EntityExtractionPort):
            ADAPTER_NAME = "litellm"
            ADAPTER_DISPLAY_NAME = "LiteLLM"
            ...
    """
    return EntityExtractionAdapterFactory.register(adapter_class)
