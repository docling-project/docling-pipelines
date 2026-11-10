# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Characterization tests for credential persistence in document metadata on current main.

These tests document and pin existing behavior:
SharePoint and OneDrive adapters write client_id, client_secret, and tenant_id into
document metadata, which is subsequently serialized to output tables/parquet/sidecars.
"""

from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter import OneDriveSourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.config import OneDriveSourceConfig
from docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter import SharePointSourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.config import SharePointSourceConfig


class TestCredentialMetadataCharacterization:
    """Characterization tests for SharePoint/OneDrive metadata credential persistence."""

    def test_sharepoint_document_metadata_contains_credentials(self) -> None:
        """On current main, SharePointSourceAdapter includes client_secret in document metadata."""
        config = SharePointSourceConfig(
            document_library_id="lib-001",
            client_id="sp-client-id-123",
            client_secret="sp-secret-canary-456",  # pragma: allowlist secret
            tenant_id="sp-tenant-id-789",
        )

        item = {
            "id": "item-001",
            "name": "sample.pdf",
            "size": 1024,
            "webUrl": "https://sharepoint.example.com/sample.pdf",
            "lastModifiedDateTime": "2026-01-01T12:00:00Z",
            "createdDateTime": "2026-01-01T10:00:00Z",
            "file": {"mimeType": "application/pdf"},
        }

        adapter = SharePointSourceAdapter()
        doc = adapter._build_sharepoint_document(
            item=item,
            document_library_id="lib-001",
            config=config,
            is_single_file=False,
        )

        # Document metadata on current main exposes credentials
        assert doc.metadata.get("client_id") == "sp-client-id-123"
        assert doc.metadata.get("client_secret") == "sp-secret-canary-456"
        assert doc.metadata.get("tenant_id") == "sp-tenant-id-789"

    def test_onedrive_document_metadata_contains_credentials(self) -> None:
        """On current main, OneDriveSourceAdapter includes client_secret in document metadata."""
        config = OneDriveSourceConfig(
            drive_id="drive-001",
            client_id="od-client-id-123",
            client_secret="od-secret-canary-456",  # pragma: allowlist secret
            tenant_id="od-tenant-id-789",
        )

        item = {
            "id": "item-002",
            "name": "sample.docx",
            "size": 2048,
            "webUrl": "https://onedrive.example.com/sample.docx",
            "lastModifiedDateTime": "2026-01-01T12:00:00Z",
            "createdDateTime": "2026-01-01T10:00:00Z",
            "file": {"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        }

        adapter = OneDriveSourceAdapter()
        doc = adapter._build_onedrive_document(
            item=item,
            drive_id="drive-001",
            config=config,
            is_single_file=False,
        )

        # Document metadata on current main exposes credentials
        assert doc.metadata.get("client_id") == "od-client-id-123"
        assert doc.metadata.get("client_secret") == "od-secret-canary-456"
        assert doc.metadata.get("tenant_id") == "od-tenant-id-789"
