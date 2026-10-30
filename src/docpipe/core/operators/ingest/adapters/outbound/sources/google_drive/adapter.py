"""Google Drive source adapter using Google Drive API."""

import hashlib
import json
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import register_source_adapter
from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.config import GoogleDriveSourceConfig
from docpipe.core.operators.ingest.domain.models import Document
from docpipe.core.operators.ingest.ports.outbound.document_source import DocumentSourcePort
from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@register_source_adapter
class GoogleDriveSourceAdapter(DocumentSourcePort):
    """
    Adapter for ingesting documents from Google Drive using Google Drive API.

    Features:
    - OAuth2 authentication with token caching (for user access)
    - Service Account authentication (for server-to-server access)
    - Automatic token refresh
    - Recursive folder traversal
    - Automatic export of Google Workspace files:
      - Google Docs → PDF
      - Google Sheets → XLSX
      - Google Slides → PDF
      - Google Drawings → PDF
    - File extension filtering
    - Lazy loading for performance optimization
    """

    # Metadata for connector discovery
    SOURCE_NAME = "google_drive"
    SOURCE_DISPLAY_NAME = "Google Drive"
    SOURCE_DESCRIPTION = "Ingest documents from Google Drive using Google Drive API"
    SOURCE_VERSION = "3.0.0"

    def __init__(self) -> None:
        # Cache (creds, service) keyed by a hash of the credentials config so a single
        # Drive API client is reused for all documents in a batch.
        self._service_cache: dict[str, tuple[Any, Any]] = {}

    @staticmethod
    def bind_file_reference(*, provider_config: dict[str, Any], file_reference: str) -> None:
        """Set a Google Drive file ID as the single file to ingest.

        ``file_reference`` is the Drive file ID the producer supplies for the
        event; batch ingestion (``fetch_documents``) already accepts a file ID
        via ``file_id`` and fetches/validates it against the Drive API, so this
        only does basic input validation rather than duplicating that call here.
        """
        if not file_reference or not file_reference.strip():
            raise ValueError("File reference must be a non-empty Google Drive file ID")

        provider_config["file_id"] = file_reference

    @staticmethod
    def _credentials_cache_key(config: GoogleDriveSourceConfig) -> str:
        """Return a stable cache key for the given credentials configuration."""
        sa_json_str = ""
        if config.service_account_json:
            sa_json_str = (
                json.dumps(config.service_account_json, sort_keys=True)
                if isinstance(config.service_account_json, dict)
                else str(config.service_account_json)
            )

        oauth_json_str = ""
        if config.credentials_json:
            oauth_json_str = (
                json.dumps(config.credentials_json, sort_keys=True)
                if isinstance(config.credentials_json, dict)
                else str(config.credentials_json)
            )

        key_material = json.dumps(
            {
                "service_account_json": sa_json_str,
                "service_account_json_path": config.service_account_json_path,
                "credentials_json": oauth_json_str,
                "credentials_path": config.credentials_path,
                "scopes": sorted(config.scopes),
            },
            sort_keys=True,
        )
        return hashlib.sha256(key_material.encode()).hexdigest()

    @staticmethod
    def _load_service_account_credentials(config: GoogleDriveSourceConfig) -> ServiceAccountCredentials:
        """Load service account credentials from inline JSON or file, raising clear errors on failure."""
        if config.service_account_json is not None:
            try:
                info = (
                    config.service_account_json
                    if isinstance(config.service_account_json, dict)
                    else json.loads(config.service_account_json)
                )
                return ServiceAccountCredentials.from_service_account_info(info, scopes=config.scopes)
            except Exception as e:
                msg = f"Failed to load service account credentials from inline service_account_json: {e}"
                raise ValueError(msg) from e

        service_account_path = None
        try:
            if config.service_account_json_path is None:
                msg = "Service account JSON or path must be provided"
                raise ValueError(msg)
            service_account_path = Path(config.service_account_json_path)
            if not service_account_path.exists():
                msg = f"Service account file not found: {service_account_path}"
                raise FileNotFoundError(msg)
            if not service_account_path.is_file():
                msg = f"Service account path is not a file: {service_account_path}"
                raise ValueError(msg)
            return ServiceAccountCredentials.from_service_account_file(str(service_account_path), scopes=config.scopes)
        except PermissionError as e:
            msg = f"Permission denied accessing service account file: {service_account_path}. Original error: {e}"
            raise PermissionError(msg) from e
        except Exception as e:
            msg = f"Failed to load service account credentials from {service_account_path}: {e}"
            raise ValueError(msg) from e

    @staticmethod
    def _refresh_or_run_oauth_flow(
        *,
        creds: Credentials | None,
        credentials_path: Path | None = None,
        token_path: Path,
        scopes: list[str],
        credentials_json: dict | str | None = None,
    ) -> Credentials:
        """Return valid OAuth2 credentials, refreshing or re-running the flow as needed."""
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            try:
                if credentials_json:
                    info = credentials_json if isinstance(credentials_json, dict) else json.loads(credentials_json)
                    flow = InstalledAppFlow.from_client_config(info, scopes=scopes)
                elif credentials_path:
                    if not credentials_path.exists():
                        msg = f"Credentials file not found: {credentials_path}"
                        raise FileNotFoundError(msg)
                    if not credentials_path.is_file():
                        msg = f"Credentials path is not a file: {credentials_path}"
                        raise ValueError(msg)
                    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), scopes=scopes)
                else:
                    msg = "Either credentials_json or credentials_path must be provided for OAuth"
                    raise ValueError(msg)

                creds = flow.run_local_server(port=0)
            except PermissionError as e:
                msg = (
                    f"Permission denied accessing credentials: {credentials_path}. "
                    "On macOS, you may need to grant Terminal/Python access to the file location in "
                    "System Preferences > Security & Privacy > Files and Folders. "
                    f"Original error: {e}"
                )
                raise PermissionError(msg) from e
            except Exception as e:
                msg = f"Failed to load OAuth credentials: {e}"
                raise ValueError(msg) from e

        token_path.parent.mkdir(parents=True, exist_ok=True)
        with Path(token_path).open("w") as token:
            token.write(creds.to_json())

        return creds

    def _get_credentials(self, config: GoogleDriveSourceConfig) -> Credentials | ServiceAccountCredentials:
        """
        Get or create credentials for Google Drive API.

        Supports two authentication methods:
        1. OAuth2 (user authentication): Interactive flow with token caching
        2. Service Account (server-to-server): Non-interactive authentication
        """
        if config.is_service_account():
            return self._load_service_account_credentials(config)

        if config.credentials_json is None and config.credentials_path is None:
            msg = "OAuth credentials_json or credentials_path is required"
            raise ValueError(msg)

        token_path_str = config.get_token_path() or str(Path.home() / ".docpipe" / "google_drive_token.json")
        token_path = Path(token_path_str)
        credentials_path = Path(config.credentials_path) if config.credentials_path else None

        creds = None
        if token_path.exists():
            try:
                with Path(token_path).open("r") as token:
                    creds = Credentials.from_authorized_user_info(json.loads(token.read()))
            except Exception:
                logger.debug("Failed to load cached token from %s, will re-authenticate", token_path)

        if not creds or not creds.valid:
            creds = self._refresh_or_run_oauth_flow(
                creds=creds,
                credentials_json=config.credentials_json,
                credentials_path=credentials_path,
                token_path=token_path,
                scopes=config.scopes,
            )

        return creds

    def _prepare_document(self, *, file_metadata: dict, config: GoogleDriveSourceConfig) -> Document:
        """
        Convert Google Drive file metadata to domain document model (lazy loading).

        Creates document with metadata only, no binary content download.
        Binary content is fetched on-demand by Extract operator.
        """
        doc_id = file_metadata.get(OperatorConstants.Columns.ID, "")
        doc_name = file_metadata.get(OperatorConstants.Columns.NAME, "unknown")

        # Parse modified time if available
        modified_time = None
        modified_time_str = file_metadata.get("modifiedTime")
        if modified_time_str:
            try:
                modified_time = datetime.fromisoformat(modified_time_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Get file size
        file_size = int(file_metadata.get("size", 0))

        # Get mime type
        mime_type = file_metadata.get("mimeType", "application/octet-stream")

        # Get file extension
        extension = Path(doc_name).suffix.lower()

        # For Google Workspace files, derive extension from MIME type
        if not extension and mime_type.startswith(OperatorConstants.MimeTypes.GOOGLE_APPS_PREFIX):
            workspace_extensions = {
                OperatorConstants.MimeTypes.GOOGLE_APPS_DOCUMENT: ".docx",
                OperatorConstants.MimeTypes.GOOGLE_APPS_SPREADSHEET: ".xlsx",
                OperatorConstants.MimeTypes.GOOGLE_APPS_PRESENTATION: ".pptx",
                OperatorConstants.MimeTypes.GOOGLE_APPS_DRAWING: ".pdf",
            }
            extension = workspace_extensions.get(mime_type, extension)

        # Build source URL
        source_url = file_metadata.get("webViewLink", f"https://drive.google.com/file/d/{doc_id}")

        return Document(
            id=doc_id,
            name=doc_name,
            content=b"",  # Empty - binary loaded on-demand by downstream operators
            source_url=source_url,
            modified_time=modified_time,
            mimetype=mime_type,
            size=file_size,
            extension=extension,
            metadata={
                "mime_type": mime_type,
                "file_size": file_size,
                "file_id": doc_id,
                "source_id": doc_id,  # Store file ID for binary fetching
                "drive_name": doc_name,
                "web_view_link": source_url,
                # Store credentials for lazy loading
                "credentials_path": config.credentials_path,
                "service_account_json_path": config.service_account_json_path,
                "folder_id": config.folder_id,
            },
        )

    def _build_drive_query(self, *, folder_id: str, file_extensions: list[str]) -> str:
        """Build the Drive API query string for a given folder and optional extension filter."""
        query_parts = [f"'{folder_id}' in parents", "trashed = false"]

        if file_extensions:
            extension_mime_map = {
                OperatorConstants.FileExtensions.EXT_PDF: "mimeType = 'application/pdf'",
                OperatorConstants.FileExtensions.EXT_DOCX: "mimeType contains 'document'",
                OperatorConstants.FileExtensions.EXT_XLSX: "mimeType contains 'spreadsheet'",
                OperatorConstants.FileExtensions.EXT_PPTX: "mimeType contains 'presentation'",
                OperatorConstants.FileExtensions.EXT_TXT: "mimeType = 'text/plain'",
            }
            mime_conditions = [extension_mime_map[ext] for ext in file_extensions if ext in extension_mime_map]
            if mime_conditions:
                mime_conditions.append("mimeType = 'application/vnd.google-apps.folder'")
                query_parts.append(f"({' or '.join(mime_conditions)})")

        return " and ".join(query_parts)

    def _process_page_items(
        self,
        *,
        items: list[dict],
        all_files: list[dict],
        folders_to_process: deque,
        recursive: bool,
        max_files: int | None,
    ) -> bool:
        """
        Process a page of Drive API results, separating files from folders.

        Returns True if the max_files limit has been reached.
        """
        for item in items:
            if item.get("mimeType") == "application/vnd.google-apps.folder":
                if recursive:
                    folders_to_process.append(item["id"])
            else:
                all_files.append(item)
                if max_files is not None and len(all_files) >= max_files:
                    return True
        return False

    def _fetch_folder_pages(
        self,
        *,
        service: Any,
        folder_id: str,
        config: GoogleDriveSourceConfig,
        all_files: list[dict],
        folders_to_process: deque,
    ) -> bool:
        """Fetch all pages for one folder, populating all_files/folders_to_process.

        Returns True when the max_files limit is reached.
        """
        query = self._build_drive_query(
            folder_id=folder_id,
            file_extensions=config.file_extensions or [],
        )
        page_token = None

        while True:
            if config.max_files is not None and len(all_files) >= config.max_files:
                return True

            page_size = min(config.max_files - len(all_files), 100) if config.max_files is not None else 100

            results = (
                service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)",
                    pageToken=page_token,
                    pageSize=page_size,
                )
                .execute()
            )

            if self._process_page_items(
                items=results.get("files", []),
                all_files=all_files,
                folders_to_process=folders_to_process,
                recursive=config.recursive,
                max_files=config.max_files,
            ):
                return True

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        return False

    def _get_drive_service(self, *, config: GoogleDriveSourceConfig) -> Any:
        """Return a cached Drive API service for the given credentials configuration.

        The service (and its underlying credentials) is created once and reused for all
        documents in a batch, avoiding a repeated ``build()`` + ``_get_credentials()``
        round-trip per document.
        """
        try:
            from googleapiclient.discovery import build
        except ImportError:
            msg = "Google API client not installed. Install with: pip install google-api-python-client"
            raise ImportError(msg) from None

        cache_key = self._credentials_cache_key(config)
        if cache_key not in self._service_cache:
            creds = self._get_credentials(config)
            service = build("drive", "v3", credentials=creds)
            self._service_cache[cache_key] = (creds, service)

        _creds, service = self._service_cache[cache_key]
        return service

    def _list_files_from_drive(self, *, config: GoogleDriveSourceConfig) -> list[dict]:
        """
        List files from Google Drive using Drive API v3 (metadata only, no download).

        Returns list of file metadata dictionaries.
        """
        service = self._get_drive_service(config=config)

        all_files: list[dict[str, Any]] = []
        folders_to_process: deque[str] = deque([config.folder_id] if config.folder_id else [])

        while folders_to_process:
            current_folder_id = folders_to_process.popleft()
            if self._fetch_folder_pages(
                service=service,
                folder_id=current_folder_id,
                config=config,
                all_files=all_files,
                folders_to_process=folders_to_process,
            ):
                return all_files

        return all_files

    @staticmethod
    def _resolve_workspace_extension(*, file_ext: str, file_mime: str) -> str:
        """Return the derived file extension for a Google Workspace MIME type, or the original extension."""
        if file_ext or not file_mime.startswith(OperatorConstants.MimeTypes.GOOGLE_APPS_PREFIX):
            return file_ext
        workspace_extensions = {
            OperatorConstants.MimeTypes.GOOGLE_APPS_DOCUMENT: ".docx",
            OperatorConstants.MimeTypes.GOOGLE_APPS_SPREADSHEET: ".xlsx",
            OperatorConstants.MimeTypes.GOOGLE_APPS_PRESENTATION: ".pptx",
            OperatorConstants.MimeTypes.GOOGLE_APPS_DRAWING: ".pdf",
        }
        return workspace_extensions.get(file_mime, file_ext)

    def _should_skip_file(self, *, file_metadata: dict, config: GoogleDriveSourceConfig) -> bool:
        """Return True if the file should be skipped based on extension or size filters."""
        file_name = file_metadata.get(OperatorConstants.Columns.NAME, "")
        file_mime = file_metadata.get("mimeType", "")

        if config.file_extensions:
            file_ext = Path(file_name).suffix.lower()
            file_ext = self._resolve_workspace_extension(file_ext=file_ext, file_mime=file_mime)
            if file_ext not in config.file_extensions:
                logger.debug("Skipping %s: extension '%s' not in %s", file_name, file_ext, config.file_extensions)
                return True

        if config.max_file_size_mb:
            file_size_mb = int(file_metadata.get("size", 0)) / (1024 * 1024)
            if file_size_mb > config.max_file_size_mb:
                logger.debug(
                    "Skipping %s: size %.2fMB exceeds limit %sMB",
                    file_name,
                    file_size_mb,
                    config.max_file_size_mb,
                )
                return True

        return False

    def _iter_documents(self, config: GoogleDriveSourceConfig) -> list[Document]:
        """
        List Google Drive files and create documents with metadata only (lazy loading).

        No binary content is downloaded - that happens on-demand via fetch_binary_content().
        """
        files = self._list_files_from_drive(config=config)
        logger.info("Found %s files in Google Drive folder '%s'", len(files), config.folder_id)

        documents = []
        for file_metadata in files:
            if self._should_skip_file(file_metadata=file_metadata, config=config):
                continue
            doc = self._prepare_document(file_metadata=file_metadata, config=config)
            documents.append(doc)
            logger.debug("Created document metadata for Google Drive file: %s (%s bytes)", doc.name, doc.size)

        extension_counts: dict[str, int] = {}
        for doc in documents:
            extension = doc.extension or "unknown"
            extension_counts[extension] = extension_counts.get(extension, 0) + 1

        if extension_counts:
            logger.info("  File breakdown by extension:")
            for extension, count in sorted(extension_counts.items(), key=lambda x: x[1], reverse=True):
                logger.info("    - %s: %s file(s)", extension, count)

        logger.info("Created %s document metadata entries from Google Drive", len(documents))
        return documents

    def _fetch_single_gdrive_file(self, *, config: GoogleDriveSourceConfig) -> Document:
        """Fetch metadata for a single Google Drive file by file_id."""
        service = self._get_drive_service(config=config)
        file_metadata = (
            service.files()
            .get(fileId=config.file_id, fields="id, name, mimeType, size, modifiedTime, webViewLink")
            .execute()
        )
        return self._prepare_document(file_metadata=file_metadata, config=config)

    async def fetch_documents(self, config: GoogleDriveSourceConfig) -> AsyncGenerator[Document, None]:  # type: ignore[override]
        """
        Fetch documents from Google Drive using Google Drive API.

        Args:
            config: Validated Google Drive configuration

        Yields:
            Document: Domain documents from Google Drive

        Raises:
            ImportError: If google-api-python-client is not installed
            ValueError: If credentials are invalid or folder not found
        """
        try:
            if config.file_id:
                logger.info("Fetching single file from Google Drive: file_id=%s", config.file_id)
                yield self._fetch_single_gdrive_file(config=config)
                return

            fetched_count = 0
            for document in self._iter_documents(config):
                if config.max_files is not None and fetched_count >= config.max_files:
                    logger.info("Reached max_files limit (%s), stopping fetch", config.max_files)
                    break
                yield document
                fetched_count += 1
        except ImportError as e:
            msg = "Google API client not installed. Install with: pip install google-api-python-client"
            raise ImportError(msg) from e
        except Exception as e:
            msg = f"Failed to fetch documents from Google Drive: {e!s}"
            raise ValueError(msg) from e

    async def test_connection(self, config: GoogleDriveSourceConfig) -> tuple[bool, str]:
        """
        Test Google Drive connection using Google Drive API.

        Args:
            config: Validated Google Drive configuration

        Returns:
            Tuple[bool, str]: (success, message)
        """
        try:
            from googleapiclient.discovery import build
        except ImportError:
            return False, "Google API client not installed. Install with: pip install google-api-python-client"

        try:
            creds = self._get_credentials(config)
            service = build("drive", "v3", credentials=creds)

            # Test by listing files in the folder (limit to 1 for quick test)
            query = f"'{config.folder_id}' in parents and trashed = false"
            results = service.files().list(q=query, spaces="drive", fields="files(id, name)", pageSize=10).execute()

            files = results.get("files", [])
            return True, f"Successfully connected to Google Drive. Found {len(files)} document(s) in folder."

        except Exception as e:
            return False, f"Connection test failed: {e!s}"

    def get_config_schema(self) -> type[GoogleDriveSourceConfig]:
        """
        Get the configuration schema for this adapter.

        Returns:
            type[GoogleDriveSourceConfig]: The Pydantic configuration model
        """
        return GoogleDriveSourceConfig

    def fetch_binary_content(
        self,
        *,
        source_id: str,
        provider_config: dict[str, Any],
    ) -> bytes | None:
        """
        Fetch binary content for a specific document from Google Drive on-demand.

        Args:
            source_id: Google Drive file ID
            provider_config: All provider-specific parameters including credentials.

        Returns:
            bytes | None: Binary content of the Google Drive file, or None if not found or error occurred
        """
        try:
            from io import BytesIO
        except ImportError:
            logger.error("Google API client not installed. Install with: pip install google-api-python-client")
            return None

        try:
            service_account_json = provider_config.get("service_account_json")
            service_account_json_path = provider_config.get("service_account_json_path")
            credentials_json = provider_config.get("credentials_json")
            credentials_path = provider_config.get("credentials_path")
            folder_id = provider_config.get("folder_id") or "root"

            config_dict: dict[str, Any] = {
                "folder_id": folder_id,
                "recursive": False,
                "file_extensions": [],
                "exclude_patterns": [],
                "scopes": provider_config.get("scopes", ["https://www.googleapis.com/auth/drive.readonly"]),
            }

            if service_account_json:
                config_dict["service_account_json"] = service_account_json
            elif service_account_json_path:
                config_dict["service_account_json_path"] = service_account_json_path

            if credentials_json:
                config_dict["credentials_json"] = credentials_json
                config_dict["token_path"] = provider_config.get("token_path", "~/.docpipe/google_drive_token.json")
            elif credentials_path:
                config_dict["credentials_path"] = credentials_path
                config_dict["token_path"] = provider_config.get("token_path", "~/.docpipe/google_drive_token.json")

            temp_config = GoogleDriveSourceConfig(**config_dict)

            # Reuse cached service — avoids repeated _get_credentials() + build() per document
            service = self._get_drive_service(config=temp_config)

            logger.info("Downloading binary content from Google Drive: file_id=%s", source_id)

            # Get file metadata first to check mime type
            file_metadata = service.files().get(fileId=source_id, fields="mimeType,name").execute()
            mime_type = file_metadata.get("mimeType", "")
            file_name = file_metadata.get(OperatorConstants.Columns.NAME, "unknown")

            # Handle Google Workspace files (need to export)
            if mime_type.startswith(OperatorConstants.MimeTypes.GOOGLE_APPS_PREFIX):
                # Export Google Workspace files
                workspace_export_mime_map = {
                    OperatorConstants.MimeTypes.GOOGLE_APPS_DOCUMENT: OperatorConstants.MimeTypes.PDF,
                    OperatorConstants.MimeTypes.GOOGLE_APPS_SPREADSHEET: OperatorConstants.MimeTypes.EXCEL_XLSX,
                    OperatorConstants.MimeTypes.GOOGLE_APPS_PRESENTATION: OperatorConstants.MimeTypes.PDF,
                    OperatorConstants.MimeTypes.GOOGLE_APPS_DRAWING: OperatorConstants.MimeTypes.PDF,
                }
                export_mime_type = workspace_export_mime_map.get(mime_type)

                if export_mime_type:
                    request = service.files().export_media(fileId=source_id, mimeType=export_mime_type)
                else:
                    logger.warning("Unsupported Google Workspace file type: %s for %s", mime_type, file_name)
                    return None
            else:
                # Regular file download
                request = service.files().get_media(fileId=source_id)

            # Download content
            from googleapiclient.http import MediaIoBaseDownload

            file_buffer = BytesIO()
            downloader = MediaIoBaseDownload(file_buffer, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    logger.debug("Download progress: %s%%", int(status.progress() * 100))

            content = file_buffer.getvalue()
            logger.info("Successfully downloaded %s bytes from Google Drive: %s", len(content), source_id)
            return content

        except Exception as e:
            logger.exception("Error fetching binary content from Google Drive %s: %s", source_id, e)
            return None

    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict,
        included_extensions: list[str] | None = None,
        max_files: int | None = None,
    ) -> GoogleDriveSourceConfig:
        """
        Build Google Drive configuration from operator parameters.

        Args:
            provider_config: All provider-specific parameters including credentials.
            included_extensions: File extensions to include (optional)
            max_files: Maximum number of files to fetch (optional).

        Returns:
            GoogleDriveSourceConfig: Validated configuration object

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        config_dict = {
            "folder_id": resolve_env_var(provider_config.get("folder_id")),
            "recursive": provider_config.get("recursive", False),
            "file_extensions": included_extensions or [],
            "exclude_patterns": [],
            "scopes": provider_config.get("scopes", ["https://www.googleapis.com/auth/drive.readonly"]),
        }

        # Add OAuth credentials if provided
        credentials_path = provider_config.get("credentials_path")
        token_path = provider_config.get("token_path")
        if credentials_path:
            config_dict["credentials_path"] = resolve_env_var(credentials_path)
            config_dict["token_path"] = resolve_env_var(token_path)

        # Add Service Account credentials if provided
        service_account_json_path = provider_config.get("service_account_json_path")
        if service_account_json_path:
            config_dict["service_account_json_path"] = resolve_env_var(service_account_json_path)

        # Add optional fields only if they exist
        if "drive_id" in provider_config:
            config_dict["drive_id"] = resolve_env_var(provider_config["drive_id"])
        if "folder_path" in provider_config:
            config_dict["folder_path"] = resolve_env_var(provider_config["folder_path"])
        if "file_id" in provider_config:
            config_dict["file_id"] = resolve_env_var(provider_config["file_id"])
        if "max_file_size_mb" in provider_config:
            config_dict["max_file_size_mb"] = provider_config["max_file_size_mb"]

        # Add max_files from operator parameter
        if max_files is not None:
            config_dict["max_files"] = max_files

        return GoogleDriveSourceConfig(**config_dict)
