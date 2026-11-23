# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the uploader allowlist in CustomOperatorService."""

from pathlib import Path
from typing import Any, Generator

import pytest

from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.core.custom_operators.file_store import LocalFileStore
from docpipe.core.custom_operators.service import CustomOperatorService
from docpipe.exceptions.docpipe_exceptions import (
    CustomOperatorsDisabledException,
    CustomOperatorUploadForbiddenException,
)
from docpipe.integrations.secrets.secret_provider import (
    SecretProvider,
    clear_providers,
    has_registered_provider,
    register_provider,
)
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader

OPERATOR_CODE = """
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
import pyarrow as pa

class AllowlistOperator(AbstractOperator):
    short_name = "allowlist_op"
    category = OperatorCategory.Quality
    owner = "custom"

    def transform(self, table: pa.Table):
        return [table], {}

    @staticmethod
    def get_metadata():
        return {"short_name": "allowlist_op"}
"""


class _Provider(SecretProvider):
    def authenticate(self) -> None:
        pass

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        return "unused"

    def is_available(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _environment(*, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    clear_providers()
    monkeypatch.setenv(EnvironmentVariables.DOCPIPE_ENABLE_CUSTOM_OPERATORS, "true")
    monkeypatch.setattr(CustomOperatorService, "_refresh_operator_factories", lambda self: None)
    yield
    clear_providers()


@pytest.fixture
def service(*, tmp_path: Path) -> CustomOperatorService:
    return CustomOperatorService(
        file_store=LocalFileStore(base_dir=tmp_path / "custom_operators"),
        metadata_storage=KeyValueFileSystemStorage(base_dir=tmp_path),
    )


@pytest.fixture
def script(*, tmp_path: Path) -> Path:
    path = tmp_path / "allowlist_op.py"
    path.write_text(OPERATOR_CODE, encoding="utf-8")
    return path


def _configure(*, allowed_uploaders: Any = None, with_provider: bool = True) -> None:
    if with_provider:
        register_provider(name="hashicorp", provider=_Provider())
    DocpipeConfigLoader._config = (
        {"custom_operators": {"allowed_uploaders": allowed_uploaders}} if allowed_uploaders is not None else {}
    )


def test_has_registered_provider_tracks_the_registry() -> None:
    assert has_registered_provider() is False
    register_provider(name="hashicorp", provider=_Provider())
    assert has_registered_provider() is True
    clear_providers()
    assert has_registered_provider() is False


class TestCreate:
    def test_unlisted_caller_is_refused_with_403_before_anything_is_stored(
        self, *, service: CustomOperatorService, script: Path, tmp_path: Path
    ) -> None:
        _configure(allowed_uploaders=["bob"])

        with pytest.raises(CustomOperatorUploadForbiddenException) as exc_info:
            service.create_operator(name="Op", description="d", operator_file_path=script, caller="alice")

        assert exc_info.value.status_code == 403
        assert "bob" not in str(exc_info.value)
        assert not (tmp_path / "custom_operators").exists() or not any((tmp_path / "custom_operators").rglob("*"))
        assert service.list_operators() == []

    def test_listed_caller_proceeds(self, *, service: CustomOperatorService, script: Path) -> None:
        _configure(allowed_uploaders=["alice"])

        created = service.create_operator(name="Op", description="d", operator_file_path=script, caller="alice")

        assert created.short_name == "allowlist_op"

    @pytest.mark.parametrize("caller", [None, ""])
    def test_missing_caller_is_refused_when_a_provider_is_registered(
        self, *, service: CustomOperatorService, script: Path, caller: str | None
    ) -> None:
        _configure(allowed_uploaders=["alice", ""])

        with pytest.raises(CustomOperatorUploadForbiddenException):
            service.create_operator(name="Op", description="d", operator_file_path=script, caller=caller)

    @pytest.mark.parametrize("allowed", [[], "alice", {"alice": 1}, 3])
    def test_empty_or_malformed_list_permits_nobody(
        self, *, service: CustomOperatorService, script: Path, allowed: Any
    ) -> None:
        _configure(allowed_uploaders=allowed)

        with pytest.raises(CustomOperatorUploadForbiddenException):
            service.create_operator(name="Op", description="d", operator_file_path=script, caller="alice")

    def test_unset_list_permits_nobody(self, *, service: CustomOperatorService, script: Path) -> None:
        _configure()

        with pytest.raises(CustomOperatorUploadForbiddenException):
            service.create_operator(name="Op", description="d", operator_file_path=script, caller="alice")

    def test_no_provider_permits_any_caller_including_none(
        self, *, service: CustomOperatorService, script: Path
    ) -> None:
        _configure(allowed_uploaders=[], with_provider=False)

        created = service.create_operator(name="Op", description="d", operator_file_path=script, caller=None)

        assert created.id is not None

    def test_disabled_check_runs_before_the_allowlist(
        self, *, service: CustomOperatorService, script: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _configure(allowed_uploaders=[])
        monkeypatch.delenv(EnvironmentVariables.DOCPIPE_ENABLE_CUSTOM_OPERATORS)

        with pytest.raises(CustomOperatorsDisabledException):
            service.create_operator(name="Op", description="d", operator_file_path=script, caller="alice")


class TestUpdateAndDelete:
    @pytest.fixture
    def operator_id(self, *, service: CustomOperatorService, script: Path) -> str:
        _configure(allowed_uploaders=["admin"])
        created = service.create_operator(name="Op", description="d", operator_file_path=script, caller="admin")
        assert created.id is not None
        return created.id

    def test_unlisted_caller_cannot_update_metadata_or_file(
        self, *, service: CustomOperatorService, script: Path, operator_id: str
    ) -> None:
        with pytest.raises(CustomOperatorUploadForbiddenException):
            service.update_operator(operator_id=operator_id, name="Hijacked", caller="mallory")
        with pytest.raises(CustomOperatorUploadForbiddenException):
            service.update_operator(operator_id=operator_id, operator_file_path=script, caller="mallory")

        assert service.get_operator(operator_id=operator_id).name == "Op"

    def test_unlisted_caller_cannot_delete(self, *, service: CustomOperatorService, operator_id: str) -> None:
        with pytest.raises(CustomOperatorUploadForbiddenException):
            service.delete_operator(operator_id=operator_id, caller="mallory")

        assert service.get_operator(operator_id=operator_id).id == operator_id

    def test_listed_caller_can_update_and_delete(
        self, *, service: CustomOperatorService, script: Path, operator_id: str
    ) -> None:
        assert service.update_operator(operator_id=operator_id, name="Renamed", caller="admin").name == "Renamed"
        service.update_operator(operator_id=operator_id, operator_file_path=script, caller="admin")
        service.delete_operator(operator_id=operator_id, caller="admin")

        assert service.list_operators() == []

    def test_allowlist_is_checked_before_the_operator_is_looked_up(self, *, service: CustomOperatorService) -> None:
        """An outsider gets 403 for an unknown id too, so ids cannot be probed."""
        _configure(allowed_uploaders=["admin"])
        unknown = "00000000-0000-4000-8000-000000000000"

        with pytest.raises(CustomOperatorUploadForbiddenException):
            service.delete_operator(operator_id=unknown, caller="mallory")
        with pytest.raises(CustomOperatorUploadForbiddenException):
            service.update_operator(operator_id=unknown, name="x", caller="mallory")
