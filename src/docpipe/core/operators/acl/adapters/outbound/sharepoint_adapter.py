# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""SharePoint ACL adapter for extracting permissions using Microsoft Graph API.

This adapter extracts Access Control List (ACL) information from SharePoint documents
using the Microsoft Graph API. It supports:
- OAuth2 client credentials authentication
- Recursive inheritance resolution (item → folder → library → site → root)
- Transitive group expansion
- Identity normalization (various SharePoint formats → canonical email/UPN)
- Shared link permissions
- Organization-wide sharing

Key Features:
- Reuses MSAL authentication from MicrosoftGraphLoader
- Handles inherited permissions from parent folders
- Resolves SharePoint-specific identity formats
- Supports both user and group principals
"""

import asyncio
import re
from typing import ClassVar

from pydantic import BaseModel, Field

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.acl.adapters.outbound.factories.acl_adapter_factory import (
    register_acl_adapter,
)
from docpipe.core.operators.acl.domain.models import ACLRequest, ACLResponse, RawPermission
from docpipe.core.operators.acl.ports.outbound.acl_extraction import ACLExtractionPort
from docpipe.exceptions.docpipe_exceptions import (
    ConfigurationError,
    ExternalServiceError,
)
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations.rest_client import RestClient, RestClientConfig, RestMethod
from docpipe.integrations.secrets.secret_value import reveal_value
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Microsoft Graph API Constants (module-level - SharePoint-specific)
_MICROSOFT_LOGIN_URL: str = "https://login.microsoftonline.com"
_MICROSOFT_GRAPH_API_BASE: str = "https://graph.microsoft.com/v1.0"
_MICROSOFT_GRAPH_SCOPE: str = "https://graph.microsoft.com/.default"
_MICROSOFT_OAUTH_TOKEN_PATH: str = "/oauth2/v2.0/token"

# SharePoint Permission Role Constants (module-level - SharePoint-specific)
_SHAREPOINT_ROLE_READ: str = "read"
_SHAREPOINT_ROLE_WRITE: str = "write"
_SHAREPOINT_ROLE_OWNER: str = "owner"

# SharePoint Identity Format Prefixes (module-level - SharePoint-specific)
_SHAREPOINT_CLAIMS_PREFIX: str = "i:0#.f|membership|"
_SHAREPOINT_AAD_PREFIX: str = "i:0#.f|aad|"
_SHAREPOINT_WINDOWS_PREFIX: str = "i:0#.w|"

# Microsoft Graph API Endpoint Templates (module-level - SharePoint-specific)
_GRAPH_PERMISSIONS_ENDPOINT: str = "/drives/{drive_id}/items/{item_id}/permissions"
_GRAPH_ITEM_ENDPOINT: str = "/drives/{drive_id}/items/{item_id}"
_GRAPH_GROUP_MEMBERS_ENDPOINT: str = "/groups/{group_id}/transitiveMembers"
_GRAPH_USER_ENDPOINT: str = "/users/{user_id}"

# Batch Processing Defaults (module-level - SharePoint-specific)
_DEFAULT_BATCH_SIZE: int = 10
_DEFAULT_MAX_CONCURRENT_REQUESTS: int = 5
_DEFAULT_REQUEST_TIMEOUT: int = 60

# Configuration Keys (module-level - SharePoint-specific)
_CONFIG_CLIENT_ID: str = "client_id"
_CONFIG_CLIENT_SECRET: str = "client_secret"
_CONFIG_TENANT_ID: str = "tenant_id"
_CONFIG_DRIVE_ID: str = "drive_id"
_CONFIG_ITEM_ID: str = "item_id"

# Graph API Response Keys (module-level - SharePoint-specific)
_GRAPH_VALUE_KEY: str = "value"
_GRAPH_NEXT_LINK_KEY: str = "@odata.nextLink"
_GRAPH_ODATA_TYPE_KEY: str = "@odata.type"
_GRAPH_USER_TYPE: str = "#microsoft.graph.user"
_GRAPH_USER_PRINCIPAL_NAME: str = "userPrincipalName"
_GRAPH_PARENT_REFERENCE: str = "parentReference"
_GRAPH_GRANTED_TO: str = "grantedTo"
_GRAPH_GRANTED_TO_IDENTITIES: str = "grantedToIdentities"
_GRAPH_INHERITED_FROM: str = "inheritedFrom"
_GRAPH_ROLES: str = "roles"
_GRAPH_USER: str = "user"
_GRAPH_GROUP: str = "group"
_GRAPH_EMAIL: str = "email"
_GRAPH_DISPLAY_NAME: str = "displayName"

# Permission Types (module-level - SharePoint-specific)
_PERMISSION_TYPE_ALLOW: str = "allow"
_PERMISSION_TYPE_DENY: str = "deny"

# Principal Types (module-level - SharePoint-specific)
_PRINCIPAL_TYPE_USER: str = "user"
_PRINCIPAL_TYPE_GROUP: str = "group"
_PRINCIPAL_TYPE_UNKNOWN: str = "unknown"

# Inheritance Constants (module-level - SharePoint-specific)
_MAX_INHERITANCE_DEPTH: int = 10


class SharePointACLConfig(BaseModel):
    """Configuration for SharePoint ACL extraction via Microsoft Graph API.

    Attributes:
        client_id: Azure AD application (client) ID
        client_secret: Azure AD application client secret
        tenant_id: Azure AD tenant ID
        drive_id: SharePoint drive (document library) ID
        resolve_inheritance: Whether to recursively resolve inheritance chain
        expand_groups: Whether to expand groups to individual users
        normalize_identities: Whether to normalize identities to canonical form
        max_concurrent_requests: Maximum concurrent API requests
        request_timeout: Request timeout in seconds
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields. The ACL operator declares
    # ``credentials.*`` operator-wide, which covers these.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = ("client_secret",)

    client_id: str = Field(..., description="Azure AD application (client) ID")
    client_secret: str = Field(..., description="Azure AD application client secret")
    tenant_id: str = Field(..., description="Azure AD tenant ID")
    drive_id: str = Field(..., description="SharePoint drive (document library) ID")

    # ACL extraction options
    resolve_inheritance: bool = Field(default=True, description="Recursively resolve inheritance chain")
    expand_groups: bool = Field(default=True, description="Expand groups to individual users")
    normalize_identities: bool = Field(default=True, description="Normalize identities to canonical email/UPN")

    # Performance options
    max_concurrent_requests: int = Field(
        default=_DEFAULT_MAX_CONCURRENT_REQUESTS, description="Maximum concurrent API requests"
    )
    request_timeout: int = Field(default=_DEFAULT_REQUEST_TIMEOUT, description="Request timeout in seconds")


@register_acl_adapter(OperatorConstants.ACL.PROVIDER_SHAREPOINT)
class SharePointACLAdapter(ACLExtractionPort[SharePointACLConfig]):
    """Adapter for extracting ACL information from SharePoint via Microsoft Graph API.

    This adapter implements the ACLExtractionPort interface for SharePoint/OneDrive
    documents. It uses the Microsoft Graph API with OAuth2 client credentials flow
    for authentication.

    Key Capabilities:
    - Extract permissions from SharePoint items (files/folders)
    - Resolve inheritance recursively up to root site
    - Expand groups transitively to individual users
    - Normalize SharePoint identity formats to canonical email/UPN
    - Handle shared links and organization-wide permissions

    Authentication:
    - Uses MSAL (Microsoft Authentication Library) for OAuth2
    - Supports client credentials flow (app-only authentication)
    - Reuses authentication pattern from MicrosoftGraphLoader
    """

    ADAPTER_NAME = "sharepoint"
    ADAPTER_DISPLAY_NAME = "SharePoint ACL"
    ADAPTER_DESCRIPTION = "Extract ACL information from SharePoint documents via Microsoft Graph API"
    ADAPTER_VERSION = "1.0.0"

    def __init__(self) -> None:
        """Initialize SharePoint ACL adapter."""
        super().__init__()
        self._token_cache: dict[str, str] = {}
        self._group_cache: dict[str, set[str]] = {}
        self._identity_cache: dict[str, str] = {}

    async def extract_acl(self, *, request: ACLRequest) -> ACLResponse:
        """Extract effective ACL for a single SharePoint item.

        This method:
        1. Fetches raw permissions from Microsoft Graph API
        2. Resolves inheritance recursively if requested
        3. Expands groups transitively if requested
        4. Normalizes identities if requested
        5. Returns effective allowed users

        Args:
            request: ACL extraction request with item details and options

        Returns:
            ACLResponse containing effective allowed users and metadata
        """
        try:
            config = self.build_config_from_operator_params(
                connection_params=request.connection_params,
                credentials=request.credentials,
                provider_metadata=request.provider_metadata,
            )

            # Extract item ID from resource_id, path, or metadata
            item_id = await self._extract_item_id(
                config=config,
                resource_id=request.resource_id,
                resource_path=request.resource_path,
                provider_metadata=request.provider_metadata,
            )

            # Fetch raw permissions from Graph API
            raw_permissions = await self._fetch_permissions(config=config, item_id=item_id)

            # Build inheritance chain if requested
            inheritance_chain = []
            if config.resolve_inheritance:
                inheritance_chain = await self.resolve_inheritance(
                    resource_id=item_id, resource_type=request.resource_type, config=config
                )

            # Process permissions to extract allowed users
            allowed_users = set()
            denied_users = set()
            resolution_metadata = {
                "raw_permission_count": len(raw_permissions),
                OperatorConstants.ACL.INHERITANCE_CHAIN: len(inheritance_chain),
                "groups_expanded": 0,
                "identities_normalized": 0,
            }

            for perm in raw_permissions:
                # Skip denied permissions (SharePoint doesn't have explicit deny)
                if perm.permission_type == _PERMISSION_TYPE_DENY:
                    denied_users.add(perm.principal_id)
                    continue

                # Handle user principals
                if perm.principal_type == _PRINCIPAL_TYPE_USER:
                    identity = perm.principal_id
                    if config.normalize_identities:
                        identity = self.normalize_identity(
                            principal_id=identity, principal_type=_PRINCIPAL_TYPE_USER, config=config
                        )
                        resolution_metadata["identities_normalized"] += 1
                    # Only add non-empty identities
                    if identity and identity.strip():
                        allowed_users.add(identity)

                # Handle group principals
                elif perm.principal_type == _PRINCIPAL_TYPE_GROUP and config.expand_groups:
                    group_members = await self.expand_group(group_id=perm.principal_id, config=config)
                    allowed_users.update(group_members)
                    resolution_metadata["groups_expanded"] += 1

            # Remove denied users from allowed users
            allowed_users -= denied_users

            return ACLResponse(
                resource_id=request.resource_id,
                resource_path=request.resource_path,
                allowed_users=allowed_users,
                denied_users=denied_users if denied_users else None,
                inheritance_chain=inheritance_chain,
                has_unique_permissions=len(raw_permissions) > 0,
                resolution_metadata=resolution_metadata,
                extraction_success=True,
            )

        except (ConfigurationError, ExternalServiceError):
            # Re-raise Docpipe exceptions as-is
            raise
        except ImportError as e:
            # Missing dependencies
            logger.exception("Missing required dependency for SharePoint ACL extraction: %s", e)
            raise ConfigurationError(
                f"SharePoint ACL adapter requires missing dependency: {e!s}. Install with: pip install msal"
            ) from e
        except Exception as e:
            # Wrap unknown exceptions as ExternalServiceError
            logger.exception("Failed to extract ACL for SharePoint item %s: %s", request.resource_path, e)
            raise ExternalServiceError(
                f"SharePoint ACL extraction failed for {request.resource_path}: {e!s}",
                error_code=ErrorCode.ACL_EXTRACTION_FAILED,
            ) from e

    async def extract_acls_batch(self, *, requests: list[ACLRequest]) -> list[ACLResponse]:
        """Extract ACLs for multiple SharePoint items in batch.

        Processes requests concurrently with configurable concurrency limit.
        Uses max_concurrent_requests from connection_params if available.

        Args:
            requests: List of ACL extraction requests

        Returns:
            List of ACL responses in the same order as requests
        """
        # Get max_concurrent_requests from first request's connection_params
        max_concurrent = _DEFAULT_MAX_CONCURRENT_REQUESTS
        if requests:
            max_concurrent = requests[0].connection_params.get(
                OperatorConstants.Config.MAX_CONCURRENT_REQUESTS, _DEFAULT_MAX_CONCURRENT_REQUESTS
            )

        # Process requests concurrently with semaphore for rate limiting
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_semaphore(req: ACLRequest) -> ACLResponse:
            async with semaphore:
                return await self.extract_acl(request=req)

        tasks = [process_with_semaphore(req) for req in requests]
        return await asyncio.gather(*tasks)

    async def resolve_inheritance(
        self, *, resource_id: str, resource_type: str, config: SharePointACLConfig
    ) -> list[str]:
        """Recursively resolve inheritance chain for a SharePoint item.

        Traverses the hierarchy from item → folder → library → site → root.

        Args:
            resource_id: SharePoint item ID
            resource_type: Type of resource (file, folder, site)
            config: SharePoint configuration

        Returns:
            List of resource IDs from item to root
        """
        inheritance_chain = [resource_id]

        try:
            rest_client = self._create_rest_client(config=config)
            token = await self._get_token(config=config)
            headers = {"Authorization": f"Bearer {token}"}

            current_id = resource_id

            for _ in range(_MAX_INHERITANCE_DEPTH):
                # Fetch item details to get parent reference
                endpoint = _GRAPH_ITEM_ENDPOINT.format(drive_id=config.drive_id, item_id=current_id)

                item_data = rest_client.call_rest_json(method=RestMethod.GET, url=endpoint, headers=headers)

                # Check if item has parent
                parent_ref = item_data.get(_GRAPH_PARENT_REFERENCE)
                if not parent_ref or OperatorConstants.Columns.ID not in parent_ref:
                    break

                parent_id = parent_ref[OperatorConstants.Columns.ID]
                if parent_id in inheritance_chain:
                    # Circular reference detected
                    break

                inheritance_chain.append(parent_id)
                current_id = parent_id

        except Exception as e:
            logger.warning("Failed to resolve full inheritance chain for %s: %s", resource_id, e)

        return inheritance_chain

    async def expand_group(self, *, group_id: str, config: SharePointACLConfig) -> set[str]:
        """Expand SharePoint/AAD group to transitive members.

        Uses Microsoft Graph API to get all transitive members (including nested groups).
        Results are cached to avoid redundant API calls.

        Args:
            group_id: Azure AD group ID
            config: SharePoint configuration

        Returns:
            Set of normalized user identities (emails/UPNs)
        """
        # Check cache first
        if group_id in self._group_cache:
            return self._group_cache[group_id]

        members = set()

        try:
            rest_client = self._create_rest_client(config=config)
            token = await self._get_token(config=config)
            headers = {"Authorization": f"Bearer {token}"}

            endpoint: str | None = _GRAPH_GROUP_MEMBERS_ENDPOINT.format(group_id=group_id)

            # Handle pagination
            while endpoint:
                data = rest_client.call_rest_json(method=RestMethod.GET, url=endpoint, headers=headers)

                for member in data.get(_GRAPH_VALUE_KEY, []):
                    # Only include users, not nested groups
                    if member.get(_GRAPH_ODATA_TYPE_KEY) == _GRAPH_USER_TYPE:
                        user_principal = member.get(_GRAPH_USER_PRINCIPAL_NAME)
                        if user_principal:
                            members.add(user_principal.lower())

                # Get next page
                next_link = data.get(_GRAPH_NEXT_LINK_KEY)
                if next_link:
                    endpoint = next_link.replace(_MICROSOFT_GRAPH_API_BASE, "")
                else:
                    endpoint = None

            # Cache the result
            self._group_cache[group_id] = members

        except Exception as e:
            logger.warning("Failed to expand group %s: %s", group_id, e)

        return members

    def normalize_identity(self, *, principal_id: str, principal_type: str, config: SharePointACLConfig) -> str:
        """Normalize SharePoint identity to canonical email/UPN format.

        Handles various SharePoint identity formats:
        - i:0#.f|membership|user@domain.com → user@domain.com
        - i:0#.f|aad|guid → lookup email via Graph API
        - user@domain.com → user@domain.com (already normalized)

        Args:
            principal_id: SharePoint principal identifier
            principal_type: Type of principal (user, group)
            config: SharePoint configuration

        Returns:
            Normalized identity string (lowercase email/UPN)
        """
        # Check cache first
        if principal_id in self._identity_cache:
            return self._identity_cache[principal_id]

        normalized = principal_id.lower()

        # Handle SharePoint claims format: i:0#.f|membership|user@domain.com
        if principal_id.startswith(_SHAREPOINT_CLAIMS_PREFIX):
            normalized = principal_id[len(_SHAREPOINT_CLAIMS_PREFIX) :].lower()

        # Handle AAD format: i:0#.f|aad|{guid}
        elif principal_id.startswith(_SHAREPOINT_AAD_PREFIX):
            guid = principal_id[len(_SHAREPOINT_AAD_PREFIX) :]
            # Try to lookup user by GUID (async operation, skip for now)
            normalized = guid.lower()

        # Handle Windows format: i:0#.w|domain\user
        elif principal_id.startswith(_SHAREPOINT_WINDOWS_PREFIX):
            windows_id = principal_id[len(_SHAREPOINT_WINDOWS_PREFIX) :]
            # Extract username from domain\user format
            if "\\" in windows_id:
                normalized = windows_id.split("\\", 1)[1].lower()
            else:
                normalized = windows_id.lower()

        # Already in email format
        elif "@" in principal_id:
            normalized = principal_id.lower()

        # Cache the result
        self._identity_cache[principal_id] = normalized

        return normalized

    async def test_connection(self, *, config: SharePointACLConfig) -> bool:
        """Test connection to Microsoft Graph API.

        Verifies that the adapter can successfully authenticate and access
        the SharePoint drive.

        Args:
            config: SharePoint configuration

        Returns:
            True if connection is successful, False otherwise
        """
        try:
            rest_client = self._create_rest_client(config=config)
            token = await self._get_token(config=config)
            headers = {"Authorization": f"Bearer {token}"}

            # Test by fetching drive details
            endpoint = f"/drives/{config.drive_id}"
            rest_client.call_rest_json(method=RestMethod.GET, url=endpoint, headers=headers)

            logger.info("Successfully connected to SharePoint drive %s", config.drive_id)
            return True

        except Exception as e:
            logger.error("Failed to connect to SharePoint: %s", e)
            return False

    def build_config_from_operator_params(
        self, *, connection_params: dict, credentials: dict, provider_metadata: dict
    ) -> SharePointACLConfig:
        """Build SharePoint configuration from operator parameters.

        Note: drive_id is optional when using URL-based ACL lookups.
        The adapter will resolve URLs to item IDs using the Graph API.

        Args:
            connection_params: Connection parameters from operator
            credentials: Authentication credentials from operator
            provider_metadata: Provider-specific metadata from operator

        Returns:
            SharePointACLConfig object

        Raises:
            ValueError: If required parameters are missing
        """
        connection_params = reveal_value(connection_params)
        credentials = reveal_value(credentials)
        provider_metadata = reveal_value(provider_metadata)
        # Extract required credentials
        client_id = credentials.get(_CONFIG_CLIENT_ID)
        client_secret = credentials.get(_CONFIG_CLIENT_SECRET)
        tenant_id = credentials.get(_CONFIG_TENANT_ID)

        if not client_id or not client_secret or not tenant_id:
            raise ConfigurationError(
                f"SharePoint ACL adapter requires {_CONFIG_CLIENT_ID}, {_CONFIG_CLIENT_SECRET}, "
                f"and {_CONFIG_TENANT_ID} in credentials"
            )

        # Extract drive_id from connection_params or provider_metadata (optional for URL-based lookups)
        # Use a placeholder if not provided - URLs will be resolved to drive_id + item_id
        # Note: IngestSourceOperator stores this as 'document_library_id' in metadata
        drive_id = (
            connection_params.get(_CONFIG_DRIVE_ID)
            or provider_metadata.get(_CONFIG_DRIVE_ID)
            or provider_metadata.get("document_library_id")  # IngestSource uses this key
            or "url-based"
        )

        return SharePointACLConfig(
            client_id=str(client_id),
            client_secret=str(client_secret),
            tenant_id=str(tenant_id),
            drive_id=str(drive_id),
            resolve_inheritance=connection_params.get(
                OperatorConstants.ACL.RESOLVE_INHERITANCE, OperatorConstants.ACL.DEFAULT_RESOLVE_INHERITANCE
            ),
            expand_groups=connection_params.get(
                OperatorConstants.ACL.EXPAND_GROUPS, OperatorConstants.ACL.DEFAULT_EXPAND_GROUPS
            ),
            normalize_identities=connection_params.get(
                OperatorConstants.ACL.NORMALIZE_IDENTITIES, OperatorConstants.ACL.DEFAULT_NORMALIZE_IDENTITIES
            ),
            max_concurrent_requests=connection_params.get(
                OperatorConstants.Config.MAX_CONCURRENT_REQUESTS, _DEFAULT_MAX_CONCURRENT_REQUESTS
            ),
            request_timeout=connection_params.get("request_timeout", _DEFAULT_REQUEST_TIMEOUT),
        )

    # Private helper methods

    def _create_rest_client(self, *, config: SharePointACLConfig) -> RestClient:
        """Create RestClient for Microsoft Graph API calls.

        Args:
            config: SharePoint configuration

        Returns:
            Configured RestClient instance
        """
        rest_config = RestClientConfig(
            timeout=config.request_timeout,
            retry_backoff_factor=2.0,
        )
        return RestClient(
            config=rest_config,
            base_url=_MICROSOFT_GRAPH_API_BASE,
        )

    async def _get_token(self, *, config: SharePointACLConfig) -> str:
        """Acquire OAuth2 access token via MSAL client credentials flow.

        Uses MSAL (Microsoft Authentication Library) to acquire an app-only
        access token for Microsoft Graph API.

        Args:
            config: SharePoint configuration

        Returns:
            Access token string

        Raises:
            ImportError: If msal package is not installed
            ValueError: If token acquisition fails
        """
        # Check cache first
        cache_key = f"{config.tenant_id}:{config.client_id}"
        if cache_key in self._token_cache:
            return self._token_cache[cache_key]

        try:
            import msal
        except ImportError as e:
            raise ConfigurationError("msal package not found. Install with: pip install msal") from e

        try:
            app = msal.ConfidentialClientApplication(
                config.client_id,
                authority=f"{_MICROSOFT_LOGIN_URL}/{config.tenant_id}",
                client_credential=config.client_secret,
            )

            result = await asyncio.to_thread(
                app.acquire_token_for_client,
                scopes=[_MICROSOFT_GRAPH_SCOPE],
            )

            if not isinstance(result, dict):
                raise ExternalServiceError(
                    f"Unexpected Microsoft Graph API response type: {type(result).__name__}",
                    error_code=ErrorCode.ACL_AUTHENTICATION_FAILED,
                )

            access_token = result.get("access_token")
            if not access_token:
                error = result.get("error", "unknown")
                error_desc = result.get("error_description", "no description")
                raise ExternalServiceError(
                    f"Failed to acquire Microsoft Graph token: {error} - {error_desc}",
                    error_code=ErrorCode.ACL_AUTHENTICATION_FAILED,
                )
        except (ConfigurationError, ExternalServiceError):
            # Re-raise Docpipe exceptions as-is
            raise
        except Exception as e:
            # Wrap authentication errors
            raise ExternalServiceError(
                f"Microsoft Graph authentication failed: {e!s}", error_code=ErrorCode.ACL_AUTHENTICATION_FAILED
            ) from e

        # Cache the token
        self._token_cache[cache_key] = access_token

        return access_token

    async def _fetch_permissions(self, *, config: SharePointACLConfig, item_id: str) -> list[RawPermission]:
        """Fetch raw permissions for a SharePoint item.

        Args:
            config: SharePoint configuration
            item_id: SharePoint item ID

        Returns:
            List of RawPermission objects
        """
        permissions = []

        try:
            rest_client = self._create_rest_client(config=config)
            token = await self._get_token(config=config)
            headers = {"Authorization": f"Bearer {token}"}

            endpoint = _GRAPH_PERMISSIONS_ENDPOINT.format(drive_id=config.drive_id, item_id=item_id)

            data = rest_client.call_rest_json(method=RestMethod.GET, url=endpoint, headers=headers)

            for perm in data.get(_GRAPH_VALUE_KEY, []):
                permissions.extend(self._parse_graph_permission(permission=perm))

        except Exception as e:
            logger.warning("Failed to fetch permissions for item %s: %s", item_id, e)

        return permissions

    def _parse_graph_permission(self, *, permission: dict) -> list[RawPermission]:
        """Parse Microsoft Graph permission object into RawPermission objects.

        Args:
            permission: Graph API permission object

        Returns:
            List of RawPermission objects (one per principal)
        """
        raw_permissions = []

        # Extract roles
        roles = permission.get(_GRAPH_ROLES, [])
        permission_type = _PERMISSION_TYPE_ALLOW  # SharePoint doesn't have explicit deny

        # Handle grantedTo (single principal)
        granted_to = permission.get(_GRAPH_GRANTED_TO)
        if granted_to:
            raw_permissions.append(
                self._create_raw_permission(
                    principal=granted_to,
                    roles=roles,
                    permission_type=permission_type,
                    is_inherited=permission.get(_GRAPH_INHERITED_FROM) is not None,
                    inherited_from=permission.get(_GRAPH_INHERITED_FROM, {}).get(OperatorConstants.Columns.ID),
                )
            )

        # Handle grantedToIdentities (multiple principals)
        granted_to_identities = permission.get(_GRAPH_GRANTED_TO_IDENTITIES, [])
        for identity in granted_to_identities:
            raw_permissions.append(
                self._create_raw_permission(
                    principal=identity,
                    roles=roles,
                    permission_type=permission_type,
                    is_inherited=permission.get(_GRAPH_INHERITED_FROM) is not None,
                    inherited_from=permission.get(_GRAPH_INHERITED_FROM, {}).get(OperatorConstants.Columns.ID),
                )
            )

        return raw_permissions

    def _create_raw_permission(
        self, *, principal: dict, roles: list[str], permission_type: str, is_inherited: bool, inherited_from: str | None
    ) -> RawPermission:
        """Create RawPermission from Graph API principal data.

        Args:
            principal: Graph API principal object
            roles: List of role names
            permission_type: Permission type (allow/deny)
            is_inherited: Whether permission is inherited
            inherited_from: Resource ID from which permission is inherited

        Returns:
            RawPermission object
        """
        user = principal.get(_GRAPH_USER, {})
        group = principal.get(_GRAPH_GROUP, {})

        if user:
            principal_type = _PRINCIPAL_TYPE_USER
            principal_id = user.get(_GRAPH_EMAIL) or user.get(OperatorConstants.Columns.ID, "")
            principal_name = user.get(_GRAPH_DISPLAY_NAME)
        elif group:
            principal_type = _PRINCIPAL_TYPE_GROUP
            principal_id = group.get(_GRAPH_EMAIL) or group.get(OperatorConstants.Columns.ID, "")
            principal_name = group.get(_GRAPH_DISPLAY_NAME)
        else:
            principal_type = _PRINCIPAL_TYPE_UNKNOWN
            principal_id = principal.get(OperatorConstants.Columns.ID, "")
            principal_name = principal.get(_GRAPH_DISPLAY_NAME)

        return RawPermission(
            principal_id=principal_id,
            principal_type=principal_type,
            principal_name=principal_name,
            role=",".join(roles) if roles else None,
            permission_type=permission_type,
            is_inherited=is_inherited,
            inherited_from=inherited_from,
            metadata={"raw_principal": principal},
        )

    async def _resolve_item_id_from_url(self, *, config: SharePointACLConfig, source_url: str) -> str:
        """Resolve SharePoint URL to DriveItem ID using Graph API.

        Supports SharePoint URL formats:
        - /sites/<site>/<library>/path/to/file
        - /teams/<team>/<library>/path/to/file
        - /personal/<user>/<library>/path/to/file

        IMPORTANT: The drive_id in config should point to the specific library.
        Graph API paths are relative to the drive root, so we skip the library name.

        For robustness, IngestSource should store item_id in metadata
        to avoid URL parsing. This method is a fallback for URL-based resolution.

        Args:
            config: SharePoint configuration with drive_id pointing to the library
            source_url: Full SharePoint URL (may be URL-encoded)

        Returns:
            DriveItem ID

        Raises:
            ConfigurationError: If URL format is unsupported
            ExternalServiceError: If item lookup fails
        """
        from urllib.parse import quote, unquote, urlparse

        try:
            # Parse URL and extract path components
            parsed = urlparse(source_url)
            # Decode URL-encoded path first (IngestSource may provide encoded URLs)
            decoded_path = unquote(parsed.path)
            # Split path and filter empty parts
            parts = [p for p in decoded_path.split("/") if p]

            # Validate SharePoint managed path
            managed_paths = {"sites", "teams", "personal"}

            if len(parts) < 3 or parts[0] not in managed_paths:
                raise ConfigurationError(
                    f"Unsupported SharePoint URL format: {source_url}. "
                    f"Expected format: https://tenant.sharepoint.com/{{sites|teams|personal}}/<name>/Library/path/to/file"
                )

            # Extract components
            managed_path = parts[0]  # 'sites', 'teams', or 'personal'
            site_name = parts[1]  # site/team/user name
            _library_name = parts[2]  # 'Shared Documents', etc.

            # Extract path relative to drive root (skip managed_path, site/team/user name, AND library name)
            # Example: ['sites', 'acl', 'Shared Documents', 'plaintext.txt'] -> 'plaintext.txt'
            # Example: ['sites', 'acl', 'Shared Documents', 'folder', 'file.txt'] -> 'folder/file.txt'
            relative_path = "/".join(parts[3:])  # Skip: managed_path, site_name, library_name

            # URL-encode the path for Graph API (encode spaces and special chars, preserve slashes)
            encoded_path = quote(relative_path, safe="/")

            # Choose endpoint based on whether we have a real drive_id
            if config.drive_id and config.drive_id != "url-based":
                endpoint = f"/drives/{config.drive_id}/root:/{encoded_path}:"
            else:
                site_path = f"/{managed_path}/{site_name}"
                endpoint = f"/sites/{parsed.netloc}:{site_path}:/drive/root:/{encoded_path}:"

            logger.info("Resolving URL to item_id: %s -> %s", source_url, endpoint)

            # Call Graph API to resolve path to item
            rest_client = self._create_rest_client(config=config)
            token = await self._get_token(config=config)
            headers = {"Authorization": f"Bearer {token}"}

            data = rest_client.call_rest_json(method=RestMethod.GET, url=endpoint, headers=headers)

            item_id = data.get("id")
            if not item_id:
                raise ExternalServiceError(
                    f"No item ID returned for URL: {source_url}", error_code=ErrorCode.ACL_EXTRACTION_FAILED
                )

            logger.info("Resolved SharePoint URL to item ID: %s", item_id)
            return str(item_id)

        except (ConfigurationError, ExternalServiceError):
            raise
        except Exception as e:
            raise ExternalServiceError(
                f"Failed to resolve item ID from SharePoint URL {source_url}: {e!s}",
                error_code=ErrorCode.ACL_EXTRACTION_FAILED,
            ) from e

    async def _extract_item_id(
        self, *, config: SharePointACLConfig, resource_id: str, resource_path: str, provider_metadata: dict
    ) -> str:
        """Extract SharePoint item ID from resource_id, path, or metadata.

        Priority order:
        1. item_id from provider_metadata (set by MicrosoftGraphLoader)
        2. id from provider_metadata (fallback)
        3. item_id from resource_id if it's not a URL
        4. Resolve from URL using Graph API (fallback)

        Args:
            config: SharePoint configuration
            resource_id: Resource identifier (typically source_id from IngestSource - may be URL or item ID)
            resource_path: Resource path (may contain item ID)
            provider_metadata: Provider-specific metadata

        Returns:
            SharePoint item ID

        Raises:
            ValueError: If item ID cannot be extracted
        """
        # BEST: Try to get item_id from metadata (set by MicrosoftGraphLoader)
        item_id = provider_metadata.get(_CONFIG_ITEM_ID) or provider_metadata.get(OperatorConstants.Columns.ID)
        if item_id:
            logger.info("Using item_id from metadata: %s", item_id)
            return str(item_id)

        # If resource_id looks like an item ID (not a URL), use it directly
        if resource_id and not resource_id.startswith("http") and not resource_id.startswith("/"):
            logger.info("Using resource_id as item_id: %s", resource_id)
            return str(resource_id)

        # Try to extract from path (format: /drives/{drive_id}/items/{item_id})
        match = re.search(r"/items/([^/]+)", resource_path)
        if match:
            item_id = match.group(1)
            logger.info("Extracted item_id from path: %s", item_id)
            return item_id

        # FALLBACK: Check if resource_id is a SharePoint URL and resolve it
        if resource_id and resource_id.startswith("http"):
            logger.info("Resolving item_id from URL: %s", resource_id)
            # Resolve URL to item ID using Graph API
            return await self._resolve_item_id_from_url(config=config, source_url=resource_id)

        raise ConfigurationError(
            f"Could not extract {_CONFIG_ITEM_ID} from resource_id '{resource_id}', path '{resource_path}', or metadata. "
            f"Provide {_CONFIG_ITEM_ID} in provider_metadata or use path format: /drives/{{drive_id}}/items/{{item_id}}"
        )
