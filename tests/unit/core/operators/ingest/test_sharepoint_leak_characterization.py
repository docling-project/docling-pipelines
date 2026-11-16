# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""SharePoint and OneDrive adapters must not persist credentials (flipped by A.2).

Before A.2 the adapters wrote ``client_id``, ``client_secret`` and ``tenant_id`` into each
document's ``metadata``. That metadata reached the output table, parquet files and the
storage ``*.meta.json`` sidecar. These tests pin the fixed behavior for literal, environment
variable and ``vault://`` reference credentials.
"""

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

# box_sdk_gen is an optional dependency not installed in the test environment.
if "box_sdk_gen" not in sys.modules:
    sys.modules["box_sdk_gen"] = MagicMock()

from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter import OneDriveSourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.config import OneDriveSourceConfig
from docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter import SharePointSourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.config import SharePointSourceConfig
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.core.operators.storage.storage_output_operator import StorageOutputOperator

CREDENTIAL_KEYS = ("client_id", "client_secret", "tenant_id")

_ITEM = {
    "id": "item-001",
    "name": "sample.pdf",
    "size": 1024,
    "webUrl": "https://example.sharepoint.com/sample.pdf",
    "lastModifiedDateTime": "2026-01-01T12:00:00Z",
    "createdDateTime": "2026-01-01T10:00:00Z",
    "file": {"mimeType": "application/pdf"},
}

# One credential triple per style the config can carry: literal, environment reference, Vault reference.
_CREDENTIAL_STYLES = {
    "literal": {
        "client_id": "canary-literal-id-111",
        "client_secret": "canary-literal-secret-222",  # pragma: allowlist secret
        "tenant_id": "canary-literal-tenant-333",
    },
    "environment": {
        "client_id": "${CANARY_ENV_CLIENT_ID}",
        "client_secret": "${CANARY_ENV_CLIENT_SECRET}",  # pragma: allowlist secret
        "tenant_id": "${CANARY_ENV_TENANT_ID}",
    },
    "reference": {
        "client_id": "vault://hashicorp/canary/azure#client_id",
        "client_secret": "vault://hashicorp/canary/azure#client_secret",  # pragma: allowlist secret
        "tenant_id": "vault://hashicorp/canary/azure#tenant_id",
    },
}


def _sharepoint_document(*, credentials: dict[str, str]) -> Any:
    config = SharePointSourceConfig(document_library_id="lib-001", **credentials)
    return SharePointSourceAdapter()._build_sharepoint_document(
        item=_ITEM, document_library_id="lib-001", config=config, is_single_file=False
    )


def _onedrive_document(*, credentials: dict[str, str]) -> Any:
    config = OneDriveSourceConfig(drive_id="drive-001", **credentials)
    return OneDriveSourceAdapter()._build_onedrive_document(
        item=_ITEM, drive_id="drive-001", config=config, is_single_file=False
    )


_BUILDERS = {"sharepoint": _sharepoint_document, "onedrive": _onedrive_document}


def _ingest_row(*, document: Any, tmp_path: Path) -> dict[str, Any]:
    """Run a domain document through the ingest operator's real row conversion."""
    operator = IngestSourceOperator({"provider": "filesystem", "provider_config": {"paths": [str(tmp_path)]}})
    langchain_doc = operator._domain_doc_to_langchain(document)
    row = operator.process_document(langchain_doc, 0, operator.create_base_metadata(total_docs_count=1))
    assert row is not None
    return row


def _write_sidecar(*, row: dict[str, Any], destination: Path) -> Path:
    config = {
        "name": "storage_output",
        "id": "node_1",
        "mode": "comprehensive_export",
        "ingest_source": {"provider": "filesystem", "connection_params": {"root_path": "/src"}, "credentials": {}},
        "destination_config": {
            "provider": "filesystem",
            "provider_config": {"root_path": str(destination), "create_dirs": True, "overwrite_existing": True},
            "credentials": {},
        },
        "output_format": {"content_format": "md", "include_metadata_sidecar": True},
        "output_structure": {"path_template": "{doc_id}/{name}.{ext}"},
    }
    table = pa.Table.from_pylist([{**row, "content": "text"}])
    with patch("docpipe.core.operators.storage.storage_output_operator.get_binary_content", return_value=b"%PDF"):
        StorageOutputOperator(config).transform(table)
    sidecars = list(destination.rglob("*.meta.json"))
    assert len(sidecars) == 1
    return sidecars[0]


@pytest.mark.parametrize("provider", sorted(_BUILDERS))
@pytest.mark.parametrize("style", sorted(_CREDENTIAL_STYLES))
class TestCredentialsAreNotPersisted:
    """No client_id, client_secret or tenant_id in metadata, table, parquet or sidecar."""

    def test_document_metadata_has_no_credentials(self, provider: str, style: str) -> None:
        credentials = _CREDENTIAL_STYLES[style]

        document = _BUILDERS[provider](credentials=credentials)

        for key in CREDENTIAL_KEYS:
            assert key not in document.metadata
        assert not set(credentials.values()) & {str(v) for v in document.metadata.values()}

    def test_table_parquet_and_sidecar_have_no_credentials(self, provider: str, style: str, tmp_path: Path) -> None:
        credentials = _CREDENTIAL_STYLES[style]
        document = _BUILDERS[provider](credentials=credentials)
        row = _ingest_row(document=document, tmp_path=tmp_path)

        table = pa.Table.from_pylist([row])
        parquet_path = tmp_path / "out.parquet"
        pq.write_table(table, parquet_path)
        sidecar_path = _write_sidecar(row=row, destination=tmp_path / "export")

        persisted = {
            "row metadata": row["metadata"],
            "table": json.dumps(table.to_pylist(), default=str),
            "parquet": json.dumps(pq.read_table(parquet_path).to_pylist(), default=str),
            "sidecar": sidecar_path.read_text(encoding="utf-8"),
        }
        for where, text in persisted.items():
            for key in CREDENTIAL_KEYS:
                assert f'"{key}"' not in text, f"{key} key found in {where}"
            for value in credentials.values():
                assert value not in text, f"credential value found in {where}"

    def test_provider_is_still_recorded_for_downstream_operators(self, provider: str, style: str) -> None:
        """The ACL operator still reads ``provider`` from metadata; only credentials were removed."""
        document = _BUILDERS[provider](credentials=_CREDENTIAL_STYLES[style])

        if provider == "sharepoint":
            assert document.metadata["provider"] == "sharepoint"
        assert document.metadata["item_id"] == "item-001"
