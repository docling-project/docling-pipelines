# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the Role enum, role parsing and the roles JWT claim."""

import pytest

from docpipe.api.auth.jwt_handler import JWTClaims, JWTConfig, create_access_token, verify_token
from docpipe.api.auth.models import User
from docpipe.api.auth.roles import Role, highest_role, parse_roles

_SECRET = "a-sufficiently-long-test-secret-key"  # pragma: allowlist secret


class TestRoleOrdering:
    """Roles are ordered viewer < editor < admin."""

    def test_values_are_lowercase_strings(self):
        assert Role.VIEWER == "viewer"
        assert Role.EDITOR == "editor"
        assert Role.ADMIN == "admin"

    def test_strict_ordering(self):
        assert Role.VIEWER < Role.EDITOR < Role.ADMIN
        assert Role.ADMIN > Role.EDITOR > Role.VIEWER

    def test_non_strict_ordering(self):
        assert Role.VIEWER <= Role.VIEWER
        assert Role.ADMIN >= Role.ADMIN
        assert Role.EDITOR >= Role.VIEWER
        assert Role.EDITOR <= Role.ADMIN

    def test_not_less_than_self(self):
        assert not Role.EDITOR < Role.EDITOR
        assert not Role.EDITOR > Role.EDITOR

    def test_comparison_with_non_role_is_unsupported(self):
        with pytest.raises(TypeError):
            _ = Role.VIEWER < 1  # type: ignore[operator]

    def test_sorted_orders_by_rank(self):
        assert sorted([Role.ADMIN, Role.VIEWER, Role.EDITOR]) == [Role.VIEWER, Role.EDITOR, Role.ADMIN]

    def test_highest_role(self):
        assert highest_role([Role.VIEWER, Role.ADMIN, Role.EDITOR]) is Role.ADMIN
        assert highest_role([Role.VIEWER]) is Role.VIEWER

    def test_highest_role_of_empty_is_viewer(self):
        assert highest_role([]) is Role.VIEWER


class TestParseRoles:
    """parse_roles fails closed to viewer."""

    def test_parses_known_roles(self):
        assert parse_roles(["editor", "admin"]) == [Role.EDITOR, Role.ADMIN]

    def test_ignores_unknown_and_duplicates(self):
        assert parse_roles(["editor", "root", "editor", 3]) == [Role.EDITOR]

    @pytest.mark.parametrize("raw", [None, [], "admin", 5, {"admin": True}, ["nope"]])
    def test_missing_or_malformed_defaults_to_viewer(self, raw):
        assert parse_roles(raw) == [Role.VIEWER]


class TestUserRoles:
    """The User model carries roles."""

    def test_default_roles_is_viewer(self):
        assert User(username="u").roles == [Role.VIEWER]

    def test_roles_accept_strings(self):
        user = User(username="u", roles=["editor", "admin"])
        assert user.roles == [Role.EDITOR, Role.ADMIN]

    def test_invalid_role_rejected(self):
        with pytest.raises(ValueError):
            User(username="u", roles=["root"])

    def test_default_roles_not_shared_between_instances(self):
        first = User(username="a")
        first.roles.append(Role.ADMIN)
        assert User(username="b").roles == [Role.VIEWER]


class TestTokenRoundTrip:
    """Roles survive create_access_token -> verify_token."""

    def test_roles_round_trip(self):
        config = JWTConfig(jwt_secret_key=_SECRET)
        user = User(username="alice", roles=[Role.EDITOR, Role.ADMIN])

        token = create_access_token(
            {JWTClaims.USERNAME: user.username, JWTClaims.ROLES: [role.value for role in user.roles]},
            config,
        )
        payload = verify_token(token, config)

        assert payload is not None
        assert payload[JWTClaims.ROLES] == ["editor", "admin"]
        assert parse_roles(payload[JWTClaims.ROLES]) == user.roles

    def test_token_without_roles_parses_to_viewer(self):
        config = JWTConfig(jwt_secret_key=_SECRET)
        token = create_access_token({JWTClaims.USERNAME: "bob"}, config)
        payload = verify_token(token, config)

        assert payload is not None
        assert parse_roles(payload.get(JWTClaims.ROLES)) == [Role.VIEWER]

    def test_claim_name(self):
        assert JWTClaims.ROLES == "roles"
