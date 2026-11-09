# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for ActorContext, can_modify and PermissionDeniedException."""

import json
from unittest.mock import MagicMock

import pytest
from fastapi import Request

from docpipe.api.auth.roles import Role
from docpipe.api.middleware.error_handler import docpipe_exception_handler
from docpipe.core.models.actor_context import (
    ROLE_ADMIN,
    ROLE_EDITOR,
    ROLE_VIEWER,
    ActorContext,
    can_modify,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException, PermissionDeniedException


def _actor(username: str, *roles: str) -> ActorContext:
    return ActorContext(username=username, roles=frozenset(roles))


class TestRoleConstants:
    """The string constants in core/ must not drift from the API Role enum."""

    def test_constants_equal_role_enum_values(self):
        assert ROLE_VIEWER == Role.VIEWER.value
        assert ROLE_EDITOR == Role.EDITOR.value
        assert ROLE_ADMIN == Role.ADMIN.value


class TestActorContext:
    def test_is_frozen(self):
        actor = _actor("alice", ROLE_EDITOR)
        with pytest.raises(AttributeError):
            actor.username = "bob"  # type: ignore[misc]

    def test_is_hashable_and_comparable(self):
        assert _actor("a", ROLE_EDITOR) == _actor("a", ROLE_EDITOR)
        assert len({_actor("a", ROLE_EDITOR), _actor("a", ROLE_EDITOR)}) == 1

    def test_role_enum_values_can_populate_roles(self):
        actor = ActorContext(username="a", roles=frozenset({Role.ADMIN.value}))
        assert ROLE_ADMIN in actor.roles


class TestCanModify:
    def test_viewer_cannot_modify_own_asset(self):
        assert can_modify(actor=_actor("alice", ROLE_VIEWER), owner="alice") is False

    def test_viewer_cannot_modify_ownerless_asset(self):
        assert can_modify(actor=_actor("alice", ROLE_VIEWER), owner=None) is False

    def test_actor_without_roles_cannot_modify(self):
        assert can_modify(actor=_actor("alice"), owner="alice") is False

    def test_editor_owner_can_modify(self):
        assert can_modify(actor=_actor("alice", ROLE_EDITOR), owner="alice") is True

    def test_editor_other_cannot_modify(self):
        assert can_modify(actor=_actor("alice", ROLE_EDITOR), owner="bob") is False

    @pytest.mark.parametrize("owner", [None, ""])
    def test_editor_can_modify_ownerless_asset(self, owner):
        assert can_modify(actor=_actor("alice", ROLE_EDITOR), owner=owner) is True

    def test_admin_can_modify_foreign_asset(self):
        assert can_modify(actor=_actor("root", ROLE_ADMIN), owner="bob") is True

    def test_admin_can_modify_ownerless_asset(self):
        assert can_modify(actor=_actor("root", ROLE_ADMIN), owner=None) is True

    def test_admin_with_other_roles_can_modify(self):
        assert can_modify(actor=_actor("root", ROLE_VIEWER, ROLE_ADMIN), owner="bob") is True

    def test_none_actor_is_always_allowed(self):
        assert can_modify(actor=None, owner="bob") is True
        assert can_modify(actor=None, owner=None) is True

    def test_owner_comparison_is_exact(self):
        assert can_modify(actor=_actor("Alice", ROLE_EDITOR), owner="alice") is False

    def test_requires_keyword_arguments(self):
        with pytest.raises(TypeError):
            can_modify(None, "bob")  # type: ignore[misc]


class TestPermissionDeniedException:
    def test_defaults(self):
        exc = PermissionDeniedException()

        assert isinstance(exc, DocpipeException)
        assert exc.status_code == 403
        assert str(exc) == "Permission denied"
        assert exc.action is None
        assert exc.target is None

    def test_carries_action_and_target(self):
        exc = PermissionDeniedException("Not allowed", action="delete", target="flow-1")

        assert str(exc) == "Not allowed"
        assert exc.action == "delete"
        assert exc.target == "flow-1"

    def test_handler_maps_to_403_forbidden(self):
        request = MagicMock(spec=Request)
        request.state = MagicMock()
        request.state.transaction_id = "12345678-1234-4234-8234-123456789012"

        response = docpipe_exception_handler(request, PermissionDeniedException("Permission denied"))

        assert response.status_code == 403
        content = json.loads(response.body)
        assert content["errors"][0]["code"] == "forbidden"
        assert content["errors"][0]["message"] == "Permission denied"
        assert content["status_code"] == 403
