# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Audit records written by the custom operator routes (real service, in-memory capture of ``docpipe.audit``)."""

import hashlib
import io
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Generator

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.auth.jwt_handler import JWTConfig, create_access_token
from docpipe.api.auth.models import User
from docpipe.api.dependencies import get_custom_operator_service
from docpipe.api.middleware.error_handler import (
    docpipe_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from docpipe.api.routes.custom_operators import MAX_OPERATOR_FILE_BYTES, custom_operators_router
from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.core.custom_operators.file_store import LocalFileStore
from docpipe.core.custom_operators.service import CustomOperatorService
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage
from docpipe.utils.infrastructure.audit import AUDIT_LOGGER_NAME, reset_audit_logger

_JWT_SECRET = "unit-test-secret-key-with-at-least-32-chars"  # pragma: allowlist secret

OPERATOR_CODE = b"""
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
import pyarrow as pa

class AuditedOperator(AbstractOperator):
    short_name = "audited_op"
    category = OperatorCategory.Quality
    owner = "custom"

    def transform(self, table: pa.Table):
        return [table], {}

    @staticmethod
    def get_metadata():
        return {"short_name": "audited_op"}
"""
OPERATOR_SHA256 = hashlib.sha256(OPERATOR_CODE).hexdigest()
ALL_FIELDS = {"timestamp", "caller", "operator_id", "short_name", "action", "script_sha256", "outcome"}


class _Capture(logging.Handler):
    """Collect every record that reaches the audit logger; each message must be one JSON object."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def refresh(self) -> list[dict[str, Any]]:
        """Return the records captured so far, parsed."""
        return [json.loads(m) for m in self.messages]


@pytest.fixture
def audit_records() -> Generator[_Capture, None, None]:
    """Capture the ``docpipe.audit`` logger output."""
    reset_audit_logger()
    capture = _Capture()
    logging.getLogger(AUDIT_LOGGER_NAME).addHandler(capture)
    yield capture
    logging.getLogger(AUDIT_LOGGER_NAME).removeHandler(capture)
    reset_audit_logger()


@pytest.fixture(autouse=True)
def _enable_custom_operators(*, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EnvironmentVariables.DOCPIPE_ENABLE_CUSTOM_OPERATORS, "true")
    monkeypatch.setattr(CustomOperatorService, "_refresh_operator_factories", lambda self: None)


@pytest.fixture
def service(*, tmp_path: Path) -> CustomOperatorService:
    return CustomOperatorService(
        file_store=LocalFileStore(base_dir=tmp_path / "custom_operators"),
        metadata_storage=KeyValueFileSystemStorage(base_dir=tmp_path),
    )


def _build_app(*, service: CustomOperatorService) -> FastAPI:
    app = FastAPI()
    app.include_router(custom_operators_router)
    app.dependency_overrides[get_custom_operator_service] = lambda: service
    app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    return app


@pytest.fixture
def client(*, service: CustomOperatorService) -> TestClient:
    app = _build_app(service=service)
    app.dependency_overrides[get_current_user] = lambda: User(username="alice", email="alice@example.com")
    return TestClient(app, raise_server_exceptions=False)


def _create(*, client: TestClient, code: bytes = OPERATOR_CODE, filename: str = "audited_op.py") -> Any:
    return client.post(
        "/custom_operators",
        data={"name": "Audited Op", "description": "desc"},
        files={"operator_file": (filename, io.BytesIO(code), "text/x-python")},
    )


def _only(*, records: Any) -> dict[str, Any]:
    refreshed = records.refresh()
    assert len(refreshed) == 1, refreshed
    return refreshed[0]


class TestAuditOnSuccess:
    """One ``success`` record per create, update, and delete, carrying every required field."""

    def test_create_writes_success_record(self, *, client: TestClient, audit_records: Any) -> None:
        response = _create(client=client)

        assert response.status_code == 201
        record = _only(records=audit_records)
        assert set(record) == ALL_FIELDS
        assert record["outcome"] == "success"
        assert record["action"] == "create"
        assert record["caller"] == "alice"
        assert record["operator_id"] == response.json()["operator_id"]
        assert record["short_name"] == "audited_op"
        assert record["script_sha256"] == OPERATOR_SHA256
        assert record["timestamp"]

    def test_file_replacement_records_digest_of_new_script(self, *, client: TestClient, audit_records: Any) -> None:
        operator_id = _create(client=client).json()["operator_id"]
        audit_records.refresh()
        new_code = OPERATOR_CODE + b"\n# v2\n"

        response = client.patch(
            f"/custom_operators/{operator_id}",
            files={"operator_file": ("audited_op.py", io.BytesIO(new_code), "text/x-python")},
        )

        assert response.status_code == 200
        record = audit_records.refresh()[-1]
        assert (record["action"], record["outcome"], record["caller"]) == ("update", "success", "alice")
        assert record["operator_id"] == operator_id
        assert record["short_name"] == "audited_op"
        assert record["script_sha256"] == hashlib.sha256(new_code).hexdigest()

    def test_metadata_only_update_records_digest_of_stored_script(
        self, *, client: TestClient, audit_records: Any
    ) -> None:
        operator_id = _create(client=client).json()["operator_id"]

        response = client.patch(f"/custom_operators/{operator_id}", data={"name": "Renamed"})

        assert response.status_code == 200
        record = audit_records.refresh()[-1]
        assert (record["action"], record["outcome"]) == ("update", "success")
        assert record["script_sha256"] == OPERATOR_SHA256

    def test_delete_writes_success_record(self, *, client: TestClient, audit_records: Any) -> None:
        operator_id = _create(client=client).json()["operator_id"]

        response = client.delete(f"/custom_operators/{operator_id}")

        assert response.status_code == 200
        records = audit_records.refresh()
        assert len(records) == 2
        record = records[-1]
        assert set(record) == ALL_FIELDS
        assert (record["action"], record["outcome"], record["caller"]) == ("delete", "success", "alice")
        assert record["operator_id"] == operator_id
        assert record["short_name"] == "audited_op"
        assert record["script_sha256"] == OPERATOR_SHA256

    def test_read_routes_are_not_audited(self, *, client: TestClient, audit_records: Any) -> None:
        operator_id = _create(client=client).json()["operator_id"]

        client.get("/custom_operators")
        client.get(f"/custom_operators/{operator_id}")
        client.get("/custom_operators/directory_tree")

        assert len(audit_records.refresh()) == 1


class TestAuditOnRejection:
    """One ``rejected`` record per refused attempt, written from either the route or the service."""

    def test_validation_failure_is_rejected_with_digest(self, *, client: TestClient, audit_records: Any) -> None:
        code = b"x = 1\n"

        response = _create(client=client, code=code)

        assert response.status_code == 400
        record = _only(records=audit_records)
        assert (record["action"], record["outcome"], record["caller"]) == ("create", "rejected", "alice")
        assert record["script_sha256"] == hashlib.sha256(code).hexdigest()
        assert record["operator_id"] is None
        assert record["reason"] == "custom_operator_invalid_data"

    def test_duplicate_short_name_is_rejected(self, *, client: TestClient, audit_records: Any) -> None:
        first_id = _create(client=client).json()["operator_id"]

        response = _create(client=client)

        assert response.status_code == 409
        record = audit_records.refresh()[-1]
        assert (record["action"], record["outcome"]) == ("create", "rejected")
        assert record["short_name"] == "audited_op"
        assert record["operator_id"] == first_id
        assert record["reason"] == "custom_operator_already_exists"

    def test_disabled_custom_operators_are_rejected(
        self, *, client: TestClient, audit_records: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(EnvironmentVariables.DOCPIPE_ENABLE_CUSTOM_OPERATORS)

        response = _create(client=client)

        assert response.status_code == 409
        assert response.json()["errors"][0]["code"] == "custom_operators_disabled"
        record = _only(records=audit_records)
        assert (record["outcome"], record["reason"]) == ("rejected", "custom_operators_disabled")
        assert record["script_sha256"] == OPERATOR_SHA256

    def test_invalid_extension_is_rejected_in_the_route(self, *, client: TestClient, audit_records: Any) -> None:
        response = _create(client=client, filename="audited_op.txt")

        assert response.status_code == 400
        record = _only(records=audit_records)
        assert (record["action"], record["outcome"], record["reason"]) == ("create", "rejected", "invalid_extension")
        assert record["caller"] == "alice"

    def test_oversized_file_is_rejected_in_the_route(self, *, client: TestClient, audit_records: Any) -> None:
        code = b"#" * (MAX_OPERATOR_FILE_BYTES + 1)

        response = _create(client=client, code=code)

        assert response.status_code == 413
        record = _only(records=audit_records)
        assert (record["outcome"], record["reason"]) == ("rejected", "file_too_large")
        assert record["script_sha256"] == hashlib.sha256(code).hexdigest()

    def test_update_with_changed_short_name_is_rejected(self, *, client: TestClient, audit_records: Any) -> None:
        operator_id = _create(client=client).json()["operator_id"]
        other = OPERATOR_CODE.replace(b"audited_op", b"other_op")

        response = client.patch(
            f"/custom_operators/{operator_id}",
            files={"operator_file": ("other_op.py", io.BytesIO(other), "text/x-python")},
        )

        assert response.status_code == 400
        record = audit_records.refresh()[-1]
        assert (record["action"], record["outcome"]) == ("update", "rejected")
        assert record["operator_id"] == operator_id
        assert record["short_name"] == "audited_op"
        assert record["script_sha256"] == hashlib.sha256(other).hexdigest()

    def test_update_unknown_operator_is_rejected(self, *, client: TestClient, audit_records: Any) -> None:
        operator_id = str(uuid.uuid4())

        response = client.patch(f"/custom_operators/{operator_id}", data={"name": "Renamed"})

        assert response.status_code == 404
        record = _only(records=audit_records)
        assert (record["action"], record["outcome"], record["operator_id"]) == ("update", "rejected", operator_id)

    def test_delete_unknown_operator_is_rejected(self, *, client: TestClient, audit_records: Any) -> None:
        operator_id = str(uuid.uuid4())

        response = client.delete(f"/custom_operators/{operator_id}")

        assert response.status_code == 404
        record = _only(records=audit_records)
        assert (record["action"], record["outcome"], record["operator_id"]) == ("delete", "rejected", operator_id)
        assert record["reason"] == "custom_operator_not_found"

    def test_forbidden_error_is_rejected_with_403(
        self, *, client: TestClient, service: CustomOperatorService, audit_records: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 403 raised below the route (here a PermissionError from storage) is audited as rejected."""
        operator_id = _create(client=client).json()["operator_id"]
        audit_records.refresh()

        def _denied(*, operator_id: str) -> None:
            raise PermissionError("denied")

        monkeypatch.setattr(service.file_store, "delete", _denied)

        response = client.delete(f"/custom_operators/{operator_id}")

        assert response.status_code == 403
        record = audit_records.refresh()[-1]
        assert (record["action"], record["outcome"], record["reason"]) == ("delete", "rejected", "PermissionError")

    def test_rejection_never_contains_exception_message(self, *, client: TestClient, audit_records: Any) -> None:
        _create(client=client, code=b"def broken(:\n")

        text = json.dumps(audit_records.refresh())
        assert "Syntax error" not in text
        assert "broken" not in text


class TestUnauthenticatedRequests:
    """A 401 is raised by the router dependency before the handler, so it is not audited here."""

    def test_missing_token_is_not_audited(
        self, *, service: CustomOperatorService, audit_records: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JWT_SECRET_KEY", _JWT_SECRET)
        unauth = TestClient(_build_app(service=service), raise_server_exceptions=False)

        assert _create(client=unauth).status_code == 401
        assert audit_records.refresh() == []

    def test_caller_comes_from_the_token(
        self, *, service: CustomOperatorService, audit_records: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JWT_SECRET_KEY", _JWT_SECRET)
        token = create_access_token({"username": "bob"}, JWTConfig(jwt_secret_key=_JWT_SECRET))
        authed = TestClient(_build_app(service=service), raise_server_exceptions=False)

        response = authed.post(
            "/custom_operators",
            headers={"Authorization": f"Bearer {token}"},
            data={"name": "Audited Op"},
            files={"operator_file": ("audited_op.py", io.BytesIO(OPERATOR_CODE), "text/x-python")},
        )

        assert response.status_code == 201
        assert _only(records=audit_records)["caller"] == "bob"
