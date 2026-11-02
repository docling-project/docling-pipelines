"""Independent configuration and lazy construction of ededup stores."""

import os
import threading
from pathlib import Path
from typing import Any, ClassVar

import yaml

from docpipe.core.constants.constants import _find_project_root
from docpipe.core.operators.quality.ededup_storage.ports.ededup_store import EdedupStore
from docpipe.exceptions.docpipe_exceptions import DocpipeException


class EdedupStoreFactory:
    """Select ededup storage without constructing incremental services."""

    _providers: ClassVar[dict[str, type[EdedupStore]]] = {}

    def __init__(self, *, backend: str = "filesystem", config: dict[str, Any] | None = None):
        if backend not in {"filesystem", "postgresql"} and backend not in self._providers:
            raise DocpipeException(f"Invalid storage backend '{backend}' for ededup")
        self.backend = backend
        self.config = config or {}
        self._store: EdedupStore | None = None
        self._lock = threading.Lock()

    @classmethod
    def register(cls, *, backend: str, store_class: type[EdedupStore]) -> None:
        """Register a custom implementation of the ededup port."""
        cls._providers[backend] = store_class

    def get_store(self) -> EdedupStore:
        """Return a lazily constructed store shared by this factory's callers."""
        with self._lock:
            if self._store is None:
                provider = self._providers.get(self.backend)
                if provider is None:
                    if self.backend == "filesystem":
                        from .adapters.filesystem_store import FilesystemEdedupStore

                        provider = FilesystemEdedupStore
                    else:
                        from .adapters.postgres_store import PostgresEdedupStore

                        provider = PostgresEdedupStore
                self._store = provider(config=self.config)
            return self._store

    @staticmethod
    def _mapping(*, value: Any, label: str) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise DocpipeException(f"{label} must be a mapping")
        return value

    @classmethod
    def _merge(cls, *, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        result = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = cls._merge(base=result[key], override=value)
            else:
                result[key] = value
        return result

    @classmethod
    def _storage_config(cls, block: dict[str, Any]) -> dict[str, Any]:
        config = dict(cls._mapping(value=block.get("config"), label="storage.config"))
        if "postgres" in config:
            cls._mapping(value=config["postgres"], label="storage.config.postgres")
        if "postgres" in block:
            config = cls._merge(
                base=config,
                override={"postgres": cls._mapping(value=block["postgres"], label="storage.postgres")},
            )
        return config

    @classmethod
    def from_config_file(cls, config_path: str) -> "EdedupStoreFactory":
        """Read ededup overrides, global defaults, or filesystem defaults."""
        path = Path(config_path)
        if not path.exists():
            return cls()
        try:
            document = cls._mapping(value=yaml.safe_load(path.read_text()), label="Configuration")
        except (OSError, yaml.YAMLError) as exc:
            raise DocpipeException("Cannot read ededup configuration") from exc
        shared = cls._mapping(value=document.get("global_storage"), label="global_storage")
        service = cls._mapping(value=document.get("ededup"), label="ededup")
        storage = cls._mapping(value=service.get("storage"), label="ededup.storage")
        backend = storage.get("type", shared.get("type", "filesystem"))
        if not isinstance(backend, str):
            raise DocpipeException("ededup storage type must be a string")
        config = cls._merge(base=cls._storage_config(shared), override=cls._storage_config(storage))
        return cls(backend=backend, config=config)

    @classmethod
    def from_default_sources(cls) -> "EdedupStoreFactory":
        """Use the common configuration file location, without incremental overrides."""
        path = os.getenv("DOCPIPE_CONFIG_PATH", str(_find_project_root() / "docling-pipelines-config.yaml"))
        return cls.from_config_file(path)


_default_ededup_factory: EdedupStoreFactory | None = None
_default_lock = threading.Lock()


def get_default_ededup_factory() -> EdedupStoreFactory:
    """Return the process-local ededup factory, constructing it once."""
    global _default_ededup_factory
    with _default_lock:
        if _default_ededup_factory is None:
            _default_ededup_factory = EdedupStoreFactory.from_default_sources()
        return _default_ededup_factory
