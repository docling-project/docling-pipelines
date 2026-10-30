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

DEFAULT_CONFIG_PATH = _find_project_root() / "docling-pipelines-config.yaml"
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
    def get_storage(
        cls, key: str, default: Any = None, *, default_type: str = DEFAULT_STORAGE_BACKEND
    ) -> tuple[str, dict[str, Any]]:
        """Return the storage type and storage config for a named service key.

        Resolves configuration with the following precedence:
        service-specific ``storage``/``store`` block → ``global_storage`` → built-in
        default (``"filesystem"`` unless *default_type* is given).

        Args:
            key: Top-level YAML key identifying the service
                 (e.g. ``"incremental_metadata"``, ``"flow_definition_snapshot"``).
            default: Fallback value passed to :meth:`get` when *key* is absent.
                     Defaults to ``None`` (treated as ``{}``).
            default_type: Storage type used when neither the service nor ``global_storage``
                          configures one. Defaults to ``"filesystem"``; a service whose
                          historical default differs (e.g. job management, ``"inmemory"``)
                          passes its own value.

        Returns:
            A ``(storage_type, config_dict)`` tuple where *storage_type* is a
            string such as ``"filesystem"`` or ``"duckdb"`` and *config_dict*
            contains backend-specific configuration.
        """
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
                storage_config = {DocpipeConfigKeys.TYPE: default_type}
                logger.info("Using default configuration for for service: %s", key)

        storage_type = storage_config.get(DocpipeConfigKeys.TYPE)
        if not storage_type:
            # A service block that sets only ``config`` still needs a type: use the
            # global type if there is one, otherwise the built-in default.
            global_type = (cls.get(key=DocpipeConfigKeys.GLOBAL_STORAGE) or {}).get(DocpipeConfigKeys.TYPE)
            storage_type = global_type or default_type
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
        config_path = Path(os.environ.get(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(DEFAULT_CONFIG_PATH)))

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
