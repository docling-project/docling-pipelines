# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Flow definition snapshot storage factory — adapter registry.

- Class-level registry of ``KeyValueStoragePort`` adapters.
- Instance-level lazy singletons for the store.
- Module-level ``get_default_factory()`` for the process-wide singleton factory instance.
- ``get_flow_definitions_snapshot_storage()`` convenience function for callers that
  need the storage adopter.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, ClassVar

from docpipe.core.constants import DocpipeConfigKeys
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure import get_data_path
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from docpipe.storage import KeyValueStoragePort


class FlowDefinitionSnapshotStorageFactory:
    """Adapter registry for Flow definition snapshot storage.

    Class-level registry
    --------------------
    Store adapters are registered via ``@register_flow_definition_snapshot_storage``.

    Instance-level DI container
    ---------------------------
    Each factory instance lazily owns one storage.  Use
    ``get_default_factory()`` to get the process-wide singleton factory, then
    call ``get_store()`` on it.

    Example::
        store = get_flow_definitions_snapshot_storage()
    """

    # ------------------------------------------------------------------ #
    # Class-level adapter registry                                         #
    # ------------------------------------------------------------------ #

    _stores: ClassVar[dict[str, type[KeyValueStoragePort]]] = {}

    @classmethod
    def clear_registry(cls) -> None:
        """Clear all registered storages.  Intended for test teardown only."""
        cls._stores.clear()

    @classmethod
    def register(cls, store_class: type[KeyValueStoragePort]) -> type[KeyValueStoragePort]:
        """Register a flow definition snapshot storage class.

        Args:
            store_class: Must define a ``STORE_BACKEND`` class attribute.

        Returns:
            The store class unchanged (supports decorator chaining).

        Raises:
            TypeError: If ``STORE_BACKEND`` is missing.
        """
        if not hasattr(store_class, "STORE_BACKEND"):
            raise TypeError(f"Store class {store_class.__name__} must define STORE_BACKEND")

        storage_type: str = store_class.STORE_BACKEND  # type: ignore[attr-defined]

        if storage_type in cls._stores:
            logger.warning("Storage type '%s' is already registered. Overwriting.", storage_type)

        cls._stores[storage_type] = store_class
        logger.debug("Registered incremental metadata store: %s", storage_type)
        return store_class

    @classmethod
    def list_storage_types(cls) -> list[str]:
        """Return all registered storage types."""
        return list(cls._stores.keys())

    def __init__(self, *, storage_type: str, config: dict[str, Any] | None = None) -> None:
        """
        Args:
            storage_type: Registered ``STORE_BACKEND`` value (e.g. ``"filesystem"``).
            config:  Configuration dict forwarded to the store constructor.
        """
        self._storage_type = storage_type
        self._config: dict[str, Any] = config or {}
        self._store: KeyValueStoragePort | None = None

    def get_store(self) -> KeyValueStoragePort:
        """Return the singleton store, creating it on first call."""
        if self._store is None:
            if self._storage_type not in FlowDefinitionSnapshotStorageFactory._stores:
                available = ", ".join(FlowDefinitionSnapshotStorageFactory._stores.keys()) or "none"
                raise DocpipeException(
                    f"Unknown flow Definition snapshot store type: '{self._storage_type}'. Available storage types: {available}"
                )
            store_class = FlowDefinitionSnapshotStorageFactory._stores[self._storage_type]
            base_dir = self._config.get(DocpipeConfigKeys.BASE_DIR) or get_data_path()
            self._store = store_class(base_dir=base_dir)  # type: ignore[call-arg]
            logger.info("Created flow definition snapshot storage for type=%s", self._storage_type)
        return self._store

    @classmethod
    def create_default_factory(cls) -> FlowDefinitionSnapshotStorageFactory:
        storage_type, storage_config = DocpipeConfigLoader.get_storage(key=DocpipeConfigKeys.FLOW_DEFINITION_SNAPSHOT)

        if storage_type not in FlowDefinitionSnapshotStorageFactory._stores:
            available = ", ".join(FlowDefinitionSnapshotStorageFactory._stores.keys()) or "none"
            raise DocpipeException(
                f"Invalid storage type '{storage_type}' for flow definition snapshot storage. Available: {available}"
            )

        return cls(storage_type=storage_type, config=storage_config)


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------
def register_flow_definition_snapshot_storage(
    store_class: type[KeyValueStoragePort],
) -> type[KeyValueStoragePort]:
    """Register a flow definition snapshot storage class via decorator.

    The decorated class must define a ``STORE_BACKEND`` class attribute whose
    value is the string used in YAML config to select this store
    (e.g. ``"filesystem"``, ``"duckdb"``).

    Usage::

        @register_flow_definition_snapshot_storage
        class KeyValueFileSystemStorage(KeyValueStoragePort):
            STORE_BACKEND = "filesystem"
    """
    return FlowDefinitionSnapshotStorageFactory.register(store_class)


# ---------------------------------------------------------------------------
# Module-level singleton factory  (mirrors get_default_factory in job_management)
# ---------------------------------------------------------------------------

_default_factory: FlowDefinitionSnapshotStorageFactory | None = None
_default_factory_lock: threading.Lock = threading.Lock()


def get_default_factory() -> FlowDefinitionSnapshotStorageFactory:
    """Return the process-wide singleton ``FlowDefinitionSnapshotStorageFactory``.

    Built once from standard config-file / env-var sources on first call.
    The store and service it owns are also lazy singletons on the factory.
    """
    global _default_factory

    if _default_factory is None:
        with _default_factory_lock:
            if _default_factory is None:
                _default_factory = FlowDefinitionSnapshotStorageFactory.create_default_factory()

    return _default_factory


def get_flow_definitions_snapshot_storage() -> KeyValueStoragePort:
    """
    Return the singleton KeyValueStoragePort adapter for flow definition snapshots.

    Built from the default configuration sources on first call.
    """
    return get_default_factory().get_store()
