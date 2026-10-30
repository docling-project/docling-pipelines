# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""OneDrive source adapter using Microsoft Graph API."""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, cast

from pydantic import BaseModel

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import (
    register_source_adapter,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.config import OneDriveSourceConfig
from docpipe.core.operators.ingest.domain.models import Document

# Import the MicrosoftGraphLoader from ingest_source.py
from docpipe.core.operators.ingest.ingest_source import MicrosoftGraphLoader
from docpipe.core.operators.ingest.ingest_utils import (
    extract_msgraph_file_id_from_url,
    handle_msgraph_resolution_result,
    resolve_msgraph_file_id_to_item_id,
)
from docpipe.core.operators.ingest.ports.outbound.document_source import DocumentSourcePort
from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.integrations.rest_client import RestMethod
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@register_source_adapter
class OneDriveSourceAdapter(DocumentSourcePort):
    """
    Adapter for ingesting documents from OneDrive using Microsoft Graph API.

    This adapter uses the custom MicrosoftGraphLoader which supports
    app-only authentication (client credentials flow) for OneDrive access.

    Features:
    - App-only authentication using Azure AD client credentials
    - Recursive folder traversal
    - Automatic text extraction from common file types:
      - Text files (.txt, .md, .csv, .json, etc.)
      - PDF files (.pdf)
      - Word documents (.docx)
      - Excel spreadsheets (.xlsx)
    - File extension filtering
    - Metadata preservation

    Authentication Requirements:
    - Azure AD App Registration with:
      - Application (client) ID
      - Client secret
      - Tenant (directory) ID
    - Microsoft Graph API permissions:
      - Files.Read.All (Application permission)
    """

    # Metadata for connector discovery
    SOURCE_NAME = "onedrive"
    SOURCE_DISPLAY_NAME = "Microsoft OneDrive"
    SOURCE_DESCRIPTION = "Ingest documents from OneDrive using Microsoft Graph API"
    SOURCE_VERSION = "1.0.0"

    def __init__(self) -> None:
        # Cache MicrosoftGraphLoader keyed by (drive_id, client_id, tenant_id, secret_hash) so
        # the single MSAL token request is reused for all documents in a batch.
        # secret_hash ensures a rotated client_secret invalidates the cached loader.
        self._loader_cache: dict[tuple[str, str, str, str], MicrosoftGraphLoader] = {}

    @staticmethod
    def bind_file_reference(*, provider_config: dict[str, Any], file_reference: str) -> None:
        """Set one OneDrive item as the only file to ingest.

        ``file_reference`` is a Microsoft Graph drive item id in the drive
        already configured on the flow, or a OneDrive or SharePoint file URL.
        ``fetch_documents`` already loads that value from ``file_path`` and
        checks it with Microsoft Graph, so this method only validates the
        reference. Credentials and the drive stay in ``provider_config`` and
        are never read from the event.
        """
        if not isinstance(file_reference, str) or not file_reference.strip():
            raise ValueError("File reference must be a non-empty OneDrive item id or file URL")

        reference = file_reference.strip()
        lowered = reference.lower()
        if "://" in reference and not lowered.startswith(("http://", "https://")):
            raise ValueError("File reference must be a Microsoft OneDrive item id or file URL, not a URI")

        if lowered.startswith(("http://", "https://")):
            extracted = extract_msgraph_file_id_from_url(reference)
            if not isinstance(extracted, str) or not extracted.strip():
                raise ValueError(
                    "File reference must be a Microsoft OneDrive item id or a file URL with an id or sourcedoc parameter"
                )

        provider_config["file_path"] = reference

    def _get_loader(
        self,
        *,
        drive_id: str,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        folder_path: str | None = None,
        recursive: bool = False,
    ) -> MicrosoftGraphLoader:
        """Return a cached MicrosoftGraphLoader for the given credentials.

        The loader (and its cached MSAL token) is created once per unique
        (drive_id, client_id, tenant_id, secret_hash) combination and reused for all
        subsequent calls, avoiding a new token request per document.  Including a hash
        of client_secret in the key ensures that a rotated secret invalidates the cached
        loader rather than silently reusing a stale one.
        """
        secret_hash = hashlib.sha256(client_secret.encode()).hexdigest()[:16]
        key = (drive_id, client_id, tenant_id, secret_hash)
        if key not in self._loader_cache:
            self._loader_cache[key] = MicrosoftGraphLoader(
                drive_id=drive_id,
                client_id=client_id,
                client_secret=client_secret,
                tenant_id=tenant_id,
                folder_path=folder_path,
                recursive=recursive,
            )
        return self._loader_cache[key]

    def _resolve_onedrive_item_id(
        self,
        *,
        file_path: str,
        drive_id: str,
        loader: "MicrosoftGraphLoader",
        token: str,
    ) -> tuple[str | None, str]:
        """Resolve a file path or URL to an (item_id, actual_drive_id) pair."""
        if not file_path.lower().startswith(("http://", "https://")):
            logger.info("Using direct file path as item ID: %s", file_path)
            return file_path, drive_id

        file_id = extract_msgraph_file_id_from_url(file_path)
        if not file_id:
            msg = f"Could not extract file ID from URL: {file_path}"
            raise ValueError(msg)
        logger.info("Extracted file ID from URL: %s", file_id)
        item_id, actual_drive_id = resolve_msgraph_file_id_to_item_id(
            file_id=file_id,
            drive_id=drive_id,
            rest_client=loader._rest_client,
            token=token,
            original_url=file_path,
        )
        return handle_msgraph_resolution_result(
            file_id=file_id,
            item_id=item_id,
            actual_drive_id=actual_drive_id,
            fallback_drive_id=drive_id,
            allow_guid_fallback=False,
            original_url=file_path,
        )

    def _build_onedrive_document(
        self,
        *,
        item: dict,
        drive_id: str,
        config: "OneDriveSourceConfig",
        is_single_file: bool = False,
    ) -> Document:
        """Build a lazy-loading Document from a Graph API item dict."""
        doc_id = item.get(OperatorConstants.Columns.ID, "")
        doc_name = item.get(OperatorConstants.Columns.NAME, "unknown")
        file_size = item.get("size", 0)
        source_url = item.get("webUrl", f"https://onedrive.live.com/?cid={doc_id}")
        extension = Path(doc_name).suffix.lower()

        modified_time = None
        last_modified = item.get("lastModifiedDateTime")
        if last_modified:
            try:
                modified_time = datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        metadata: dict = {
            "drive_id": drive_id,
            "item_id": doc_id,
            "file_size": file_size,
            "mime_type": item.get("file", {}).get("mimeType"),
            "created_time": item.get("createdDateTime"),
            "web_url": source_url,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "tenant_id": config.tenant_id,
        }
        if not is_single_file:
            metadata["source_id"] = doc_id  # Required by binary_content_fetcher

        return Document(
            id=doc_id,
            name=doc_name,
            content=b"",
            source_url=source_url,
            modified_time=modified_time,
            mimetype=item.get("file", {}).get("mimeType", "application/octet-stream"),
            size=file_size,
            extension=extension,
            metadata=metadata,
        )

    @staticmethod
    def _should_skip_onedrive_item(*, doc_name: str, file_size: int, config: "OneDriveSourceConfig") -> bool:
        """Return True if the item should be filtered out based on extension or size."""
        if config.file_extensions and Path(doc_name).suffix.lower() not in config.file_extensions:
            return True
        if config.max_file_size_mb and file_size / (1024 * 1024) > config.max_file_size_mb:
            return True
        return False

    @staticmethod
    def _resolve_folder_item_id(
        *, loader: "MicrosoftGraphLoader", drive_id: str, folder_path: str, headers: dict
    ) -> str | None:
        """Look up the item ID for a folder path in a drive."""
        path = folder_path.strip("/")
        try:
            data = loader._rest_client.call_rest_json(
                method=RestMethod.GET,
                url=f"/drives/{drive_id}/root:/{path}",
                headers=headers,
            )
            return data.get(OperatorConstants.Columns.ID)
        except Exception as e:
            msg = f"Folder path '{folder_path}' not found in drive '{drive_id}': {e!s}"
            raise ValueError(msg) from e

    async def fetch_documents(self, config: OneDriveSourceConfig) -> AsyncGenerator[Document, None]:  # type: ignore[override]
        """
        Fetch document metadata from OneDrive using Microsoft Graph API.

        This method implements lazy loading - it only fetches metadata, not binary content.
        Binary content is fetched on-demand by the Extract operator via fetch_binary_content().
        """
        onedrive_config: OneDriveSourceConfig = config
        try:
            loader = self._get_loader(
                drive_id=onedrive_config.drive_id,
                client_id=onedrive_config.client_id,
                client_secret=onedrive_config.client_secret,
                tenant_id=onedrive_config.tenant_id,
                folder_path=onedrive_config.folder_path,
                recursive=onedrive_config.recursive,
            )

            if config.file_path:
                token = loader._get_token()
                item_id, actual_drive_id = self._resolve_onedrive_item_id(
                    file_path=config.file_path,
                    drive_id=config.drive_id,
                    loader=loader,
                    token=token,
                )
                headers = {"Authorization": f"Bearer {token}"}
                item = loader._rest_client.call_rest_json(
                    method=RestMethod.GET,
                    url=f"/drives/{actual_drive_id}/items/{item_id}",
                    headers=headers,
                )
                yield self._build_onedrive_document(
                    item=item, drive_id=actual_drive_id, config=onedrive_config, is_single_file=True
                )
                return

            # Folder mode
            token = loader._get_token()
            headers = {"Authorization": f"Bearer {token}"}

            folder_item_id = None
            if onedrive_config.folder_path:
                folder_item_id = self._resolve_folder_item_id(
                    loader=loader,
                    drive_id=onedrive_config.drive_id,
                    folder_path=onedrive_config.folder_path,
                    headers=headers,
                )

            for item in loader._list_files(folder_item_id=folder_item_id):
                doc_name = item.get(OperatorConstants.Columns.NAME, "unknown")
                file_size = item.get("size", 0)
                if self._should_skip_onedrive_item(doc_name=doc_name, file_size=file_size, config=onedrive_config):
                    continue
                document = self._build_onedrive_document(
                    item=item, drive_id=onedrive_config.drive_id, config=onedrive_config
                )
                logger.debug("Created document metadata for OneDrive file: %s (%s bytes)", doc_name, file_size)
                yield document

        except ImportError as e:
            msg = "Microsoft Graph dependencies not installed. Install with: pip install msal requests"
            raise ImportError(msg) from e
        except Exception as e:
            msg = f"Failed to fetch documents from OneDrive: {e!s}"
            raise ValueError(msg) from e

    async def test_connection(self, config: BaseModel) -> tuple[bool, str]:
        """
        Test OneDrive connection using Microsoft Graph API.

        Args:
            config: Validated OneDrive configuration

        Returns:
            Tuple[bool, str]: (success, message)
        """
        onedrive_config: OneDriveSourceConfig = cast(OneDriveSourceConfig, config)
        try:
            # Create loader to test authentication
            loader = MicrosoftGraphLoader(
                drive_id=onedrive_config.drive_id,
                client_id=onedrive_config.client_id,
                client_secret=onedrive_config.client_secret,
                tenant_id=onedrive_config.tenant_id,
                folder_path=onedrive_config.folder_path,
                recursive=False,  # Don't recurse for connection test
            )

            # Try to get access token (this will fail if credentials are invalid)
            token = loader._get_token()

            if not token:
                return False, "Failed to acquire access token"

            # Try to list files (this will fail if drive_id or folder_path is invalid)
            files = list(loader.lazy_load())

            return True, f"Successfully connected to OneDrive. Found {len(files)} document(s)."

        except ImportError:
            return False, "Microsoft Graph dependencies not installed (msal, requests)"
        except ValueError as e:
            return False, f"Configuration error: {e!s}"
        except Exception as e:
            return False, f"Connection test failed: {e!s}"

    def get_config_schema(self) -> type[BaseModel]:
        """
        Get the configuration schema for this adapter.

        Returns:
            type[BaseModel]: The Pydantic configuration model
        """
        return OneDriveSourceConfig

    def fetch_binary_content(
        self,
        *,
        source_id: str,
        provider_config: dict[str, Any],
    ) -> bytes | None:
        """
        Fetch binary content for a specific document from OneDrive on-demand.

        Args:
            source_id: OneDrive item ID (file ID) or web URL
            provider_config: All provider-specific parameters including credentials.

        Returns:
            bytes | None: Binary content of the OneDrive file, or None if not found or error occurred
        """
        try:
            drive_id = resolve_env_var(provider_config.get("drive_id"))
            client_id = resolve_env_var(provider_config.get("client_id"))
            client_secret = resolve_env_var(provider_config.get("client_secret"))
            tenant_id = resolve_env_var(provider_config.get("tenant_id"))

            if not all([drive_id, client_id, client_secret, tenant_id]):
                logger.error("Missing required parameters for OneDrive binary content fetch")
                return None

            logger.debug("Using drive_id for binary fetch: %s", drive_id)

            # Handle case where source_id is a web URL instead of item_id
            item_id = source_id
            if source_id.lower().startswith(("http://", "https://")):
                extracted_id = provider_config.get("item_id")
                if not extracted_id:
                    logger.error("source_id is a web URL but no item_id found in provider_config: %s", source_id)
                    return None
                item_id = str(extracted_id)
                logger.info("Extracted item_id from provider_config: %s (source_id was web URL)", item_id)

            # Reuse cached loader — avoids a new MSAL token request per document
            loader = self._get_loader(
                drive_id=str(drive_id),
                client_id=str(client_id),
                client_secret=str(client_secret),
                tenant_id=str(tenant_id),
            )

            # Get access token (cached on loader instance)
            token = loader._get_token()
            headers = {"Authorization": f"Bearer {token}"}

            logger.info("Downloading binary content from OneDrive: drive_id=%s, item_id=%s", drive_id, item_id)

            # Try direct download URL first
            endpoint = f"/drives/{drive_id}/items/{item_id}"
            item_data = loader._rest_client.call_rest_json(
                method=RestMethod.GET,
                url=endpoint,
                headers=headers,
            )

            download_url = item_data.get("@microsoft.graph.downloadUrl")

            if download_url:
                # Use direct download URL
                from docpipe.integrations.rest_client import RestClient, RestClientConfig

                temp_config = RestClientConfig(
                    timeout=120,
                    max_retries=3,
                    retry_backoff_factor=2.0,
                    verify_ssl=True,
                )
                temp_client = RestClient(config=temp_config)
                response = temp_client.call_rest(
                    method=RestMethod.GET,
                    url=download_url,
                )
                content = response.content
            else:
                # Fallback: use content endpoint
                content_endpoint = f"/drives/{drive_id}/items/{item_id}/content"
                response = loader._rest_client.call_rest(
                    method=RestMethod.GET,
                    url=content_endpoint,
                    headers=headers,
                    expected_status_codes=[200, 302],
                )
                content = response.content

            logger.info("Successfully downloaded %s bytes from OneDrive: %s", len(content), item_id)
            return content

        except Exception:
            logger.exception("Error fetching binary content from OneDrive %s", source_id)
            return None

    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict,
        included_extensions: list[str] | None = None,
        max_files: int | None = None,
    ) -> BaseModel:
        """
        Build OneDrive configuration from operator parameters.

        Args:
            provider_config: All provider-specific parameters including credentials.
            included_extensions: File extensions to include (optional)
            max_files: Not used by the OneDrive adapter.

        Returns:
            OneDriveSourceConfig: Validated configuration object
        """
        if included_extensions is None:
            included_extensions = []

        config_params = {
            "client_id": resolve_env_var(provider_config.get("client_id", "")),
            "client_secret": resolve_env_var(provider_config.get("client_secret", "")),
            "tenant_id": resolve_env_var(provider_config.get("tenant_id", "")),
            "drive_id": resolve_env_var(provider_config.get("drive_id", "")),
            "folder_path": resolve_env_var(provider_config.get("folder_path")),
            "recursive": provider_config.get("recursive", True),
            "file_extensions": included_extensions,
            "max_file_size_mb": provider_config.get("max_file_size_mb"),
        }

        if "file_path" in provider_config:
            config_params["file_path"] = provider_config["file_path"]

        if "graph_api_version" in provider_config:
            config_params["graph_api_version"] = provider_config["graph_api_version"]

        return OneDriveSourceConfig(**config_params)
