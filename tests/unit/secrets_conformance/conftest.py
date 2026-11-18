# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Shared state reset for the secret conformance suite."""

from collections.abc import Generator

import pytest

from docpipe.core.orchestration.operator_loader.isolation.worker_client import get_worker_pool
from docpipe.integrations.secrets.registry import get_registry
from docpipe.integrations.secrets.secret_provider import clear_providers
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader


@pytest.fixture(autouse=True)
def _clean_secret_state() -> Generator[None, None, None]:
    """Start and end every test without providers, policy, registry entries or isolation workers."""
    clear_providers()
    DocpipeConfigLoader.reset()
    get_registry().clear_all()
    yield
    get_worker_pool().release_all()
    get_registry().clear_all()
    clear_providers()
    DocpipeConfigLoader.reset()
