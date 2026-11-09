# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Integration tests for the CSRF defence on the real ``/api/v1`` router."""

from collections.abc import Generator
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from docpipe.api.auth.config import DEFAULT_COOKIE_NAME
from docpipe.api.auth.jwt_handler import JWTConfig, create_access_token
from docpipe.api.dependencies import get_flow_service
from docpipe.api.main import app
from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.models.actor_context import ActorContext

_JWT_SECRET = "test-secret-key-for-integration-tests"  # pragma: allowlist secret
_FLOW_ID = "12345678-1234-1234-1234-123456789abc"
_FLOW_URL = f"/api/v1/flows/{_FLOW_ID}"


@pytest.fixture
def jwt_config() -> JWTConfig:
    return JWTConfig(jwt_secret_key=_JWT_SECRET)


@pytest.fixture
def flow_service() -> Generator[Mock, None, None]:
    service = Mock(spec=FlowService)
    app.dependency_overrides[get_flow_service] = lambda: service
    yield service
    app.dependency_overrides.clear()


@pytest.fixture
def client(*, auth_enabled, monkeypatch, flow_service) -> TestClient:
    monkeypatch.setenv("JWT_SECRET_KEY", _JWT_SECRET)
    return TestClient(app, raise_server_exceptions=False)


def _actor(username: str) -> ActorContext:
    return ActorContext(username=username, roles=frozenset({"editor"}))


def _token(*, config: JWTConfig, username: str) -> str:
    return create_access_token({"username": username, "roles": ["editor"]}, config)


class TestCsrfOnFlowsRoute:
    def test_cookie_delete_without_header_is_rejected_and_nothing_is_deleted(self, *, client, flow_service, jwt_config):
        client.cookies.set(DEFAULT_COOKIE_NAME, _token(config=jwt_config, username="alice"))

        response = client.delete(_FLOW_URL)

        assert response.status_code == 403
        assert response.json()["errors"][0]["code"] == "forbidden"
        flow_service.delete_flow.assert_not_called()

    def test_cookie_delete_with_header_is_processed(self, *, client, flow_service, jwt_config):
        client.cookies.set(DEFAULT_COOKIE_NAME, _token(config=jwt_config, username="alice"))

        response = client.delete(_FLOW_URL, headers={"X-Requested-With": "XMLHttpRequest"})

        assert response.status_code == 204
        flow_service.delete_flow.assert_called_once_with(_FLOW_ID, actor=_actor("alice"))

    def test_cookie_read_needs_no_header(self, *, client, flow_service, jwt_config):
        flow_service.get_flow.return_value = None
        client.cookies.set(DEFAULT_COOKIE_NAME, _token(config=jwt_config, username="alice"))

        response = client.get(_FLOW_URL)

        assert response.status_code != 403
        assert response.status_code != 401

    def test_bearer_delete_without_header_is_exempt(self, *, client, flow_service, jwt_config):
        token = _token(config=jwt_config, username="alice")

        response = client.delete(_FLOW_URL, headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 204
        flow_service.delete_flow.assert_called_once_with(_FLOW_ID, actor=_actor("alice"))

    def test_bearer_for_one_user_wins_over_cookie_for_another(self, *, client, flow_service, jwt_config):
        client.cookies.set(DEFAULT_COOKIE_NAME, _token(config=jwt_config, username="bob"))
        token = _token(config=jwt_config, username="alice")

        response = client.delete(_FLOW_URL, headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 204
        flow_service.delete_flow.assert_called_once_with(_FLOW_ID, actor=_actor("alice"))

    def test_unauthenticated_delete_is_401(self, *, client, flow_service):
        response = client.delete(_FLOW_URL)

        assert response.status_code == 401
        flow_service.delete_flow.assert_not_called()
