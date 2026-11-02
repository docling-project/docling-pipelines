"""Unit tests for PostgresAttachmentRepository (engine mocked, no database needed).

Coverage:
- Registration with AttachmentRepositoryFactory under "postgres"
- Factory create(): config validation, missing password, unexpected-error wrapping
- save() upsert statement and error wrapping
- get() / delete() / exists() result mapping and error wrapping
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from docpipe.core.assets.common.adapters.repositories.postgres_attachment_repository import (
    PostgresAttachmentRepository,
)
from docpipe.core.assets.common.adapters.repositories.postgres_storage_utils import PostgresStorageUtils
from docpipe.core.assets.common.domain.models.attachment_ref import AttachmentRef
from docpipe.core.assets.common.factories.attachment_repository_factory import AttachmentRepositoryFactory
from docpipe.exceptions.docpipe_exceptions import DocpipeException, RepositoryConfigurationException
from docpipe.exceptions.error_codes import ErrorCode


@pytest.fixture(autouse=True)
def _no_postgres_env(monkeypatch):
    monkeypatch.delenv("DOCPIPE_POSTGRES_PASSWORD", raising=False)


@pytest.fixture
def connection():
    return MagicMock(name="connection")


@pytest.fixture
def engine(connection):
    engine = MagicMock(name="engine")
    engine.begin.return_value.__enter__.return_value = connection
    engine.connect.return_value.__enter__.return_value = connection
    return engine


@pytest.fixture
def repo(engine):
    return PostgresAttachmentRepository(engine=engine, ensure_schema=False)


@pytest.fixture
def sample_ref():
    return AttachmentRef(backend_type="duckdb", name="tbl", details={"table_name": "tbl"}, attachment_id="a1")


class TestRegistration:
    def test_registered_under_postgres(self):
        info = AttachmentRepositoryFactory.get_adapter_info(adapter_name="postgres")
        assert info == {"name": "postgres", "display_name": "PostgreSQL", "class": "PostgresAttachmentRepository"}

    def test_factory_rejects_invalid_config(self):
        with pytest.raises(DocpipeException, match="Invalid configuration for adapter 'postgres'") as exc_info:
            AttachmentRepositoryFactory.create(adapter_name="postgres", config={"postgres": "not-a-mapping"})
        assert exc_info.value.status_code == 400

    def test_factory_missing_password_raises_configuration_error(self):
        with pytest.raises(RepositoryConfigurationException, match="attachment repository"):
            AttachmentRepositoryFactory.create(adapter_name="postgres", config={"database_path": "x.duckdb"})

    def test_create_wraps_unexpected_errors(self):
        with patch.object(PostgresStorageUtils, "get_engine", side_effect=RuntimeError("boom")):
            with pytest.raises(DocpipeException, match="boom") as exc_info:
                PostgresAttachmentRepository.create(config={"postgres": {"password": "p"}})  # pragma: allowlist secret
        assert exc_info.value.status_code == 500
        assert exc_info.value.error_code == ErrorCode.DOCUMENT_SET_REPOSITORY_ERROR

    def test_create_uses_configured_schema(self, engine):
        tables = PostgresStorageUtils.get_tables(schema="tenant_b")
        with (
            patch.object(PostgresStorageUtils, "get_engine", return_value=engine),
            patch.object(PostgresStorageUtils, "ensure_schema", return_value=tables) as ensure,
        ):
            repo = PostgresAttachmentRepository.create(config={"postgres": {"schema": "tenant_b"}})
        assert isinstance(repo, PostgresAttachmentRepository)
        ensure.assert_called_once_with(engine=engine, schema="tenant_b")


class TestOperations:
    def test_save_is_an_upsert(self, repo, connection, sample_ref):
        repo.save(asset_id="asset-1", data=sample_ref)

        statement = connection.execute.call_args.args[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert "INSERT INTO docpipe_assets.asset_attachments" in sql
        assert "ON CONFLICT (collection, asset_id) DO UPDATE" in sql

    def test_save_wraps_errors(self, repo, engine, sample_ref):
        engine.begin.side_effect = OperationalError("insert", {}, Exception("down"))
        with pytest.raises(DocpipeException, match="Failed to save attachment ref") as exc_info:
            repo.save(asset_id="asset-1", data=sample_ref)
        assert exc_info.value.error_code == ErrorCode.DOCUMENT_SET_REPOSITORY_ERROR

    def test_get_maps_payload(self, repo, connection, sample_ref):
        connection.execute.return_value.scalar_one_or_none.return_value = sample_ref.to_dict()
        assert repo.get(asset_id="asset-1") == sample_ref
        connection.execute.return_value.scalar_one_or_none.return_value = None
        assert repo.get(asset_id="asset-1") is None

    def test_delete_and_exists(self, repo, connection):
        connection.execute.return_value.first.return_value = ("asset-1",)
        assert repo.delete(asset_id="asset-1") is True
        connection.execute.return_value.first.return_value = None
        assert repo.delete(asset_id="asset-1") is False
        connection.execute.return_value.scalar.return_value = True
        assert repo.exists(asset_id="asset-1") is True

    @pytest.mark.parametrize("method", ["get", "delete", "exists"])
    def test_read_errors_are_wrapped(self, repo, engine, method):
        engine.begin.side_effect = OperationalError("x", {}, Exception("down"))
        engine.connect.side_effect = OperationalError("x", {}, Exception("down"))
        with pytest.raises(DocpipeException, match="attachment ref") as exc_info:
            getattr(repo, method)(asset_id="asset-1")
        assert exc_info.value.status_code == 500
