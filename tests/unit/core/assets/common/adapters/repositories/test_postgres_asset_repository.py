# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for PostgresAssetRepository and PostgresStorageUtils (no database needed).

The SQLAlchemy engine is mocked; behaviour against a real server is covered by
tests/integration/assets/test_postgres_asset_repository_integration.py.

Coverage:
- PostgresStorageUtils: config validation, schema resolution, engine caching,
  missing-password error, schema bootstrap statements, table layout
- PostgresAssetRepository: save / find / update / delete / bulk_delete /
  health_check control flow and error mapping, from_config validation
- RepositoryFactory: postgres registration and env/YAML selection
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError

from docpipe.core.assets.common.adapters.repositories.postgres_asset_repository import PostgresAssetRepository
from docpipe.core.assets.common.adapters.repositories.postgres_storage_utils import (
    DEFAULT_ASSET_SCHEMA,
    RECORDS_LISTING_INDEX,
    RECORDS_NAME_UNIQUE_CONSTRAINT,
    PostgresStorageUtils,
)
from docpipe.core.assets.common.factories.repository_factory import RepositoryFactory, RepositoryType
from docpipe.core.assets.document_libraries.domain.models.document_library import DocumentLibrary
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet
from docpipe.exceptions.docpipe_exceptions import (
    AssetAlreadyExistsException,
    AssetInvalidDataException,
    AssetNotFoundException,
    DocpipeException,
    RepositoryConfigurationException,
)

DATABASE_MODULE = "docpipe.storage.postgres.connection"
POSTGRES_ENV_VARS = (
    "DOCPIPE_POSTGRES_HOST",
    "DOCPIPE_POSTGRES_PORT",
    "DOCPIPE_POSTGRES_DB",
    "DOCPIPE_POSTGRES_USER",
    "DOCPIPE_POSTGRES_PASSWORD",
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_postgres_env(monkeypatch):
    for var in POSTGRES_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("DOCUMENTSET_REPOSITORY_TYPE", raising=False)
    yield
    PostgresStorageUtils.dispose_engines()


@pytest.fixture
def connection():
    return MagicMock(name="connection")


@pytest.fixture
def engine(connection):
    engine = MagicMock(name="engine")
    engine.begin.return_value.__enter__.return_value = connection
    engine.connect.return_value.__enter__.return_value = connection
    engine.url = make_url("postgresql+psycopg2://docpipe:s3cret@db.example:5432/docpipe")  # pragma: allowlist secret
    return engine


@pytest.fixture
def repo(engine):
    return PostgresAssetRepository(asset_type=DocumentSet, engine=engine, ensure_schema=False)


def _result(*, first=None, scalar=None, scalar_one_or_none=None, scalars_all=None) -> MagicMock:
    result = MagicMock(name="result")
    result.first.return_value = first
    result.scalar.return_value = scalar
    result.scalar_one_or_none.return_value = scalar_one_or_none
    result.scalars.return_value.all.return_value = scalars_all or []
    return result


def _compiled(*, statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def _unique_violation() -> IntegrityError:
    return _integrity_error(pgcode="23505")


class _FakeDriverError(Exception):
    """Stand-in for a psycopg2 error carrying a SQLSTATE code."""

    def __init__(self, pgcode: str) -> None:
        super().__init__(pgcode)
        self.pgcode = pgcode


def _integrity_error(*, pgcode: str) -> IntegrityError:
    return IntegrityError("UPDATE ...", {}, _FakeDriverError(pgcode))


# ---------------------------------------------------------------------------
# PostgresStorageUtils
# ---------------------------------------------------------------------------


class TestPostgresStorageUtilsConfig:
    def test_validate_config_accepts_empty_config(self):
        assert PostgresStorageUtils.validate_config(config={}) == []

    def test_validate_config_accepts_full_section(self):
        config = {"postgres": {"host": "h", "password": "p", "schema": "my_assets_2"}}  # pragma: allowlist secret
        assert PostgresStorageUtils.validate_config(config=config) == []

    def test_validate_config_rejects_non_mapping_section(self):
        errors = PostgresStorageUtils.validate_config(config={"postgres": "localhost"})
        assert len(errors) == 1
        assert "mapping" in errors[0]

    @pytest.mark.parametrize("schema", ["Bad", "1abc", "has-dash", "x" * 64, "", 5, 'a"; drop'])
    def test_validate_config_rejects_bad_schema(self, schema):
        errors = PostgresStorageUtils.validate_config(config={"postgres": {"schema": schema}})
        assert errors
        assert "schema" in errors[0]

    def test_resolve_schema_default_and_custom(self):
        assert PostgresStorageUtils.resolve_schema(config={}) == DEFAULT_ASSET_SCHEMA
        assert PostgresStorageUtils.resolve_schema(config={"postgres": None}) == DEFAULT_ASSET_SCHEMA
        assert PostgresStorageUtils.resolve_schema(config={"postgres": {"schema": "abc"}}) == "abc"


class TestPostgresStorageUtilsEngine:
    def test_missing_password_raises_repository_configuration_exception(self):
        with pytest.raises(RepositoryConfigurationException, match="DOCPIPE_POSTGRES_PASSWORD") as exc_info:
            PostgresStorageUtils.get_engine(config={"postgres": {"host": "h"}}, owner="DocumentSet repository")
        assert exc_info.value.repository_type == "postgres"
        assert exc_info.value.status_code == 400

    def test_engine_is_cached_per_connection_settings(self):
        config = {"postgres": {"host": "h", "password": "p"}}  # pragma: allowlist secret
        with patch(f"{DATABASE_MODULE}.create_postgres_engine", side_effect=lambda **_: MagicMock()) as create:
            first = PostgresStorageUtils.get_engine(config=config, owner="a")
            second = PostgresStorageUtils.get_engine(config=dict(config), owner="b")
            other_pool = PostgresStorageUtils.get_engine(
                config={"postgres": {"host": "h", "password": "p", "pool_size": 2}},  # pragma: allowlist secret
                owner="c",
            )

        assert first is second
        assert other_pool is not first
        assert create.call_count == 2
        assert create.call_args_list[0].kwargs["connection_string"].endswith("@h:5432/docpipe")

    def test_env_fallback_is_used(self, monkeypatch):
        monkeypatch.setenv("DOCPIPE_POSTGRES_PASSWORD", "envpw")
        monkeypatch.setenv("DOCPIPE_POSTGRES_HOST", "envhost")
        with patch(f"{DATABASE_MODULE}.create_postgres_engine", return_value=MagicMock()) as create:
            PostgresStorageUtils.get_engine(config={}, owner="x")
        assert "envpw@envhost:" in create.call_args.kwargs["connection_string"]

    def test_dispose_engines_disposes_and_clears(self):
        config = {"postgres": {"password": "p"}}  # pragma: allowlist secret
        mock_engine = MagicMock()
        with patch(f"{DATABASE_MODULE}.create_postgres_engine", return_value=mock_engine):
            PostgresStorageUtils.get_engine(config=config, owner="x")
        PostgresStorageUtils.dispose_engines()
        mock_engine.dispose.assert_called_once()
        with patch(f"{DATABASE_MODULE}.create_postgres_engine", return_value=MagicMock()) as create:
            PostgresStorageUtils.get_engine(config=config, owner="x")
        create.assert_called_once()

    def test_describe_engine_hides_password(self, engine):
        description = PostgresStorageUtils.describe_engine(engine=engine)
        assert description == "docpipe@db.example:5432/docpipe"
        assert "s3cret" not in description


class TestPostgresStorageUtilsSchema:
    def test_tables_are_cached_per_schema(self):
        assert PostgresStorageUtils.get_tables(schema="s_one") is PostgresStorageUtils.get_tables(schema="s_one")
        assert PostgresStorageUtils.get_tables(schema="s_one") is not PostgresStorageUtils.get_tables(schema="s_two")

    def test_table_layout(self):
        tables = PostgresStorageUtils.get_tables(schema="layout_check")
        records = tables.records
        assert records.schema == "layout_check"
        assert [c.name for c in records.primary_key.columns] == ["collection", "asset_id"]
        assert {"name", "data", "asset_created_at", "created_at", "updated_at"} <= set(records.c.keys())
        assert records.c.asset_created_at.nullable
        assert any(getattr(c, "name", None) == RECORDS_NAME_UNIQUE_CONSTRAINT for c in records.constraints)
        assert {index.name for index in records.indexes} == {RECORDS_LISTING_INDEX}
        assert [c.name for c in tables.attachments.primary_key.columns] == ["collection", "asset_id"]

    def test_ensure_schema_takes_advisory_lock_before_ddl(self, engine, connection):
        tables = PostgresStorageUtils.get_tables(schema="ensure_check")
        with patch.object(tables.metadata, "create_all") as create_all:
            result = PostgresStorageUtils.ensure_schema(engine=engine, schema="ensure_check")

        assert result is tables
        executed = [_compiled(statement=c.args[0]) for c in connection.execute.call_args_list]
        assert "pg_advisory_xact_lock" in executed[0]
        assert executed[1] == "CREATE SCHEMA IF NOT EXISTS ensure_check"
        create_all.assert_called_once_with(connection, checkfirst=True)
        engine.begin.assert_called_once()


# ---------------------------------------------------------------------------
# PostgresAssetRepository
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_bootstraps_schema_by_default(self, engine):
        tables = PostgresStorageUtils.get_tables(schema="custom_schema")
        with patch.object(PostgresStorageUtils, "ensure_schema", return_value=tables) as ensure:
            repo = PostgresAssetRepository(asset_type=DocumentLibrary, engine=engine, schema="custom_schema")
        ensure.assert_called_once_with(engine=engine, schema="custom_schema")
        assert repo._collection == "document_libraries"

    def test_init_without_bootstrap_touches_no_database(self, engine):
        repo = PostgresAssetRepository(asset_type=DocumentSet, engine=engine, ensure_schema=False)
        assert repo._collection == "document_sets"
        engine.begin.assert_not_called()
        engine.connect.assert_not_called()


class TestSave:
    def test_save_inserts_with_on_conflict_do_nothing(self, repo, connection):
        connection.execute.return_value = _result(first=("id",))
        asset = DocumentSet(name="alpha")

        assert repo.save(asset=asset) is asset

        statement = connection.execute.call_args.args[0]
        sql = _compiled(statement=statement)
        assert "INSERT INTO docpipe_assets.asset_records" in sql
        assert "ON CONFLICT DO NOTHING" in sql
        assert "RETURNING" in sql
        assert statement.compile().params["asset_created_at"] == asset.created_at

    def test_save_validates_before_touching_database(self, repo, engine):
        with pytest.raises(AssetInvalidDataException):
            repo.save(asset=DocumentSet(name="9 starts with digit"))
        engine.begin.assert_not_called()

    def test_save_requires_asset_id(self, repo, engine):
        asset = DocumentSet(name="alpha")
        asset.asset_id = ""
        with pytest.raises(AssetInvalidDataException, match="asset_id"):
            repo.save(asset=asset)
        engine.begin.assert_not_called()

    def test_save_conflict_on_id(self, repo, connection):
        connection.execute.side_effect = [_result(first=None), _result(scalar=True)]
        with pytest.raises(AssetAlreadyExistsException, match="with ID") as exc_info:
            repo.save(asset=DocumentSet(name="alpha"))
        assert exc_info.value.status_code == 409

    def test_save_conflict_on_name(self, repo, connection):
        connection.execute.side_effect = [_result(first=None), _result(scalar=False)]
        with pytest.raises(AssetAlreadyExistsException, match="with name 'alpha'") as exc_info:
            repo.save(asset=DocumentSet(name="alpha"))
        assert exc_info.value.asset_name == "alpha"

    def test_save_wraps_driver_errors(self, repo, engine):
        engine.begin.side_effect = OperationalError("connect", {}, Exception("down"))
        with pytest.raises(DocpipeException, match="Failed to save DocumentSet") as exc_info:
            repo.save(asset=DocumentSet(name="alpha"))
        assert exc_info.value.status_code == 500


class TestFind:
    def test_find_by_id_returns_asset(self, repo, connection):
        stored = DocumentSet(name="alpha")
        connection.execute.return_value = _result(scalar_one_or_none=stored.to_dict())
        found = repo.find_by_id(asset_id=stored.asset_id)
        assert isinstance(found, DocumentSet)
        assert found.to_dict() == stored.to_dict()

    def test_find_by_id_missing(self, repo, connection):
        connection.execute.return_value = _result(scalar_one_or_none=None)
        assert repo.find_by_id(asset_id="nope") is None

    def test_find_by_name_filters_on_collection_and_name(self, repo, connection):
        connection.execute.return_value = _result(scalar_one_or_none=None)
        assert repo.find_by_name(name="alpha") is None
        statement = connection.execute.call_args.args[0]
        params = statement.compile(dialect=postgresql.dialect()).params
        assert params == {"collection_1": "document_sets", "name_1": "alpha"}

    def test_find_errors_are_wrapped(self, repo, engine):
        engine.connect.side_effect = OperationalError("select", {}, Exception("down"))
        with pytest.raises(DocpipeException, match="Failed to retrieve"):
            repo.find_by_id(asset_id="x")
        with pytest.raises(DocpipeException, match="Failed to list"):
            repo.find_all()
        with pytest.raises(DocpipeException, match="existence"):
            repo.exists(asset_id="x")

    def test_find_all_sorts_newest_first_in_the_database(self, repo, connection):
        rows = [DocumentSet(name="new").to_dict(), DocumentSet(name="old").to_dict()]
        connection.execute.return_value = _result(scalars_all=rows)

        assert [a.name for a in repo.find_all()] == ["new", "old"]

        sql = _compiled(statement=connection.execute.call_args.args[0])
        assert sql.endswith(
            "WHERE docpipe_assets.asset_records.collection = %(collection_1)s "
            "ORDER BY docpipe_assets.asset_records.asset_created_at DESC NULLS LAST, "
            "docpipe_assets.asset_records.created_at, docpipe_assets.asset_records.asset_id"
        )

    @pytest.mark.parametrize(
        ("limit", "offset", "clause"),
        [
            (2, None, " LIMIT %(param_1)s"),
            (None, 3, " LIMIT ALL OFFSET %(param_1)s"),
            (2, 3, " LIMIT %(param_1)s OFFSET %(param_2)s"),
            (None, 0, "asset_records.asset_id"),
        ],
    )
    def test_list_all_paginates_in_the_database(self, repo, connection, limit, offset, clause):
        connection.execute.return_value = _result(scalars_all=[])

        assert repo.list_all(limit=limit, offset=offset) == []

        statement = connection.execute.call_args.args[0]
        assert _compiled(statement=statement).endswith(clause)
        params = statement.compile().params
        assert [v for k, v in params.items() if k.startswith("param_")] == [v for v in (limit, offset) if v]

    def test_exists(self, repo, connection):
        connection.execute.return_value = _result(scalar=True)
        assert repo.exists(asset_id="x") is True
        connection.execute.return_value = _result(scalar=False)
        assert repo.exists(asset_id="x") is False


class TestUpdate:
    def test_update_missing_asset_raises_not_found_without_touching_timestamp(self, repo, connection):
        asset = DocumentSet(name="alpha")
        before = asset.updated_at
        connection.execute.return_value = _result(first=None)

        with pytest.raises(AssetNotFoundException):
            repo.update(asset=asset)
        assert asset.updated_at == before
        assert "FOR UPDATE" in _compiled(statement=connection.execute.call_args.args[0])

    def test_update_name_taken_by_other(self, repo, connection):
        connection.execute.side_effect = [_result(first=("id",)), _result(scalar=True)]
        with pytest.raises(AssetInvalidDataException, match="already exists"):
            repo.update(asset=DocumentSet(name="alpha"))

    def test_update_success_writes_row(self, repo, connection):
        connection.execute.side_effect = [_result(first=("id",)), _result(scalar=False), _result()]
        asset = DocumentSet(name="alpha")
        before = asset.updated_at

        assert repo.update(asset=asset) is asset

        assert asset.updated_at >= before
        statement = connection.execute.call_args_list[-1].args[0]
        sql = _compiled(statement=statement)
        assert sql.startswith("UPDATE docpipe_assets.asset_records SET name=")
        assert statement.compile().params["asset_created_at"] == asset.created_at

    def test_update_unique_violation_race_maps_to_invalid_data(self, repo, connection):
        connection.execute.side_effect = [_result(first=("id",)), _result(scalar=False), _unique_violation()]
        with pytest.raises(AssetInvalidDataException, match="already exists"):
            repo.update(asset=DocumentSet(name="alpha"))

    def test_update_other_integrity_error_is_internal_error(self, repo, connection):
        other = _integrity_error(pgcode="23502")
        connection.execute.side_effect = [_result(first=("id",)), _result(scalar=False), other]
        with pytest.raises(DocpipeException, match="Failed to update") as exc_info:
            repo.update(asset=DocumentSet(name="alpha"))
        assert exc_info.value.status_code == 500

    def test_partial_update_applies_known_fields_only(self, repo):
        asset = DocumentSet(name="alpha")
        with patch.object(repo, "update", side_effect=lambda *, asset: asset) as update:
            result = repo.partial_update(asset, {"description": "patched", "unknown": 1})
        assert result.description == "patched"
        assert not hasattr(result, "unknown")
        update.assert_called_once()


class TestDelete:
    def test_delete_true_and_false(self, repo, connection):
        connection.execute.return_value = _result(first=("x",))
        assert repo.delete(asset_id="x") is True
        connection.execute.return_value = _result(first=None)
        assert repo.delete(asset_id="x") is False

    def test_delete_wraps_errors(self, repo, engine):
        engine.begin.side_effect = OperationalError("delete", {}, Exception("down"))
        with pytest.raises(DocpipeException, match="Failed to delete"):
            repo.delete(asset_id="x")

    def test_bulk_delete_reports_per_id_results_in_request_order(self, repo, connection):
        connection.execute.return_value = _result(scalars_all=["b", "a"])

        result = repo.bulk_delete(asset_ids=["a", "missing", "b", "a"])

        assert result == {
            "total_requested": 4,
            "total_deleted": 2,
            "total_failed": 2,
            "deleted": ["a", "b"],
            "failed": [
                {"asset_id": "missing", "error": "DocumentSet not found"},
                {"asset_id": "a", "error": "DocumentSet not found"},
            ],
        }
        params = connection.execute.call_args.args[0].compile(dialect=postgresql.dialect()).params
        assert params["asset_id_1"] == ["a", "missing", "b"]

    def test_bulk_delete_empty_list_skips_database(self, repo, engine):
        assert repo.bulk_delete(asset_ids=[])["total_requested"] == 0
        engine.begin.assert_not_called()

    def test_bulk_delete_database_failure_marks_all_failed(self, repo, engine):
        engine.begin.side_effect = OperationalError("delete", {}, Exception("down"))
        result = repo.bulk_delete(asset_ids=["a", "b"])
        assert result["total_deleted"] == 0
        assert result["total_failed"] == 2
        assert [f["asset_id"] for f in result["failed"]] == ["a", "b"]


class TestHealthCheck:
    def test_healthy(self, repo, connection):
        connection.execute.return_value = _result(scalar=True)
        health = repo.health_check()
        assert health["status"] == "healthy"
        assert health["details"]["collection_exists"] is True
        assert health["details"]["database"] == "docpipe@db.example:5432/docpipe"
        assert "s3cret" not in str(health)

    def test_unhealthy(self, repo, engine):
        engine.connect.side_effect = OperationalError("select", {}, Exception("down"))
        health = repo.health_check()
        assert health["status"] == "unhealthy"
        assert "error" in health["details"]


class TestFromConfig:
    def test_invalid_config_raises_repository_configuration_exception(self):
        with pytest.raises(RepositoryConfigurationException, match="Invalid config for DocumentSet"):
            PostgresAssetRepository.from_config(asset_type=DocumentSet, config={"postgres": ["nope"]})

    def test_missing_password_raises_repository_configuration_exception(self):
        with pytest.raises(RepositoryConfigurationException, match="DocumentSet repository"):
            PostgresAssetRepository.from_config(asset_type=DocumentSet, config={"database_path": "x.duckdb"})

    def test_builds_repository_with_cached_engine_and_schema(self, engine):
        config = {
            "database_path": "ignored",
            "postgres": {"password": "p", "schema": "tenant_a"},
        }  # pragma: allowlist secret
        with (
            patch.object(PostgresStorageUtils, "get_engine", return_value=engine) as get_engine,
            patch.object(
                PostgresStorageUtils, "ensure_schema", return_value=PostgresStorageUtils.get_tables(schema="tenant_a")
            ) as ensure,
        ):
            repo = PostgresAssetRepository.from_config(asset_type=DocumentLibrary, config=config)

        assert isinstance(repo, PostgresAssetRepository)
        get_engine.assert_called_once_with(config=config, owner="DocumentLibrary repository")
        ensure.assert_called_once_with(engine=engine, schema="tenant_a")


# ---------------------------------------------------------------------------
# RepositoryFactory integration
# ---------------------------------------------------------------------------


class TestRepositoryFactoryPostgres:
    def test_postgres_is_registered(self):
        available = RepositoryFactory.get_available_repository_types()
        assert available[RepositoryType.POSTGRES] is PostgresAssetRepository
        assert "postgres" in RepositoryFactory._get_valid_types()

    def test_missing_password_surfaces_as_repository_configuration_exception(self):
        with pytest.raises(RepositoryConfigurationException, match="DOCPIPE_POSTGRES_PASSWORD"):
            RepositoryFactory.create_repository(asset_type=DocumentSet, adapter_name="postgres")

    def test_env_var_selects_postgres(self, monkeypatch):
        monkeypatch.setenv("DOCUMENTSET_REPOSITORY_TYPE", "POSTGRES")
        sentinel = MagicMock(spec=PostgresAssetRepository)
        with patch.object(PostgresAssetRepository, "from_config", return_value=sentinel) as from_config:
            repo = RepositoryFactory.create_repository(asset_type=DocumentSet)
        assert repo is sentinel
        assert from_config.call_args.kwargs["asset_type"] is DocumentSet

    def test_connection_failure_is_wrapped(self):
        with patch.object(PostgresStorageUtils, "get_engine", side_effect=RuntimeError("connection refused")):
            with pytest.raises(RepositoryConfigurationException, match="connection refused") as exc_info:
                RepositoryFactory.create_repository(
                    asset_type=DocumentSet,
                    adapter_name="postgres",
                    config_override={"postgres": {"password": "p"}},  # pragma: allowlist secret
                )
        assert exc_info.value.repository_type == "postgres"
