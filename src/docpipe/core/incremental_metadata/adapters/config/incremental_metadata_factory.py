# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Incremental metadata factory — adapter registry and DI container.

Mirrors ``JobManagementFactory``:
- Class-level registry of ``IncrementalMetadataStore`` adapters.
- Instance-level lazy singletons for the store and ``IncrementalUpdateService``.
- Module-level ``get_default_factory()`` for the process-wide singleton factory instance.
- ``get_incremental_update_service()`` convenience function for callers that
  only need the service.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, ClassVar

from docpipe.core.constants import DocpipeConfigKeys
from docpipe.core.incremental_metadata.domain import IncrementalMetadataStore
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader
from docpipe.utils.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from docpipe.core.incremental_metadata.application.services import IncrementalUpdateService

logger = get_logger(__name__)


class IncrementalMetadataFactory:
    """Adapter registry and DI container for incremental metadata.

    Class-level registry
    --------------------
    Store adapters are registered via ``@register_incremental_update_store``.

    Instance-level DI container
    ---------------------------
    Each factory instance lazily owns one store and one service.  Use
    ``get_default_factory()`` to get the process-wide singleton factory, then
    call ``get_store()`` or ``get_service()`` on it.

    Example::

        service = get_incremental_update_service()   # simplest call
        store   = get_default_factory().get_store()  # if you only need the store
    """

    # ------------------------------------------------------------------ #
    # Class-level adapter registry                                         #
    # ------------------------------------------------------------------ #

    _stores: ClassVar[dict[str, type[IncrementalMetadataStore]]] = {}

    @classmethod
    def clear_registry(cls) -> None:
        """Clear all registered backends.  Intended for test teardown only."""
        cls._stores.clear()

    @classmethod
    def register(cls, store_class: type[IncrementalMetadataStore]) -> type[IncrementalMetadataStore]:
        """Register an incremental metadata store class.

        Args:
            store_class: Must define a ``STORE_BACKEND`` class attribute.

        Returns:
            The store class unchanged (supports decorator chaining).

        Raises:
            TypeError: If ``STORE_BACKEND`` is missing.
        """
        if not hasattr(store_class, "STORE_BACKEND"):
            raise TypeError(f"Store class {store_class.__name__} must define STORE_BACKEND")

        backend_name: str = store_class.STORE_BACKEND  # type: ignore[attr-defined]

        if backend_name in cls._stores:
            logger.warning("Store backend '%s' is already registered. Overwriting.", backend_name)

        cls._stores[backend_name] = store_class
        logger.debug("Registered incremental metadata store: %s", backend_name)
        return store_class

    @classmethod
    def list_backends(cls) -> list[str]:
        """Return all registered backend names."""
        return list(cls._stores.keys())

    # ------------------------------------------------------------------ #
    # Instance — DI container                                              #
    # ------------------------------------------------------------------ #

    def __init__(self, *, storage_type: str, config: dict[str, Any] | None = None) -> None:
        """
        Args:
            storage_type: Registered ``STORE_TYPE`` value (e.g. ``"filesystem"``).
            config:  Configuration dict forwarded to the store constructor.
        """
        self._storage_type = storage_type
        self._config: dict[str, Any] = config or {}
        self._store: IncrementalMetadataStore | None = None
        self._service: IncrementalUpdateService | None = None

    def get_store(self) -> IncrementalMetadataStore:
        """Return the singleton store, creating it on first call."""
        if self._store is None:
            if self._storage_type not in IncrementalMetadataFactory._stores:
                available = ", ".join(IncrementalMetadataFactory._stores.keys()) or "none"
                raise DocpipeException(
                    f"Unknown incremental metadata store backend: '{self._storage_type}'. Available backends: {available}"
                )
            store_class = IncrementalMetadataFactory._stores[self._storage_type]
            self._store = store_class(config=self._config)  # type: ignore[call-arg]
            logger.info("Created IncrementalMetadataStore: backend=%s", self._storage_type)
        return self._store

    def get_service(self) -> IncrementalUpdateService:
        """Return the singleton ``IncrementalUpdateService``, creating it on first call."""
        if self._service is None:
            # Deferred import to avoid circular dependency at module load time.
            from docpipe.core.incremental_metadata.application.services import (
                IncrementalUpdateService,
            )

            self._service = IncrementalUpdateService(store=self.get_store())
            logger.info("Created IncrementalUpdateService")
        return self._service

    @classmethod
    def create_default_factory(cls) -> IncrementalMetadataFactory:
        storage_type, storage_config = DocpipeConfigLoader.get_storage(key=DocpipeConfigKeys.INCREMENTAL_METADATA)

        if storage_type not in IncrementalMetadataFactory._stores:
            available = ", ".join(IncrementalMetadataFactory._stores.keys()) or "none"
            raise DocpipeException(
                f"Invalid storage type '{storage_type}' for incremental metadata. Available: {available}"
            )

        return cls(storage_type=storage_type, config=storage_config)


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------
def register_incremental_update_store(
    store_class: type[IncrementalMetadataStore],
) -> type[IncrementalMetadataStore]:
    """Register an incremental metadata store class via decorator.

    The decorated class must define a ``STORE_BACKEND`` class attribute whose
    value is the string used in YAML config to select this store
    (e.g. ``"filesystem"``, ``"postgresql"``).

    Usage::

        @register_incremental_update_store
        class FilesystemIncrementalMetadataStore(IncrementalMetadataStore):
            STORE_BACKEND = "filesystem"
    """
    return IncrementalMetadataFactory.register(store_class)


# ---------------------------------------------------------------------------
# Module-level singleton factory  (mirrors get_default_factory in job_management)
# ---------------------------------------------------------------------------

_default_factory: IncrementalMetadataFactory | None = None
_default_factory_lock: threading.Lock = threading.Lock()


def get_default_factory() -> IncrementalMetadataFactory:
    """Return the process-wide singleton ``IncrementalMetadataFactory``.

    Built once from standard config-file / env-var sources on first call.
    The store and service it owns are also lazy singletons on the factory.
    """
    global _default_factory

    if _default_factory is None:
        with _default_factory_lock:
            if _default_factory is None:
                _default_factory = IncrementalMetadataFactory.create_default_factory()

    return _default_factory


def set_default_factory(factory: IncrementalMetadataFactory) -> None:
    """Replace the process-wide singleton factory.

    Intended for callers that need to install a pre-configured factory
    before any component requests the singleton.  Thread-safe: acquires
    the same lock used by get_default_factory().

    Args:
        factory: The IncrementalMetadataFactory instance to install as
                 the process-wide singleton.
    """
    global _default_factory
    with _default_factory_lock:
        _default_factory = factory


def get_incremental_update_service() -> IncrementalUpdateService:
    """Return the process-wide singleton ``IncrementalUpdateService``.

    Thin convenience wrapper over ``get_default_factory().get_service()``.
    All callers share the same store and service instance.
    """
    return get_default_factory().get_service()
