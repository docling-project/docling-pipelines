"""Unit tests for DuckDBAssetRepository: constraints, partial and bulk operations, config and failures.

Happy paths use a real DuckDB key-value store in a temporary directory. Storage failures use a
storage double whose methods raise, because a real DuckDB file cannot be made to fail reliably.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from docpipe.core.assets.common.adapters.repositories.duckdb_asset_repository import DuckDBAssetRepository
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet
from docpipe.exceptions.docpipe_exceptions import (
    AssetInvalidDataException,
    DocpipeException,
)
from docpipe.storage import StorageFactory


@pytest.fixture
def database_path(tmp_path: Path) -> str:
    return str(tmp_path / "assets.duckdb")


@pytest.fixture
def repo(database_path: str) -> DuckDBAssetRepository[DocumentSet]:
    storage = StorageFactory.create_key_value_storage(storage_type="duckdb", database_path=database_path)
    return DuckDBAssetRepository(asset_type=DocumentSet, key_value_storage=storage, database_path=database_path)


def _failing_repo(error: Exception) -> DuckDBAssetRepository[DocumentSet]:
    storage = MagicMock()
    for method in ("record_exists", "get_record", "list_records", "save_record", "delete_record", "collection_exists"):
        getattr(storage, method).side_effect = error
    return DuckDBAssetRepository(asset_type=DocumentSet, key_value_storage=storage, database_path="unused.duckdb")


def test_collection_comes_from_asset_type(repo: DuckDBAssetRepository[DocumentSet]) -> None:
    assert repo._collection == DocumentSet.get_collection_name()


class TestUpdateConstraints:
    """update() and partial_update() against stored data."""

    def test_rename_to_existing_name_is_rejected(self, repo: DuckDBAssetRepository[DocumentSet]) -> None:
        repo.save(asset=DocumentSet(asset_id="a", name="Alpha"))
        beta = repo.save(asset=DocumentSet(asset_id="b", name="Beta"))
        beta.name = "Alpha"

        with pytest.raises(AssetInvalidDataException, match="name 'Alpha' already exists"):
            repo.update(asset=beta)

        stored = repo.find_by_id(asset_id="b")
        assert stored is not None
        assert stored.name == "Beta"

    def test_update_keeping_own_name_is_allowed(self, repo: DuckDBAssetRepository[DocumentSet]) -> None:
        alpha = repo.save(asset=DocumentSet(asset_id="a", name="Alpha"))
        alpha.description = "same name, new description"

        repo.update(asset=alpha)

        stored = repo.find_by_id(asset_id="a")
        assert stored is not None
        assert stored.description == "same name, new description"

    def test_update_without_id_is_rejected(self, repo: DuckDBAssetRepository[DocumentSet]) -> None:
        asset = DocumentSet(name="No id")
        asset.asset_id = ""

        with pytest.raises(AssetInvalidDataException, match="asset_id cannot be None"):
            repo.update(asset=asset)

    def test_partial_update_persists_known_fields_only(self, repo: DuckDBAssetRepository[DocumentSet]) -> None:
        stored = repo.save(asset=DocumentSet(asset_id="p", name="Partial"))

        repo.partial_update(stored, {"description": "patched", "unknown_field": "ignored"})

        reloaded = repo.find_by_id(asset_id="p")
        assert reloaded is not None
        assert reloaded.description == "patched"
        assert not hasattr(reloaded, "unknown_field")

    def test_partial_update_with_invalid_result_is_not_persisted(
        self, repo: DuckDBAssetRepository[DocumentSet]
    ) -> None:
        stored = repo.save(asset=DocumentSet(asset_id="p", name="Partial"))

        with pytest.raises(AssetInvalidDataException):
            repo.partial_update(stored, {"name": ""})

        reloaded = repo.find_by_id(asset_id="p")
        assert reloaded is not None
        assert reloaded.name == "Partial"


class TestBulkDelete:
    """bulk_delete() result reporting."""

    def test_reports_deleted_missing_and_failed(self, repo: DuckDBAssetRepository[DocumentSet], monkeypatch) -> None:
        repo.save(asset=DocumentSet(asset_id="one", name="One"))
        repo.save(asset=DocumentSet(asset_id="two", name="Two"))
        original_delete = DuckDBAssetRepository.delete

        def _delete(self: DuckDBAssetRepository[DocumentSet], *, asset_id: str) -> bool:
            if asset_id == "two":
                raise DocpipeException("Failed to delete DocumentSet: disk full", status_code=500)
            if asset_id == "missing":
                return False
            return original_delete(self, asset_id=asset_id)

        monkeypatch.setattr(DuckDBAssetRepository, "delete", _delete)

        result = repo.bulk_delete(asset_ids=["one", "missing", "two"])

        assert result["total_requested"] == 3
        assert result["deleted"] == ["one"]
        assert result["failed"] == [
            {"asset_id": "missing", "error": "DocumentSet not found"},
            {"asset_id": "two", "error": "Failed to delete DocumentSet: disk full"},
        ]
        assert (result["total_deleted"], result["total_failed"]) == (1, 2)
        assert repo.exists(asset_id="one") is False


class TestConfig:
    """from_config() and validate_config()."""

    def test_from_config_builds_working_repository(self, database_path: str) -> None:
        repo = DuckDBAssetRepository.from_config(asset_type=DocumentSet, config={"database_path": database_path})

        repo.save(asset=DocumentSet(asset_id="cfg", name="From config"))

        assert repo.exists(asset_id="cfg") is True
        assert repo._collection == DocumentSet.get_collection_name()

    @pytest.mark.parametrize(
        ("config", "error"),
        [
            ({}, "Missing required configuration: 'database_path'"),
            ({"database_path": 42}, "Configuration 'database_path' must be a string"),
            ({"database_path": ""}, "Configuration 'database_path' cannot be empty"),
        ],
    )
    def test_invalid_config(self, config: dict, error: str) -> None:
        assert DuckDBAssetRepository.validate_config(config=config) == [error]

        with pytest.raises(DocpipeException, match=error) as exc_info:
            DuckDBAssetRepository.from_config(asset_type=DocumentSet, config=config)
        assert exc_info.value.status_code == 400

    def test_unsupported_storage_adapter_is_reported(self, database_path: str) -> None:
        with pytest.raises(DocpipeException, match="Failed to create storage for DocumentSet repository") as exc_info:
            DuckDBAssetRepository.from_config(
                asset_type=DocumentSet, config={"database_path": database_path, "storage_adapter": "tape"}
            )

        assert exc_info.value.status_code == 500


class TestStorageFailures:
    """Unexpected storage errors become DocpipeException(500); DocpipeException passes through."""

    @pytest.mark.parametrize(
        ("operation", "message"),
        [
            (lambda r: r.save(asset=DocumentSet(name="S")), "Failed to save DocumentSet"),
            (lambda r: r.find_by_id(asset_id="x"), "Failed to retrieve DocumentSet"),
            (lambda r: r.find_by_name(name="x"), "Failed to retrieve DocumentSet by name"),
            (lambda r: r.update(asset=DocumentSet(asset_id="x", name="U")), "Failed to update DocumentSet"),
            (lambda r: r.delete(asset_id="x"), "Failed to delete DocumentSet"),
            (lambda r: r.find_all(), "Failed to list DocumentSet assets"),
            (lambda r: r.exists(asset_id="x"), "Failed to check DocumentSet existence"),
        ],
    )
    def test_unexpected_error_is_wrapped(self, operation, message: str) -> None:
        repo = _failing_repo(RuntimeError("connection lost"))

        with pytest.raises(DocpipeException, match=f"{message}.*connection lost") as exc_info:
            operation(repo)

        assert exc_info.value.status_code == 500
        assert isinstance(exc_info.value.__cause__, RuntimeError)

    @pytest.mark.parametrize(
        "operation",
        [
            lambda r: r.find_by_id(asset_id="x"),
            lambda r: r.find_by_name(name="x"),
            lambda r: r.delete(asset_id="x"),
            lambda r: r.find_all(),
            lambda r: r.exists(asset_id="x"),
        ],
    )
    def test_docpipe_exception_passes_through(self, operation) -> None:
        original = DocpipeException("storage unavailable", status_code=503)
        repo = _failing_repo(original)

        with pytest.raises(DocpipeException) as exc_info:
            operation(repo)

        assert exc_info.value is original

    def test_health_check_reports_unhealthy(self) -> None:
        repo = _failing_repo(RuntimeError("connection lost"))

        health = repo.health_check()

        assert health["status"] == "unhealthy"
        assert health["details"]["error"] == "connection lost"
        assert health["details"]["collection"] == DocumentSet.get_collection_name()

    def test_health_check_reports_healthy(self, repo: DuckDBAssetRepository[DocumentSet], database_path: str) -> None:
        health = repo.health_check()

        assert health["status"] == "healthy"
        assert health["details"]["database_path"] == database_path
        assert health["details"]["asset_type"] == "DocumentSet"
