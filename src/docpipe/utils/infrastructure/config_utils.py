# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Utility for reading and caching the docling-pipelines-config.yaml file.

Provides a thread-safe singleton that reads the YAML configuration file exactly
once and serves lookups for any top-level key. All factory classes that previously
loaded the file independently should use this module instead.

Resolution order for the config file path:
1. ``DOCPIPE_CONFIG_PATH`` environment variable
2. ``<project_root>/docling-pipelines-config.yaml`` (via ``_find_project_root()``)

If the file does not exist or is unreadable, the loader returns an empty dict and
logs a warning, so callers can fall through to their own defaults without crashing.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import yaml

from docpipe.core.constants.constants import DocpipeConfigKeys, EnvironmentVariables, _find_project_root
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_CONFIG_PATH = _find_project_root() / "docling-pipelines-config.yaml"
DEFAULT_STORAGE_BACKEND = "filesystem"


class DocpipeConfigLoader:
    """Thread-safe singleton that reads docling-pipelines-config.yaml once.

    Usage::

        config = DocpipeConfigLoader.get_config()          # full dict
        storage = DocpipeConfigLoader.get("global_storage", {})
        job_mgmt = DocpipeConfigLoader.get("job_management", {})

    The loaded dict is cached for the lifetime of the process.  Call
    ``reset()`` in tests to force a fresh read after changing the environment
    or the config file.
    """

    _config: dict[str, Any] | None = None
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get_config(cls) -> dict[str, Any]:
        """Return the full parsed configuration dictionary.

        The file is read at most once per process.  Subsequent calls return
        the cached result without touching the filesystem.

        Returns:
            Parsed YAML contents, or an empty dict when the file is absent or
            unreadable.
        """
        if cls._config is None:
            with cls._lock:
                if cls._config is None:
                    cls._config = cls._load()
        return cls._config

    @classmethod
    def get(cls, *, key: str, default: Any = None) -> Any:
        """Return the value for *key* from the top-level config dict.

        Args:
            key: Top-level YAML key (e.g. ``"global_storage"``).
            default: Value to return when the key is absent.  Defaults to
                     ``None``.

        Returns:
            The value associated with *key*, or *default* if not found.
        """
        service_config = cls.get_config().get(key)
        if service_config:
            logger.info("Found configuration in config file for the service: %s", key)
            return service_config
        logger.info("Did not find configuration in config file for the service: %s, so using default config", key)
        return default

    @classmethod
    def get_storage(cls, key: str, default: Any = None) -> tuple[str, dict[str, Any]]:
        # Returns storage type (ex: filesystem, duckdb, etc.) and
        # storage configuration for the given key (ex: incremental_metadata, flow_definition_snapshot, etc.)

        # Precedence: service-specific > global_storage > default
        config = cls.get(key=key, default=default or {})
        storage_config = config.get(DocpipeConfigKeys.STORAGE, {}) or config.get(DocpipeConfigKeys.STORE, {})
        if storage_config:
            logger.info("Using service specific configuration for service: %s", key)
        else:
            storage_config = cls.get(key=DocpipeConfigKeys.GLOBAL_STORAGE)
            if storage_config:
                logger.info("Using global configuration for for service: %s", key)
            else:
                storage_config = {DocpipeConfigKeys.TYPE: DEFAULT_STORAGE_BACKEND}
                logger.info("Using default configuration for for service: %s", key)

        storage_type = storage_config.get(DocpipeConfigKeys.TYPE)
        config = storage_config.get(DocpipeConfigKeys.CONFIG, {})
        logger.info("Storage type for service, %s is: %s", key, storage_type)
        return storage_type, config

    @classmethod
    def reset(cls) -> None:
        """Clear the cached config so the next call re-reads the file.

        Intended for use in tests only.  Not safe to call from concurrent
        production code.
        """
        with cls._lock:
            cls._config = None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @classmethod
    def _load(cls) -> dict[str, Any]:
        """Read and parse the YAML config file.  Returns ``{}`` on any error."""
        config_path = Path(os.environ.get(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(_DEFAULT_CONFIG_PATH)))

        if not config_path.exists():
            logger.debug("Config file not found at %s; using empty configuration.", config_path)
            return {}

        try:
            with config_path.open() as fh:
                result = yaml.safe_load(fh)
            logger.debug("Loaded configuration from %s", config_path)
            return result or {}
        except yaml.YAMLError as exc:
            logger.warning("Invalid YAML in config file %s: %s", config_path, exc)
            return {}
