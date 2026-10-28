"""Unit tests for the generic AssetService, backed by a real LocalAssetRepository."""

from pathlib import Path

import pytest

from docpipe.core.assets.common.adapters.repositories.local_asset_repository import LocalAssetRepository
from docpipe.core.assets.common.application.services.asset_service import AssetService
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.exceptions.docpipe_exceptions import DocpipeException


@pytest.fixture
def service(tmp_path: Path) -> AssetService[Flow]:
    repository = LocalAssetRepository(asset_type=Flow, storage_path=str(tmp_path / "flows"))
    for index in range(5):
        repository.save(asset=Flow(asset_id=f"flow-{index}", name=f"Flow {index}", definition={"doc_type": "pipeline"}))
    return AssetService(repository=repository)


def test_get_by_id_and_name(service: AssetService[Flow]) -> None:
    assert service.get_by_id(asset_id="flow-2").name == "Flow 2"
    assert service.get_by_name(name="Flow 4").asset_id == "flow-4"


@pytest.mark.parametrize(
    ("call", "status", "message"),
    [
        (lambda s: s.get_by_id(asset_id="missing"), 404, "Asset with ID 'missing' not found"),
        (lambda s: s.get_by_name(name="Missing"), 404, "Asset with name 'Missing' not found"),
        (lambda s: s.delete(asset_id="missing"), 404, "Asset with ID 'missing' not found"),
        (lambda s: s.get_by_id(asset_id="  "), 400, "asset_id cannot be empty"),
        (lambda s: s.delete(asset_id=""), 400, "asset_id cannot be empty"),
        (lambda s: s.exists(asset_id=" "), 400, "asset_id cannot be empty"),
    ],
)
def test_lookup_errors(service: AssetService[Flow], call, status: int, message: str) -> None:
    with pytest.raises(DocpipeException, match=message) as exc_info:
        call(service)

    assert exc_info.value.status_code == status


def test_delete_and_exists(service: AssetService[Flow]) -> None:
    assert service.exists(asset_id="flow-1") is True

    assert service.delete(asset_id="flow-1") is True

    assert service.exists(asset_id="flow-1") is False
    assert service.count_all() == 4


def test_exists_by_name(service: AssetService[Flow]) -> None:
    assert service.exists_by_name(name="Flow 3") is True
    assert service.exists_by_name(name="Flow 9") is False


@pytest.mark.parametrize(("skip", "limit", "expected_count"), [(0, 100, 5), (0, 2, 2), (4, 10, 1), (5, 10, 0)])
def test_list_all_paginates(service: AssetService[Flow], skip: int, limit: int, expected_count: int) -> None:
    assets = service.list_all(skip=skip, limit=limit)

    assert len(assets) == expected_count
    assert {a.asset_id for a in assets} <= {f"flow-{i}" for i in range(5)}


def test_list_all_pages_do_not_overlap(service: AssetService[Flow]) -> None:
    first = service.list_all(skip=0, limit=3)
    second = service.list_all(skip=3, limit=3)

    assert {a.asset_id for a in first}.isdisjoint({a.asset_id for a in second})
    assert len(first) + len(second) == service.count_all() == 5


@pytest.mark.parametrize(
    ("skip", "limit", "message"),
    [(-1, 10, "skip must be >= 0"), (0, 0, "limit must be > 0"), (0, -5, "limit must be > 0")],
)
def test_list_all_rejects_invalid_pagination(service: AssetService[Flow], skip: int, limit: int, message: str) -> None:
    with pytest.raises(DocpipeException, match=message) as exc_info:
        service.list_all(skip=skip, limit=limit)

    assert exc_info.value.status_code == 400


def test_health_check_delegates_to_repository(service: AssetService[Flow], tmp_path: Path) -> None:
    health = service.health_check()

    assert health["status"] == "healthy"
    assert health["asset_count"] == 5
    assert health["storage_path"] == str(tmp_path / "flows")
