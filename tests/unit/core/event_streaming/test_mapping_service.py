"""Unit tests for event mapping persistence and case-insensitive lookup."""

import pytest

from docpipe.core.event_streaming.mapping_service import EVENT_MAPPINGS_COLLECTION, EventMappingService
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.storage.interfaces.key_value_storage_port import KeyValueStoragePort

pytestmark = pytest.mark.unit


class InMemoryKeyValueStorage(KeyValueStoragePort):
    """Small storage fake that exercises the service through its port."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, object]] = {}

    def save_record(self, *, collection: str, key: str, data: dict[str, object]) -> None:
        self.records[(collection, key)] = data.copy()

    def get_record(self, *, collection: str, key: str) -> dict[str, object] | None:
        record = self.records.get((collection, key))
        return record.copy() if record is not None else None

    def list_records(self, *, collection: str, filters: dict[str, object] | None = None) -> list[dict[str, object]]:
        return [
            record.copy() for (record_collection, _), record in self.records.items() if record_collection == collection
        ]

    def delete_record(self, *, collection: str, key: str) -> bool:
        return self.records.pop((collection, key), None) is not None

    def collection_exists(self, *, collection: str) -> bool:
        return any(record_collection == collection for record_collection, _ in self.records)

    def record_exists(self, *, collection: str, key: str) -> bool:
        return (collection, key) in self.records


@pytest.fixture
def storage() -> InMemoryKeyValueStorage:
    return InMemoryKeyValueStorage()


@pytest.fixture
def service(storage: InMemoryKeyValueStorage) -> EventMappingService:
    return EventMappingService(storage=storage)


def test_create_mapping_persists_using_normalized_key(
    *, service: EventMappingService, storage: InMemoryKeyValueStorage
) -> None:
    mapping = service.create_mapping(key="Invoice-Ready", flow_id="flow-123")

    assert mapping.key == "Invoice-Ready"
    assert storage.records[(EVENT_MAPPINGS_COLLECTION, "invoice-ready")] == {
        "key": "Invoice-Ready",
        "flow_id": "flow-123",
    }


def test_create_mapping_rejects_case_insensitive_duplicate(*, service: EventMappingService) -> None:
    service.create_mapping(key="Invoice-Ready", flow_id="flow-123")

    with pytest.raises(DocpipeException) as exc_info:
        service.create_mapping(key="INVOICE-READY", flow_id="flow-456")

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == ErrorCode.EVENT_MAPPING_ALREADY_EXISTS


def test_get_mapping_is_case_insensitive_and_reports_missing_key(*, service: EventMappingService) -> None:
    service.create_mapping(key="Invoice-Ready", flow_id="flow-123")

    assert service.get_mapping(key="INVOICE-READY").key == "Invoice-Ready"

    with pytest.raises(DocpipeException) as exc_info:
        service.get_mapping(key="missing")

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == ErrorCode.EVENT_MAPPING_NOT_FOUND


def test_update_mapping_preserves_key_and_replaces_flow_id(*, service: EventMappingService) -> None:
    service.create_mapping(key="Invoice-Ready", flow_id="flow-123")

    updated = service.update_mapping(key="INVOICE-READY", flow_id="flow-456")

    assert updated.key == "Invoice-Ready"
    assert updated.flow_id == "flow-456"
    assert service.get_mapping(key="invoice-ready") == updated


def test_update_mapping_reports_missing_key(*, service: EventMappingService) -> None:
    with pytest.raises(DocpipeException) as exc_info:
        service.update_mapping(key="missing", flow_id="flow-456")

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == ErrorCode.EVENT_MAPPING_NOT_FOUND


def test_delete_mapping_is_case_insensitive_and_reports_missing_key(*, service: EventMappingService) -> None:
    service.create_mapping(key="Invoice-Ready", flow_id="flow-123")

    assert service.delete_mapping(key="INVOICE-READY") is None
    assert service.list_mappings() == []

    with pytest.raises(DocpipeException) as exc_info:
        service.delete_mapping(key="invoice-ready")

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == ErrorCode.EVENT_MAPPING_NOT_FOUND


def test_list_mappings_returns_stored_mappings(*, service: EventMappingService) -> None:
    assert service.list_mappings() == []
    service.create_mapping(key="Invoice-Ready", flow_id="flow-123")
    service.create_mapping(key="Report-Ready", flow_id="flow-456")

    assert [mapping.key for mapping in service.list_mappings()] == ["Invoice-Ready", "Report-Ready"]
