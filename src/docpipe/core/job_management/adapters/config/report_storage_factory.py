# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
ContentStorageFactory — factory for content storage adapters used by report generation.

Creates the appropriate ContentStoragePort implementation based on the
`job_run_report.storage` section of docling-pipelines-config.yaml.

docling-pipelines ships with ContentFileSystemStorage.
Additional storage backends can be registered at import time.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, ClassVar

from docpipe.core.constants import DocpipeConfigKeys
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.storage.file_system.content_file_system_storage import ContentFileSystemStorage
from docpipe.utils.infrastructure.config_utils import DEFAULT_STORAGE_BACKEND, DocpipeConfigLoader
from docpipe.utils.infrastructure.filesystem import get_data_path
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

if TYPE_CHECKING:
    from docpipe.storage.interfaces.content_storage_port import ContentStoragePort


class ContentStorageFactory:
    """Adapter registry for report content storage."""

    _stores: ClassVar[dict[str, type[ContentStoragePort]]] = {
        DEFAULT_STORAGE_BACKEND: ContentFileSystemStorage,
    }

    @classmethod
    def clear_registry(cls) -> None:
        """Clear all registered backends. Intended for test teardown only."""
        cls._stores.clear()

    @classmethod
    def register(cls, store_class: type[ContentStoragePort]) -> type[ContentStoragePort]:
        """Register a content storage class."""
        if not hasattr(store_class, "STORAGE_BACKEND"):
            raise TypeError(f"Content storage class {store_class.__name__} must define STORAGE_BACKEND")

        backend_name: str = store_class.STORAGE_BACKEND  # type: ignore[attr-defined]

        if backend_name in cls._stores:
            logger.warning("Content storage backend '%s' is already registered. Overwriting.", backend_name)

        cls._stores[backend_name] = store_class
        logger.debug("Registered content storage backend: %s", backend_name)
        return store_class

    @classmethod
    def list_storage_types(cls) -> list[str]:
        """Return all registered backend names."""
        return list(cls._stores.keys())

    def __init__(self, *, storage_type: str, config: dict[str, Any] | None = None) -> None:
        self._storage_type = storage_type
        self._config: dict[str, Any] = config or {}
        self._store: ContentStoragePort | None = None

    def get_store(self) -> ContentStoragePort:
        """Return the singleton store, creating it on first call."""
        if self._store is None:
            if self._storage_type not in ContentStorageFactory._stores:
                available = ", ".join(ContentStorageFactory._stores.keys()) or "none"
                raise DocpipeException(
                    f"Unknown report content storage backend: '{self._storage_type}'. Available backends: {available}"
                )

            store_class = ContentStorageFactory._stores[self._storage_type]
            base_dir = self._config.get("data_root") or self._config.get(DocpipeConfigKeys.BASE_DIR) or get_data_path()
            self._store = store_class(base_dir=str(base_dir))  # type: ignore[call-arg]
            logger.info("Created report content storage: backend=%s", self._storage_type)
        return self._store

    @classmethod
    def create_default_factory(cls) -> ContentStorageFactory:
        """Create a ``ContentStorageFactory`` configured from ``docling-pipelines-config.yaml``.

        Reads the ``job_run_report`` storage section (falling back to ``global_storage``
        and then the filesystem default) and validates that the resolved backend is
        registered before returning a factory instance.

        Returns:
            ContentStorageFactory: Configured factory for report content storage.

        Raises:
            DocpipeException: If the resolved storage type is not registered.
        """
        storage_type, storage_config = DocpipeConfigLoader.get_storage(key=DocpipeConfigKeys.JOB_RUN_REPORT)

        if storage_type not in ContentStorageFactory._stores:
            available = ", ".join(ContentStorageFactory._stores.keys()) or "none"
            raise DocpipeException(f"Invalid storage type '{storage_type}' for job run report. Available: {available}")

        return cls(storage_type=storage_type, config=storage_config)


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------
def register_content_storage(store_class: type[ContentStoragePort]) -> type[ContentStoragePort]:
    """Register a ContentStoragePort implementation via decorator."""
    return ContentStorageFactory.register(store_class)


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------

_default_factory: ContentStorageFactory | None = None
_default_factory_lock: threading.Lock = threading.Lock()


def get_default_factory() -> ContentStorageFactory:
    """Return the process-wide singleton ``ContentStorageFactory``."""
    global _default_factory

    if _default_factory is None:
        with _default_factory_lock:
            if _default_factory is None:
                _default_factory = ContentStorageFactory.create_default_factory()

    return _default_factory


def get_report_storage() -> ContentStoragePort:
    """Return the singleton ContentStoragePort adapter for report generation."""
    return get_default_factory().get_store()


def reset_report_storage() -> None:
    """Reset singleton instances (useful for testing)."""
    global _default_factory
    _default_factory = None
