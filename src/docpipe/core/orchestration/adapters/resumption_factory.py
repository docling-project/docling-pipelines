# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Factory wiring the resumption service to its storage adapter."""

from typing import Any

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.data_access.data_access_utils import DataAccessConstants
from docpipe.core.orchestration.adapters.filesystem_resumption_store import FilesystemResumptionStore
from docpipe.core.orchestration.application.services.resumption_service import ResumptionService


def is_resumption_enabled(*, config: dict[str, Any]) -> bool:
    """Resumption needs durable checkpoints, so it is only active with local intermediate storage."""
    return config.get(DocpipeConstants.DATA_STORAGE_TYPE, "") == DataAccessConstants.LOCAL


def create_resumption_service(*, config: dict[str, Any]) -> ResumptionService | None:
    """Create a ResumptionService for the given flow/operator config, or None when resumption is inactive."""
    if not is_resumption_enabled(config=config):
        return None
    return ResumptionService(
        store=FilesystemResumptionStore(),
        max_retry_attempts=int(
            config.get(DocpipeConstants.MAX_RETRY_ATTEMPTS, DocpipeConstants.DEFAULT_MAX_RETRY_ATTEMPTS)
        ),
    )
