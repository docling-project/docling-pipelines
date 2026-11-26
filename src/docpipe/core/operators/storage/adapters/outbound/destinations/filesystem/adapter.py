# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Filesystem destination adapter implementation."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
    register_destination_adapter,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.filesystem.config import (
    FilesystemDestinationConfig,
)
from docpipe.core.operators.storage.domain.models import WriteResult
from docpipe.core.operators.storage.ports.outbound.destination_adapter import DestinationAdapterPort
from docpipe.integrations.secrets.secret_value import reveal_value
from docpipe.utils.infrastructure.exception_sanitizer import sanitize_exception
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@register_destination_adapter
class FilesystemDestinationAdapter(DestinationAdapterPort[FilesystemDestinationConfig]):
    """Write documents to a local filesystem destination."""

    DEST_NAME = "filesystem"
    DEST_DISPLAY_NAME = "Local Filesystem"
    DEST_VERSION = "1.0.0"

    def validate_destination(
        self,
        *,
        config: FilesystemDestinationConfig | None = None,
    ) -> "WriteResult | None":
        """Validate destination."""
        if config is None:
            return None
        root = Path(config.root_path)
        if not root.exists():
            if not config.create_dirs:
                return WriteResult(
                    doc_id="",
                    doc_name="",
                    success=False,
                    error_message=f"destination directory does not exist and create_dirs is disabled: {root}",
                )
        return None

    def write_document(
        self,
        *,
        content: bytes,
        destination_path: str,
        overwrite: bool = True,
        config: FilesystemDestinationConfig | None = None,
    ) -> WriteResult:
        """Write document."""
        path = Path(destination_path)

        if not overwrite and path.exists():
            return WriteResult(
                doc_id="",
                doc_name=path.name,
                success=False,
                error_message="file exists, overwrite disabled",
            )

        create_dirs = config.create_dirs if config is not None else True
        if not path.parent.exists():
            if not create_dirs:
                return WriteResult(
                    doc_id="",
                    doc_name=path.name,
                    success=False,
                    error_message=f"destination directory does not exist and create_dirs is disabled: {path.parent}",
                )
            path.parent.mkdir(parents=True, exist_ok=True)

        try:
            logger.info("Writing binary content to filesystem: path=%s", destination_path)
            path.write_bytes(content)
            logger.info("Successfully wrote %d bytes to filesystem: %s", len(content), destination_path)
            return WriteResult(
                doc_id="",
                doc_name=path.name,
                success=True,
                destination_path=destination_path,
                bytes_written=len(content),
            )
        except Exception as e:
            return WriteResult(
                doc_id="",
                doc_name=path.name,
                success=False,
                error_message=sanitize_exception(exc=e, config_key="storage_output.destination_config.filesystem"),
            )

    def ensure_directory(self, *, path: str) -> None:
        """Ensure directory."""
        Path(path).mkdir(parents=True, exist_ok=True)

    def resolve_destination_path(
        self,
        *,
        relative_path: str,
        config: FilesystemDestinationConfig,
    ) -> str:
        """Prepend the filesystem root_path to produce an absolute path."""
        return str(Path(config.root_path) / relative_path)

    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> FilesystemDestinationConfig:
        """Build config from operator params."""
        provider_config = reveal_value(provider_config)
        credentials = reveal_value(credentials)
        return FilesystemDestinationConfig(
            root_path=provider_config["root_path"],
            create_dirs=provider_config.get("create_dirs", True),
        )

    def get_config_schema(self) -> type[BaseModel]:
        """Get config schema."""
        return FilesystemDestinationConfig
