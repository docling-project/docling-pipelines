"""Unit tests for initialize_secret_providers()."""

import logging
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, mock_open, patch

import pytest

from docpipe.integrations.secrets.secret_provider import clear_providers, get_provider
from docpipe.integrations.secrets.vault_initializer import initialize_secret_providers

_MANAGED_ENV = (
    "DOCPIPE_VAULT_ENABLED",
    "DOCPIPE_VAULT_PROVIDER_NAME",
    "DOCPIPE_CONFIG_PATH",
)
_DEFAULT_YAML = "secrets:\n  vault:\n    enabled: true\n    provider: hashicorp\n"
_UNEXPECTED_WARNING = "Vault initialization failed unexpectedly - application will continue without Vault"


@pytest.fixture(autouse=True)
def _clean_providers():
    clear_providers()
    yield
    clear_providers()


def _call(*, env=None, yaml_content=_DEFAULT_YAML):
    """Run initialize_secret_providers through the shared helper."""
    return _run(env=env, yaml_content=yaml_content)


def mock_open_yaml(content: str):
    return mock_open(read_data=content)


def _mock_provider():
    """Return a provider double that passes validation and is reachable."""
    provider = MagicMock()
    provider._config.validate.return_value = None
    provider._config.addr = "http://vault.test:8200"
    provider._config.mount_point = "secret"
    provider.is_available.return_value = True
    return provider


@contextmanager
def _isolated_vault_env(overrides):
    """Set vault env vars for one call and restore whatever was there before."""
    overrides = overrides or {}
    saved = {key: os.environ.get(key) for key in _MANAGED_ENV}
    try:
        for key in _MANAGED_ENV:
            os.environ.pop(key, None)
        os.environ.update(overrides)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run(*, env=None, yaml_content=None, exists=True, provider=None, provider_error=None):
    """Run initializer with the provider and config file mocked."""
    content = _DEFAULT_YAML if yaml_content is None else yaml_content
    mock_provider = provider if provider is not None else _mock_provider()
    if provider_error is not None:
        provider_patch = patch(
            "docpipe.integrations.secrets.vault_initializer.HashiCorpVaultProvider",
            side_effect=provider_error,
        )
    else:
        provider_patch = patch(
            "docpipe.integrations.secrets.vault_initializer.HashiCorpVaultProvider",
            return_value=mock_provider,
        )

    with (
        _isolated_vault_env(env),
        provider_patch,
        patch("pathlib.Path.open", mock_open(read_data=content)),
        patch("pathlib.Path.exists", return_value=exists),
    ):
        initialize_secret_providers()
    return mock_provider


class TestInitializeSecretProviders:
    def test_disabled_via_env_var(self):
        """DOCPIPE_VAULT_ENABLED=false skips registration regardless of YAML."""
        mock_provider = _call(env={"DOCPIPE_VAULT_ENABLED": "false"})
        assert get_provider(name="hashicorp") is None
        mock_provider.is_available.assert_not_called()

    def test_disabled_when_yaml_enabled_false(self):
        """secrets.vault.enabled=false in YAML → no registration."""
        mock_provider = _call(yaml_content="secrets:\n  vault:\n    enabled: false\n")
        assert get_provider(name="hashicorp") is None
        mock_provider.is_available.assert_not_called()

    def test_disabled_when_no_secrets_section(self):
        """No secrets section in YAML → no registration."""
        mock_provider = _call(yaml_content="job_management:\n  framework:\n    type: default\n")
        assert get_provider(name="hashicorp") is None
        mock_provider.is_available.assert_not_called()

    def test_env_var_true_overrides_yaml_disabled(self):
        """DOCPIPE_VAULT_ENABLED=true enables Vault even when YAML says enabled: false."""
        env = {
            "DOCPIPE_VAULT_ENABLED": "true",
            "VAULT_ROLE_ID": "role",
            "VAULT_SECRET_ID": "secret",
        }
        _call(env=env, yaml_content="secrets:\n  vault:\n    enabled: false\n")
        assert get_provider(name="hashicorp") is not None

    def test_missing_credentials_skips_registration(self, caplog):
        """Missing VAULT_ROLE_ID/VAULT_SECRET_ID → warning, no registration."""
        from docpipe.exceptions.docpipe_exceptions import ConfigurationError

        caplog.set_level(logging.WARNING, logger="docpipe")
        mock_provider = MagicMock()
        mock_provider._config.validate.side_effect = ConfigurationError("VAULT_ROLE_ID must be set")

        with (
            patch.dict(os.environ, {"DOCPIPE_VAULT_ENABLED": "true"}, clear=False),
            patch("docpipe.integrations.secrets.vault_initializer.HashiCorpVaultProvider", return_value=mock_provider),
            patch("pathlib.Path.open", mock_open_yaml("secrets:\n  vault:\n    enabled: true\n")),
            patch("pathlib.Path.exists", return_value=True),
        ):
            initialize_secret_providers()

        assert get_provider(name="hashicorp") is None
        mock_provider.is_available.assert_not_called()
        assert (
            "Vault is enabled in config but credentials are missing - "
            "set VAULT_ROLE_ID and VAULT_SECRET_ID environment variables."
        ) in caplog.text
        assert "VAULT_ROLE_ID must be set" in caplog.text

    def test_unreachable_vault_skips_registration(self, caplog):
        """Vault not reachable → warning, no registration."""
        caplog.set_level(logging.WARNING, logger="docpipe")
        mock_provider = MagicMock()
        mock_provider._config.validate.return_value = None
        mock_provider._config.addr = "http://vault.test:8200"
        mock_provider.is_available.return_value = False

        with (
            patch.dict(os.environ, {"DOCPIPE_VAULT_ENABLED": "true"}, clear=False),
            patch("docpipe.integrations.secrets.vault_initializer.HashiCorpVaultProvider", return_value=mock_provider),
            patch("pathlib.Path.open", mock_open_yaml("secrets:\n  vault:\n    enabled: true\n")),
            patch("pathlib.Path.exists", return_value=True),
        ):
            initialize_secret_providers()

        assert get_provider(name="hashicorp") is None
        assert (
            "Vault provider will not be registered - check VAULT_ADDR=http://vault.test:8200, "
            "VAULT_TLS_SKIP_VERIFY, and VAULT_CA_CERT."
        ) in caplog.text

    def test_successful_registration(self):
        """Happy path — provider is registered under configured name."""
        env = {"DOCPIPE_VAULT_ENABLED": "true", "VAULT_ROLE_ID": "role", "VAULT_SECRET_ID": "secret"}
        _call(env=env)
        assert get_provider(name="hashicorp") is not None

    def test_custom_provider_name_from_env(self):
        """DOCPIPE_VAULT_PROVIDER_NAME overrides YAML provider name."""
        env = {
            "DOCPIPE_VAULT_ENABLED": "true",
            "DOCPIPE_VAULT_PROVIDER_NAME": "my-vault",
            "VAULT_ROLE_ID": "role",
            "VAULT_SECRET_ID": "secret",
        }
        _call(env=env)
        assert get_provider(name="my-vault") is not None
        assert get_provider(name="hashicorp") is None

    @pytest.mark.parametrize("flag", ["0", "no", "FALSE"])
    def test_env_disable_flags_skip_registration(self, *, flag, caplog):
        """0, no, and any case of false disable Vault before the provider is used."""
        caplog.set_level(logging.INFO, logger="docpipe")
        provider = _run(
            env={"DOCPIPE_VAULT_ENABLED": flag},
            yaml_content="secrets:\n  vault:\n    enabled: true\n",
        )
        assert get_provider(name="hashicorp") is None
        provider.is_available.assert_not_called()
        assert "Vault integration disabled via DOCPIPE_VAULT_ENABLED env var" in caplog.text

    @pytest.mark.parametrize("flag", ["1", "yes", "TRUE"])
    def test_env_enable_flags_override_disabled_config(self, *, flag):
        """1, yes, and any case of true enable Vault even when config says disabled."""
        provider = _run(
            env={"DOCPIPE_VAULT_ENABLED": flag},
            yaml_content="secrets:\n  vault:\n    enabled: false\n",
        )
        assert get_provider(name="hashicorp") is provider

    def test_yaml_enabled_registers_configured_provider_name(self, caplog):
        """Config enabled=true registers the YAML provider name without an env override."""
        caplog.set_level(logging.INFO, logger="docpipe")
        provider = _run(yaml_content="secrets:\n  vault:\n    enabled: true\n    provider: team-vault\n")
        assert get_provider(name="team-vault") is provider
        assert get_provider(name="hashicorp") is None
        assert (
            "HashiCorp Vault provider registered as 'team-vault' (addr=http://vault.test:8200, mount=secret)"
        ) in caplog.text

    def test_yaml_enabled_without_provider_name_uses_hashicorp(self):
        """A missing provider name falls back to hashicorp."""
        provider = _run(yaml_content="secrets:\n  vault:\n    enabled: true\n")
        assert get_provider(name="hashicorp") is provider

    def test_missing_config_file_disables_vault(self, caplog):
        """A missing config file leaves Vault disabled when env does not force it on."""
        caplog.set_level(logging.DEBUG, logger="docpipe")
        provider = _run(exists=False, yaml_content="secrets:\n  vault:\n    enabled: true\n")
        assert get_provider(name="hashicorp") is None
        provider.is_available.assert_not_called()
        assert "Vault integration disabled" in caplog.text
        assert "Invalid YAML in config file" not in caplog.text
        assert _UNEXPECTED_WARNING not in caplog.text

    def test_env_enable_registers_when_config_file_is_missing(self, caplog):
        """DOCPIPE_VAULT_ENABLED=true still registers the default provider if no config file exists."""
        caplog.set_level(logging.INFO, logger="docpipe")
        provider = _run(env={"DOCPIPE_VAULT_ENABLED": "true"}, exists=False)
        assert get_provider(name="hashicorp") is provider
        assert "HashiCorp Vault provider registered as 'hashicorp'" in caplog.text
        assert "Invalid YAML in config file" not in caplog.text

    def test_empty_config_document_disables_vault(self, caplog):
        """An empty config document is treated as Vault disabled, not as a startup failure."""
        caplog.set_level(logging.DEBUG, logger="docpipe")
        provider = _run(yaml_content="")
        assert get_provider(name="hashicorp") is None
        provider.is_available.assert_not_called()
        assert "Vault integration disabled" in caplog.text
        assert "Invalid YAML in config file" not in caplog.text
        assert _UNEXPECTED_WARNING not in caplog.text

    def test_unreadable_config_disables_vault(self, caplog):
        """A config file that cannot be parsed logs a warning and skips registration."""
        caplog.set_level(logging.WARNING, logger="docpipe")
        provider = _run(yaml_content=":\n")
        assert get_provider(name="hashicorp") is None
        provider.is_available.assert_not_called()
        assert "Invalid YAML in config file" in caplog.text
        assert "docling-pipelines-config.yaml" in caplog.text
        assert _UNEXPECTED_WARNING not in caplog.text

    def test_unreadable_config_does_not_block_env_enable(self, caplog):
        """DOCPIPE_VAULT_ENABLED=true still registers when the config file cannot be parsed."""
        caplog.set_level(logging.INFO, logger="docpipe")
        provider = _run(env={"DOCPIPE_VAULT_ENABLED": "true"}, yaml_content=":\n")
        assert get_provider(name="hashicorp") is provider
        assert "Invalid YAML in config file" in caplog.text
        assert "docling-pipelines-config.yaml" in caplog.text

    def test_docpipe_config_path_selects_config_file(self, tmp_path):
        """DOCPIPE_CONFIG_PATH is the file read for the vault section."""
        config_file = tmp_path / "pipeline-config.yaml"
        config_file.write_text(
            "secrets:\n  vault:\n    enabled: true\n    provider: path-vault\n",
            encoding="utf-8",
        )
        provider = _mock_provider()
        with (
            _isolated_vault_env({"DOCPIPE_CONFIG_PATH": str(config_file)}),
            patch(
                "docpipe.integrations.secrets.vault_initializer.HashiCorpVaultProvider",
                return_value=provider,
            ),
        ):
            initialize_secret_providers()
        assert get_provider(name="path-vault") is provider
        assert get_provider(name="hashicorp") is None

    def test_provider_construction_failure_does_not_block_startup(self, caplog):
        """An unexpected provider error is logged and does not escape the initializer."""
        caplog.set_level(logging.WARNING, logger="docpipe")
        _run(
            yaml_content="secrets:\n  vault:\n    enabled: true\n",
            provider_error=RuntimeError("vault client unavailable"),
        )
        assert get_provider(name="hashicorp") is None
        assert _UNEXPECTED_WARNING in caplog.text
        assert "vault client unavailable" in caplog.text
