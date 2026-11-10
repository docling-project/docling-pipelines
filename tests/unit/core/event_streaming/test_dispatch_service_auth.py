# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Dispatch authenticates to the job-run API with a short-lived editor token."""

from datetime import UTC, datetime
from typing import Annotated, Any
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.auth.jwt_handler import JWTClaims, JWTConfig, verify_token
from docpipe.api.auth.models import User
from docpipe.api.auth.roles import Role, parse_roles
from docpipe.api.dependencies import get_custom_operator_service, get_job_management_service
from docpipe.api.middleware.error_handler import docpipe_exception_handler
from docpipe.api.routes.custom_operators import custom_operators_router
from docpipe.api.routes.job_runs import job_runs_router
from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.core.event_streaming.dispatch_service import (
    SYSTEM_TOKEN_MAX_MINUTES,
    SYSTEM_USERNAME,
    EventDispatchService,
)
from docpipe.core.event_streaming.models import EventMapping, InputEvent
from docpipe.exceptions.docpipe_exceptions import DocpipeException

SECRET = "s" * 40
BASE_URL = "http://docpipe.test"


def _event() -> InputEvent:
    return InputEvent.model_validate(
        {
            "event_id": "550e8400-e29b-41d4-a716-446655440000",
            "event_timestamp": "2026-10-12T12:00:00Z",
            "routing_key": "invoices",
            "operation": "create",
            "file_reference": "/documents/invoice.pdf",
        }
    )


def _bearer_user(authorization: Annotated[str | None, Header()] = None) -> User:
    """Resolve the user from the bearer token the way the session dependency will."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = verify_token(authorization.removeprefix("Bearer "), JWTConfig())
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    return User(username=payload[JWTClaims.USERNAME], roles=parse_roles(payload.get(JWTClaims.ROLES)))


@pytest.fixture
def api(monkeypatch, auth_enabled):
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv(EnvironmentVariables.DOCPIPE_API_BASE_URL, BASE_URL)
    job_service = MagicMock()
    job_service.create_job_run_from_request.return_value = {
        "job_run_id": "99ecd646-bb8e-494a-a0c5-86b40c1d4f90",
        "status": "Starting",
        "message": "Job run created successfully",
    }
    app = FastAPI()
    app.include_router(job_runs_router, prefix="/api/v1")
    app.include_router(custom_operators_router, prefix="/api/v1")
    app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    app.dependency_overrides[get_current_user] = _bearer_user
    app.dependency_overrides[get_job_management_service] = lambda: job_service
    app.dependency_overrides[get_custom_operator_service] = lambda: MagicMock()
    return TestClient(app, raise_server_exceptions=False), job_service


@pytest.fixture
def dispatch(api, mocker):
    """Run ``EventDispatchService.dispatch`` against the stubbed API, capturing sent headers."""
    client, _ = api
    sent: dict[str, Any] = {}

    def fake_post(url: str, *, json: dict, headers: dict, timeout: float):
        sent["headers"] = headers
        return client.post(url.removeprefix(BASE_URL), json=json, headers=headers)

    mocker.patch("docpipe.core.event_streaming.dispatch_service.httpx.post", side_effect=fake_post)
    mapping_service = MagicMock()
    mapping_service.get_mapping.return_value = EventMapping(
        key="invoices", flow_id="22222222-2222-4222-8222-222222222222"
    )
    service = EventDispatchService(mapping_service=mapping_service)
    return service, sent


def _token(headers: dict[str, str]) -> str:
    assert headers["Authorization"].startswith("Bearer ")
    return headers["Authorization"].removeprefix("Bearer ")


def test_dispatch_sends_editor_token_and_api_accepts_it(dispatch, api):
    service, sent = dispatch

    result = service.dispatch(event=_event())

    assert result["job_run_id"] == "99ecd646-bb8e-494a-a0c5-86b40c1d4f90"
    payload = jwt.decode(_token(sent["headers"]), SECRET, algorithms=["HS256"])
    assert payload[JWTClaims.USERNAME] == SYSTEM_USERNAME
    assert payload[JWTClaims.ROLES] == [Role.EDITOR.value]
    assert sent["headers"]["X-Global-Transaction-Id"] == "550e8400-e29b-41d4-a716-446655440000"


def test_token_lifetime_is_at_most_five_minutes(dispatch):
    service, sent = dispatch

    service.dispatch(event=_event())

    payload = jwt.decode(_token(sent["headers"]), SECRET, algorithms=["HS256"])
    remaining = payload["exp"] - datetime.now(UTC).timestamp()
    assert 0 < remaining <= SYSTEM_TOKEN_MAX_MINUTES * 60


def test_shorter_configured_lifetime_is_kept(dispatch, monkeypatch):
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "2")
    service, sent = dispatch

    service.dispatch(event=_event())

    payload = jwt.decode(_token(sent["headers"]), SECRET, algorithms=["HS256"])
    assert payload["exp"] - datetime.now(UTC).timestamp() <= 2 * 60


def test_dispatch_token_cannot_use_admin_routes(dispatch, api):
    service, sent = dispatch
    service.dispatch(event=_event())
    client, _ = api

    response = client.post("/api/v1/custom_operators", headers={"Authorization": f"Bearer {_token(sent['headers'])}"})

    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "forbidden"


def test_no_authorization_header_when_auth_disabled(monkeypatch, mocker):
    monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "false")
    response = MagicMock()
    response.json.return_value = {"job_run_id": "99ecd646-bb8e-494a-a0c5-86b40c1d4f90"}
    post = mocker.patch("docpipe.core.event_streaming.dispatch_service.httpx.post", return_value=response)
    mapping_service = MagicMock()
    mapping_service.get_mapping.return_value = EventMapping(
        key="invoices", flow_id="22222222-2222-4222-8222-222222222222"
    )

    EventDispatchService(mapping_service=mapping_service).dispatch(event=_event())

    assert "Authorization" not in post.call_args.kwargs["headers"]
