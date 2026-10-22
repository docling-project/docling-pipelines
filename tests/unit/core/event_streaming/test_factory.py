"""Design acceptance tests for event-mapping storage selection.

Coverage: filesystem default, YAML backend selection, and environment-over-YAML
precedence, all through ``create_event_mapping_service``.

Do not add, modify, or delete test cases in this file unless the user explicitly
asks you to make those changes here. Add new test cases in a separate file otherwise.
"""

from pathlib import Path

import yaml

import docpipe.core.event_streaming.factory as event_streaming_factory
from docpipe.core.event_streaming.factory import EventStreamingFactory
from docpipe.storage.duck_db.duckdb_key_value_storage import DuckDBKeyValueStorage
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage


def _write_config(*, path: Path, backend: str, storage_config: dict[str, str]) -> None:
    path.write_text(
        yaml.safe_dump({"global_storage": {"type": backend, "config": storage_config}}),
        encoding="utf-8",
    )


def test_create_event_mapping_service_defaults_to_filesystem(*, tmp_path, monkeypatch) -> None:
    """Use filesystem storage when neither environment nor YAML selects a backend."""
    data_dir = tmp_path / "default-data"
    monkeypatch.setattr(event_streaming_factory, "get_data_path", lambda: str(data_dir))
    monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "missing-config.yaml"))
    monkeypatch.delenv("DOCPIPE_STORAGE_BACKEND", raising=False)

    service = EventStreamingFactory.create_event_mapping_service()

    assert isinstance(service._storage, KeyValueFileSystemStorage)
    assert service._storage.base_dir == data_dir


def test_create_event_mapping_service_uses_yaml_backend(*, tmp_path, monkeypatch) -> None:
    """Use the backend and database path configured in YAML when no environment override exists."""
    database_path = tmp_path / "yaml-config" / "event-mappings.duckdb"
    config_path = tmp_path / "docling-pipelines-config.yaml"
    _write_config(path=config_path, backend="duckdb", storage_config={"database_path": str(database_path)})
    monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("DOCPIPE_STORAGE_BACKEND", raising=False)

    service = EventStreamingFactory.create_event_mapping_service()

    assert isinstance(service._storage, DuckDBKeyValueStorage)
    assert service._storage.database_path == str(database_path)


def test_create_event_mapping_service_environment_overrides_yaml(*, tmp_path, monkeypatch) -> None:
    """Use the environment backend instead of the backend selected in YAML."""
    data_dir = tmp_path / "environment-data"
    config_path = tmp_path / "docling-pipelines-config.yaml"
    _write_config(
        path=config_path,
        backend="duckdb",
        storage_config={"database_path": str(tmp_path / "yaml-config" / "event-mappings.duckdb")},
    )
    monkeypatch.setattr(event_streaming_factory, "get_data_path", lambda: str(data_dir))
    monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DOCPIPE_STORAGE_BACKEND", "filesystem")

    service = EventStreamingFactory.create_event_mapping_service()

    assert isinstance(service._storage, KeyValueFileSystemStorage)
    assert service._storage.base_dir == data_dir
