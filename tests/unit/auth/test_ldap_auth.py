"""Unit tests for LDAP authentication.

python-ldap is never allowed to reach a real server: ``ldap.initialize`` is
replaced with a factory that hands out ``MagicMock`` connections. The real
python-ldap exception classes (``ldap.SERVER_DOWN``, ``ldap.INVALID_CREDENTIALS``
...) are kept so the exception-mapping logic is exercised for real.
"""

import logging
import secrets
from unittest.mock import MagicMock, call

import ldap
import pytest
from ldap.filter import escape_filter_chars

from docpipe.api.auth import ldap_auth
from docpipe.api.auth.ldap_auth import LDAPAuthenticator, LDAPConfig
from docpipe.api.auth.models import User
from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError

_SERVER = "ldap://ldap.example.com:389"
_BASE_DN = "dc=example,dc=com"
_USER_DN = "ou=people,dc=example,dc=com"
_BIND_DN = "cn=service,dc=example,dc=com"
_BIND_CREDENTIAL = secrets.token_urlsafe(24)
_USER_CREDENTIAL = secrets.token_urlsafe(24)
_AD_DOMAIN = "corp.example.com"

_FILTER_SPECIAL_USERNAMES = [
    "*",
    "*)(uid=*",
    "admin)(|(uid=*",
    "jdoe)(objectClass=*",
    "back\\slash",
    "nul\x00byte",
]


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _entry(dn: str, **attrs: str) -> tuple[str, dict[str, list[bytes]]]:
    """Build a python-ldap style search result entry with bytes attribute values."""
    return dn, {name: [value.encode("utf-8")] for name, value in attrs.items()}


@pytest.fixture
def ldap_config() -> LDAPConfig:
    """Standard (OpenLDAP-style) configuration: service bind, search, user bind."""
    return LDAPConfig(
        ldap_server=_SERVER,
        ldap_base_dn=_BASE_DN,
        ldap_user_dn=_USER_DN,
        ldap_bind_dn=_BIND_DN,
        ldap_bind_password=_BIND_CREDENTIAL,
    )


@pytest.fixture
def ad_config() -> LDAPConfig:
    """Active Directory configuration: direct UPN bind."""
    return LDAPConfig(
        ldap_server=_SERVER,
        ldap_user_dn=_USER_DN,
        ldap_use_active_directory=True,
        ldap_ad_domain=_AD_DOMAIN,
    )


@pytest.fixture
def ldap_clients(monkeypatch) -> list[MagicMock]:
    """Patch ``ldap.initialize`` to return pre-built mock connections in order.

    Index 0 is the first connection opened (service / AD bind), index 1 the
    second one (re-bind as the end user in the standard flow).
    """
    clients = [MagicMock(name="ldap_conn_0"), MagicMock(name="ldap_conn_1")]
    monkeypatch.setattr(ldap_auth.ldap, "initialize", MagicMock(side_effect=clients))
    return clients


@pytest.fixture
def ldap_log(caplog):
    """Capture records from the LDAP module logger.

    The ``docpipe`` logger hierarchy may have propagation disabled by
    ``setup_logging()``, so caplog's handler is attached to the module logger directly.
    """
    module_logger = logging.getLogger(ldap_auth.__name__)
    module_logger.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger=ldap_auth.__name__)
    yield caplog
    module_logger.removeHandler(caplog.handler)


# ---------------------------------------------------------------------------
# LDAPConfig
# ---------------------------------------------------------------------------


class TestLDAPConfig:
    """LDAP settings model."""

    def test_defaults_are_empty_and_insecure_flags_off(self, *, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)  # no stray .env file
        for var in (
            "LDAP_SERVER",
            "LDAP_BASE_DN",
            "LDAP_USER_DN",
            "LDAP_BIND_DN",
            "LDAP_BIND_PASSWORD",
            "LDAP_USE_SSL",
            "LDAP_USE_ACTIVE_DIRECTORY",
            "LDAP_AD_DOMAIN",
        ):
            monkeypatch.delenv(var, raising=False)

        config = LDAPConfig()

        assert config.ldap_server == ""
        assert config.ldap_bind_dn == ""
        assert config.ldap_use_ssl is False
        assert config.ldap_use_active_directory is False
        assert config.ldap_ad_domain == ""

    def test_values_loaded_from_environment(self, *, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LDAP_SERVER", _SERVER)
        monkeypatch.setenv("LDAP_USER_DN", _USER_DN)
        monkeypatch.setenv("LDAP_USE_SSL", "true")
        monkeypatch.setenv("LDAP_USE_ACTIVE_DIRECTORY", "1")
        monkeypatch.setenv("LDAP_AD_DOMAIN", _AD_DOMAIN)

        config = LDAPConfig()

        assert config.ldap_server == _SERVER
        assert config.ldap_user_dn == _USER_DN
        assert config.ldap_use_ssl is True
        assert config.ldap_use_active_directory is True
        assert config.ldap_ad_domain == _AD_DOMAIN

    def test_values_loaded_from_dotenv_file(self, *, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LDAP_SERVER", raising=False)
        (tmp_path / ".env").write_text(f"LDAP_SERVER={_SERVER}\nUNRELATED_SETTING=ignored\n")

        config = LDAPConfig()

        assert config.ldap_server == _SERVER


# ---------------------------------------------------------------------------
# Standard LDAP flow (service bind -> search -> user bind)
# ---------------------------------------------------------------------------


class TestStandardLDAPAuthentication:
    """``authenticate`` with ``ldap_use_active_directory=False``."""

    def test_successful_login_returns_user_with_ldap_attributes(self, *, ldap_config, ldap_clients):
        service_conn, _ = ldap_clients
        service_conn.search_s.return_value = [
            _entry("uid=jdoe,ou=people,dc=example,dc=com", cn="John Doe", mail="jdoe@example.com", uid="jdoe")
        ]

        user = LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        assert user == User(username="jdoe", email="jdoe@example.com", full_name="John Doe")

    def test_successful_login_performs_expected_ldap_calls(self, *, ldap_config, ldap_clients):
        service_conn, user_conn = ldap_clients
        service_conn.search_s.return_value = [_entry("uid=jdoe,ou=people,dc=example,dc=com", cn="John Doe")]

        LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        assert ldap_auth.ldap.initialize.call_args_list == [call(_SERVER), call(_SERVER)]
        for conn in (service_conn, user_conn):
            conn.set_option.assert_any_call(ldap.OPT_REFERRALS, 0)
            conn.set_option.assert_any_call(ldap.OPT_PROTOCOL_VERSION, 3)
            conn.start_tls_s.assert_not_called()
        # Service account bind, then search for the user's DN.
        service_conn.simple_bind_s.assert_called_once_with(_BIND_DN, _BIND_CREDENTIAL)
        service_conn.search_s.assert_called_once_with(_USER_DN, ldap.SCOPE_SUBTREE, "(uid=jdoe)", ["cn", "mail", "uid"])
        # The user's password is checked by binding as the discovered DN.
        user_conn.simple_bind_s.assert_called_once_with("uid=jdoe,ou=people,dc=example,dc=com", _USER_CREDENTIAL)
        user_conn.search_s.assert_not_called()

    def test_both_connections_are_unbound(self, *, ldap_config, ldap_clients):
        service_conn, user_conn = ldap_clients
        service_conn.search_s.return_value = [_entry("uid=jdoe,ou=people,dc=example,dc=com")]

        LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        service_conn.unbind_s.assert_called_once_with()
        user_conn.unbind_s.assert_called_once_with()

    def test_missing_mail_and_cn_attributes_default_to_empty_strings(self, *, ldap_config, ldap_clients):
        service_conn, _ = ldap_clients
        service_conn.search_s.return_value = [_entry("uid=jdoe,ou=people,dc=example,dc=com", uid="jdoe")]

        user = LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        assert user == User(username="jdoe", email="", full_name="")

    def test_utf8_attribute_values_are_decoded(self, *, ldap_config, ldap_clients):
        service_conn, _ = ldap_clients
        service_conn.search_s.return_value = [
            _entry("uid=jdoe,ou=people,dc=example,dc=com", cn="José Müller", mail="jose@example.com")
        ]

        user = LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        assert user is not None
        assert user.full_name == "José Müller"

    def test_first_entry_is_used_when_search_returns_several(self, *, ldap_config, ldap_clients):
        service_conn, user_conn = ldap_clients
        service_conn.search_s.return_value = [
            _entry("uid=jdoe,ou=people,dc=example,dc=com", cn="First"),
            _entry("uid=jdoe,ou=legacy,dc=example,dc=com", cn="Second"),
        ]

        user = LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        assert user is not None
        assert user.full_name == "First"
        user_conn.simple_bind_s.assert_called_once_with("uid=jdoe,ou=people,dc=example,dc=com", _USER_CREDENTIAL)

    def test_unknown_user_returns_none_without_user_bind(self, *, ldap_config, ldap_clients):
        service_conn, user_conn = ldap_clients
        service_conn.search_s.return_value = []

        result = LDAPAuthenticator(ldap_config).authenticate("ghost", _USER_CREDENTIAL)

        assert result is None
        assert ldap_auth.ldap.initialize.call_count == 1
        user_conn.simple_bind_s.assert_not_called()
        service_conn.unbind_s.assert_called_once_with()

    def test_wrong_user_password_returns_none(self, *, ldap_config, ldap_clients):
        service_conn, user_conn = ldap_clients
        service_conn.search_s.return_value = [_entry("uid=jdoe,ou=people,dc=example,dc=com")]
        user_conn.simple_bind_s.side_effect = ldap.INVALID_CREDENTIALS({"desc": "Invalid credentials"})

        result = LDAPAuthenticator(ldap_config).authenticate("jdoe", "wrong-password")

        assert result is None
        user_conn.unbind_s.assert_called_once_with()

    def test_invalid_service_account_credentials_raise_external_service_error(self, *, ldap_config, ldap_clients):
        """A misconfigured service account is a server-side error, not a failed user login."""
        service_conn, _ = ldap_clients
        service_conn.simple_bind_s.side_effect = ldap.INVALID_CREDENTIALS({"desc": "Invalid credentials"})

        with pytest.raises(ExternalServiceError, match="LDAP authentication error"):
            LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        service_conn.search_s.assert_not_called()

    def test_server_down_raises_external_service_error(self, *, ldap_config, ldap_clients):
        service_conn, _ = ldap_clients
        service_conn.simple_bind_s.side_effect = ldap.SERVER_DOWN({"desc": "Can't contact LDAP server"})

        with pytest.raises(ExternalServiceError, match="LDAP server is unavailable") as exc_info:
            LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        assert exc_info.value.status_code == 502
        # ``raise ... from None`` hides the python-ldap internals from API clients.
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__suppress_context__ is True
        service_conn.unbind_s.assert_called_once_with()

    def test_server_down_during_user_bind_raises_external_service_error(self, *, ldap_config, ldap_clients):
        service_conn, user_conn = ldap_clients
        service_conn.search_s.return_value = [_entry("uid=jdoe,ou=people,dc=example,dc=com")]
        user_conn.simple_bind_s.side_effect = ldap.SERVER_DOWN({"desc": "Can't contact LDAP server"})

        with pytest.raises(ExternalServiceError, match="LDAP server is unavailable"):
            LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

    def test_search_timeout_raises_external_service_error(self, *, ldap_config, ldap_clients):
        service_conn, _ = ldap_clients
        timeout = ldap.TIMEOUT({"desc": "Timed out"})
        service_conn.search_s.side_effect = timeout

        with pytest.raises(ExternalServiceError, match="LDAP authentication error") as exc_info:
            LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        assert exc_info.value.__cause__ is timeout
        service_conn.unbind_s.assert_called_once_with()

    def test_invalid_dn_syntax_raises_configuration_error(self, *, ldap_config, ldap_clients):
        service_conn, _ = ldap_clients
        service_conn.simple_bind_s.side_effect = ldap.INVALID_DN_SYNTAX({"desc": "Invalid DN syntax"})

        with pytest.raises(ConfigurationError, match="invalid bind DN format") as exc_info:
            LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        assert isinstance(exc_info.value.__cause__, ldap.INVALID_DN_SYNTAX)

    def test_unexpected_error_is_wrapped_in_external_service_error(self, *, ldap_config, ldap_clients):
        service_conn, _ = ldap_clients
        service_conn.search_s.side_effect = RuntimeError("socket closed")

        with pytest.raises(ExternalServiceError, match="socket closed"):
            LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

    def test_unbind_failure_does_not_mask_successful_login(self, *, ldap_config, ldap_clients, ldap_log):
        service_conn, user_conn = ldap_clients
        service_conn.search_s.return_value = [_entry("uid=jdoe,ou=people,dc=example,dc=com", cn="John Doe")]
        user_conn.unbind_s.side_effect = ldap.LDAPError({"desc": "already closed"})

        user = LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        assert user is not None
        assert user.username == "jdoe"
        assert "Failed to unbind LDAP connection" in ldap_log.text

    def test_start_tls_is_negotiated_on_every_connection_when_ssl_enabled(self, *, ldap_config, ldap_clients):
        ldap_config.ldap_use_ssl = True
        service_conn, user_conn = ldap_clients
        service_conn.search_s.return_value = [_entry("uid=jdoe,ou=people,dc=example,dc=com")]

        LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        for conn in (service_conn, user_conn):
            conn.start_tls_s.assert_called_once_with()
        # StartTLS must happen before credentials are sent.
        assert service_conn.method_calls.index(call.start_tls_s()) < service_conn.method_calls.index(
            call.simple_bind_s(_BIND_DN, _BIND_CREDENTIAL)
        )

    def test_start_tls_failure_raises_external_service_error(self, *, ldap_config, ldap_clients):
        ldap_config.ldap_use_ssl = True
        service_conn, _ = ldap_clients
        service_conn.start_tls_s.side_effect = ldap.CONNECT_ERROR({"desc": "TLS handshake failed"})

        with pytest.raises(ExternalServiceError):
            LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        service_conn.simple_bind_s.assert_not_called()

    def test_password_is_never_logged(self, *, ldap_config, ldap_clients, ldap_log):
        service_conn, user_conn = ldap_clients
        service_conn.search_s.return_value = [_entry("uid=jdoe,ou=people,dc=example,dc=com")]
        user_conn.simple_bind_s.side_effect = ldap.INVALID_CREDENTIALS({"desc": "Invalid credentials"})
        secret = "S3cr3t-P@ssw0rd!"  # pragma: allowlist secret

        LDAPAuthenticator(ldap_config).authenticate("jdoe", secret)

        assert "Invalid credentials for user: jdoe" in ldap_log.text
        assert secret not in ldap_log.text
        assert _BIND_CREDENTIAL not in ldap_log.text


# ---------------------------------------------------------------------------
# Active Directory flow (direct UPN bind)
# ---------------------------------------------------------------------------


class TestActiveDirectoryAuthentication:
    """``authenticate`` with ``ldap_use_active_directory=True``."""

    def test_successful_login_binds_with_upn_and_returns_user(self, *, ad_config, ldap_clients):
        conn, _ = ldap_clients
        conn.search_s.return_value = [
            _entry("CN=John Doe,OU=Users,DC=corp,DC=example,DC=com", cn="John Doe", mail="jdoe@corp.example.com")
        ]

        user = LDAPAuthenticator(ad_config).authenticate("jdoe", _USER_CREDENTIAL)

        assert user == User(username="jdoe", email="jdoe@corp.example.com", full_name="John Doe")
        conn.simple_bind_s.assert_called_once_with(f"jdoe@{_AD_DOMAIN}", _USER_CREDENTIAL)
        conn.search_s.assert_called_once_with(
            _USER_DN,
            ldap.SCOPE_SUBTREE,
            "(sAMAccountName=jdoe)",
            ["cn", "mail", "sAMAccountName", "userPrincipalName"],
        )
        # AD flow uses a single connection and no service account.
        assert ldap_auth.ldap.initialize.call_count == 1
        conn.unbind_s.assert_called_once_with()

    def test_invalid_credentials_return_none_without_search(self, *, ad_config, ldap_clients):
        conn, _ = ldap_clients
        conn.simple_bind_s.side_effect = ldap.INVALID_CREDENTIALS({"desc": "Invalid credentials"})

        result = LDAPAuthenticator(ad_config).authenticate("jdoe", "wrong-password")

        assert result is None
        conn.search_s.assert_not_called()
        conn.unbind_s.assert_called_once_with()

    def test_user_missing_from_directory_search_still_authenticates_with_empty_attributes(
        self, *, ad_config, ldap_clients
    ):
        """The UPN bind already proved the password; attributes are best-effort."""
        conn, _ = ldap_clients
        conn.search_s.return_value = []

        user = LDAPAuthenticator(ad_config).authenticate("jdoe", _USER_CREDENTIAL)

        assert user == User(username="jdoe", email="", full_name="")

    def test_missing_ad_domain_raises_configuration_error(self, *, ad_config, ldap_clients):
        ad_config.ldap_ad_domain = ""
        conn, _ = ldap_clients

        with pytest.raises(ConfigurationError, match="ldap_ad_domain must be configured"):
            LDAPAuthenticator(ad_config).authenticate("jdoe", _USER_CREDENTIAL)

        conn.simple_bind_s.assert_not_called()
        conn.unbind_s.assert_called_once_with()

    def test_server_down_raises_external_service_error(self, *, ad_config, ldap_clients):
        conn, _ = ldap_clients
        conn.simple_bind_s.side_effect = ldap.SERVER_DOWN({"desc": "Can't contact LDAP server"})

        with pytest.raises(ExternalServiceError, match="LDAP server is unavailable"):
            LDAPAuthenticator(ad_config).authenticate("jdoe", _USER_CREDENTIAL)

    def test_search_timeout_raises_external_service_error(self, *, ad_config, ldap_clients):
        conn, _ = ldap_clients
        conn.search_s.side_effect = ldap.TIMEOUT({"desc": "Timed out"})

        with pytest.raises(ExternalServiceError, match="LDAP authentication error"):
            LDAPAuthenticator(ad_config).authenticate("jdoe", _USER_CREDENTIAL)

    def test_start_tls_used_when_ssl_enabled(self, *, ad_config, ldap_clients):
        ad_config.ldap_use_ssl = True
        conn, _ = ldap_clients
        conn.search_s.return_value = []

        LDAPAuthenticator(ad_config).authenticate("jdoe", _USER_CREDENTIAL)

        conn.start_tls_s.assert_called_once_with()


# ---------------------------------------------------------------------------
# Input hardening: LDAP filter injection and empty credentials
# ---------------------------------------------------------------------------


class TestLDAPInputHardening:
    """User-controlled input must never change the meaning of an LDAP query."""

    @pytest.mark.parametrize("username", _FILTER_SPECIAL_USERNAMES)
    def test_standard_search_filter_escapes_username(self, *, ldap_config, ldap_clients, username):
        service_conn, _ = ldap_clients
        service_conn.search_s.return_value = []

        LDAPAuthenticator(ldap_config).authenticate(username, _USER_CREDENTIAL)

        search_filter = service_conn.search_s.call_args.args[2]
        assert search_filter == f"(uid={escape_filter_chars(username)})"
        assigned_value = search_filter[len("(uid=") : -1]
        for special in ("*", "(", ")", "\x00"):
            assert special not in assigned_value

    @pytest.mark.parametrize("username", _FILTER_SPECIAL_USERNAMES)
    def test_active_directory_search_filter_escapes_username(self, *, ad_config, ldap_clients, username):
        conn, _ = ldap_clients
        conn.search_s.return_value = []

        LDAPAuthenticator(ad_config).authenticate(username, _USER_CREDENTIAL)

        search_filter = conn.search_s.call_args.args[2]
        assert search_filter == f"(sAMAccountName={escape_filter_chars(username)})"
        assigned_value = search_filter[len("(sAMAccountName=") : -1]
        for special in ("*", "(", ")", "\x00"):
            assert special not in assigned_value

    def test_wildcard_injection_is_neutralised(self, *, ldap_config, ldap_clients):
        """Regression: ``*)(uid=*`` used to produce the match-everything filter ``(uid=*)(uid=*)``."""
        service_conn, _ = ldap_clients
        service_conn.search_s.return_value = []

        LDAPAuthenticator(ldap_config).authenticate("*)(uid=*", _USER_CREDENTIAL)

        assert service_conn.search_s.call_args.args[2] == r"(uid=\2a\29\28uid=\2a)"

    @pytest.mark.parametrize("use_active_directory", [False, True], ids=["standard", "active_directory"])
    def test_empty_password_is_rejected_without_contacting_server(
        self, *, ldap_config, ldap_clients, use_active_directory
    ):
        """Regression: a simple bind with an empty password is an *unauthenticated* bind
        (RFC 4513 section 5.1.2) that many servers accept, which would log in anyone."""
        ldap_config.ldap_use_active_directory = use_active_directory
        ldap_config.ldap_ad_domain = _AD_DOMAIN

        result = LDAPAuthenticator(ldap_config).authenticate("jdoe", "")

        assert result is None
        ldap_auth.ldap.initialize.assert_not_called()
        for conn in ldap_clients:
            conn.simple_bind_s.assert_not_called()

    def test_empty_username_is_rejected_without_contacting_server(self, *, ldap_config, ldap_clients, ldap_log):
        result = LDAPAuthenticator(ldap_config).authenticate("", _USER_CREDENTIAL)

        assert result is None
        ldap_auth.ldap.initialize.assert_not_called()
        assert "empty username or password" in ldap_log.text


# ---------------------------------------------------------------------------
# Transport security (known gaps, tracked as strict xfails)
# ---------------------------------------------------------------------------


class TestLDAPTransportSecurity:
    """Known transport-level gaps. Remove the xfail markers once fixed."""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "ldap_use_ssl sets OPT_X_TLS_REQUIRE_CERT=OPT_X_TLS_NEVER, so StartTLS accepts any "
            "certificate and LDAP credentials are exposed to MITM. Needs a configurable CA / verify mode."
        ),
    )
    def test_tls_certificate_verification_is_not_disabled(self, *, ldap_config, ldap_clients):
        ldap_config.ldap_use_ssl = True
        service_conn, _ = ldap_clients
        service_conn.search_s.return_value = []

        LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        assert call(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER) not in service_conn.set_option.call_args_list

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "No OPT_NETWORK_TIMEOUT / OPT_TIMEOUT is set, so an unresponsive LDAP server blocks "
            "the (synchronous) login call indefinitely. Needs a configurable timeout."
        ),
    )
    def test_network_timeout_is_configured(self, *, ldap_config, ldap_clients):
        service_conn, _ = ldap_clients
        service_conn.search_s.return_value = []

        LDAPAuthenticator(ldap_config).authenticate("jdoe", _USER_CREDENTIAL)

        configured_options = {c.args[0] for c in service_conn.set_option.call_args_list}
        assert ldap.OPT_NETWORK_TIMEOUT in configured_options


# ---------------------------------------------------------------------------
# verify_connection
# ---------------------------------------------------------------------------


class TestVerifyConnection:
    """``verify_connection`` health check."""

    def test_returns_true_when_service_bind_succeeds(self, *, ldap_config, ldap_clients):
        conn, _ = ldap_clients

        assert LDAPAuthenticator(ldap_config).verify_connection() is True

        ldap_auth.ldap.initialize.assert_called_once_with(_SERVER)
        conn.set_option.assert_any_call(ldap.OPT_REFERRALS, 0)
        conn.set_option.assert_any_call(ldap.OPT_PROTOCOL_VERSION, 3)
        conn.simple_bind_s.assert_called_once_with(_BIND_DN, _BIND_CREDENTIAL)
        conn.start_tls_s.assert_not_called()
        conn.unbind_s.assert_called_once_with()

    def test_uses_start_tls_when_ssl_enabled(self, *, ldap_config, ldap_clients):
        ldap_config.ldap_use_ssl = True
        conn, _ = ldap_clients

        assert LDAPAuthenticator(ldap_config).verify_connection() is True

        conn.start_tls_s.assert_called_once_with()

    @pytest.mark.parametrize(
        "error",
        [
            ldap.SERVER_DOWN({"desc": "Can't contact LDAP server"}),
            ldap.INVALID_CREDENTIALS({"desc": "Invalid credentials"}),
            ldap.TIMEOUT({"desc": "Timed out"}),
        ],
        ids=["server_down", "invalid_credentials", "timeout"],
    )
    def test_returns_false_when_bind_fails(self, *, ldap_config, ldap_clients, error):
        conn, _ = ldap_clients
        conn.simple_bind_s.side_effect = error

        assert LDAPAuthenticator(ldap_config).verify_connection() is False

        conn.unbind_s.assert_called_once_with()

    def test_returns_false_when_initialize_fails(self, *, ldap_config, monkeypatch):
        monkeypatch.setattr(ldap_auth.ldap, "initialize", MagicMock(side_effect=ldap.LDAPError("bad URI")))

        assert LDAPAuthenticator(ldap_config).verify_connection() is False

    def test_unbind_failure_is_logged_not_raised(self, *, ldap_config, ldap_clients, ldap_log):
        conn, _ = ldap_clients
        conn.unbind_s.side_effect = ldap.LDAPError("already closed")

        assert LDAPAuthenticator(ldap_config).verify_connection() is True

        assert "Error unbinding LDAP connection" in ldap_log.text
