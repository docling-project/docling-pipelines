# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Integration tests for the PostgreSQL asset and attachment repositories.

Runs against a real PostgreSQL server (see ``conftest.py`` for the environment
variables); skipped automatically when none is configured or reachable.

Coverage:
- Full AssetRepository contract round-trip for DocumentSet and DocumentLibrary
  (save / find_by_id / find_by_name / find_all / list_all / update /
  partial_update / exists / exists_by_name / delete / bulk_delete / health_check)
- Wiring through RepositoryFactory and AttachmentRepositoryFactory
- Collection isolation between asset types
- Concurrent writers using independent connection pools (stand-ins for
  separate API replicas): duplicate-name races on save and on update,
  DocumentSetService get-or-create races, and concurrent schema bootstrap
- AttachmentRepository round-trip including upsert
- End-to-end: YAML ``type: postgres`` makes DocumentSetOperator write, and the
  API dependency providers read, the same metadata and attachment rows
"""

import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pyarrow as pa
import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from docpipe.api import dependencies
from docpipe.core.assets.common.adapters.repositories.postgres_asset_repository import PostgresAssetRepository
from docpipe.core.assets.common.adapters.repositories.postgres_attachment_repository import (
    PostgresAttachmentRepository,
)
from docpipe.core.assets.common.adapters.repositories.postgres_storage_utils import PostgresStorageUtils
from docpipe.core.assets.common.domain.models.asset import Asset
from docpipe.core.assets.common.domain.models.attachment_ref import AttachmentRef
from docpipe.core.assets.common.factories.asset_repository_factory import AssetRepositoryFactory, RepositoryType
from docpipe.core.assets.common.factories.attachment_repository_factory import AttachmentRepositoryFactory
from docpipe.core.assets.document_libraries.domain.models.document_library import DocumentLibrary
from docpipe.core.assets.document_sets.application.services.document_set_service import DocumentSetService
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.document_sets.document_set_operator import DocumentSetOperator
from docpipe.exceptions.docpipe_exceptions import (
    AssetAlreadyExistsException,
    AssetInvalidDataException,
    AssetNotFoundException,
    DocpipeException,
)
from docpipe.utils.infrastructure import DocpipeConfigLoader

pytestmark = pytest.mark.integration


def _make_document_set(*, name: str, offset_minutes: int = 0) -> DocumentSet:
    created = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=offset_minutes)
    return DocumentSet(
        name=name,
        description=f"{name} description",
        total_documents=3,
        total_size_bytes=1024,
        total_pages=7,
        created_at=created,
        updated_at=created,
        metadata={"owner": "it", "nested": {"tags": ["a", "b"]}},
    )


def _make_library(*, name: str, offset_minutes: int = 0) -> DocumentLibrary:
    del offset_minutes  # DocumentLibrary has no timestamps
    return DocumentLibrary(
        name=name,
        description=f"{name} description",
        purpose="integration test",
        tags=["x", "y"],
        created_by="tester",
        document_set_ids=["ds-1", "ds-2"],
    )


ASSET_CASES = [
    pytest.param(DocumentSet, _make_document_set, id="document_set"),
    pytest.param(DocumentLibrary, _make_library, id="document_library"),
]


@pytest.fixture(autouse=True)
def reset_config_loader():
    """Clear the DocpipeConfigLoader cache before and after each test."""
    DocpipeConfigLoader.reset()
    yield
    DocpipeConfigLoader.reset()


def _create_repo(*, asset_type: type[Asset], repo_config: dict[str, Any]) -> PostgresAssetRepository:
    repo = AssetRepositoryFactory.create_repository(
        asset_type=asset_type,
        adapter_name=RepositoryType.POSTGRES.value,
        config_override=repo_config,
    )
    assert isinstance(repo, PostgresAssetRepository)
    return repo


@pytest.mark.parametrize(("asset_type", "factory"), ASSET_CASES)
class TestAssetRepositoryContract:
    """Round-trip of every AssetRepository port method for each asset type."""

    def test_save_and_find(self, asset_type, factory, *, repo_config):
        repo = _create_repo(asset_type=asset_type, repo_config=repo_config)
        asset = factory(name="alpha")

        saved = repo.save(asset=asset)

        assert saved is asset
        by_id = repo.find_by_id(asset_id=asset.asset_id)
        assert by_id is not None
        assert type(by_id) is asset_type
        assert by_id.to_dict() == asset.to_dict()
        by_name = repo.find_by_name(name="alpha")
        assert by_name is not None
        assert by_name.asset_id == asset.asset_id
        assert repo.exists(asset_id=asset.asset_id) is True
        assert repo.exists_by_name(name="alpha") is True
        assert repo.find_by_id(asset_id="missing") is None
        assert repo.find_by_name(name="missing") is None
        assert repo.exists(asset_id="missing") is False
        assert repo.exists_by_name(name="missing") is False

    def test_save_rejects_duplicate_id_and_name(self, asset_type, factory, *, repo_config):
        repo = _create_repo(asset_type=asset_type, repo_config=repo_config)
        first = repo.save(asset=factory(name="alpha"))

        same_id = factory(name="beta")
        same_id.asset_id = first.asset_id
        with pytest.raises(AssetAlreadyExistsException, match="with ID"):
            repo.save(asset=same_id)

        with pytest.raises(AssetAlreadyExistsException, match="with name 'alpha'") as exc_info:
            repo.save(asset=factory(name="alpha"))
        assert exc_info.value.status_code == 409

        assert len(repo.find_all()) == 1

    def test_save_rejects_invalid_asset(self, asset_type, factory, *, repo_config):
        repo = _create_repo(asset_type=asset_type, repo_config=repo_config)
        # DocumentSet raises AssetInvalidDataException, DocumentLibrary a plain DocpipeException (400)
        with pytest.raises(DocpipeException) as exc_info:
            repo.save(asset=factory(name=" "))
        assert exc_info.value.status_code == 400
        assert repo.find_all() == []

    def test_update(self, asset_type, factory, *, repo_config):
        repo = _create_repo(asset_type=asset_type, repo_config=repo_config)
        asset = repo.save(asset=factory(name="alpha"))
        other = repo.save(asset=factory(name="beta", offset_minutes=1))

        asset.description = "changed"
        asset.name = "alpha renamed"
        repo.update(asset=asset)

        reloaded = repo.find_by_id(asset_id=asset.asset_id)
        assert reloaded is not None
        assert reloaded.description == "changed"
        assert repo.find_by_name(name="alpha") is None
        renamed = repo.find_by_name(name="alpha renamed")
        assert renamed is not None
        assert renamed.asset_id == asset.asset_id

        asset.name = other.name
        with pytest.raises(AssetInvalidDataException, match="already exists"):
            repo.update(asset=asset)

        ghost = factory(name="ghost")
        with pytest.raises(AssetNotFoundException):
            repo.update(asset=ghost)
        assert repo.exists(asset_id=ghost.asset_id) is False

    def test_partial_update(self, asset_type, factory, *, repo_config):
        repo = _create_repo(asset_type=asset_type, repo_config=repo_config)
        asset = repo.save(asset=factory(name="alpha"))

        repo.partial_update(asset, {"description": "patched", "not_a_field": 1})

        reloaded = repo.find_by_id(asset_id=asset.asset_id)
        assert reloaded is not None
        assert reloaded.description == "patched"
        assert not hasattr(reloaded, "not_a_field")

    def test_find_all_and_list_all(self, asset_type, factory, *, repo_config):
        repo = _create_repo(asset_type=asset_type, repo_config=repo_config)
        # Insertion order differs from creation order, so ordering by row insert time would fail
        created_minutes = {"first": 2, "second": 0, "third": 3, "fourth": 1}
        names = list(created_minutes)
        for name, minutes in created_minutes.items():
            repo.save(asset=factory(name=name, offset_minutes=minutes))

        all_assets = repo.find_all()
        assert len(all_assets) == 4
        listed_names = [a.name for a in all_assets]
        if asset_type is DocumentSet:
            # newest-first by the asset's own created_at
            assert listed_names == ["third", "first", "fourth", "second"]
        else:
            # no creation timestamp: insertion order (same as the DuckDB adapter)
            assert listed_names == names

        assert [a.name for a in repo.list_all()] == listed_names
        assert [a.name for a in repo.list_all(limit=2)] == listed_names[:2]
        assert [a.name for a in repo.list_all(limit=2, offset=1)] == listed_names[1:3]
        assert [a.name for a in repo.list_all(offset=3)] == listed_names[3:]
        assert repo.list_all(offset=10) == []

    def test_delete_and_bulk_delete(self, asset_type, factory, *, repo_config):
        repo = _create_repo(asset_type=asset_type, repo_config=repo_config)
        a = repo.save(asset=factory(name="a"))
        b = repo.save(asset=factory(name="b"))
        c = repo.save(asset=factory(name="c"))
        d = repo.save(asset=factory(name="d"))

        assert repo.delete(asset_id=a.asset_id) is True
        assert repo.delete(asset_id=a.asset_id) is False
        assert repo.find_by_id(asset_id=a.asset_id) is None

        result = repo.bulk_delete(asset_ids=[b.asset_id, "missing", c.asset_id, b.asset_id])

        assert result["total_requested"] == 4
        assert result["deleted"] == [b.asset_id, c.asset_id]
        assert result["total_deleted"] == 2
        assert result["total_failed"] == 2
        assert [f["asset_id"] for f in result["failed"]] == ["missing", b.asset_id]
        assert all("not found" in f["error"] for f in result["failed"])
        assert [x.asset_id for x in repo.find_all()] == [d.asset_id]

        empty = repo.bulk_delete(asset_ids=[])
        assert empty["total_requested"] == 0
        assert empty["deleted"] == []

    def test_health_check(self, asset_type, factory, *, repo_config, asset_schema):
        repo = _create_repo(asset_type=asset_type, repo_config=repo_config)
        health = repo.health_check()
        assert health["status"] == "healthy"
        assert health["details"]["schema"] == asset_schema
        assert health["details"]["collection"] == asset_type.get_collection_name()
        assert health["details"]["collection_exists"] is False
        assert "password" not in str(health)

        repo.save(asset=factory(name="alpha"))
        assert repo.health_check()["details"]["collection_exists"] is True

    def test_writes_visible_to_second_instance(
        self, asset_type, factory, *, repo_config, asset_schema, independent_engine
    ):
        repo = _create_repo(asset_type=asset_type, repo_config=repo_config)
        other = PostgresAssetRepository(asset_type=asset_type, engine=independent_engine, schema=asset_schema)

        asset = repo.save(asset=factory(name="shared"))

        seen = other.find_by_id(asset_id=asset.asset_id)
        assert seen is not None
        assert seen.to_dict() == asset.to_dict()
        assert other.delete(asset_id=asset.asset_id) is True
        assert repo.exists(asset_id=asset.asset_id) is False


class TestCollectionIsolation:
    """Document sets and document libraries share tables but not namespaces."""

    def test_same_name_in_different_collections(self, *, repo_config):
        set_repo = _create_repo(asset_type=DocumentSet, repo_config=repo_config)
        lib_repo = _create_repo(asset_type=DocumentLibrary, repo_config=repo_config)

        doc_set = set_repo.save(asset=_make_document_set(name="shared name"))
        library = lib_repo.save(asset=_make_library(name="shared name"))

        assert [x.asset_id for x in set_repo.find_all()] == [doc_set.asset_id]
        assert [x.asset_id for x in lib_repo.find_all()] == [library.asset_id]
        assert lib_repo.find_by_id(asset_id=doc_set.asset_id) is None
        assert lib_repo.delete(asset_id=doc_set.asset_id) is False
        assert set_repo.exists(asset_id=doc_set.asset_id) is True


class TestConcurrentWriters:
    """Two repositories with independent connection pools, as separate replicas would have."""

    WORKERS = 8

    @staticmethod
    def _run_concurrently(*, tasks: Sequence[Callable[..., Any]]) -> list[Any]:
        barrier = threading.Barrier(len(tasks))

        def run(task: Callable[..., Any]) -> Any:
            barrier.wait()
            try:
                return task()
            except Exception as exc:
                return exc

        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            return list(pool.map(run, tasks))

    @pytest.mark.parametrize(("asset_type", "factory"), ASSET_CASES)
    def test_concurrent_save_same_name_only_one_wins(
        self, asset_type, factory, *, repo_config, asset_schema, independent_engine
    ):
        repo_a = _create_repo(asset_type=asset_type, repo_config=repo_config)
        repo_b = PostgresAssetRepository(asset_type=asset_type, engine=independent_engine, schema=asset_schema)
        repos = [repo_a, repo_b]

        tasks = [(lambda r=repos[i % 2]: r.save(asset=factory(name="contested"))) for i in range(self.WORKERS)]
        results = self._run_concurrently(tasks=tasks)

        winners = [r for r in results if isinstance(r, Asset)]
        losers = [r for r in results if isinstance(r, Exception)]
        assert len(winners) == 1
        assert len(losers) == self.WORKERS - 1
        assert all(isinstance(e, AssetAlreadyExistsException) for e in losers)
        assert [x.asset_id for x in repo_a.find_all()] == [winners[0].asset_id]
        assert repo_b.find_by_name(name="contested").asset_id == winners[0].asset_id

    def test_concurrent_save_distinct_names_all_persist(self, *, repo_config, asset_schema, independent_engine):
        repo_a = _create_repo(asset_type=DocumentSet, repo_config=repo_config)
        repo_b = PostgresAssetRepository(asset_type=DocumentSet, engine=independent_engine, schema=asset_schema)
        repos = [repo_a, repo_b]

        tasks = [
            (lambda i=i: repos[i % 2].save(asset=_make_document_set(name=f"set_{i}", offset_minutes=i)))
            for i in range(self.WORKERS * 2)
        ]
        results = self._run_concurrently(tasks=tasks)

        assert all(isinstance(r, DocumentSet) for r in results), results
        assert sorted(x.name for x in repo_b.find_all()) == sorted(f"set_{i}" for i in range(self.WORKERS * 2))

    def test_concurrent_rename_to_same_name_only_one_wins(self, *, repo_config, asset_schema, independent_engine):
        repo_a = _create_repo(asset_type=DocumentSet, repo_config=repo_config)
        repo_b = PostgresAssetRepository(asset_type=DocumentSet, engine=independent_engine, schema=asset_schema)
        first = repo_a.save(asset=_make_document_set(name="one"))
        second = repo_a.save(asset=_make_document_set(name="two"))

        copy_first = repo_a.find_by_id(asset_id=first.asset_id)
        copy_second = repo_b.find_by_id(asset_id=second.asset_id)
        assert copy_first is not None
        assert copy_second is not None
        copy_first.name = "target"
        copy_second.name = "target"

        results = self._run_concurrently(
            tasks=[lambda: repo_a.update(asset=copy_first), lambda: repo_b.update(asset=copy_second)]
        )

        assert sum(isinstance(r, DocumentSet) for r in results) == 1
        errors = [r for r in results if isinstance(r, Exception)]
        assert len(errors) == 1
        assert isinstance(errors[0], AssetInvalidDataException)
        assert sorted(x.name for x in repo_a.find_all()) in (["one", "target"], ["target", "two"])

    def test_concurrent_service_get_or_create_converges(self, *, repo_config, asset_schema, independent_engine):
        """DocumentSetService.create_document_set relies on the 409 to resolve races."""
        repo_a = _create_repo(asset_type=DocumentSet, repo_config=repo_config)
        repo_b = PostgresAssetRepository(asset_type=DocumentSet, engine=independent_engine, schema=asset_schema)
        services = [
            DocumentSetService(metadata_repository=repo, data_store=None, attachment_repository=None)  # type: ignore[arg-type]
            for repo in (repo_a, repo_b)
        ]

        tasks = [
            (lambda s=services[i % 2]: s.create_document_set(name="race set", description=None))
            for i in range(self.WORKERS)
        ]
        results = self._run_concurrently(tasks=tasks)

        assert all(isinstance(r, DocumentSet) for r in results), results
        assert len({r.asset_id for r in results}) == 1
        assert len(repo_b.find_all()) == 1

    def test_concurrent_schema_bootstrap(self, *, postgres_settings, asset_schema):
        """Several fresh pools racing to create the schema must all succeed."""
        url = (
            f"postgresql+psycopg2://{postgres_settings['user']}:{postgres_settings['password']}"
            f"@{postgres_settings['host']}:{postgres_settings['port']}/{postgres_settings['database']}"
        )
        engines: list[Engine] = [create_engine(url) for _ in range(4)]
        try:
            tasks = [(lambda e=e: PostgresStorageUtils.ensure_schema(engine=e, schema=asset_schema)) for e in engines]
            results = self._run_concurrently(tasks=tasks)
            assert not [r for r in results if isinstance(r, Exception)], results
            with engines[0].connect() as connection:
                count = connection.execute(
                    text("SELECT count(*) FROM information_schema.tables WHERE table_schema = :s"),
                    {"s": asset_schema},
                ).scalar()
            assert count == 2
        finally:
            for engine in engines:
                engine.dispose()


class TestPostgresAttachmentRepository:
    """AttachmentRepository round-trip through the factory."""

    def test_round_trip(self, *, repo_config):
        repo = AttachmentRepositoryFactory.create(
            adapter_name="postgres",
            config={**repo_config, "database_path": "ignored.duckdb"},
        )
        assert isinstance(repo, PostgresAttachmentRepository)

        ref = AttachmentRef(
            backend_type="duckdb",
            name="ds_table",
            details={"database_path": "/data/x.duckdb", "table_name": "ds_table"},
            attachment_id="att-1",
            created_at="2026-01-01T00:00:00+00:00",
        )
        assert repo.get(asset_id="asset-1") is None
        assert repo.exists(asset_id="asset-1") is False

        repo.save(asset_id="asset-1", data=ref)
        assert repo.exists(asset_id="asset-1") is True
        assert repo.get(asset_id="asset-1") == ref

        replacement = AttachmentRef(backend_type="duckdb", name="ds_table_v2")
        repo.save(asset_id="asset-1", data=replacement)
        assert repo.get(asset_id="asset-1") == replacement

        assert repo.delete(asset_id="asset-1") is True
        assert repo.delete(asset_id="asset-1") is False
        assert repo.get(asset_id="asset-1") is None

    def test_attachments_do_not_collide_with_assets(self, *, repo_config):
        asset_repo = _create_repo(asset_type=DocumentSet, repo_config=repo_config)
        attachment_repo = AttachmentRepositoryFactory.create(adapter_name="postgres", config=repo_config)
        doc_set = asset_repo.save(asset=_make_document_set(name="with attachment"))

        attachment_repo.save(asset_id=doc_set.asset_id, data=AttachmentRef(backend_type="duckdb", name="t"))
        assert attachment_repo.delete(asset_id=doc_set.asset_id) is True

        assert asset_repo.exists(asset_id=doc_set.asset_id) is True


def _clear_dependency_caches() -> None:
    dependencies.get_document_set_repository.cache_clear()
    dependencies.get_document_set_data_store.cache_clear()
    dependencies.get_document_set_attachment_repository.cache_clear()
    dependencies.get_document_library_repository.cache_clear()


class TestEndToEndWiring:
    """YAML-configured ``type: postgres`` drives both the flow operator and the API providers."""

    @pytest.fixture
    def postgres_yaml_config(self, tmp_path, monkeypatch, *, repo_config):
        database_path = str(tmp_path / "document_sets.duckdb")
        yaml_config = {
            "assets_management": {
                "documentset_repository": {
                    "type": "postgres",
                    "config": {"database_path": database_path, **repo_config},
                },
                "documentlibrary_repository": {"type": "postgres", "config": dict(repo_config)},
            }
        }
        config_path = tmp_path / "docling-pipelines-config.yaml"
        config_path.write_text(yaml.safe_dump(yaml_config))
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))
        monkeypatch.delenv("DOCUMENTSET_REPOSITORY_TYPE", raising=False)
        monkeypatch.delenv("DOCUMENTLIBRARY_REPOSITORY_TYPE", raising=False)
        _clear_dependency_caches()
        yield database_path
        _clear_dependency_caches()

    def test_operator_writes_metadata_and_attachment_to_postgres(self, *, postgres_yaml_config):
        table = pa.table({"id": ["d1", "d2"], "content": ["one", "two"], "size": [10, 20], "pages_processed": [1, 2]})
        operator = DocumentSetOperator({"document_set_name": "e2e set", "database_path": postgres_yaml_config})

        _, metadata = operator.transform(table)

        doc_set_id = metadata[OperatorConstants.DocumentSet.META_DOCUMENT_SET_ID]
        assert metadata[OperatorConstants.DocumentSet.META_TABLE_NAME]

        # The API dependency providers resolve the same PostgreSQL storage.
        repo = dependencies.get_document_set_repository()
        attachments = dependencies.get_document_set_attachment_repository()
        assert isinstance(repo, PostgresAssetRepository)
        assert isinstance(attachments, PostgresAttachmentRepository)
        stored = repo.find_by_id(asset_id=doc_set_id)
        assert stored is not None
        assert stored.name == "e2e set"
        assert stored.total_documents == 2
        ref = attachments.get(asset_id=doc_set_id)
        assert ref is not None
        assert ref.name == metadata[OperatorConstants.DocumentSet.META_TABLE_NAME]

        service = dependencies.get_document_set_service(
            repository=repo,
            data_store=dependencies.get_document_set_data_store(),
            attachment_repository=attachments,
        )
        assert service.preview_data(document_set_id=doc_set_id).num_rows == 2

        # A second run reuses the same document set (get-or-create by name).
        _, second = operator.transform(table)
        assert second[OperatorConstants.DocumentSet.META_DOCUMENT_SET_ID] == doc_set_id
        assert len(repo.find_all()) == 1

        assert isinstance(dependencies.get_document_library_repository(), PostgresAssetRepository)
