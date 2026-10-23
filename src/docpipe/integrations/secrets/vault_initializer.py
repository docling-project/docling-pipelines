"""HashiCorp Vault provider initializer.

Reads the ``secrets.vault`` section from docling-pipelines-config.yaml to decide
whether to enable the Vault integration. Credentials (role_id, secret_id) are
always read from environment variables — never from the config file.

Enable/disable logic (evaluated in order):
1. ``DOCPIPE_VAULT_ENABLED=false`` env var  → disabled (always wins)
2. ``DOCPIPE_VAULT_ENABLED=true`` env var   → enabled (overrides YAML, no config edit needed)
3. ``secrets.vault.enabled: false`` in YAML → disabled (default)
4. ``secrets.vault.enabled: true`` in YAML  → enabled if credentials are present

This means existing deployments with no ``secrets`` section in their config are
completely unaffected — the function is a no-op for them.
"""

import os
from pathlib import Path

import yaml

from docpipe.core.constants.constants import EnvironmentVariables, _find_project_root
from docpipe.exceptions.docpipe_exceptions import ConfigurationError
from docpipe.integrations.secrets.hashicorp_vault import HashiCorpVaultProvider
from docpipe.integrations.secrets.secret_provider import register_provider
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

_DEFAULT_CONFIG_PATH = _find_project_root() / "docling-pipelines-config.yaml"


def initialize_secret_providers() -> None:
    """Register secret providers based on docling-pipelines-config.yaml.

    This function is a no-op when:
    - ``DOCPIPE_VAULT_ENABLED=false`` is set in the environment
    - The ``secrets.vault.enabled`` key is absent or false in the YAML config
    - Vault credentials (``VAULT_ROLE_ID`` / ``VAULT_ROLE_ID_FILE``) are not set
    - Vault is configured but not reachable

    In all no-op cases, existing flow execution is completely unaffected.
    Operators receive their config dicts unchanged and ``resolve_value()`` is a
    no-op for any value that does not start with ``vault://``.

    Never raises — all errors are logged as WARNING so startup is never blocked.
    """
    try:
        _initialize_secret_providers()
    except Exception as exc:
        logger.warning(
            "Vault initialization failed unexpectedly - application will continue without Vault. Detail: %s",
            exc,
            exc_info=True,
        )


def _initialize_secret_providers() -> None:
    """Internal implementation — called only by initialize_secret_providers()."""
    # 1. Check env-var override — takes precedence over YAML in both directions
    env_override = os.environ.get(EnvironmentVariables.DOCPIPE_VAULT_ENABLED, "").lower()
    if env_override in ("false", "0", "no"):
        logger.info("Vault integration disabled via %s env var", EnvironmentVariables.DOCPIPE_VAULT_ENABLED)
        return
    env_force_enabled = env_override in ("true", "1", "yes")

    # 2. Load YAML config — same pattern used by JobManagementFactory and others
    config_path = Path(os.environ.get(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(_DEFAULT_CONFIG_PATH)))
    yaml_config: dict = {}
    if config_path.exists():
        try:
            with Path(config_path).open() as fh:
                yaml_config = yaml.safe_load(fh) or {}
        except Exception as exc:
            logger.warning("Could not read config file %s: %s", config_path, exc)

    # 3. Read secrets.vault section — absent or enabled=false means disabled
    #    unless DOCPIPE_VAULT_ENABLED=true overrides it
    vault_section: dict = yaml_config.get("secrets", {}).get("vault", {})
    if not env_force_enabled and not vault_section.get("enabled", False):
        logger.debug("Vault integration disabled (secrets.vault.enabled is not true in config)")
        return

    # Provider name: env var > YAML > default "hashicorp"
    provider_name: str = os.environ.get(EnvironmentVariables.DOCPIPE_VAULT_PROVIDER_NAME) or vault_section.get(
        "provider", "hashicorp"
    )

    # 4. Build provider — credentials come exclusively from env vars
    provider = HashiCorpVaultProvider()

    # 5. Validate credentials are present before attempting connection
    try:
        provider._config.validate()
    except ConfigurationError as exc:
        logger.warning(
            "Vault is enabled in config but credentials are missing - "
            "set VAULT_ROLE_ID and VAULT_SECRET_ID environment variables. Detail: %s",
            exc,
            exc_info=True,
        )
        return

    # 6. Check reachability — fail gracefully, don't crash startup
    #    is_available() logs the full stacktrace internally on failure
    if not provider.is_available():
        logger.warning(
            "Vault provider will not be registered - "
            "check VAULT_ADDR=%s, VAULT_TLS_SKIP_VERIFY, and VAULT_CA_CERT. "
            "Set DS_LOG_LEVEL=DEBUG for full stacktrace.",
            provider._config.addr,
        )
        return

    # 7. Register provider under the configured name (used in vault:// URIs)
    register_provider(name=provider_name, provider=provider)
    logger.info(
        "HashiCorp Vault provider registered as '%s' (addr=%s, mount=%s)",
        provider_name,
        provider._config.addr,
        provider._config.mount_point,
    )
