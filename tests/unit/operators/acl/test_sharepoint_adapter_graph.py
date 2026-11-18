"""SharePoint ACL adapter tests against canned Microsoft Graph responses.

The adapter's own code (permission parsing, group pagination, inheritance walk, URL
resolution, error handling) runs unchanged. Only the HTTP client is replaced by a fake
that serves Graph JSON per endpoint, and the OAuth token is pre-seeded in the adapter's
token cache, so no network or MSAL call happens unless a test asks for it.
"""

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.acl.adapters.outbound.sharepoint_adapter import (
    SharePointACLAdapter,
    SharePointACLConfig,
)
from docpipe.core.operators.acl.domain.models import ACLRequest, RawPermission
from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError

_CREDENTIALS = {
    "client_id": "client-1",
    "client_secret": "<test-secret>",  # pragma: allowlist secret
    "tenant_id": "tenant-1",
}
_GRAPH = "https://graph.microsoft.com/v1.0"


class FakeGraph:
    """Serves canned Graph responses by endpoint and records every call."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def call_rest_json(self, *, method: Any, url: str, headers: dict[str, str]) -> dict[str, Any]:
        assert headers == {"Authorization": "Bearer cached-token"}
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def _adapter(graph: FakeGraph) -> SharePointACLAdapter:
    adapter = SharePointACLAdapter()
    adapter._token_cache["tenant-1:client-1"] = "cached-token"
    adapter._create_rest_client = lambda *, config: graph  # type: ignore[method-assign]
    return adapter


def _config(**overrides: Any) -> SharePointACLConfig:
    values = {**_CREDENTIALS, "drive_id": "drive-1", **overrides}
    return SharePointACLConfig(**values)


def _request(
    *,
    resource_id: str = "item-1",
    resource_path: str = "/docs/report.pdf",
    provider_metadata: dict | None = None,
    connection_params: dict | None = None,
) -> ACLRequest:
    return ACLRequest(
        resource_id=resource_id,
        resource_path=resource_path,
        resource_type="file",
        provider="sharepoint",
        provider_metadata={"drive_id": "drive-1"} if provider_metadata is None else provider_metadata,
        credentials=dict(_CREDENTIALS),
        connection_params=connection_params or {},
    )


def _user(email: str | None, user_id: str = "", name: str = "User") -> dict:
    user: dict[str, Any] = {"id": user_id, "displayName": name}
    if email:
        user["email"] = email
    return {"user": user}


_PERMISSIONS = {
    "value": [
        {"roles": ["read"], "grantedTo": _user("Alice@Contoso.com", "u-alice")},
        {
            "roles": ["write", "read"],
            "inheritedFrom": {"id": "folder-1"},
            "grantedToIdentities": [
                _user(None, "U-BOB-ID"),
                {"group": {"id": "group-1", "displayName": "Team"}},
                {"application": {"displayName": "Sync App"}, "id": "app-1"},
            ],
        },
        {"roles": ["owner"]},
    ]
}
_GROUP_PAGE_1 = {
    "value": [
        {"@odata.type": "#microsoft.graph.user", "userPrincipalName": "Carol@Contoso.com"},
        {"@odata.type": "#microsoft.graph.group", "userPrincipalName": "nested-group@contoso.com"},
        {"@odata.type": "#microsoft.graph.user"},
    ],
    "@odata.nextLink": f"{_GRAPH}/groups/group-1/transitiveMembers?$skiptoken=page2",
}
_GROUP_PAGE_2 = {"value": [{"@odata.type": "#microsoft.graph.user", "userPrincipalName": "dave@contoso.com"}]}


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph(
        {
            "/drives/drive-1/items/item-1/permissions": _PERMISSIONS,
            "/groups/group-1/transitiveMembers": _GROUP_PAGE_1,
            "/groups/group-1/transitiveMembers?$skiptoken=page2": _GROUP_PAGE_2,
            "/drives/drive-1/items/item-1": {"parentReference": {"id": "folder-1"}},
            "/drives/drive-1/items/folder-1": {"parentReference": {"id": "root-1"}},
            "/drives/drive-1/items/root-1": {"parentReference": {"driveId": "drive-1"}},
        }
    )


class TestExtractAclAgainstGraph:
    """extract_acl end to end over the Graph responses."""

    async def test_resolves_users_groups_and_inheritance(self, graph: FakeGraph) -> None:
        request = _request(
            resource_id="https://ignored", provider_metadata={"drive_id": "drive-1", "item_id": "item-1"}
        )
        response = await _adapter(graph).extract_acl(request=request)

        assert response.extraction_success is True
        assert response.allowed_users == {"alice@contoso.com", "u-bob-id", "carol@contoso.com", "dave@contoso.com"}
        assert response.denied_users is None
        assert response.inheritance_chain == ["item-1", "folder-1", "root-1"]
        assert response.has_unique_permissions is True
        assert response.resolution_metadata == {
            "raw_permission_count": 4,
            "inheritance_chain": 3,
            "groups_expanded": 1,
            "identities_normalized": 2,
        }

    async def test_without_expansion_and_normalization(self, graph: FakeGraph) -> None:
        request = _request(
            connection_params={"resolve_inheritance": False, "expand_groups": False, "normalize_identities": False}
        )

        response = await _adapter(graph).extract_acl(request=request)

        assert response.allowed_users == {"Alice@Contoso.com", "U-BOB-ID"}
        assert response.inheritance_chain == []
        assert response.resolution_metadata["groups_expanded"] == 0
        assert not any("transitiveMembers" in call for call in graph.calls)

    async def test_user_without_email_or_id_is_skipped(self) -> None:
        graph = FakeGraph({"/drives/drive-1/items/item-1/permissions": {"value": [{"grantedTo": _user(None, "")}]}})
        request = _request(connection_params={"resolve_inheritance": False, "normalize_identities": False})

        response = await _adapter(graph).extract_acl(request=request)

        assert response.allowed_users == set()
        assert response.has_unique_permissions is True

    async def test_permission_fetch_failure_yields_no_users(self) -> None:
        graph = FakeGraph({"/drives/drive-1/items/item-1/permissions": RuntimeError("503 Service Unavailable")})
        request = _request(connection_params={"resolve_inheritance": False})

        response = await _adapter(graph).extract_acl(request=request)

        assert response.allowed_users == set()
        assert response.has_unique_permissions is False

    async def test_denied_principal_is_removed_from_allowed_users(self, graph: FakeGraph) -> None:
        adapter = _adapter(graph)
        permissions = [
            RawPermission(principal_id="eve@contoso.com", principal_type="user", permission_type="allow"),
            RawPermission(principal_id="eve@contoso.com", principal_type="user", permission_type="deny"),
            RawPermission(principal_id="frank@contoso.com", principal_type="user", permission_type="allow"),
        ]

        async def _fetch(*, config: SharePointACLConfig, item_id: str) -> list[RawPermission]:
            return permissions

        adapter._fetch_permissions = _fetch  # type: ignore[method-assign]
        response = await adapter.extract_acl(request=_request(connection_params={"resolve_inheritance": False}))

        assert response.allowed_users == {"frank@contoso.com"}
        assert response.denied_users == {"eve@contoso.com"}


class TestExtractAclErrors:
    """Error mapping in extract_acl."""

    async def test_configuration_error_passes_through(self) -> None:
        request = _request()
        request.credentials = {}

        with pytest.raises(ConfigurationError, match="requires client_id, client_secret, and tenant_id"):
            await SharePointACLAdapter().extract_acl(request=request)

    async def test_missing_dependency_becomes_configuration_error(self, graph: FakeGraph) -> None:
        adapter = _adapter(graph)

        async def _fetch(*, config: SharePointACLConfig, item_id: str) -> list[RawPermission]:
            raise ImportError("No module named 'msal'")

        adapter._fetch_permissions = _fetch  # type: ignore[method-assign]

        with pytest.raises(ConfigurationError, match="requires missing dependency"):
            await adapter.extract_acl(request=_request())

    async def test_unexpected_error_becomes_external_service_error(self, graph: FakeGraph) -> None:
        adapter = _adapter(graph)

        async def _fetch(*, config: SharePointACLConfig, item_id: str) -> list[RawPermission]:
            raise KeyError("value")

        adapter._fetch_permissions = _fetch  # type: ignore[method-assign]

        with pytest.raises(ExternalServiceError, match=r"SharePoint ACL extraction failed for /docs/report.pdf"):
            await adapter.extract_acl(request=_request())


class TestExtractAclsBatch:
    """Concurrent batch extraction."""

    async def test_empty_batch(self) -> None:
        assert await SharePointACLAdapter().extract_acls_batch(requests=[]) == []

    async def test_keeps_request_order(self) -> None:
        graph = FakeGraph(
            {
                "/drives/drive-1/items/a/permissions": {"value": [{"grantedTo": _user("a@contoso.com")}]},
                "/drives/drive-1/items/b/permissions": {"value": [{"grantedTo": _user("b@contoso.com")}]},
            }
        )
        params = {"resolve_inheritance": False, "max_concurrent_requests": 1}

        responses = await _adapter(graph).extract_acls_batch(
            requests=[
                _request(resource_id="b", connection_params=params),
                _request(resource_id="a", connection_params=params),
            ]
        )

        assert [r.allowed_users for r in responses] == [{"b@contoso.com"}, {"a@contoso.com"}]


class TestGraphHelpers:
    """Inheritance, group expansion and identity normalisation edge cases."""

    async def test_inheritance_walk_stops_at_error_and_keeps_partial_chain(self) -> None:
        graph = FakeGraph(
            {
                "/drives/drive-1/items/item-1": {"parentReference": {"id": "folder-1"}},
                "/drives/drive-1/items/folder-1": RuntimeError("404 Not Found"),
            }
        )

        chain = await _adapter(graph).resolve_inheritance(resource_id="item-1", resource_type="file", config=_config())

        assert chain == ["item-1", "folder-1"]

    async def test_inheritance_walk_is_capped_at_ten_levels(self) -> None:
        responses = {f"/drives/drive-1/items/n{i}": {"parentReference": {"id": f"n{i + 1}"}} for i in range(20)}
        graph = FakeGraph(responses)

        chain = await _adapter(graph).resolve_inheritance(resource_id="n0", resource_type="file", config=_config())

        assert chain == [f"n{i}" for i in range(11)]
        assert len(graph.calls) == 10

    async def test_failed_group_expansion_is_not_cached(self) -> None:
        graph = FakeGraph({"/groups/group-1/transitiveMembers": RuntimeError("429 Too Many Requests")})
        adapter = _adapter(graph)

        assert await adapter.expand_group(group_id="group-1", config=_config()) == set()

        graph.responses["/groups/group-1/transitiveMembers"] = _GROUP_PAGE_2
        assert await adapter.expand_group(group_id="group-1", config=_config()) == {"dave@contoso.com"}

    @pytest.mark.parametrize(
        ("principal_id", "expected"),
        [
            ("i:0#.w|plainuser", "plainuser"),
            ("i:0#.w|CONTOSO\\Grace", "grace"),
            ("Heidi@Contoso.com", "heidi@contoso.com"),
            ("Opaque-Id", "opaque-id"),
        ],
    )
    def test_normalize_identity_formats(self, principal_id: str, expected: str) -> None:
        adapter = SharePointACLAdapter()

        assert (
            adapter.normalize_identity(principal_id=principal_id, principal_type="user", config=_config()) == expected
        )


class TestResolveItemIdFromUrl:
    """URL to DriveItem resolution."""

    async def test_uses_drive_relative_path_when_drive_is_known(self) -> None:
        endpoint = "/drives/drive-1/root:/Folder%20A/report%20final.pdf:"
        graph = FakeGraph({endpoint: {"id": "resolved-1"}})
        url = "https://contoso.sharepoint.com/sites/acl/Shared%20Documents/Folder%20A/report%20final.pdf"

        item_id = await _adapter(graph)._resolve_item_id_from_url(config=_config(), source_url=url)

        assert item_id == "resolved-1"
        assert graph.calls == [endpoint]

    async def test_uses_site_path_when_drive_is_unknown(self) -> None:
        endpoint = "/sites/contoso.sharepoint.com:/teams/eng:/drive/root:/spec.docx:"
        graph = FakeGraph({endpoint: {"id": "resolved-2"}})
        url = "https://contoso.sharepoint.com/teams/eng/Documents/spec.docx"

        item_id = await _adapter(graph)._resolve_item_id_from_url(config=_config(drive_id="url-based"), source_url=url)

        assert item_id == "resolved-2"

    @pytest.mark.parametrize(
        "url",
        ["https://contoso.sharepoint.com/sites/acl", "https://contoso.sharepoint.com/drive/x/y/z.txt"],
    )
    async def test_rejects_unsupported_url(self, url: str) -> None:
        with pytest.raises(ConfigurationError, match="Unsupported SharePoint URL format"):
            await _adapter(FakeGraph({}))._resolve_item_id_from_url(config=_config(), source_url=url)

    async def test_missing_item_id_in_response(self) -> None:
        graph = FakeGraph({"/drives/drive-1/root:/a.txt:": {"name": "a.txt"}})

        with pytest.raises(ExternalServiceError, match="No item ID returned"):
            await _adapter(graph)._resolve_item_id_from_url(
                config=_config(), source_url="https://contoso.sharepoint.com/sites/acl/Docs/a.txt"
            )

    async def test_graph_error_is_wrapped(self) -> None:
        graph = FakeGraph({"/drives/drive-1/root:/a.txt:": RuntimeError("401 Unauthorized")})

        with pytest.raises(ExternalServiceError, match=r"Failed to resolve item ID from SharePoint URL.*401"):
            await _adapter(graph)._resolve_item_id_from_url(
                config=_config(), source_url="https://contoso.sharepoint.com/sites/acl/Docs/a.txt"
            )


class TestExtractItemId:
    """Priority order for finding the DriveItem ID."""

    async def test_resource_id_that_is_not_a_url(self) -> None:
        item_id = await SharePointACLAdapter()._extract_item_id(
            config=_config(), resource_id="plain-item", resource_path="", provider_metadata={}
        )

        assert item_id == "plain-item"

    async def test_item_id_from_drive_items_path(self) -> None:
        item_id = await SharePointACLAdapter()._extract_item_id(
            config=_config(),
            resource_id="/x",
            resource_path="/drives/drive-1/items/from-path/children",
            provider_metadata={},
        )

        assert item_id == "from-path"

    async def test_url_is_resolved_through_graph(self) -> None:
        graph = FakeGraph({"/drives/drive-1/root:/a.txt:": {"id": "from-url"}})

        item_id = await _adapter(graph)._extract_item_id(
            config=_config(),
            resource_id="https://contoso.sharepoint.com/sites/acl/Docs/a.txt",
            resource_path="",
            provider_metadata={},
        )

        assert item_id == "from-url"

    async def test_nothing_usable_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="Could not extract item_id"):
            await SharePointACLAdapter()._extract_item_id(
                config=_config(), resource_id="", resource_path="no-items-here", provider_metadata={}
            )


class TestBuildConfig:
    """Drive ID fallbacks."""

    @pytest.mark.parametrize(
        ("provider_metadata", "expected"),
        [({"document_library_id": "library-drive"}, "library-drive"), ({}, "url-based")],
    )
    def test_drive_id_fallbacks(self, provider_metadata: dict, expected: str) -> None:
        config = SharePointACLAdapter().build_config_from_operator_params(
            connection_params={}, credentials=dict(_CREDENTIALS), provider_metadata=provider_metadata
        )

        assert config.drive_id == expected


class TestGetToken:
    """Token acquisition failures from MSAL."""

    async def test_msal_not_installed(self) -> None:
        with patch.dict(sys.modules, {"msal": None}):
            with pytest.raises(ConfigurationError, match="msal package not found"):
                await SharePointACLAdapter()._get_token(config=_config())

    @pytest.mark.parametrize(
        ("result", "message"),
        [
            ("not-a-dict", "Unexpected Microsoft Graph API response type: str"),
            ({"error": "invalid_client"}, "invalid_client - no description"),
            ({}, "unknown - no description"),
        ],
    )
    async def test_unusable_token_response(self, result: Any, message: str) -> None:
        app = MagicMock()
        app.acquire_token_for_client.return_value = result

        with patch("msal.ConfidentialClientApplication", return_value=app):
            with pytest.raises(ExternalServiceError, match=message):
                await SharePointACLAdapter()._get_token(config=_config())

    async def test_msal_exception_is_wrapped(self) -> None:
        with patch("msal.ConfidentialClientApplication", side_effect=ValueError("bad authority")):
            with pytest.raises(ExternalServiceError, match="Microsoft Graph authentication failed: bad authority"):
                await SharePointACLAdapter()._get_token(config=_config())
