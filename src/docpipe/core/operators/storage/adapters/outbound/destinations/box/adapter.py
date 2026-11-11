# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Box destination adapter — writes documents via the box-sdk-gen library."""

from io import BytesIO
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from docpipe.core.operators.ingest.adapters.outbound.sources.box.auth import get_box_client
from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.core.operators.storage.adapters.outbound.destinations.box.config import (
    BoxDestinationConfig,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
    register_destination_adapter,
)
from docpipe.core.operators.storage.domain.models import WriteResult
from docpipe.core.operators.storage.ports.outbound.destination_adapter import DestinationAdapterPort
from docpipe.integrations.secrets.secret_value import reveal_value
from docpipe.utils.infrastructure.exception_sanitizer import sanitize_exception
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Lazy import guard — box-sdk-gen is an optional dependency.
try:
    from box_sdk_gen import (
        BoxClient,
        BoxJWTAuth,
        CreateFolderParent,
        JWTConfig,
        UploadFileAttributes,
        UploadFileAttributesParentField,
    )

    _BOX_AVAILABLE = True
except ImportError:
    BoxClient = None  # type: ignore[assignment,misc]
    BoxJWTAuth = None  # type: ignore[assignment,misc]
    JWTConfig = None  # type: ignore[assignment,misc]
    CreateFolderParent = None  # type: ignore[assignment,misc]
    UploadFileAttributes = None  # type: ignore[assignment,misc]
    UploadFileAttributesParentField = None  # type: ignore[assignment,misc]
    _BOX_AVAILABLE = False

_BOX_INSTALL_HINT = "box-sdk-gen is not installed. Install with: uv pip install 'docling-pipelines[box]'"


@register_destination_adapter
class BoxDestinationAdapter(DestinationAdapterPort[BoxDestinationConfig]):
    """Write documents to a Box folder via the box-sdk-gen library.

    Uses Box JWT / App Authentication, the same mechanism as BoxSourceAdapter.
    Folder creation is performed on-demand when ``create_dirs`` is enabled;
    resolved folder IDs are cached per adapter instance to minimise API calls
    within a single operator run.
    """

    DEST_NAME = "box"
    DEST_DISPLAY_NAME = "Box"
    DEST_VERSION = "1.0.0"

    def __init__(self) -> None:
        super().__init__()
        # Cache: maps (parent_folder_id, folder_name) -> child_folder_id
        self._folder_id_cache: dict[tuple[str, str], str] = {}

    # ------------------------------------------------------------------
    # DestinationAdapterPort interface
    # ------------------------------------------------------------------

    def validate_destination(
        self,
        *,
        config: BoxDestinationConfig | None = None,
    ) -> WriteResult | None:
        """Verify that the target Box folder is reachable before any content is fetched.

        Returns a failed WriteResult on the first problem, or None when all is well.
        """
        if not _BOX_AVAILABLE:
            return WriteResult(
                doc_id="",
                doc_name="",
                success=False,
                error_message=_BOX_INSTALL_HINT,
            )
        if config is None:
            return None

        try:
            client = self._get_box_client(config)
            folder = client.folders.get_folder_by_id(config.folder_id)
            logger.info(
                "Box destination validated: folder_id=%s, name=%s, create_dirs=%s",
                config.folder_id,
                getattr(folder, "name", "unknown"),
                config.create_dirs,
            )
        except Exception as e:
            safe_error = sanitize_exception(exc=e, config_key="storage_output.destination_config.box")
            msg = f"Box destination validation failed: folder_id={config.folder_id}, error={safe_error}"
            logger.error(msg)
            return WriteResult(doc_id="", doc_name="", success=False, error_message=msg)

        return None

    def write_document(
        self,
        *,
        content: bytes,
        destination_path: str,
        overwrite: bool = True,
        config: BoxDestinationConfig | None = None,
    ) -> WriteResult:
        """Upload bytes to Box at destination_path.

        ``destination_path`` is the relative path within the root folder,
        already resolved by ``resolve_destination_path``. Intermediate
        sub-folders are created when ``config.create_dirs`` is True.
        """
        if not _BOX_AVAILABLE:
            return WriteResult(
                doc_id="",
                doc_name=destination_path,
                success=False,
                error_message=_BOX_INSTALL_HINT,
            )
        if config is None:
            return WriteResult(
                doc_id="",
                doc_name=destination_path,
                success=False,
                error_message="BoxDestinationConfig is required",
            )

        try:
            client = self._get_box_client(config)
            path = Path(destination_path)
            filename = path.name
            parent_relative = str(path.parent) if str(path.parent) != "." else ""

            # Resolve the target parent folder ID, creating sub-folders as needed.
            parent_folder_id = self._resolve_folder_id(
                client=client,
                relative_dir=parent_relative,
                root_folder_id=config.folder_id,
                create_dirs=config.create_dirs,
            )

            if not overwrite:
                existing_id = self._find_existing_file(
                    client=client,
                    filename=filename,
                    parent_folder_id=parent_folder_id,
                )
                if existing_id is not None:
                    return WriteResult(
                        doc_id="",
                        doc_name=destination_path,
                        success=False,
                        error_message="file exists, overwrite disabled",
                    )

            logger.info(
                "Uploading to Box: parent_folder_id=%s, filename=%s, size=%d bytes",
                parent_folder_id,
                filename,
                len(content),
            )

            attributes = UploadFileAttributes(
                name=filename,
                parent=UploadFileAttributesParentField(id=parent_folder_id),
            )
            uploaded_files = client.uploads.upload_file(
                attributes=attributes,
                file=BytesIO(content),
            )

            uploaded_file = uploaded_files.entries[0] if uploaded_files.entries else None
            file_id = str(getattr(uploaded_file, "id", "")) if uploaded_file else ""

            # Construct a stable web URL from the file ID.
            web_url = f"https://app.box.com/file/{file_id}" if file_id else destination_path

            logger.info("Successfully uploaded %d bytes to Box: %s", len(content), web_url)
            return WriteResult(
                doc_id="",
                doc_name=destination_path,
                success=True,
                destination_path=web_url,
                bytes_written=len(content),
            )

        except Exception as e:
            safe_error = sanitize_exception(exc=e, config_key="storage_output.destination_config.box")
            msg = f"Unexpected error writing to Box '{destination_path}': {safe_error}"
            logger.error(msg)
            return WriteResult(doc_id="", doc_name=destination_path, success=False, error_message=msg)

    def ensure_directory(self, *, path: str) -> None:
        """No-op — sub-folder creation is handled lazily inside write_document."""

    def resolve_destination_path(
        self,
        *,
        relative_path: str,
        config: BoxDestinationConfig,
    ) -> str:
        """Return relative_path unchanged.

        Box is folder-ID-based, not string-path-based. The string path is used
        only as a human-readable label; actual placement is resolved to a folder
        ID inside write_document via _resolve_folder_id.
        """
        return relative_path

    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> BoxDestinationConfig:
        """Build BoxDestinationConfig from operator flow params.

        Expected flow config shape::

            provider_config:
                folder_id: "123456789"   # target Box folder ID; "0" = root
                create_dirs: true

            credentials:
                credentials_json_path: "${BOX_CONFIG_PATH}"
        """
        provider_config = reveal_value(provider_config)
        credentials = reveal_value(credentials)
        credentials_path = resolve_env_var(credentials.get("credentials_json_path"))
        if not credentials_path:
            raise ValueError("Missing required Box credential: 'credentials_json_path'")

        folder_id = resolve_env_var(provider_config.get("folder_id")) or "0"

        return BoxDestinationConfig(
            credentials_path=credentials_path,
            folder_id=folder_id,
            create_dirs=provider_config.get("create_dirs", True),
        )

    def get_config_schema(self) -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        return BoxDestinationConfig

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_box_client(self, config: BoxDestinationConfig) -> Any:
        """Return an authenticated BoxClient using JWT / App Authentication."""
        return get_box_client(credentials_path=config.credentials_path)

    def _resolve_folder_id(
        self,
        *,
        client: Any,
        relative_dir: str,
        root_folder_id: str,
        create_dirs: bool,
    ) -> str:
        """Walk or create the sub-folder hierarchy and return the leaf folder ID.

        ``relative_dir`` is the directory portion of the destination path
        (e.g. ``"sub01/sub02"``). Each path segment is resolved against the
        previous folder, using the instance-level cache to minimise API calls
        across documents in the same batch.
        """
        if not relative_dir:
            return root_folder_id

        current_id = root_folder_id
        for segment in Path(relative_dir).parts:
            cache_key = (current_id, segment)
            if cache_key in self._folder_id_cache:
                current_id = self._folder_id_cache[cache_key]
                continue

            existing_id = self._find_subfolder_id(
                client=client,
                name=segment,
                parent_id=current_id,
            )
            if existing_id is not None:
                self._folder_id_cache[cache_key] = existing_id
                current_id = existing_id
            elif create_dirs:
                new_id = self._create_subfolder(
                    client=client,
                    name=segment,
                    parent_id=current_id,
                )
                self._folder_id_cache[cache_key] = new_id
                current_id = new_id
            else:
                raise FileNotFoundError(
                    f"Destination sub-folder '{segment}' does not exist under folder_id='{current_id}' "
                    "and create_dirs is disabled."
                )

        return current_id

    def _find_subfolder_id(
        self,
        *,
        client: Any,
        name: str,
        parent_id: str,
    ) -> str | None:
        """Return the Box folder ID of a named sub-folder, or None if not found."""
        try:
            items = client.folders.get_folder_items(parent_id)
            for entry in items.entries or []:
                if getattr(entry, "type", None) == "folder" and getattr(entry, "name", None) == name:
                    return str(entry.id)
        except Exception as e:
            logger.error(
                "Error listing Box folder items for parent_id=%s: %s",
                parent_id,
                sanitize_exception(exc=e, config_key="storage_output.destination_config.box"),
            )
        return None

    def _find_existing_file(
        self,
        *,
        client: Any,
        filename: str,
        parent_folder_id: str,
    ) -> str | None:
        """Return the Box file ID if a file with the given name exists in the folder, else None."""
        try:
            items = client.folders.get_folder_items(parent_folder_id)
            for entry in items.entries or []:
                if getattr(entry, "type", None) == "file" and getattr(entry, "name", None) == filename:
                    return str(entry.id)
        except Exception as e:
            logger.error(
                "Error checking for existing file '%s' in Box folder_id=%s: %s",
                filename,
                parent_folder_id,
                sanitize_exception(exc=e, config_key="storage_output.destination_config.box"),
            )
        return None

    def _create_subfolder(
        self,
        *,
        client: Any,
        name: str,
        parent_id: str,
    ) -> str:
        """Create a sub-folder named ``name`` under ``parent_id`` and return its ID."""
        logger.info("Creating Box sub-folder: name=%s, parent_id=%s", name, parent_id)
        created = client.folders.create_folder(
            name=name,
            parent=CreateFolderParent(id=parent_id),
        )
        return str(created.id)
