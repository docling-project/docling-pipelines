"""Dropbox source adapter using the official Dropbox Python SDK."""

import hashlib
import mimetypes
from collections.abc import AsyncGenerator, Iterator
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from dropbox import Dropbox
from dropbox.exceptions import ApiError, AuthError, BadInputError, HttpError
from dropbox.files import FileMetadata

from docpipe.core.operators.ingest.adapters.outbound.sources.dropbox.config import DropboxSourceConfig
from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import register_source_adapter
from docpipe.core.operators.ingest.domain.models import Document
from docpipe.core.operators.ingest.ports.outbound.document_source import DocumentSourcePort
from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

# Dropbox user agent identifier sent with every API call.
DROPBOX_CLIENT_IDENTIFIER = "docling-pipelines"


@register_source_adapter
class DropboxSourceAdapter(DocumentSourcePort[DropboxSourceConfig]):
    """Adapter for ingesting documents from Dropbox using the Dropbox SDK."""

    SOURCE_NAME = "dropbox"
    SOURCE_DISPLAY_NAME = "Dropbox"
    SOURCE_DESCRIPTION = "Ingest documents from a Dropbox account folder"
    SOURCE_VERSION = "1.0.0"
    CONFIG_CLASS = DropboxSourceConfig

    def __init__(self) -> None:
        # Cache authenticated Dropbox clients keyed by a credential fingerprint so a single
        # client (and its token refresh state) is reused for all documents in a batch.
        self._client_cache: dict[str, Dropbox] = {}

    @staticmethod
    def bind_file_reference(*, provider_config: dict[str, Any], file_reference: str) -> None:
        """Set a Dropbox file reference as the single file to ingest.

        ``file_reference`` is the Dropbox path or id the producer supplies
        for the event; batch ingestion (``fetch_documents``) already accepts
        a reference via ``file_path`` and fetches/validates it against the
        Dropbox API, so this only does basic input validation rather than
        duplicating that call here.
        """
        if not file_reference or not file_reference.strip():
            raise ValueError("File reference must be a non-empty Dropbox path or id")

        provider_config["file_path"] = file_reference

    # ------------------------------------------------------------------
    # Client handling
    # ------------------------------------------------------------------

    @staticmethod
    def _client_cache_key(*, config: DropboxSourceConfig) -> str:
        """Build a non-reversible cache key from the configured credentials."""
        material = "|".join(
            [
                config.access_token or "",
                config.refresh_token or "",
                config.app_key or "",
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _get_dropbox_client(self, *, config: DropboxSourceConfig) -> Dropbox:
        """Return a cached authenticated Dropbox client for the given credentials."""
        key = self._client_cache_key(config=config)
        if key not in self._client_cache:
            if config.refresh_token:
                client = Dropbox(
                    oauth2_refresh_token=config.refresh_token,
                    app_key=config.app_key,
                    app_secret=config.app_secret,
                    user_agent=DROPBOX_CLIENT_IDENTIFIER,
                )
            else:
                client = Dropbox(
                    oauth2_access_token=config.access_token,
                    user_agent=DROPBOX_CLIENT_IDENTIFIER,
                )
            self._client_cache[key] = client
        return self._client_cache[key]

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    def _should_include_file(self, *, entry: FileMetadata, config: DropboxSourceConfig) -> bool:
        """Check whether a Dropbox file passes extension, size and exclusion filters."""
        file_name = entry.name or ""
        file_ext = Path(file_name).suffix.lower()

        if config.file_extensions and file_ext not in config.file_extensions:
            return False

        file_size = entry.size or 0
        if config.max_file_size_mb is not None and file_size / (1024 * 1024) > config.max_file_size_mb:
            return False

        if config.exclude_patterns:
            candidate_path = entry.path_display or entry.path_lower or file_name
            for pattern in config.exclude_patterns:
                if fnmatch(candidate_path, pattern) or fnmatch(file_name, pattern):
                    return False

        return True

    def _iter_dropbox_files(self, *, client: Dropbox, config: DropboxSourceConfig) -> Iterator[FileMetadata]:
        """Iterate Dropbox files under the configured folder, following pagination cursors."""
        result = client.files_list_folder(path=config.folder_path, recursive=config.recursive)

        while True:
            for entry in result.entries:
                if not isinstance(entry, FileMetadata):
                    continue
                if self._should_include_file(entry=entry, config=config):
                    yield entry

            if not result.has_more:
                return

            result = client.files_list_folder_continue(result.cursor)

    # ------------------------------------------------------------------
    # Document mapping
    # ------------------------------------------------------------------

    def _compute_relative_path(self, *, entry: FileMetadata, folder_path: str) -> str:
        """Compute the file path relative to the configured root folder."""
        display_path = entry.path_display or entry.path_lower or entry.name or ""
        relative = display_path.lstrip("/")

        if folder_path:
            root = folder_path.strip("/")
            lowered = relative.lower()
            if lowered.startswith(f"{root.lower()}/"):
                relative = relative[len(root) + 1 :]
            elif lowered == root.lower():
                relative = entry.name or relative

        return relative

    def _prepare_document(self, *, entry: FileMetadata, config: DropboxSourceConfig) -> Document:
        """Convert Dropbox file metadata to the domain document model (lazy loading).

        No binary content is downloaded here. Content is fetched on-demand by the
        Extract operator via fetch_binary_content().
        """
        doc_id = entry.id or entry.path_lower or entry.name
        doc_name = entry.name or "unknown"
        display_path = entry.path_display or entry.path_lower or f"/{doc_name}"
        source_url = f"https://www.dropbox.com/home{display_path}"
        size = entry.size or 0
        mimetype = mimetypes.guess_type(doc_name)[0] or "application/octet-stream"
        relative_path = self._compute_relative_path(entry=entry, folder_path=config.folder_path)

        client_modified = getattr(entry, "client_modified", None)
        server_modified = getattr(entry, "server_modified", None)

        return Document(
            id=doc_id,
            name=doc_name,
            content=b"",  # Empty - binary loaded on-demand by downstream operators
            source_url=source_url,
            size=size,
            mimetype=mimetype,
            extension=Path(doc_name).suffix.lstrip("."),
            modified_time=server_modified,
            created_time=client_modified,
            metadata={
                "source": source_url,  # Required for document_url in failed_docs
                "source_id": doc_id,  # Required by binary_content_fetcher
                "dropbox_id": entry.id,
                "dropbox_name": doc_name,
                "path": display_path,
                "relative_path": relative_path,
                "size": size,
                "client_modified": client_modified.isoformat() if client_modified else None,
                "server_modified": server_modified.isoformat() if server_modified else None,
                "rev": getattr(entry, "rev", None),
                "content_hash": getattr(entry, "content_hash", None),
            },
        )

    # ------------------------------------------------------------------
    # Port implementation
    # ------------------------------------------------------------------

    async def fetch_documents(self, config: DropboxSourceConfig) -> AsyncGenerator[Document, None]:  # type: ignore[override]
        """Fetch document metadata from Dropbox, streaming results as they are listed."""
        try:
            client = self._get_dropbox_client(config=config)

            # Single file mode
            if config.file_path:
                logger.info("Fetching single file from Dropbox: %s", config.file_path)
                entry = client.files_get_metadata(config.file_path)
                if not isinstance(entry, FileMetadata):
                    raise ValueError(f"Dropbox path is not a file: {config.file_path}")
                yield self._prepare_document(entry=entry, config=config)
                return

            # Folder mode
            doc_count = 0
            for entry in self._iter_dropbox_files(client=client, config=config):
                if config.max_files is not None and doc_count >= config.max_files:
                    break
                yield self._prepare_document(entry=entry, config=config)
                doc_count += 1

            logger.info(
                "Fetched %s document(s) from Dropbox folder '%s'",
                doc_count,
                config.folder_path or "/",
            )

        except AuthError as e:
            logger.error("Dropbox authentication failed: %s", e)
            raise ValueError(f"Dropbox authentication failed: {e!s}") from e
        except (ApiError, BadInputError, HttpError) as e:
            logger.error("Dropbox API error while listing documents: %s", e)
            raise ValueError(f"Failed to fetch documents from Dropbox: {e!s}") from e

    async def test_connection(self, config: DropboxSourceConfig) -> tuple[bool, str]:
        """Test the Dropbox connection with the cheapest read-only calls available."""
        try:
            client = self._get_dropbox_client(config=config)
            account = client.users_get_current_account()
            display_name = getattr(getattr(account, "name", None), "display_name", "unknown account")

            if config.folder_path:
                client.files_get_metadata(config.folder_path)

            return True, f"Successfully connected to Dropbox as {display_name}"
        except AuthError as e:
            return False, f"Dropbox authentication failed, check the configured token: {e!s}"
        except BadInputError as e:
            return False, f"Invalid Dropbox credentials or request: {e!s}"
        except ApiError as e:
            return False, f"Dropbox API error, check that '{config.folder_path or '/'}' exists and is readable: {e!s}"
        except HttpError as e:
            return False, f"Could not reach the Dropbox API: {e!s}"
        except Exception as e:  # Connection test must never raise
            return False, f"Connection test failed: {e!s}"

    def get_config_schema(self) -> type[DropboxSourceConfig]:
        """Get the configuration schema for this adapter."""
        return DropboxSourceConfig

    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict,
        included_extensions: list[str] | None = None,
        max_files: int | None = None,
    ) -> DropboxSourceConfig:
        """Build the Dropbox configuration from operator parameters."""
        params = provider_config

        config_dict: dict[str, Any] = {
            "access_token": resolve_env_var(params.get("access_token")),
            "refresh_token": resolve_env_var(params.get("refresh_token")),
            "app_key": resolve_env_var(params.get("app_key")),
            "app_secret": resolve_env_var(params.get("app_secret")),
            "folder_path": resolve_env_var(params.get("folder_path", "")) or "",
            "recursive": params.get("recursive", True),
            "file_extensions": included_extensions or [],
            "exclude_patterns": params.get("exclude_patterns", []),
        }

        # Support single file ingestion via file_path
        if params.get("file_path"):
            config_dict["file_path"] = resolve_env_var(params["file_path"])

        if "max_file_size_mb" in params:
            config_dict["max_file_size_mb"] = params["max_file_size_mb"]

        if max_files is not None:
            config_dict["max_files"] = max_files

        return DropboxSourceConfig(**config_dict)

    def fetch_binary_content(
        self,
        *,
        source_id: str,
        provider_config: dict[str, Any],
    ) -> bytes | None:
        """
        Fetch binary content for a specific Dropbox file on-demand.

        Args:
            source_id: Dropbox file id (e.g. "id:abc123"), file path, or file URL
            provider_config: All provider-specific parameters including credentials
                (access_token, or refresh_token + app_key + app_secret)

        Returns:
            bytes | None: Binary content of the file, or None if it could not be downloaded

        Raises:
            ValueError: If source_id is empty
        """
        if not source_id:
            raise ValueError("Missing source_id for Dropbox binary content fetch")

        config = self.build_config_from_operator_params(provider_config=provider_config)

        file_ref = self._normalize_source_id(source_id=source_id)

        try:
            client = self._get_dropbox_client(config=config)
            logger.info("Downloading binary content from Dropbox: %s", file_ref)
            _, response = client.files_download(file_ref)
            content = response.content
            logger.info("Successfully downloaded %s bytes from Dropbox", len(content))
            return content
        except AuthError as e:
            logger.error("Dropbox authentication failed while downloading %s: %s", file_ref, e)
            return None
        except ApiError as e:
            logger.error("Dropbox file could not be downloaded (%s): %s", file_ref, e)
            return None
        except (BadInputError, HttpError) as e:
            logger.error("Dropbox API error while downloading %s: %s", file_ref, e)
            return None

    @staticmethod
    def _normalize_source_id(*, source_id: str) -> str:
        """Convert a stored source identifier into a reference the Dropbox API accepts."""
        reference = source_id.strip()

        # Documents ingested by this adapter store the Dropbox file id, which is accepted as-is.
        if reference.startswith(("id:", "rev:", "ns:")):
            return reference

        # Documents referenced by their Dropbox web URL (https://www.dropbox.com/home/<path>).
        if reference.startswith("http"):
            _, _, path_part = reference.partition("/home")
            path_part = path_part.split("?", 1)[0]
            reference = path_part or reference

        return reference if reference.startswith("/") else f"/{reference}"
