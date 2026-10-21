"""Application service for persistent event-to-flow mappings."""

import threading
from typing import ClassVar

from docpipe.core.event_streaming.models import EventMapping
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.storage.interfaces.key_value_storage_port import KeyValueStoragePort

EVENT_MAPPINGS_COLLECTION = "event_mappings"


class EventMappingService:
    """Store and resolve routing mappings through the key-value storage port."""

    _write_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, *, storage: KeyValueStoragePort) -> None:
        self._storage = storage

    @staticmethod
    def _normalize_key(*, key: str) -> str:
        """Normalize keys so case variants share one storage record."""
        return key.lower()

    def create_mapping(self, *, key: str, flow_id: str) -> EventMapping:
        """Create a mapping only when its normalized key is unused."""
        mapping = EventMapping(key=key, flow_id=flow_id)
        storage_key = self._normalize_key(key=key)

        with self._write_lock:
            if self._storage.record_exists(collection=EVENT_MAPPINGS_COLLECTION, key=storage_key):
                raise DocpipeException(
                    f"Event mapping for key '{key}' already exists",
                    status_code=409,
                    error_code=ErrorCode.EVENT_MAPPING_ALREADY_EXISTS,
                )
            self._storage.save_record(
                collection=EVENT_MAPPINGS_COLLECTION,
                key=storage_key,
                data=mapping.model_dump(mode="json"),
            )

        return mapping

    def get_mapping(self, *, key: str) -> EventMapping:
        """Resolve a case-insensitive routing key or raise if it is not registered."""
        storage_key = self._normalize_key(key=key)

        record = self._storage.get_record(collection=EVENT_MAPPINGS_COLLECTION, key=storage_key)
        if record is None:
            raise DocpipeException(
                f"Event mapping for key '{key}' was not found",
                status_code=404,
                error_code=ErrorCode.EVENT_MAPPING_NOT_FOUND,
            )

        return EventMapping.model_validate(record)

    def update_mapping(self, *, key: str, flow_id: str) -> EventMapping:
        """Update the flow ID for an existing mapping, preserving its registered key spelling."""
        storage_key = self._normalize_key(key=key)

        with self._write_lock:
            existing_mapping = self.get_mapping(key=key)
            mapping = EventMapping(key=existing_mapping.key, flow_id=flow_id)
            self._storage.save_record(
                collection=EVENT_MAPPINGS_COLLECTION,
                key=storage_key,
                data=mapping.model_dump(mode="json"),
            )
            return mapping

    def delete_mapping(self, *, key: str) -> None:
        """Delete a mapping by its case-insensitive key."""
        storage_key = self._normalize_key(key=key)
        with self._write_lock:
            self.get_mapping(key=key)
            self._storage.delete_record(collection=EVENT_MAPPINGS_COLLECTION, key=storage_key)

    def list_mappings(self) -> list[EventMapping]:
        """Return every stored routing mapping."""
        records = self._storage.list_records(collection=EVENT_MAPPINGS_COLLECTION)
        return [EventMapping.model_validate(record) for record in records]
