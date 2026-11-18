"""Unit tests for LocalAssetRepository (JSON files on the local filesystem)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from docpipe.core.assets.common.adapters.repositories.local_asset_repository import LocalAssetRepository
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.exceptions.docpipe_exceptions import (
    AssetAlreadyExistsException,
    AssetInvalidDataException,
    AssetNotFoundException,
)

_DEFINITION = {"doc_type": "pipeline", "version": "3.0", "pipelines": []}


def _flow(*, name: str, asset_id: str | None = None, modified_on: datetime | None = None) -> Flow:
    return Flow(asset_id=asset_id, name=name, definition=dict(_DEFINITION), modified_on=modified_on)


@pytest.fixture
def storage_path(tmp_path: Path) -> Path:
    return tmp_path / "flows"


@pytest.fixture
def repo(storage_path: Path) -> LocalAssetRepository[Flow]:
    return LocalAssetRepository(asset_type=Flow, storage_path=str(storage_path))


class TestConstruction:
    """Storage directory handling."""

    def test_creates_storage_directory(self, storage_path: Path, repo: LocalAssetRepository[Flow]) -> None:
        assert storage_path.is_dir()

    def test_from_config_uses_base_dir(self, tmp_path: Path) -> None:
        repo = LocalAssetRepository.from_config(asset_type=Flow, config={"base_dir": str(tmp_path / "configured")})

        repo.save(asset=_flow(name="Configured"))

        assert len(list((tmp_path / "configured").glob("*.json"))) == 1

    def test_default_path_is_under_home(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        repo = LocalAssetRepository(asset_type=Flow)

        default_path = tmp_path / "Documents" / "pipeline" / "assets"
        assert default_path.is_dir()
        assert repo.health_check()["storage_path"] == str(default_path)


class TestSaveAndFind:
    """Round trip through JSON files."""

    def test_save_writes_json_file_and_find_by_id_reads_it(
        self, storage_path: Path, repo: LocalAssetRepository[Flow]
    ) -> None:
        flow = _flow(name="Ingest", asset_id="flow-1")

        repo.save(asset=flow)

        stored = json.loads((storage_path / "flow-1.json").read_text())
        assert stored["name"] == "Ingest"
        loaded = repo.find_by_id(asset_id="flow-1")
        assert loaded is not None
        assert (loaded.asset_id, loaded.name, loaded.definition) == ("flow-1", "Ingest", _DEFINITION)

    def test_save_rejects_duplicate_name(self, repo: LocalAssetRepository[Flow]) -> None:
        repo.save(asset=_flow(name="Same"))

        with pytest.raises(AssetAlreadyExistsException, match="Same"):
            repo.save(asset=_flow(name="Same"))

    def test_find_by_id_missing_returns_none(self, repo: LocalAssetRepository[Flow]) -> None:
        assert repo.find_by_id(asset_id="missing") is None

    def test_find_by_name(self, repo: LocalAssetRepository[Flow]) -> None:
        repo.save(asset=_flow(name="First", asset_id="f1"))
        repo.save(asset=_flow(name="Second", asset_id="f2"))

        found = repo.find_by_name(name="Second")

        assert found is not None
        assert found.asset_id == "f2"
        assert repo.find_by_name(name="Third") is None
        assert repo.exists_by_name(name="First") is True
        assert repo.exists_by_name(name="Third") is False

    def test_find_all_skips_unreadable_files(self, storage_path: Path, repo: LocalAssetRepository[Flow]) -> None:
        repo.save(asset=_flow(name="Valid", asset_id="valid"))
        (storage_path / "broken.json").write_text("{not json")

        assets = repo.find_all()

        assert [a.asset_id for a in assets] == ["valid"]


class TestListAll:
    """Sorting and pagination."""

    @pytest.fixture
    def three_flows(self, repo: LocalAssetRepository[Flow]) -> None:
        for name, month in [("Oldest", 1), ("Newest", 6), ("Middle", 3)]:
            flow = _flow(name=name, modified_on=datetime(2024, month, 1, tzinfo=UTC))
            # save() refreshes modified_on, so pin it on disk afterwards
            repo.save(asset=flow)
            flow.modified_on = datetime(2024, month, 1, tzinfo=UTC)
            path = repo._get_file_path(asset_id=flow.asset_id)
            path.write_text(json.dumps(flow.to_dict()))

    @pytest.mark.usefixtures("three_flows")
    def test_sorted_newest_first(self, repo: LocalAssetRepository[Flow]) -> None:
        assert [f.name for f in repo.list_all()] == ["Newest", "Middle", "Oldest"]

    @pytest.mark.usefixtures("three_flows")
    @pytest.mark.parametrize(
        ("limit", "offset", "expected"),
        [(2, None, ["Newest", "Middle"]), (None, 1, ["Middle", "Oldest"]), (1, 1, ["Middle"]), (5, 3, [])],
    )
    def test_pagination(
        self, repo: LocalAssetRepository[Flow], limit: int | None, offset: int | None, expected: list[str]
    ) -> None:
        assert [f.name for f in repo.list_all(limit=limit, offset=offset)] == expected

    def test_assets_without_update_time_sort_by_name(self, repo: LocalAssetRepository[Flow], monkeypatch) -> None:
        repo.save(asset=_flow(name="alpha"))
        repo.save(asset=_flow(name="beta"))
        monkeypatch.setattr(Flow, "get_updated_at", lambda self: None)

        assert [f.name for f in repo.list_all()] == ["beta", "alpha"]


class TestUpdate:
    """Full and partial updates."""

    def test_update_persists_changes_and_refreshes_timestamp(self, repo: LocalAssetRepository[Flow]) -> None:
        flow = repo.save(asset=_flow(name="Before", asset_id="u1"))
        flow.modified_on = datetime(2020, 1, 1, tzinfo=UTC)
        flow.description = "changed"

        repo.update(asset=flow)

        loaded = repo.find_by_id(asset_id="u1")
        assert loaded is not None
        assert loaded.description == "changed"
        assert loaded.modified_on is not None
        assert loaded.modified_on > datetime(2020, 1, 1, tzinfo=UTC)

    def test_update_without_id_raises(self, repo: LocalAssetRepository[Flow]) -> None:
        flow = _flow(name="No id")
        flow.asset_id = ""

        with pytest.raises(AssetInvalidDataException, match="Asset ID is required"):
            repo.update(asset=flow)

    def test_update_missing_asset_raises(self, repo: LocalAssetRepository[Flow]) -> None:
        with pytest.raises(AssetNotFoundException, match="missing"):
            repo.update(asset=_flow(name="Ghost", asset_id="missing"))

    def test_partial_update_applies_known_fields_only(self, repo: LocalAssetRepository[Flow]) -> None:
        flow = repo.save(asset=_flow(name="Partial", asset_id="p1"))

        repo.partial_update(flow, {"description": "new description", "not_a_field": "ignored"})

        loaded = repo.find_by_id(asset_id="p1")
        assert loaded is not None
        assert loaded.description == "new description"
        assert not hasattr(loaded, "not_a_field")

    def test_partial_update_rejects_invalid_result(self, repo: LocalAssetRepository[Flow], monkeypatch) -> None:
        flow = repo.save(asset=_flow(name="Valid", asset_id="p2"))

        def _reject(self: Flow) -> None:
            raise ValueError("definition is not a pipeline")

        monkeypatch.setattr(Flow, "validate", _reject)

        with pytest.raises(ValueError, match="Invalid flow data after update: definition is not a pipeline"):
            repo.partial_update(flow, {"description": "x"})

        loaded = repo.find_by_id(asset_id="p2")
        assert loaded is not None
        assert loaded.description is None


class TestDelete:
    """Single and bulk deletion."""

    def test_delete_removes_file(self, storage_path: Path, repo: LocalAssetRepository[Flow]) -> None:
        repo.save(asset=_flow(name="Doomed", asset_id="d1"))

        assert repo.delete(asset_id="d1") is True
        assert not (storage_path / "d1.json").exists()
        assert repo.exists(asset_id="d1") is False

    def test_delete_missing_returns_false(self, repo: LocalAssetRepository[Flow]) -> None:
        assert repo.delete(asset_id="missing") is False

    def test_bulk_delete_reports_deleted_missing_and_failed(
        self, repo: LocalAssetRepository[Flow], monkeypatch
    ) -> None:
        repo.save(asset=_flow(name="One", asset_id="b1"))
        repo.save(asset=_flow(name="Two", asset_id="b2"))
        original_delete = LocalAssetRepository.delete

        def _delete(self: LocalAssetRepository[Flow], *, asset_id: str) -> bool:
            if asset_id == "b2":
                raise PermissionError("read-only file")
            return original_delete(self, asset_id=asset_id)

        monkeypatch.setattr(LocalAssetRepository, "delete", _delete)

        result = repo.bulk_delete(asset_ids=["b1", "missing", "b2"])

        assert result == {
            "total_requested": 3,
            "total_deleted": 1,
            "total_failed": 2,
            "deleted": ["b1"],
            "failed": [
                {"asset_id": "missing", "error": "Asset not found"},
                {"asset_id": "b2", "error": "read-only file"},
            ],
        }


def test_health_check_reports_storage_state(storage_path: Path, repo: LocalAssetRepository[Flow]) -> None:
    repo.save(asset=_flow(name="Counted"))

    health = repo.health_check()

    assert health == {
        "status": "healthy",
        "storage_path": str(storage_path),
        "storage_exists": True,
        "storage_writable": True,
        "asset_count": 1,
    }
