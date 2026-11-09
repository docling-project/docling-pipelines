# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Secret provider integration for external vault/secret managers.

Supports resolving secret references in flow configurations using the
vault:// URI scheme. Credentials for vault connectivity are read from
environment variables (typically via .env file for local development).

Usage in flow.json:
    "password": "vault://hashicorp/opensearch/credentials#password"  # pragma: allowlist secret

Supported providers:
    - hashicorp: HashiCorp Vault (AppRole authentication)

Adding new providers:
    1. Create a new module implementing SecretProvider
    2. Register it via register_provider()
"""

from docpipe.integrations.secrets.secret_provider import (
    SecretProvider,
    SecretReference,
    parse_reference,
    register_provider,
    resolve_value,
)
from docpipe.integrations.secrets.secret_value import SecretValue, secret_json_default

__all__ = [
    "SecretProvider",
    "SecretReference",
    "SecretValue",
    "parse_reference",
    "register_provider",
    "resolve_value",
    "secret_json_default",
]
