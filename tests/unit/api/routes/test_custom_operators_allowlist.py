# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Uploader allowlist on the custom operator routes (real service, real error handlers, real HTTP responses)."""

import io
import json
import logging
from pathlib import Path
from typing import Any, Generator

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.auth.models import User
from docpipe.api.dependencies import get_custom_operator_service
from docpipe.api.middleware.error_handler import (
    docpipe_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from docpipe.api.routes.custom_operators import custom_operators_router
from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.core.custom_operators.file_store import LocalFileStore
from docpipe.core.custom_operators.service import CustomOperatorService
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.integrations.secrets.secret_provider import SecretProvider, clear_providers, register_provider
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage
from docpipe.utils.infrastructure.audit import AUDIT_LOGGER_NAME, reset_audit_logger
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader

OPERATOR_CODE = b"""
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
import pyarrow as pa

class ListedOperator(AbstractOperator):
    short_name = "listed_op"
    category = OperatorCategory.Quality
    owner = "custom"

    def transform(self, table: pa.Table):
        return [table], {}

    @staticmethod
    def get_metadata():
        return {"short_name": "listed_op"}
"""
REFUSAL_REASON = "custom_operator_upload_forbidden"


class _Provider(SecretProvider):
    def authenticate(self) -> None:
        pass

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        return "unused"

    def is_available(self) -> bool:
        return True


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def refresh(self) -> list[dict[str, Any]]:
        return [json.loads(m) for m in self.messages]


@pytest.fixture
def audit_records() -> Generator[_Capture, None, None]:
    reset_audit_logger()
    capture = _Capture()
    logging.getLogger(AUDIT_LOGGER_NAME).addHandler(capture)
    yield capture
    logging.getLogger(AUDIT_LOGGER_NAME).removeHandler(capture)
    reset_audit_logger()


@pytest.fixture(autouse=True)
def _environment(*, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    clear_providers()
    monkeypatch.setenv(EnvironmentVariables.DOCPIPE_ENABLE_CUSTOM_OPERATORS, "true")
    monkeypatch.setattr(CustomOperatorService, "_refresh_operator_factories", lambda self: None)
    yield
    clear_providers()


@pytest.fixture
def storage_root(*, tmp_path: Path) -> Path:
    return tmp_path / "custom_operators"


@pytest.fixture
def service(*, tmp_path: Path, storage_root: Path) -> CustomOperatorService:
    return CustomOperatorService(
        file_store=LocalFileStore(base_dir=storage_root),
        metadata_storage=KeyValueFileSystemStorage(base_dir=tmp_path),
    )


def _client(*, service: CustomOperatorService, username: str) -> TestClient:
    app = FastAPI()
    app.include_router(custom_operators_router)
    app.dependency_overrides[get_custom_operator_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: User(username=username, email=f"{username}@example.com")
    app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    return TestClient(app, raise_server_exceptions=False)


def _register_provider(*, allowed_uploaders: Any = "unset") -> None:
    """Register a provider and set the allowlist AFTER it (clear_providers resets the config loader)."""
    register_provider(name="hashicorp", provider=_Provider())
    config: dict[str, Any] = {}
    if allowed_uploaders != "unset":
        config["custom_operators"] = {"allowed_uploaders": allowed_uploaders}
    DocpipeConfigLoader._config = config


def _create(*, client: TestClient) -> Any:
    return client.post(
        "/custom_operators",
        data={"name": "Listed Op", "description": "desc"},
        files={"operator_file": ("listed_op.py", io.BytesIO(OPERATOR_CODE), "text/x-python")},
    )


def _update_with_file(*, client: TestClient, operator_id: str) -> Any:
    return client.patch(
        f"/custom_operators/{operator_id}",
        data={"name": "Renamed"},
        files={"operator_file": ("listed_op.py", io.BytesIO(OPERATOR_CODE), "text/x-python")},
    )


def _seed_operator(*, service: CustomOperatorService) -> str:
    """Create an operator as an allowed uploader and return its id."""
    _register_provider(allowed_uploaders=["admin"])
    created = _client(service=service, username="admin")
    response = _create(client=created)
    assert response.status_code == 201, response.text
    return str(response.json()["operator_id"])


def _stored_files(*, storage_root: Path) -> list[Path]:
    return [p for p in storage_root.rglob("*") if p.is_file()] if storage_root.exists() else []


class TestProviderRegistered:
    def test_listed_uploader_can_create(self, *, service: CustomOperatorService) -> None:
        _register_provider(allowed_uploaders=["alice", "bob"])

        response = _create(client=_client(service=service, username="alice"))

        assert response.status_code == 201

    def test_unlisted_user_gets_403_and_nothing_is_stored(
        self, *, service: CustomOperatorService, storage_root: Path
    ) -> None:
        _register_provider(allowed_uploaders=["bob"])

        response = _create(client=_client(service=service, username="alice"))

        assert response.status_code == 403
        assert response.json()["errors"][0]["code"] == REFUSAL_REASON
        assert _stored_files(storage_root=storage_root) == []
        assert service.list_operators() == []

    @pytest.mark.parametrize("allowed", [[], None, "alice", {"alice": True}, [["alice"]], 7])
    def test_empty_unset_or_malformed_list_permits_nobody(
        self, *, service: CustomOperatorService, allowed: Any
    ) -> None:
        _register_provider(allowed_uploaders=allowed)

        response = _create(client=_client(service=service, username="alice"))

        assert response.status_code == 403

    def test_missing_section_permits_nobody(self, *, service: CustomOperatorService) -> None:
        _register_provider()

        assert _create(client=_client(service=service, username="alice")).status_code == 403

    def test_username_match_is_exact(self, *, service: CustomOperatorService) -> None:
        _register_provider(allowed_uploaders=["Alice", "alice "])

        assert _create(client=_client(service=service, username="alice")).status_code == 403

    def test_unlisted_user_cannot_update_file_or_metadata(
        self, *, service: CustomOperatorService, storage_root: Path
    ) -> None:
        operator_id = _seed_operator(service=service)
        before = {p: p.read_bytes() for p in _stored_files(storage_root=storage_root)}
        outsider = _client(service=service, username="mallory")

        file_response = _update_with_file(client=outsider, operator_id=operator_id)
        metadata_response = outsider.patch(f"/custom_operators/{operator_id}", data={"name": "Hijacked"})

        assert file_response.status_code == 403
        assert metadata_response.status_code == 403
        assert {p: p.read_bytes() for p in _stored_files(storage_root=storage_root)} == before
        assert service.get_operator(operator_id=operator_id).name == "Listed Op"

    def test_unlisted_user_cannot_delete(self, *, service: CustomOperatorService) -> None:
        operator_id = _seed_operator(service=service)

        response = _client(service=service, username="mallory").delete(f"/custom_operators/{operator_id}")

        assert response.status_code == 403
        assert service.get_operator(operator_id=operator_id).id == operator_id

    def test_listed_uploader_can_update_and_delete(self, *, service: CustomOperatorService) -> None:
        operator_id = _seed_operator(service=service)
        admin = _client(service=service, username="admin")

        assert _update_with_file(client=admin, operator_id=operator_id).status_code == 200
        assert admin.delete(f"/custom_operators/{operator_id}").status_code == 200

    def test_read_routes_stay_open_to_any_authenticated_user(self, *, service: CustomOperatorService) -> None:
        operator_id = _seed_operator(service=service)
        outsider = _client(service=service, username="mallory")

        assert outsider.get("/custom_operators").status_code == 200
        assert outsider.get(f"/custom_operators/{operator_id}").status_code == 200


class TestRefusalOrdering:
    def test_disabled_is_reported_before_the_allowlist(
        self, *, service: CustomOperatorService, audit_records: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _register_provider(allowed_uploaders=[])
        monkeypatch.delenv(EnvironmentVariables.DOCPIPE_ENABLE_CUSTOM_OPERATORS)

        response = _create(client=_client(service=service, username="alice"))

        # The HTTP rendering of this error needs the separate ErrorCode Literal fix (PR #586), so assert the audit reason.
        assert response.status_code != 403
        records = audit_records.refresh()
        assert [r["reason"] for r in records] == ["custom_operators_disabled"]


class TestNoProvider:
    def test_any_authenticated_user_can_write_without_an_allowlist(self, *, service: CustomOperatorService) -> None:
        DocpipeConfigLoader._config = {}
        client = _client(service=service, username="alice")

        created = _create(client=client)
        operator_id = created.json()["operator_id"]

        assert created.status_code == 201
        assert client.patch(f"/custom_operators/{operator_id}", data={"name": "Renamed"}).status_code == 200
        assert client.delete(f"/custom_operators/{operator_id}").status_code == 200

    def test_the_allowlist_is_ignored_without_a_provider(self, *, service: CustomOperatorService) -> None:
        DocpipeConfigLoader._config = {"custom_operators": {"allowed_uploaders": ["bob"]}}

        assert _create(client=_client(service=service, username="alice")).status_code == 201


class TestRefusalIsAudited:
    def test_one_rejected_record_with_a_fixed_reason_and_no_allowlist(
        self, *, service: CustomOperatorService, audit_records: Any
    ) -> None:
        _register_provider(allowed_uploaders=["secret-admin-name"])

        response = _create(client=_client(service=service, username="alice"))

        assert response.status_code == 403
        records = audit_records.refresh()
        assert len(records) == 1
        assert (records[0]["caller"], records[0]["action"], records[0]["outcome"]) == ("alice", "create", "rejected")
        assert records[0]["reason"] == REFUSAL_REASON
        assert "secret-admin-name" not in json.dumps(records)
        assert "secret-admin-name" not in response.text

    def test_refused_update_and_delete_are_each_audited_once(
        self, *, service: CustomOperatorService, audit_records: Any
    ) -> None:
        operator_id = _seed_operator(service=service)
        audit_records.messages.clear()
        outsider = _client(service=service, username="mallory")

        outsider.patch(f"/custom_operators/{operator_id}", data={"name": "Hijacked"})
        outsider.delete(f"/custom_operators/{operator_id}")

        records = audit_records.refresh()
        assert [(r["caller"], r["action"], r["outcome"], r["reason"]) for r in records] == [
            ("mallory", "update", "rejected", REFUSAL_REASON),
            ("mallory", "delete", "rejected", REFUSAL_REASON),
        ]
