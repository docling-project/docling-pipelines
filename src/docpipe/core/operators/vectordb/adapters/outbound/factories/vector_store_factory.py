# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Factory for creating vector store adapters with lazy loading support.

This factory enables automatic registration of vector store adapters through decorators
and supports lazy loading to avoid importing optional dependencies until needed.
"""

import importlib
from typing import Any, ClassVar

from docpipe.core.operators.vectordb.ports.outbound.vector_store import VectorStorePort
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class VectorStoreFactory:
    """Factory for creating vector store adapters with lazy loading.

    This factory maintains a registry of available vector store adapters and
    provides methods to create instances based on adapter names. Adapters are
    loaded lazily to avoid importing optional dependencies (like pymilvus) until
    they are actually needed.

    Usage:
        # Register an adapter (eager)
        @register_vector_store
        class OpenSearchAdapter(VectorStorePort):
            ADAPTER_NAME = "opensearch"
            ...

        # Register an adapter (lazy)
        VectorStoreFactory.register_lazy(
            "milvus",
            "docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter",
            "MilvusAdapter"
        )

        # Create an adapter instance (triggers lazy load if needed)
        adapter = VectorStoreFactory.create("opensearch", config=config)
    """

    _adapters: ClassVar[dict[str, type[VectorStorePort]]] = {}
    _lazy_adapters: ClassVar[dict[str, tuple[str, str]]] = {}

    @classmethod
    def register(cls, adapter_class: type[VectorStorePort]) -> type[VectorStorePort]:
        """Register a vector store adapter class (eager loading).

        Args:
            adapter_class: The adapter class to register

        Returns:
            The adapter class (for decorator chaining)

        Raises:
            DocpipeException: If adapter_class doesn't have ADAPTER_NAME or is already registered
        """
        if not hasattr(adapter_class, "ADAPTER_NAME"):
            raise DocpipeException(
                message=f"Adapter class {adapter_class.__name__} must define ADAPTER_NAME",
                status_code=500,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        adapter_name = adapter_class.ADAPTER_NAME

        if adapter_name in cls._adapters:
            logger.warning("Adapter '%s' is already registered. Overwriting.", adapter_name)

        cls._adapters[adapter_name] = adapter_class
        # Remove from lazy registry if it was there
        cls._lazy_adapters.pop(adapter_name, None)
        logger.debug("Registered vector store adapter: %s", adapter_name)

        return adapter_class

    @classmethod
    def register_lazy(cls, adapter_name: str, module_path: str, class_name: str) -> None:
        """Register a vector store adapter for lazy loading.

        The adapter will only be imported when first accessed via create().
        This avoids importing optional dependencies until they are actually needed.

        Args:
            adapter_name: Name to register the adapter under (e.g., "milvus")
            module_path: Full module path (e.g., "docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter")
            class_name: Name of the adapter class (e.g., "MilvusAdapter")

        Example:
            VectorStoreFactory.register_lazy(
                "milvus",
                "docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter",
                "MilvusAdapter"
            )
        """
        if adapter_name in cls._adapters:
            logger.warning("Adapter '%s' is already eagerly registered. Skipping lazy registration.", adapter_name)
            return

        cls._lazy_adapters[adapter_name] = (module_path, class_name)
        logger.debug("Registered lazy vector store adapter: %s", adapter_name)

    @classmethod
    def _load_lazy_adapter(cls, adapter_name: str) -> type[VectorStorePort]:
        """Load a lazy adapter by importing its module.

        Args:
            adapter_name: Name of the adapter to load

        Returns:
            The loaded adapter class

        Raises:
            DocpipeException: If the adapter cannot be loaded
        """
        if adapter_name not in cls._lazy_adapters:
            raise DocpipeException(
                message=f"Lazy adapter '{adapter_name}' not found in registry",
                status_code=500,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        module_path, class_name = cls._lazy_adapters[adapter_name]

        try:
            logger.debug("Lazy loading adapter '%s' from %s.%s", adapter_name, module_path, class_name)
            module = importlib.import_module(module_path)
            adapter_class = getattr(module, class_name)

            # Move to eager registry after successful load.
            # Use pop() instead of del — the @register_vector_store decorator on the adapter
            # class calls register() during import, which already removes the entry from
            # _lazy_adapters via pop(). A second del here raises KeyError: 'milvus'.
            cls._adapters[adapter_name] = adapter_class
            cls._lazy_adapters.pop(adapter_name, None)

            logger.info("Successfully loaded lazy adapter: %s", adapter_name)
            return adapter_class

        except ImportError as e:
            # Don't remove from lazy registry on failure - user might install dependency later
            raise DocpipeException(
                message=(
                    f"Failed to import adapter '{adapter_name}' from {module_path}.{class_name}. "
                    f"This may be due to missing optional dependencies. Error: {e!s}"
                ),
                status_code=500,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            ) from e
        except AttributeError as e:
            # Don't remove from lazy registry on failure
            raise DocpipeException(
                message=f"Class '{class_name}' not found in module {module_path}: {e!s}",
                status_code=500,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            ) from e

    @classmethod
    def create(cls, adapter_name: str, **config: Any) -> VectorStorePort:
        """Create a vector store adapter instance.

        This method supports both eager and lazy loaded adapters. If the adapter
        is registered for lazy loading, it will be imported on first use.

        Args:
            adapter_name: Name of the adapter to create
            **config: Configuration parameters for the adapter

        Returns:
            Initialized adapter instance

        Raises:
            DocpipeException: If adapter_name is not registered or cannot be loaded
        """
        # Check if adapter is already loaded
        if adapter_name in cls._adapters:
            adapter_class = cls._adapters[adapter_name]
        # Check if adapter is registered for lazy loading
        elif adapter_name in cls._lazy_adapters:
            adapter_class = cls._load_lazy_adapter(adapter_name)
        else:
            # Adapter not found in either registry
            available_eager = list(cls._adapters.keys())
            available_lazy = list(cls._lazy_adapters.keys())
            all_available = sorted(set(available_eager + available_lazy))
            available_str = ", ".join(all_available) if all_available else "none"

            raise DocpipeException(
                message=f"Unknown vector store adapter: '{adapter_name}'. Available adapters: {available_str}",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        logger.debug("Creating vector store adapter: %s", adapter_name)

        try:
            return adapter_class(**config)
        except DocpipeException:
            # Already a docpipe exception with its own status/error code and message: do not wrap it again.
            raise
        except Exception as e:
            raise DocpipeException(
                message=f"Failed to create vector store adapter '{adapter_name}': {e!s}",
                status_code=500,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            ) from e

    @classmethod
    def list_adapters(cls) -> list[str]:
        """List all registered adapter names (both eager and lazy).

        Returns:
            List of registered adapter names
        """
        eager_adapters = list(cls._adapters.keys())
        lazy_adapters = list(cls._lazy_adapters.keys())
        return sorted(set(eager_adapters + lazy_adapters))

    @classmethod
    def get_adapter_info(cls, adapter_name: str) -> dict[str, Any]:
        """Get information about a registered adapter.

        For lazy adapters, this will trigger loading to get full information.

        Args:
            adapter_name: Name of the adapter

        Returns:
            Dictionary with adapter information

        Raises:
            DocpipeException: If adapter_name is not registered
        """
        # Check eager registry first
        if adapter_name in cls._adapters:
            adapter_class = cls._adapters[adapter_name]
            return {
                "name": adapter_class.ADAPTER_NAME,
                "display_name": adapter_class.ADAPTER_DISPLAY_NAME,
                "class": adapter_class.__name__,
                "loaded": True,
            }

        # Check lazy registry
        if adapter_name in cls._lazy_adapters:
            module_path, class_name = cls._lazy_adapters[adapter_name]
            return {
                "name": adapter_name,
                "display_name": adapter_name.title(),
                "class": class_name,
                "module": module_path,
                "loaded": False,
            }

        # Not found
        raise DocpipeException(
            message=f"Unknown vector store adapter: '{adapter_name}'",
            status_code=400,
            error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
        )


def register_vector_store(adapter_class: type[VectorStorePort]) -> type[VectorStorePort]:
    """Decorator to register a vector store adapter.

    Usage:
        @register_vector_store
        class OpenSearchAdapter(VectorStorePort):
            ADAPTER_NAME = "opensearch"
            ADAPTER_DISPLAY_NAME = "OpenSearch"
            ...

    Args:
        adapter_class: The adapter class to register

    Returns:
        The adapter class (for decorator chaining)
    """
    return VectorStoreFactory.register(adapter_class)
