# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Google Drive destination adapter — writes documents via the Google Drive API v3."""

import mimetypes
from io import BytesIO
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials  # noqa: F401
from google.oauth2.service_account import Credentials as ServiceAccountCredentials  # noqa: F401
from googleapiclient.discovery import build as _gdrive_build
from googleapiclient.http import MediaIoBaseUpload
from pydantic import BaseModel

from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
    register_destination_adapter,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.google_drive.config import (
    GoogleDriveDestinationConfig,
)
from docpipe.core.operators.storage.domain.models import WriteResult
from docpipe.core.operators.storage.ports.outbound.destination_adapter import DestinationAdapterPort
from docpipe.utils.infrastructure.exception_sanitizer import sanitize_exception
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

_GDRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"


@register_destination_adapter
class GoogleDriveDestinationAdapter(DestinationAdapterPort[GoogleDriveDestinationConfig]):
    """Write documents to a Google Drive folder via the Drive API v3.

    Supports both Service Account (recommended for pipelines) and OAuth2
    authentication.  Folder creation is performed on-demand when ``create_dirs``
    is enabled; resolved folder IDs are cached per adapter instance to minimise
    API calls within a single operator run.
    """

    DEST_NAME = "google_drive"
    DEST_DISPLAY_NAME = "Google Drive"
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
        config: GoogleDriveDestinationConfig | None = None,
    ) -> WriteResult | None:
        """Verify that the target folder is reachable before any content is fetched.

        Returns a failed WriteResult on the first problem, or None when all is well.
        """
        if config is None:
            return None

        try:
            service = self._build_service(config)
            kwargs: dict[str, Any] = {
                "fileId": config.folder_id,
                "fields": "id,name,mimeType",
                "supportsAllDrives": True,
            }
            if config.drive_id:
                kwargs["driveId"] = config.drive_id
            file_meta = service.files().get(**kwargs).execute()
            if file_meta.get("mimeType") != _GDRIVE_FOLDER_MIME:
                msg = (
                    f"Google Drive destination folder_id '{config.folder_id}' "
                    f"is not a folder (mimeType={file_meta.get('mimeType')})"
                )
                logger.error(msg)
                return WriteResult(doc_id="", doc_name="", success=False, error_message=msg)

            logger.info(
                "Google Drive destination validated: folder_id=%s, name=%s, create_dirs=%s",
                config.folder_id,
                file_meta.get("name"),
                config.create_dirs,
            )
        except Exception as e:
            safe_error = sanitize_exception(exc=e, config_key="storage_output.destination_config.google_drive")
            msg = f"Google Drive destination validation failed: folder_id={config.folder_id}, error={safe_error}"
            logger.error(msg)
            return WriteResult(doc_id="", doc_name="", success=False, error_message=msg)

        return None

    def write_document(
        self,
        *,
        content: bytes,
        destination_path: str,
        overwrite: bool = True,
        config: GoogleDriveDestinationConfig | None = None,
    ) -> WriteResult:
        """Upload bytes to Google Drive at destination_path.

        ``destination_path`` is the relative path within the root folder,
        already resolved by ``resolve_destination_path``.  Intermediate
        directories are created when ``config.create_dirs`` is True.
        """
        if config is None:
            return WriteResult(
                doc_id="",
                doc_name=destination_path,
                success=False,
                error_message="GoogleDriveDestinationConfig is required",
            )

        try:
            service = self._build_service(config)
            path = Path(destination_path)
            filename = path.name
            parent_relative = str(path.parent) if str(path.parent) != "." else ""

            # Resolve the target parent folder ID, creating dirs as needed.
            parent_folder_id = self._resolve_folder_id(
                service=service,
                relative_dir=parent_relative,
                root_folder_id=config.folder_id,
                drive_id=config.drive_id,
                create_dirs=config.create_dirs,
            )

            if not overwrite:
                existing_id = self._find_file_id(
                    service=service,
                    name=filename,
                    parent_id=parent_folder_id,
                    drive_id=config.drive_id,
                )
                if existing_id:
                    return WriteResult(
                        doc_id="",
                        doc_name=destination_path,
                        success=False,
                        error_message="file exists, overwrite disabled",
                    )

            mime_type = self._guess_mime_type(filename)
            file_metadata: dict[str, Any] = {
                "name": filename,
                "parents": [parent_folder_id],
            }
            if config.drive_id:
                file_metadata["driveId"] = config.drive_id

            chunk_size = config.chunk_size_mb * 1024 * 1024
            media = MediaIoBaseUpload(BytesIO(content), mimetype=mime_type, chunksize=chunk_size, resumable=True)

            create_kwargs: dict[str, Any] = {
                "body": file_metadata,
                "media_body": media,
                "fields": "id,webViewLink",
            }
            if config.drive_id:
                create_kwargs["supportsAllDrives"] = True

            logger.info(
                "Uploading to Google Drive: folder_id=%s, filename=%s, size=%d bytes",
                parent_folder_id,
                filename,
                len(content),
            )
            uploaded = service.files().create(**create_kwargs).execute()

            web_link = uploaded.get("webViewLink", destination_path)
            logger.info("Successfully uploaded %d bytes to Google Drive: %s", len(content), web_link)
            return WriteResult(
                doc_id="",
                doc_name=destination_path,
                success=True,
                destination_path=web_link,
                bytes_written=len(content),
            )

        except Exception as e:
            safe_error = sanitize_exception(exc=e, config_key="storage_output.destination_config.google_drive")
            msg = f"Unexpected error writing to Google Drive '{destination_path}': {safe_error}"
            logger.error(msg)
            return WriteResult(doc_id="", doc_name=destination_path, success=False, error_message=msg)

    def ensure_directory(self, *, path: str) -> None:
        """No-op — directory creation is handled lazily inside write_document."""

    def resolve_destination_path(
        self,
        *,
        relative_path: str,
        config: GoogleDriveDestinationConfig,
    ) -> str:
        """Return the relative_path unchanged.

        Google Drive paths are resolved to folder IDs inside write_document;
        the string path is used only as a human-readable label.
        """
        return relative_path

    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> GoogleDriveDestinationConfig:
        """Build GoogleDriveDestinationConfig from operator flow params.

        Supports Service Account or OAuth2 credentials::

            provider_config:
                folder_id: "${GDRIVE_FOLDER_ID}"
                drive_id: null           # optional shared drive
                create_dirs: true

            credentials (Service Account):
                service_account_json_path: "${GDRIVE_SA_JSON_PATH}"

            credentials (OAuth2):
                credentials_path: "${GDRIVE_OAUTH_CREDENTIALS_PATH}"
                token_path: "~/.docpipe/gdrive_token.pickle"  # optional
        """
        folder_id = resolve_env_var(provider_config.get("folder_id"))
        if not folder_id:
            raise ValueError("Missing required Google Drive connection parameter: 'folder_id'")

        config_dict: dict[str, Any] = {
            "folder_id": folder_id,
            "create_dirs": provider_config.get("create_dirs", True),
            "scopes": credentials.get("scopes", ["https://www.googleapis.com/auth/drive"]),
        }

        drive_id = resolve_env_var(provider_config.get("drive_id"))
        if drive_id:
            config_dict["drive_id"] = drive_id

        chunk_size_mb = provider_config.get("chunk_size_mb")
        if chunk_size_mb is not None:
            config_dict["chunk_size_mb"] = int(chunk_size_mb)

        sa_path = resolve_env_var(credentials.get("service_account_json_path"))
        oauth_path = resolve_env_var(credentials.get("credentials_path"))

        if sa_path:
            config_dict["service_account_json_path"] = sa_path
        elif oauth_path:
            config_dict["credentials_path"] = oauth_path
            token_path = resolve_env_var(credentials.get("token_path"))
            if token_path:
                config_dict["token_path"] = token_path
        else:
            raise ValueError(
                "Missing required Google Drive credential: provide either "
                "'service_account_json_path' or 'credentials_path'."
            )

        return GoogleDriveDestinationConfig(**config_dict)

    def get_config_schema(self) -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        return GoogleDriveDestinationConfig

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_service(self, config: GoogleDriveDestinationConfig) -> Any:
        """Build an authenticated Google Drive API service client."""
        # Import the ingest-side adapter to reuse its _get_credentials() logic,
        # avoiding duplication of the OAuth2 / Service Account auth flow.
        from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.adapter import (
            GoogleDriveSourceAdapter,
        )
        from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.config import (
            GoogleDriveSourceConfig,
        )

        # Build a minimal source config solely for credential resolution.
        source_config_dict: dict[str, Any] = {
            "folder_id": config.folder_id or "root",
            "scopes": config.scopes,
            "recursive": False,
            "file_extensions": [],
            "exclude_patterns": [],
        }
        if config.is_service_account():
            source_config_dict["service_account_json_path"] = config.service_account_json_path
        else:
            source_config_dict["credentials_path"] = config.credentials_path
            token_path = config.get_token_path()
            if token_path:
                source_config_dict["token_path"] = token_path

        source_config = GoogleDriveSourceConfig(**source_config_dict)
        creds = GoogleDriveSourceAdapter()._get_credentials(source_config)
        return _gdrive_build("drive", "v3", credentials=creds)

    def _resolve_folder_id(
        self,
        *,
        service: Any,
        relative_dir: str,
        root_folder_id: str,
        drive_id: str | None,
        create_dirs: bool,
    ) -> str:
        """Walk or create the folder hierarchy and return the leaf folder ID.

        ``relative_dir`` is the directory portion of the destination path
        (e.g. ``"sub01/sub02"``).  Each path segment is resolved against the
        previous folder, using the instance-level cache to avoid redundant
        API calls across documents in the same batch.
        """
        if not relative_dir:
            return root_folder_id

        current_id = root_folder_id
        for segment in Path(relative_dir).parts:
            cache_key = (current_id, segment)
            if cache_key in self._folder_id_cache:
                current_id = self._folder_id_cache[cache_key]
                continue

            existing_id = self._find_folder_id(
                service=service,
                name=segment,
                parent_id=current_id,
                drive_id=drive_id,
            )
            if existing_id:
                self._folder_id_cache[cache_key] = existing_id
                current_id = existing_id
            elif create_dirs:
                new_id = self._create_folder(
                    service=service,
                    name=segment,
                    parent_id=current_id,
                    drive_id=drive_id,
                )
                self._folder_id_cache[cache_key] = new_id
                current_id = new_id
            else:
                raise FileNotFoundError(
                    f"Destination folder '{segment}' does not exist under folder_id='{current_id}' "
                    "and create_dirs is disabled."
                )

        return current_id

    def _find_folder_id(
        self,
        *,
        service: Any,
        name: str,
        parent_id: str,
        drive_id: str | None,
    ) -> str | None:
        """Return the Drive ID of an existing subfolder, or None if not found."""
        query = f"name='{name}' and mimeType='{_GDRIVE_FOLDER_MIME}' and '{parent_id}' in parents and trashed=false"
        list_kwargs: dict[str, Any] = {
            "q": query,
            "spaces": "drive",
            "fields": "files(id)",
            "pageSize": 1,
        }
        if drive_id:
            list_kwargs["driveId"] = drive_id
            list_kwargs["corpora"] = "drive"
            list_kwargs["includeItemsFromAllDrives"] = True
            list_kwargs["supportsAllDrives"] = True

        result = service.files().list(**list_kwargs).execute()
        files = result.get("files", [])
        return files[0]["id"] if files else None

    def _find_file_id(
        self,
        *,
        service: Any,
        name: str,
        parent_id: str,
        drive_id: str | None,
    ) -> str | None:
        """Return the Drive ID of an existing file in parent_id, or None."""
        escaped_name = name.replace("'", "\\'")
        query = f"name='{escaped_name}' and '{parent_id}' in parents and trashed=false"
        list_kwargs: dict[str, Any] = {
            "q": query,
            "spaces": "drive",
            "fields": "files(id)",
            "pageSize": 1,
        }
        if drive_id:
            list_kwargs["driveId"] = drive_id
            list_kwargs["corpora"] = "drive"
            list_kwargs["includeItemsFromAllDrives"] = True
            list_kwargs["supportsAllDrives"] = True

        result = service.files().list(**list_kwargs).execute()
        files = result.get("files", [])
        return files[0]["id"] if files else None

    def _create_folder(
        self,
        *,
        service: Any,
        name: str,
        parent_id: str,
        drive_id: str | None,
    ) -> str:
        """Create a folder named ``name`` under ``parent_id`` and return its ID."""
        metadata: dict[str, Any] = {
            "name": name,
            "mimeType": _GDRIVE_FOLDER_MIME,
            "parents": [parent_id],
        }
        if drive_id:
            metadata["driveId"] = drive_id

        create_kwargs: dict[str, Any] = {"body": metadata, "fields": "id"}
        if drive_id:
            create_kwargs["supportsAllDrives"] = True

        logger.info("Creating Google Drive folder: name=%s, parent_id=%s", name, parent_id)
        created = service.files().create(**create_kwargs).execute()
        return created["id"]

    @staticmethod
    def _guess_mime_type(filename: str) -> str:
        """Guess the MIME type from the filename extension, falling back to octet-stream."""
        mime, _ = mimetypes.guess_type(filename)
        return mime or "application/octet-stream"
