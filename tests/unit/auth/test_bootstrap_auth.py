# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the bootstrap administrator authenticator."""

import logging

import bcrypt
import pytest

from docpipe.api.auth.bootstrap_auth import (
    AUDIT_ACTION_BOOTSTRAP_LOGIN,
    BCRYPT_MAX_PASSWORD_BYTES,
    BootstrapAdminAuthenticator,
)
from docpipe.api.auth.config import AuthSettings
from docpipe.api.auth.dependencies import LOCAL_PRINCIPAL_USERNAME
from docpipe.api.auth.roles import Role
from docpipe.exceptions.docpipe_exceptions import ConfigurationError

_USERNAME = "breakglass"
_PASSWORD = "correct horse battery staple"  # pragma: allowlist secret
_WRONG_PASSWORD = "wrong-password"  # pragma: allowlist secret
_NOT_A_HASH = "not-a-bcrypt-hash"  # pragma: allowlist secret
_SHORT_HASH = "$2b$12$short"  # pragma: allowlist secret
_HASH = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()  # pragma: allowlist secret


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def capture():
    """Capture one logger by name without depending on propagation."""

    def _capture(name: str) -> _ListHandler:
        handler = _ListHandler()
        target = logging.getLogger(name)
        previous = (target.level, target.propagate)
        target.setLevel(logging.DEBUG)
        target.propagate = False
        target.addHandler(handler)
        restores.append((target, handler, previous))
        return handler

    restores: list = []
    yield _capture
    for target, handler, (level, propagate) in restores:
        target.removeHandler(handler)
        target.setLevel(level)
        target.propagate = propagate


@pytest.fixture
def authenticator() -> BootstrapAdminAuthenticator:
    return BootstrapAdminAuthenticator(username=_USERNAME, password_hash=_HASH)


class TestAuthenticate:
    def test_matching_credentials_yield_admin(self, authenticator):
        user = authenticator.authenticate(username=_USERNAME, password=_PASSWORD)

        assert user is not None
        assert user.username == _USERNAME
        assert user.roles == [Role.ADMIN]

    def test_wrong_password_is_rejected(self, authenticator):
        assert authenticator.authenticate(username=_USERNAME, password=_WRONG_PASSWORD) is None

    def test_wrong_username_is_rejected_after_bcrypt_work(self, authenticator, monkeypatch):
        calls: list[bytes] = []
        real_checkpw = bcrypt.checkpw

        def _spy(password: bytes, hashed: bytes) -> bool:
            calls.append(password)
            return real_checkpw(password, hashed)

        monkeypatch.setattr("docpipe.api.auth.bootstrap_auth.bcrypt.checkpw", _spy)

        assert authenticator.authenticate(username="someone-else", password=_PASSWORD) is None
        assert calls == [_PASSWORD.encode()]

    def test_username_is_compared_with_compare_digest(self, authenticator, monkeypatch):
        compared: list[tuple[bytes, bytes]] = []

        def _spy(left: bytes, right: bytes) -> bool:
            compared.append((left, right))
            return left == right

        monkeypatch.setattr("docpipe.api.auth.bootstrap_auth.secrets.compare_digest", _spy)

        assert authenticator.authenticate(username=_USERNAME, password=_PASSWORD) is not None
        assert compared == [(_USERNAME.encode(), _USERNAME.encode())]

    def test_oversized_password_is_rejected_without_bcrypt(self, authenticator, monkeypatch):
        def _fail(*args: object, **kwargs: object) -> bool:
            raise AssertionError("bcrypt must not run for an oversized password")

        monkeypatch.setattr("docpipe.api.auth.bootstrap_auth.bcrypt.checkpw", _fail)

        assert authenticator.authenticate(username=_USERNAME, password="a" * (BCRYPT_MAX_PASSWORD_BYTES + 1)) is None

    def test_multibyte_password_over_72_bytes_is_rejected(self, authenticator):
        # 37 two-byte characters = 74 bytes, but only 37 characters.
        assert authenticator.authenticate(username=_USERNAME, password="\u00e9" * 37) is None

    def test_password_of_exactly_72_bytes_is_accepted(self):
        password = "p" * BCRYPT_MAX_PASSWORD_BYTES
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()
        authenticator = BootstrapAdminAuthenticator(username=_USERNAME, password_hash=hashed)

        assert authenticator.authenticate(username=_USERNAME, password=password) is not None

    @pytest.mark.parametrize(("username", "password"), [("", _PASSWORD), (_USERNAME, "")])
    def test_empty_credentials_are_rejected(self, authenticator, username, password):
        assert authenticator.authenticate(username=username, password=password) is None

    def test_reserved_username_is_rejected(self, capture):
        # Configuring the reserved name is refused outright, so it can never log in.
        with pytest.raises(ConfigurationError):
            BootstrapAdminAuthenticator(username=LOCAL_PRINCIPAL_USERNAME, password_hash=_HASH)

    def test_reserved_username_login_is_rejected(self, authenticator):
        assert authenticator.authenticate(username=LOCAL_PRINCIPAL_USERNAME, password=_PASSWORD) is None


class TestAudit:
    def test_successful_login_is_audited(self, authenticator, capture):
        handler = capture("docpipe.audit")

        authenticator.authenticate(username=_USERNAME, password=_PASSWORD)

        assert handler.messages == [
            f"AUDIT user={_USERNAME} action={AUDIT_ACTION_BOOTSTRAP_LOGIN} target=/auth/login outcome=success status=-"
        ]

    def test_failed_login_is_not_audited_and_password_not_logged(self, authenticator, capture):
        handler = capture("docpipe.audit")

        authenticator.authenticate(username=_USERNAME, password=_WRONG_PASSWORD)  # pragma: allowlist secret

        assert handler.messages == []


class TestConfiguration:
    def test_malformed_hash_fails(self):
        with pytest.raises(ConfigurationError, match="not a valid bcrypt hash"):
            BootstrapAdminAuthenticator(username=_USERNAME, password_hash=_NOT_A_HASH)

    def test_empty_username_fails(self):
        with pytest.raises(ConfigurationError):
            BootstrapAdminAuthenticator(username="  ", password_hash=_HASH)

    def test_neither_variable_set_means_not_configured(self):
        assert BootstrapAdminAuthenticator.from_settings(settings=AuthSettings()) is None

    @pytest.mark.parametrize(
        "settings",
        [
            AuthSettings(bootstrap_username=_USERNAME),
            AuthSettings(bootstrap_password_hash=_HASH),
        ],
        ids=["username_only", "hash_only"],
    )
    def test_one_variable_set_fails_startup(self, settings):
        with pytest.raises(ConfigurationError, match="must be set together"):
            BootstrapAdminAuthenticator.from_settings(settings=settings)

    def test_malformed_hash_from_settings_fails_startup(self):
        settings = AuthSettings(bootstrap_username=_USERNAME, bootstrap_password_hash=_SHORT_HASH)

        with pytest.raises(ConfigurationError):
            BootstrapAdminAuthenticator.from_settings(settings=settings)

    def test_both_variables_set_builds_authenticator_and_warns(self, capture):
        handler = capture("docpipe.api.auth.bootstrap_auth")
        settings = AuthSettings(bootstrap_username=_USERNAME, bootstrap_password_hash=_HASH)

        built = BootstrapAdminAuthenticator.from_settings(settings=settings)

        assert built is not None
        assert built.authenticate(username=_USERNAME, password=_PASSWORD) is not None
        assert any("bootstrap administrator login is active" in message for message in handler.messages)
        assert all(_HASH not in message for message in handler.messages)
