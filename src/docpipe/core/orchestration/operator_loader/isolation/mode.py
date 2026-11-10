# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""The ``custom_operators.isolation`` setting (design D12, task D.3).

Parent process only: the worker never imports this module, because it reads the deployment configuration and asks
whether a secret provider is registered.
"""

from enum import StrEnum

from docpipe.integrations.secrets.secret_provider import has_registered_provider
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

CUSTOM_OPERATORS_CONFIG_SECTION = "custom_operators"
ISOLATION_KEY = "isolation"


class IsolationMode(StrEnum):
    """How an untrusted custom operator may run.

    ``PROCESS`` and ``DISABLED`` are the values a deployer can set. ``IN_PROCESS`` is the behavior from before the
    secret-management change; it applies only when no secret provider is registered and the setting is absent.
    """

    PROCESS = "process"
    DISABLED = "disabled"
    IN_PROCESS = "in_process"


def resolve_isolation_mode() -> IsolationMode:
    """Return the isolation mode for untrusted custom operators.

    An unset setting means ``DISABLED`` while a secret provider is registered and ``IN_PROCESS`` (unchanged
    behavior) otherwise. A value that is neither ``process`` nor ``disabled`` is a configuration error and
    resolves to ``DISABLED``, so a typo can never loosen the boundary.
    """
    section = DocpipeConfigLoader.get_config().get(CUSTOM_OPERATORS_CONFIG_SECTION)
    value = section.get(ISOLATION_KEY) if isinstance(section, dict) else None
    if value is None:
        return IsolationMode.DISABLED if has_registered_provider() else IsolationMode.IN_PROCESS
    if isinstance(value, str) and value.strip().lower() in (IsolationMode.PROCESS, IsolationMode.DISABLED):
        return IsolationMode(value.strip().lower())
    logger.error(
        "Invalid 'custom_operators.isolation' setting; expected 'process' or 'disabled'. "
        "Untrusted custom operators are not permitted until it is corrected."
    )
    return IsolationMode.DISABLED
