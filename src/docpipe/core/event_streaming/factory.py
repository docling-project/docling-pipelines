"""Factories for event streaming services and adapters."""

import os
from pathlib import Path
from typing import Any

import yaml

from docpipe.core.constants import DocpipeConfigKeys, EnvironmentVariables
from docpipe.core.event_streaming.dispatch_service import EventDispatchService
from docpipe.core.event_streaming.kafka_listener import KafkaEventListener
from docpipe.core.event_streaming.mapping_service import EventMappingService
from docpipe.storage.factory import StorageFactory
from docpipe.utils.infrastructure.config_utils import DEFAULT_CONFIG_PATH, DEFAULT_STORAGE_BACKEND
from docpipe.utils.infrastructure.filesystem import get_data_path
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class EventStreamingFactory:
    """Create event streaming services using the configured storage backend."""

    @staticmethod
    def create_event_dispatch_service() -> EventDispatchService:
        """Create the event dispatcher with persistent mapping storage."""
        return EventDispatchService(
            mapping_service=EventStreamingFactory.create_event_mapping_service(),
        )

    @staticmethod
    def create_kafka_listener() -> KafkaEventListener | None:
        """Create a Kafka listener only when explicitly enabled by the environment."""
        enabled = os.getenv(EnvironmentVariables.DOCPIPE_EVENT_STREAMING_ENABLED, "false").strip().lower()
        if enabled == "true":
            return KafkaEventListener.from_environment(
                dispatch_service=EventStreamingFactory.create_event_dispatch_service(),
            )
        return None

    @staticmethod
    def create_event_mapping_service() -> EventMappingService:
        """Build the mapping service with environment, YAML, and filesystem defaults."""
        storage_backend, storage_config = EventStreamingFactory._resolve_storage_configuration()
        if storage_backend == "filesystem":
            storage_config = {"base_dir": storage_config.get(DocpipeConfigKeys.BASE_DIR) or get_data_path()}
        elif storage_backend == "duckdb":
            database_path = storage_config.get("database_path") or str(Path(get_data_path()) / "event_mappings.duckdb")
            storage_config = {"database_path": database_path}
        else:
            storage_config = {}

        storage = StorageFactory.create_key_value_storage(storage_type=storage_backend, **storage_config)
        return EventMappingService(storage=storage)

    @staticmethod
    def _resolve_storage_configuration() -> tuple[str, dict[str, Any]]:
        """Resolve backend as environment override, global YAML setting, then filesystem default."""
        config_path = Path(os.environ.get(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(DEFAULT_CONFIG_PATH)))
        yaml_config: dict[str, Any] = {}
        if config_path.exists():
            try:
                with config_path.open(encoding="utf-8") as config_file:
                    loaded_config = yaml.safe_load(config_file) or {}
                if isinstance(loaded_config, dict):
                    yaml_config = loaded_config
            except (OSError, yaml.YAMLError) as error:
                logger.warning("Could not read storage configuration from %s: %s", config_path, error)

        global_storage = yaml_config.get(DocpipeConfigKeys.GLOBAL_STORAGE, {})
        storage_backend = (
            os.getenv(EnvironmentVariables.DOCPIPE_STORAGE_BACKEND)
            or global_storage.get(DocpipeConfigKeys.TYPE)
            or DEFAULT_STORAGE_BACKEND
        )
        storage_config = global_storage.get(DocpipeConfigKeys.CONFIG, {})
        return storage_backend, storage_config
