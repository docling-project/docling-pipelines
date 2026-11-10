# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the get_actor dependency."""

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from docpipe.api.auth.actor import get_actor
from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.auth.models import User
from docpipe.api.auth.roles import Role
from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.core.models.actor_context import ActorContext


@pytest.fixture
def make_client():
    """Build a client whose get_current_user returns the given user (or None)."""

    def _make(user: User | None) -> TestClient:
        app = FastAPI()

        @app.get("/actor")
        def read_actor(actor: Annotated[ActorContext | None, Depends(get_actor)]) -> dict:
            if actor is None:
                return {"actor": None}
            return {"actor": {"username": actor.username, "roles": sorted(actor.roles)}}

        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    return _make


class TestGetActor:
    def test_auth_disabled_returns_none(self, make_client):
        client = make_client(User(username="alice", roles=[Role.EDITOR]))

        assert client.get("/actor").json() == {"actor": None}

    def test_auth_disabled_returns_none_for_local_admin_principal(self, make_client):
        client = make_client(User(username="reserved-local", roles=[Role.ADMIN]))

        assert client.get("/actor").json() == {"actor": None}

    def test_auth_enabled_with_user_returns_actor_with_roles(self, make_client, auth_enabled):
        client = make_client(User(username="alice", roles=[Role.EDITOR, Role.ADMIN]))

        assert client.get("/actor").json() == {"actor": {"username": "alice", "roles": ["admin", "editor"]}}

    def test_auth_enabled_default_user_is_viewer(self, make_client, auth_enabled):
        client = make_client(User(username="bob"))

        assert client.get("/actor").json() == {"actor": {"username": "bob", "roles": ["viewer"]}}

    def test_auth_enabled_without_user_returns_none(self, make_client, auth_enabled):
        client = make_client(None)

        assert client.get("/actor").json() == {"actor": None}

    def test_toggle_is_read_per_request(self, make_client, monkeypatch):
        client = make_client(User(username="alice", roles=[Role.EDITOR]))

        assert client.get("/actor").json() == {"actor": None}

        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_ENABLED, "true")
        assert client.get("/actor").json()["actor"]["username"] == "alice"

    def test_direct_call_builds_frozenset_of_strings(self, auth_enabled):
        actor = get_actor(User(username="alice", roles=[Role.EDITOR]))

        assert actor == ActorContext(username="alice", roles=frozenset({"editor"}))
