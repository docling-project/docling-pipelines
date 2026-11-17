# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pytest fixtures for ACL operator tests."""

from unittest.mock import AsyncMock, Mock

import pyarrow as pa
import pytest

from docpipe.core.operators.acl.domain.models import ACLRequest, ACLResponse, RawPermission


@pytest.fixture
def sample_acl_config():
    """Basic configuration for ACL operator (credentials come from the operator's own config)."""
    return {
        "credentials": {
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",  # pragma: allowlist secret
            "tenant_id": "test-tenant-id",
        },
        "provider_config": {"resolve_inheritance": True, "expand_groups": True, "normalize_identities": True},
        "fail_on_error": True,
    }


@pytest.fixture
def sample_document_metadata():
    """Sample document metadata (from IngestSourceOperator); carries no credentials."""
    import json

    return json.dumps(
        {
            "document_library_id": "test-drive-id",
            "web_url": "https://contoso.sharepoint.com/sites/mysite/Shared Documents/doc1.pdf",
            "provider": "sharepoint",
        }
    )


@pytest.fixture
def sample_acl_table(sample_document_metadata):
    """PyArrow table with document data for ACL extraction."""
    data = {
        "id": ["doc1", "doc2", "doc3"],
        "name": ["Document 1.pdf", "Document 2.docx", "Document 3.xlsx"],
        "source_id": [
            "https://contoso.sharepoint.com/sites/mysite/Shared Documents/doc1.pdf",
            "https://contoso.sharepoint.com/sites/mysite/Shared Documents/doc2.docx",
            "https://contoso.sharepoint.com/sites/mysite/Shared Documents/doc3.xlsx",
        ],
        "content": ["Content 1", "Content 2", "Content 3"],
        "path": [
            "https://contoso.sharepoint.com/sites/mysite/Shared Documents/doc1.pdf",
            "https://contoso.sharepoint.com/sites/mysite/Shared Documents/doc2.docx",
            "https://contoso.sharepoint.com/sites/mysite/Shared Documents/doc3.xlsx",
        ],
        "metadata": [sample_document_metadata, sample_document_metadata, sample_document_metadata],
    }
    return pa.table(data)


@pytest.fixture
def sample_acl_table_single_doc(sample_document_metadata):
    """PyArrow table with a single document."""
    data = {
        "id": ["doc1"],
        "name": ["Document 1.pdf"],
        "source_id": ["https://contoso.sharepoint.com/sites/mysite/Shared Documents/doc1.pdf"],
        "content": ["Content 1"],
        "path": ["https://contoso.sharepoint.com/sites/mysite/Shared Documents/doc1.pdf"],
        "metadata": [sample_document_metadata],
    }
    return pa.table(data)


@pytest.fixture
def sample_acl_table_missing_source_id(sample_document_metadata):
    """PyArrow table with missing source_id."""
    data = {
        "id": ["doc1", "doc2"],
        "path": ["Document 1.pdf", "Document 2.docx"],
        "source_id": ["https://contoso.sharepoint.com/sites/mysite/Shared Documents/doc1.pdf", None],
        "content": ["Content 1", "Content 2"],
        "metadata": [sample_document_metadata, sample_document_metadata],
    }
    return pa.table(data)


@pytest.fixture
def sample_acl_table_empty():
    """Empty PyArrow table."""
    data: dict[str, list] = {"id": [], "name": [], "source_id": [], "content": [], "metadata": []}
    return pa.table(data)


@pytest.fixture
def mock_acl_request():
    """Mock ACL request."""
    return ACLRequest(
        resource_id="item-id-1",
        resource_path="/path/to/doc1.pdf",
        resource_type="file",
        provider="sharepoint",
        provider_metadata={"drive_id": "test-drive-id", "item_id": "item-id-1"},
        credentials={
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",  # pragma: allowlist secret
            "tenant_id": "test-tenant-id",
        },
        connection_params={
            "timeout": 30,
            "resolve_inheritance": True,
            "expand_groups": True,
            "normalize_identities": True,
        },
        resolve_inheritance=True,
        expand_groups=True,
        normalize_identities=True,
    )


@pytest.fixture
def mock_acl_response_success():
    """Mock successful ACL response."""
    return ACLResponse(
        resource_id="item-id-1",
        resource_path="/path/to/doc1.pdf",
        allowed_users={"user1@example.com", "user2@example.com", "user3@example.com"},
        denied_users=None,
        inheritance_chain=["item-id-1", "folder-id-1", "library-id-1"],
        has_unique_permissions=True,
        resolution_metadata={
            "raw_permission_count": 3,
            "inheritance_chain": 3,
            "groups_expanded": 1,
            "identities_normalized": 3,
        },
        extraction_success=True,
        extraction_error=None,
        extraction_warnings=[],
    )


@pytest.fixture
def mock_acl_response_failure():
    """Mock failed ACL response."""
    return ACLResponse(
        resource_id="item-id-2",
        resource_path="/path/to/doc2.docx",
        allowed_users=set(),
        denied_users=None,
        inheritance_chain=[],
        has_unique_permissions=False,
        resolution_metadata={},
        extraction_success=False,
        extraction_error="Authentication failed",
        extraction_warnings=[],
    )


@pytest.fixture
def mock_acl_response_with_warnings():
    """Mock ACL response with warnings."""
    return ACLResponse(
        resource_id="item-id-3",
        resource_path="/path/to/doc3.xlsx",
        allowed_users={"user1@example.com"},
        denied_users=None,
        inheritance_chain=["item-id-3"],
        has_unique_permissions=True,
        resolution_metadata={
            "raw_permission_count": 1,
            "inheritance_chain": 1,
            "groups_expanded": 0,
            "identities_normalized": 1,
        },
        extraction_success=True,
        extraction_error=None,
        extraction_warnings=["Group expansion failed for group-id-1"],
    )


@pytest.fixture
def mock_raw_permissions():
    """Mock raw permissions from SharePoint."""
    return [
        RawPermission(
            principal_id="user1@example.com",
            principal_type="user",
            principal_name="User One",
            role="read",
            permission_type="allow",
            is_inherited=False,
            inherited_from=None,
            metadata={},
        ),
        RawPermission(
            principal_id="user2@example.com",
            principal_type="user",
            principal_name="User Two",
            role="write",
            permission_type="allow",
            is_inherited=False,
            inherited_from=None,
            metadata={},
        ),
        RawPermission(
            principal_id="group-id-1",
            principal_type="group",
            principal_name="Test Group",
            role="read",
            permission_type="allow",
            is_inherited=True,
            inherited_from="folder-id-1",
            metadata={},
        ),
    ]


@pytest.fixture
def mock_sharepoint_graph_response():
    """Mock Microsoft Graph API response for permissions."""
    return {
        "value": [
            {
                "id": "perm-1",
                "roles": ["read"],
                "grantedTo": {"user": {"id": "user-id-1", "email": "user1@example.com", "displayName": "User One"}},
            },
            {
                "id": "perm-2",
                "roles": ["write"],
                "grantedTo": {"user": {"id": "user-id-2", "email": "user2@example.com", "displayName": "User Two"}},
            },
            {
                "id": "perm-3",
                "roles": ["read"],
                "grantedTo": {
                    "group": {"id": "group-id-1", "email": "testgroup@example.com", "displayName": "Test Group"}
                },
                "inheritedFrom": {"id": "folder-id-1"},
            },
        ]
    }


@pytest.fixture
def mock_sharepoint_group_members():
    """Mock Microsoft Graph API response for group members."""
    return {
        "value": [
            {
                "@odata.type": "#microsoft.graph.user",
                "id": "user-id-3",
                "userPrincipalName": "user3@example.com",
                "displayName": "User Three",
            },
            {
                "@odata.type": "#microsoft.graph.user",
                "id": "user-id-4",
                "userPrincipalName": "user4@example.com",
                "displayName": "User Four",
            },
        ]
    }


@pytest.fixture
def mock_sharepoint_token_response():
    """Mock MSAL token response."""
    return {"access_token": "mock-access-token-12345", "token_type": "Bearer", "expires_in": 3600}


@pytest.fixture
def mock_acl_adapter():
    """Mock ACL adapter."""
    adapter = Mock()
    adapter.extract_acl = AsyncMock()
    adapter.extract_acls_batch = AsyncMock()
    adapter.resolve_inheritance = AsyncMock(return_value=["item-id-1", "folder-id-1"])
    adapter.expand_group = AsyncMock(return_value={"user3@example.com", "user4@example.com"})
    adapter.normalize_identity = Mock(side_effect=lambda principal_id, principal_type, config: principal_id.lower())
    adapter.test_connection = AsyncMock(return_value=True)
    return adapter


@pytest.fixture
def sharepoint_config_dict():
    """SharePoint configuration dictionary."""
    return {
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",  # pragma: allowlist secret
        "tenant_id": "test-tenant-id",
        "drive_id": "test-drive-id",
        "resolve_inheritance": True,
        "expand_groups": True,
        "normalize_identities": True,
        "max_concurrent_requests": 5,
        "request_timeout": 60,
    }
