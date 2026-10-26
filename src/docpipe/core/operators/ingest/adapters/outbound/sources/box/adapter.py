"""Box source adapter using Box SDK directly."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

from box_sdk_gen import BoxClient

from docpipe.core.operators.ingest.adapters.outbound.sources.box.auth import get_box_client
from docpipe.core.operators.ingest.adapters.outbound.sources.box.config import BoxSourceConfig
from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import register_source_adapter
from docpipe.core.operators.ingest.domain.models import Document
from docpipe.core.operators.ingest.ports.outbound.document_source import DocumentSourcePort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


@register_source_adapter
class BoxSourceAdapter(DocumentSourcePort):
    """Adapter for ingesting documents from Box using the Box SDK."""

    SOURCE_NAME = "box_driver"
    SOURCE_DISPLAY_NAME = "Box Driver"
    CONFIG_CLASS = BoxSourceConfig

    def __init__(self) -> None:
        # Cache authenticated BoxClient keyed by credentials_path so a single JWT
        # auth flow is performed for all documents in a batch.
        self._client_cache: dict[str, BoxClient] = {}

    @staticmethod
    def bind_file_reference(*, provider_config: dict[str, Any], file_reference: str) -> None:
        """Set a Box file ID as the single file to ingest.

        ``file_reference`` is the Box file ID the producer supplies for the
        event; batch ingestion (``fetch_documents``) already accepts a file
        ID via ``file_id`` and fetches/validates it against the Box API, so
        this only does basic input validation rather than duplicating that
        call here.
        """
        if not file_reference or not file_reference.strip():
            raise ValueError("File reference must be a non-empty Box file ID")

        provider_config["file_id"] = file_reference

    def _get_box_client(self, *, config: BoxSourceConfig) -> BoxClient:
        """Return a cached authenticated Box client for the given credentials.

        The client is created once per unique credentials and reused for all
        subsequent calls, avoiding a new JWT auth round-trip per document.
        """
        if config.credentials_json is not None:
            raw_str = (
                json.dumps(config.credentials_json, sort_keys=True)
                if isinstance(config.credentials_json, dict)
                else str(config.credentials_json)
            )
            key = hashlib.sha256(raw_str.encode()).hexdigest()
        else:
            key = config.credentials_path or "default"

        if key not in self._client_cache:
            self._client_cache[key] = get_box_client(
                credentials_json=config.credentials_json,
                credentials_path=config.credentials_path,
            )
        return self._client_cache[key]

    def _should_include_file(self, file_name: str, file_size_bytes: int, config: BoxSourceConfig) -> bool:
        """Check whether a Box file passes extension and size filters."""
        file_ext = Path(file_name).suffix.lower()

        if config.file_extensions and file_ext not in config.file_extensions:
            return False

        if config.max_file_size_mb is not None:
            size_mb = file_size_bytes / (1024 * 1024)
            if size_mb > config.max_file_size_mb:
                return False

        return True

    def _iter_box_files(self, *, client: BoxClient, config: BoxSourceConfig, folder_id: str | None = None):
        """Iterate Box files recursively from the given folder.

        Args:
            client: Authenticated Box client
            config: Box source configuration
            folder_id: Folder ID to start from. If None, uses config.folder_id
        """
        if folder_id is None:
            folder_id = config.folder_id
        try:
            folder = client.folders.get_folder_by_id(folder_id)
            items = client.folders.get_folder_items(folder.id)

            for item in items.entries:
                item_type = getattr(item, "type", None)

                if item_type == "folder":
                    if config.recursive:
                        yield from self._iter_box_files(client=client, config=config, folder_id=str(item.id))
                    continue

                if item_type != "file":
                    continue

                file_info = client.files.get_file_by_id(str(item.id))
                file_name = getattr(file_info, "name", "unknown")
                file_size = getattr(file_info, "size", 0) or 0

                if not self._should_include_file(file_name, file_size, config):
                    continue

                yield file_info
        except Exception as e:
            logger.exception("Error iterating Box files: %s", e)
            raise

    def _compute_relative_path(self, *, file_info, root_folder_id: str) -> str | None:
        """Compute the path of a file relative to the configured root folder.

        Uses the ``path_collection`` returned by the Box API to locate the
        root folder in the ancestry chain and return only the sub-folder
        segments below it, joined with the filename.

        Example:
            root_folder_id = "400527909052"  (source_files)
            path_collection = [All Files, vt_workspace, source_files, sub01]
            file name        = "TR-INV_001_3_2.1.pdf"
            → relative_path  = "sub01/TR-INV_001_3_2.1.pdf"
        """
        doc_name = getattr(file_info, "name", "")
        path_collection = getattr(file_info, "path_collection", None)
        path_entries = getattr(path_collection, "entries", []) if path_collection else []

        # Find the index of the root folder in the ancestry chain.
        root_idx = None
        for idx, entry in enumerate(path_entries):
            if str(getattr(entry, "id", "")) == root_folder_id:
                root_idx = idx
                break

        if root_idx is None:
            return None

        # Segments *below* the root folder.
        sub_segments = [str(entry.name) for entry in path_entries[root_idx + 1 :] if getattr(entry, "name", None)]
        return "/".join([*sub_segments, doc_name]) if doc_name else None

    def _download_file_content(self, *, client: BoxClient, file_id: str) -> bytes:
        """Download Box file content."""
        try:
            stream = client.downloads.download_file(file_id)
            return stream.read()
        except Exception as e:
            logger.exception("Error downloading file %s: %s", file_id, e)
            raise

    def _parse_modified_time(self, modified_at: str | None):
        """Parse Box modified timestamp."""
        if not modified_at:
            return None

        try:
            # Box SDK Gen returns datetime objects, not strings
            if isinstance(modified_at, datetime):
                return modified_at
            # If it's a string, parse it
            if isinstance(modified_at, str):
                return datetime.fromisoformat(modified_at.replace("Z", "+00:00"))
            return None
        except (ValueError, AttributeError, TypeError):
            return None

    def _prepare_document(self, *, file_info, root_folder_id: str) -> Document:
        """Convert a Box file object to the domain document model (lazy loading).

        No binary content is downloaded here. Content is fetched on-demand by the
        Extract operator via fetch_binary_content().
        """
        doc_id = str(getattr(file_info, "id", ""))
        doc_name = getattr(file_info, "name", "unknown")
        modified_time = self._parse_modified_time(getattr(file_info, "modified_at", None))

        shared_link = getattr(file_info, "shared_link", None)
        source_url = ""
        if shared_link and isinstance(shared_link, dict):
            source_url = shared_link.get("url", "")
        if not source_url:
            source_url = f"https://app.box.com/file/{doc_id}"

        path_collection = getattr(file_info, "path_collection", None)
        path_entries = getattr(path_collection, "entries", []) if path_collection else []
        full_path = "/".join(str(entry.name) for entry in path_entries if getattr(entry, "name", None))

        extension = Path(doc_name).suffix.lstrip(".")
        size = getattr(file_info, "size", 0) or 0

        # Convert datetime objects to ISO format strings for JSON serialization
        created_at = getattr(file_info, "created_at", None)
        created_at_str = created_at.isoformat() if isinstance(created_at, datetime) else None

        modified_at = getattr(file_info, "modified_at", None)
        modified_at_str = modified_at.isoformat() if isinstance(modified_at, datetime) else None

        relative_path = self._compute_relative_path(file_info=file_info, root_folder_id=root_folder_id)

        return Document(
            id=doc_id,
            name=doc_name,
            content=b"",  # Empty - binary loaded on-demand by downstream operators
            source_url=source_url,
            size=size,
            mimetype="application/octet-stream",
            extension=extension,
            modified_time=modified_time,
            metadata={
                "source": source_url,  # Required for document_url in failed_docs
                "source_id": doc_id,  # Required by binary_content_fetcher
                "box_id": doc_id,
                "box_name": doc_name,
                "path": full_path,
                "size": size,
                "created_at": created_at_str,
                "modified_at": modified_at_str,
                "owned_by": getattr(getattr(file_info, "owned_by", None), "login", None),
                "relative_path": relative_path,
            },
        )

    async def fetch_documents(self, config: BoxSourceConfig) -> AsyncGenerator[Document, None]:  # type: ignore[override]
        """Fetch documents from Box using the Box SDK."""
        try:
            client = self._get_box_client(config=config)

            # Single file mode
            if config.file_id:
                logger.info("Fetching single file from Box: file_id=%s", config.file_id)
                file_info = client.files.get_file_by_id(config.file_id)
                document = self._prepare_document(file_info=file_info, root_folder_id="")
                yield document
                return

            # Folder mode
            doc_count = 0
            for file_info in self._iter_box_files(client=client, config=config, folder_id=config.folder_id):
                # Check max_files limit
                if config.max_files is not None and doc_count >= config.max_files:
                    break

                document = self._prepare_document(
                    file_info=file_info,
                    root_folder_id=config.folder_id,
                )
                yield document
                doc_count += 1

        except ImportError as e:
            raise ImportError(
                "Box SDK dependencies not installed. Install with: uv pip install 'docling-pipelines[box]'"
            ) from e
        except Exception as e:
            logger.exception("Error fetching documents from Box: %s", e)
            raise ValueError(f"Failed to fetch documents from Box: {e!s}") from e

    async def test_connection(self, config: BoxSourceConfig) -> tuple[bool, str]:
        """Test Box connection using the Box SDK."""
        try:
            client = self._get_box_client(config=config)
            root_folder = client.folders.get_folder_by_id("0")
            return True, f"Successfully connected to Box. Root folder: {getattr(root_folder, 'name', 'All Files')}"
        except ImportError:
            return False, "Box SDK dependencies not installed"
        except Exception as e:
            return False, f"Connection test failed: {e!s}"

    def get_config_schema(self) -> type[BoxSourceConfig]:
        """Get the configuration schema for this adapter."""
        return BoxSourceConfig

    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict,
        included_extensions: list[str] | None = None,
        max_files: int | None = None,
    ) -> BoxSourceConfig:
        """Build Box configuration from operator parameters.

        Accepts both "credentials_path" and the legacy "credentials_json_path" key
        inside provider_config for backward compatibility with stored configs.
        """
        credentials_json = provider_config.get("credentials_json")
        credentials_path = provider_config.get("credentials_json_path") or provider_config.get("credentials_path")

        config_dict = {
            "credentials_json": credentials_json,
            "credentials_path": credentials_path,
            "folder_id": provider_config.get("folder_id", "0"),
            "recursive": provider_config.get("recursive", True),
            "file_extensions": included_extensions or [],
            "exclude_patterns": provider_config.get("exclude_patterns", []),
        }

        # Support single file ingestion via file_id
        if "file_id" in provider_config:
            config_dict["file_id"] = provider_config["file_id"]

        if "max_file_size_mb" in provider_config:
            config_dict["max_file_size_mb"] = provider_config["max_file_size_mb"]

        if max_files is not None:
            config_dict["max_files"] = max_files

        return BoxSourceConfig(**config_dict)

    def fetch_binary_content(
        self,
        *,
        source_id: str,
        provider_config: dict[str, Any],
    ) -> bytes | None:
        """
        Fetch binary content for a specific Box file on-demand.

        Args:
            source_id: Box file ID or URL (e.g., "702199884861" or "https://app.box.com/file/702199884861")
            provider_config: All provider-specific parameters including credentials.

        Returns:
            bytes | None: Binary content of the Box file, or None if not found or error occurred
        """
        try:
            # Extract file ID from URL if needed
            # Box URLs are in format: https://app.box.com/file/{file_id}
            file_id = source_id
            if source_id.startswith("http"):
                parts = source_id.rstrip("/").split("/")
                if len(parts) >= 2 and parts[-2] == "file":
                    file_id = parts[-1]
                else:
                    logger.error("Could not extract file ID from Box URL: %s", source_id)
                    return None

            credentials_json = provider_config.get("credentials_json")
            credentials_path = provider_config.get("credentials_json_path") or provider_config.get("credentials_path")
            if not credentials_json and not credentials_path:
                logger.error("Missing 'credentials_json' or 'credentials_path' in provider_config")
                return None

            config = BoxSourceConfig(
                credentials_json=credentials_json,
                credentials_path=credentials_path,
                recursive=False,
                file_extensions=[],
                exclude_patterns=[],
            )

            # Reuse cached client — avoids a new JWT auth round-trip per document
            client = self._get_box_client(config=config)

            # Download file content using existing method
            logger.info("Downloading binary content from Box: file_id=%s", file_id)
            content = self._download_file_content(client=client, file_id=file_id)

            logger.info("Successfully downloaded %d bytes from Box: %s", len(content), source_id)
            return content

        except FileNotFoundError as e:
            logger.error("Box credentials file not found: %s", e)
            return None
        except ValueError as e:
            logger.error("Box authentication error: %s", e)
            return None
        except Exception:
            logger.exception("Unexpected error fetching binary content from Box %s", source_id)
            return None
