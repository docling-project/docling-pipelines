# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""SharePoint destination adapter — writes documents via Microsoft Graph API."""

from typing import Any

from pydantic import BaseModel

from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
    register_destination_adapter,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.config import (
    SharePointDestinationConfig,
)
from docpipe.core.operators.storage.domain.models import WriteResult
from docpipe.core.operators.storage.ports.outbound.destination_adapter import DestinationAdapterPort
from docpipe.utils.infrastructure.exception_sanitizer import sanitize_exception
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Lazy import guard — msal is an optional dependency.
try:
    from docpipe.core.operators.ingest.ingest_source import MicrosoftGraphLoader
    from docpipe.integrations.rest_client import RestClient, RestClientConfig, RestMethod

    _GRAPH_AVAILABLE = True
except ImportError:
    MicrosoftGraphLoader = None  # type: ignore[assignment,misc]
    RestClient = None  # type: ignore[assignment]
    RestClientConfig = None  # type: ignore[assignment]
    RestMethod = None  # type: ignore[assignment]
    _GRAPH_AVAILABLE = False

_GRAPH_BASE_URL = "https://graph.microsoft.com"


@register_destination_adapter
class SharePointDestinationAdapter(DestinationAdapterPort[SharePointDestinationConfig]):
    """Write documents to a SharePoint document library via the Microsoft Graph API.

    Mirrors the SharePointSourceAdapter: uses drive-based Graph API endpoints
    with document_library_id as the drive ID, matching the ingest-side convention::

        GET/PUT /drives/{document_library_id}/root:/{folder_path}/{file}:/content
    """

    DEST_NAME = "sharepoint"
    DEST_DISPLAY_NAME = "Microsoft SharePoint"
    DEST_VERSION = "1.0.0"

    # ------------------------------------------------------------------
    # DestinationAdapterPort interface
    # ------------------------------------------------------------------

    def validate_destination(
        self,
        *,
        config: SharePointDestinationConfig | None = None,
    ) -> WriteResult | None:
        """Verify that the document library (and optionally the target folder) is reachable.

        Returns a failed WriteResult on the first problem, or None when all is well.
        """
        if not _GRAPH_AVAILABLE:
            return WriteResult(
                doc_id="",
                doc_name="",
                success=False,
                error_message=(
                    "Microsoft Graph dependencies are not installed. Install with: uv pip install msal requests"
                ),
            )
        if config is None:
            return None

        try:
            loader = self._make_loader(config)
            token = loader._get_token()
            headers = {"Authorization": f"Bearer {token}"}
            # Use relative endpoints with MicrosoftGraphLoader's RestClient base_url.
            drive_endpoint = f"/drives/{config.drive_id}"
            logger.info("Validating SharePoint drive access: drive_id=%s, endpoint=%s", config.drive_id, drive_endpoint)
            response = loader._rest_client.call_rest(
                method=RestMethod.GET,
                url=drive_endpoint,
                headers=headers,
                expected_status_codes=[200],
            )
            if response.status_code != 200:
                msg = f"SharePoint document library '{config.drive_id}' is not accessible (HTTP {response.status_code})"
                logger.error(msg)
                return WriteResult(doc_id="", doc_name="", success=False, error_message=msg)

            logger.info(
                "SharePoint drive validation succeeded: drive_id=%s, folder_path=%s, create_dirs=%s",
                config.drive_id,
                config.folder_path,
                config.create_dirs,
            )

            # When create_dirs is disabled, verify the target folder already exists.
            if not config.create_dirs and config.folder_path:
                folder_path = config.folder_path.strip("/")
                folder_endpoint = f"/drives/{config.drive_id}/root:/{folder_path}"
                logger.info("Validating SharePoint folder access: endpoint=%s", folder_endpoint)
                folder_response = loader._rest_client.call_rest(
                    method=RestMethod.GET,
                    url=folder_endpoint,
                    headers=headers,
                    expected_status_codes=[200, 404],
                )
                if folder_response.status_code == 404:
                    msg = f"destination folder path does not exist and create_dirs is disabled: {config.folder_path}"
                    logger.error(msg)
                    return WriteResult(doc_id="", doc_name="", success=False, error_message=msg)

        except Exception as e:
            safe_error = sanitize_exception(exc=e, config_key="storage_output.destination_config.sharepoint")
            msg = (
                "SharePoint destination validation failed: "
                f"drive_id={config.drive_id}, folder_path={config.folder_path}, create_dirs={config.create_dirs}, "
                f"error={safe_error}"
            )
            logger.error(msg)
            return WriteResult(doc_id="", doc_name="", success=False, error_message=msg)

        return None

    def write_document(
        self,
        *,
        content: bytes,
        destination_path: str,
        overwrite: bool = True,
        config: SharePointDestinationConfig | None = None,
    ) -> WriteResult:
        """Upload bytes to SharePoint at destination_path.

        destination_path is the full path within the drive, already resolved
        by resolve_destination_path (folder_path prepended).
        """
        if not _GRAPH_AVAILABLE:
            return WriteResult(
                doc_id="",
                doc_name=destination_path,
                success=False,
                error_message=(
                    "Microsoft Graph dependencies are not installed. Install with: uv pip install msal requests"
                ),
            )
        if config is None:
            return WriteResult(
                doc_id="",
                doc_name=destination_path,
                success=False,
                error_message="SharePointDestinationConfig is required",
            )

        try:
            loader = self._make_loader(config)
            token = loader._get_token()
            headers = {"Authorization": f"Bearer {token}"}
            drive_id = config.drive_id

            # Mirrors source adapter: /drives/{drive_id}/root:/{path}
            item_path = destination_path.lstrip("/")
            item_endpoint = f"/drives/{drive_id}/root:/{item_path}"

            if not overwrite:
                check_response = loader._rest_client.call_rest(
                    method=RestMethod.GET,
                    url=item_endpoint,
                    headers=headers,
                    expected_status_codes=[200, 404],
                )
                if check_response.status_code == 200:
                    return WriteResult(
                        doc_id="",
                        doc_name=destination_path,
                        success=False,
                        error_message="file exists, overwrite disabled",
                    )

            # PUT /drives/{id}/root:/{path}:/content — creates or replaces the file.
            upload_endpoint = f"{item_endpoint}:/content"
            upload_headers = {**headers, "Content-Type": "application/octet-stream"}

            logger.info(
                "Uploading binary content to SharePoint: document_library_id=%s, path=%s",
                drive_id,
                item_path,
            )

            upload_response = loader._rest_client.session.put(
                url=loader._rest_client._build_url(upload_endpoint),
                headers=upload_headers,
                data=content,
                timeout=120,
                verify=loader._rest_client.config.verify_ssl,
            )
            if upload_response.status_code not in (200, 201):
                error_msg = (
                    f"Unexpected status code {upload_response.status_code}. Expected one of [200, 201]. "
                    f"Response: {upload_response.text[:500]}"
                )
                logger.error(error_msg)

            if upload_response.status_code not in (200, 201):
                msg = f"SharePoint upload failed (HTTP {upload_response.status_code}): {upload_response.text[:200]}"
                return WriteResult(doc_id="", doc_name=destination_path, success=False, error_message=msg)

            web_url = upload_response.json().get("webUrl", destination_path)
            logger.info("Successfully uploaded %d bytes to SharePoint: %s", len(content), web_url)
            return WriteResult(
                doc_id="",
                doc_name=destination_path,
                success=True,
                destination_path=web_url,
                bytes_written=len(content),
            )

        except Exception as e:
            safe_error = sanitize_exception(exc=e, config_key="storage_output.destination_config.sharepoint")
            msg = f"Unexpected error writing to SharePoint '{destination_path}': {safe_error}"
            logger.error(msg)
            return WriteResult(doc_id="", doc_name=destination_path, success=False, error_message=msg)

    def ensure_directory(self, *, path: str) -> None:
        """No-op — Microsoft Graph creates intermediate folders automatically on upload."""

    def resolve_destination_path(
        self,
        *,
        relative_path: str,
        config: SharePointDestinationConfig,
    ) -> str:
        """Prepend folder_path to the relative path to form the full item path in the drive.

        Mirrors source adapter: folder_path acts as the root within the document library.
        """
        if config.folder_path:
            return config.folder_path.rstrip("/") + "/" + relative_path.lstrip("/")
        return relative_path

    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> SharePointDestinationConfig:
        """Build SharePointDestinationConfig from operator flow params.

        Uses the same credentials keys as SharePointSourceConfig.
        Note: the source adapter uses ``document_library_id`` for the same value;
        the destination adapter uses the Graph API term ``drive_id`` instead::

            provider_config:
                drive_id: "b!abc123..."
                folder_path: "/Processed Documents"   # optional
            credentials:
                client_id:     "${SHAREPOINT_CLIENT_ID}"
                client_secret: "${SHAREPOINT_CLIENT_SECRET}"
                tenant_id:     "${SHAREPOINT_TENANT_ID}"
        """
        client_id = resolve_env_var(credentials.get("client_id"))
        client_secret = resolve_env_var(credentials.get("client_secret"))
        tenant_id = resolve_env_var(credentials.get("tenant_id"))

        if not client_id:
            raise ValueError("Missing required SharePoint credential: 'client_id'")
        if not client_secret:
            raise ValueError("Missing required SharePoint credential: 'client_secret'")
        if not tenant_id:
            raise ValueError("Missing required SharePoint credential: 'tenant_id'")

        drive_id = resolve_env_var(provider_config.get("drive_id"))
        if not drive_id:
            raise ValueError("Missing required SharePoint provider_config parameter: 'drive_id'")

        return SharePointDestinationConfig(
            client_id=client_id,
            client_secret=client_secret,
            tenant_id=tenant_id,
            drive_id=drive_id,
            folder_path=provider_config.get("folder_path", ""),
            create_dirs=provider_config.get("create_dirs", True),
            graph_api_version=provider_config.get("graph_api_version", "v1.0"),
        )

    def get_config_schema(self) -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        return SharePointDestinationConfig

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _make_loader(self, config: SharePointDestinationConfig) -> Any:
        """Instantiate a MicrosoftGraphLoader for token acquisition and REST client reuse.

        Mirrors SharePointSourceAdapter: document_library_id is passed as drive_id.
        """
        return MicrosoftGraphLoader(
            drive_id=config.drive_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            tenant_id=config.tenant_id,
            folder_path=None,
            recursive=False,
        )
