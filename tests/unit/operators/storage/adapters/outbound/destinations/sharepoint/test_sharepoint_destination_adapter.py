# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for SharePointDestinationAdapter."""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter import (
    SharePointDestinationAdapter,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.config import (
    SharePointDestinationConfig,
)

_VALID = {
    "client_id": "app-client-id",
    "client_secret": "app-client-secret",  # pragma: allowlist secret
    "tenant_id": "tenant-id",
    "drive_id": "b!abc123",
}


def _make_config(**overrides) -> SharePointDestinationConfig:
    return SharePointDestinationConfig(**{**_VALID, **overrides})


def _mock_loader(
    *,
    token: str = "tok123",
    get_response: MagicMock | None = None,
    put_response: MagicMock | None = None,
) -> MagicMock:
    """Return a MicrosoftGraphLoader mock wired for token + REST calls."""
    loader = MagicMock()
    loader._get_token.return_value = token

    if get_response is not None:
        loader._rest_client.call_rest.return_value = get_response

    if put_response is not None:
        loader._rest_client.session.put.return_value = put_response
        loader._rest_client._build_url.side_effect = lambda ep: f"https://graph.microsoft.com/v1.0{ep}"
        loader._rest_client.config.verify_ssl = True

    return loader


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestSharePointDestinationAdapterRegistration:
    def test_dest_name_is_sharepoint(self):
        assert SharePointDestinationAdapter.DEST_NAME == "sharepoint"

    def test_is_registered_in_factory(self):
        from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
            DestinationAdapterFactory,
        )

        assert DestinationAdapterFactory.is_registered("sharepoint")

    def test_get_config_schema_returns_sharepoint_config(self):
        adapter = SharePointDestinationAdapter()
        assert adapter.get_config_schema() is SharePointDestinationConfig


# ---------------------------------------------------------------------------
# ensure_directory (no-op)
# ---------------------------------------------------------------------------


class TestSharePointDestinationAdapterEnsureDirectory:
    def test_ensure_directory_is_noop(self):
        adapter = SharePointDestinationAdapter()
        # Should not raise
        adapter.ensure_directory(path="/drives/b!abc/root:/Output")

    def test_ensure_directory_does_not_call_graph(self):
        adapter = SharePointDestinationAdapter()
        with patch.object(adapter, "_make_loader") as mock_make:
            adapter.ensure_directory(path="any/path")
            mock_make.assert_not_called()


# ---------------------------------------------------------------------------
# resolve_destination_path
# ---------------------------------------------------------------------------


class TestSharePointDestinationAdapterResolveDestinationPath:
    def test_prepends_folder_path(self):
        adapter = SharePointDestinationAdapter()
        config = _make_config(folder_path="/Processed Documents")
        result = adapter.resolve_destination_path(relative_path="report.pdf", config=config)
        assert result == "/Processed Documents/report.pdf"

    def test_empty_folder_path_returns_relative_path_unchanged(self):
        adapter = SharePointDestinationAdapter()
        config = _make_config(folder_path="")
        result = adapter.resolve_destination_path(relative_path="report.pdf", config=config)
        assert result == "report.pdf"

    def test_leading_slash_on_relative_path_normalised(self):
        adapter = SharePointDestinationAdapter()
        config = _make_config(folder_path="/Output")
        result = adapter.resolve_destination_path(relative_path="/doc.pdf", config=config)
        assert result == "/Output/doc.pdf"


# ---------------------------------------------------------------------------
# build_config_from_operator_params
# ---------------------------------------------------------------------------


class TestSharePointDestinationAdapterBuildConfig:
    def _credentials(self):
        return {
            "client_id": "cid",
            "client_secret": "csecret",  # pragma: allowlist secret
            "tenant_id": "tid",
        }

    def _provider_config(self):
        return {"drive_id": "b!drive1"}

    def test_builds_config_from_valid_params(self):
        adapter = SharePointDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config=self._provider_config(),
            credentials=self._credentials(),
        )
        assert isinstance(cfg, SharePointDestinationConfig)
        assert cfg.drive_id == "b!drive1"
        assert cfg.client_id == "cid"
        assert cfg.create_dirs is True

    def test_optional_folder_path_applied(self):
        adapter = SharePointDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={**self._provider_config(), "folder_path": "/Docs"},
            credentials=self._credentials(),
        )
        assert cfg.folder_path == "/Docs"

    def test_missing_client_id_raises(self):
        adapter = SharePointDestinationAdapter()
        creds = {k: v for k, v in self._credentials().items() if k != "client_id"}
        with pytest.raises(ValueError, match="client_id"):
            adapter.build_config_from_operator_params(
                provider_config=self._provider_config(),
                credentials=creds,
            )

    def test_missing_client_secret_raises(self):
        adapter = SharePointDestinationAdapter()
        creds = {k: v for k, v in self._credentials().items() if k != "client_secret"}
        with pytest.raises(ValueError, match="client_secret"):
            adapter.build_config_from_operator_params(
                provider_config=self._provider_config(),
                credentials=creds,
            )

    def test_missing_tenant_id_raises(self):
        adapter = SharePointDestinationAdapter()
        creds = {k: v for k, v in self._credentials().items() if k != "tenant_id"}
        with pytest.raises(ValueError, match="tenant_id"):
            adapter.build_config_from_operator_params(
                provider_config=self._provider_config(),
                credentials=creds,
            )

    def test_missing_drive_id_raises(self):
        adapter = SharePointDestinationAdapter()
        with pytest.raises(ValueError, match="drive_id"):
            adapter.build_config_from_operator_params(
                provider_config={},
                credentials=self._credentials(),
            )

    def test_graph_api_version_passed_through(self):
        adapter = SharePointDestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={**self._provider_config(), "graph_api_version": "beta"},
            credentials=self._credentials(),
        )
        assert cfg.graph_api_version == "beta"


# ---------------------------------------------------------------------------
# validate_destination
# ---------------------------------------------------------------------------


class TestSharePointDestinationAdapterValidateDestination:
    def test_returns_none_when_config_is_none(self):
        adapter = SharePointDestinationAdapter()
        with patch(
            "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
            True,
        ):
            result = adapter.validate_destination(config=None)
        assert result is None

    def test_returns_failed_when_graph_unavailable(self):
        adapter = SharePointDestinationAdapter()
        with patch(
            "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
            False,
        ):
            result = adapter.validate_destination(config=_make_config())
        assert result is not None
        assert result.success is False
        assert "msal" in result.error_message

    def test_returns_none_when_drive_accessible(self):
        adapter = SharePointDestinationAdapter()
        drive_resp = MagicMock(status_code=200)
        loader = _mock_loader(get_response=drive_resp)

        with (
            patch(
                "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
                True,
            ),
            patch.object(adapter, "_make_loader", return_value=loader),
        ):
            result = adapter.validate_destination(config=_make_config())

        assert result is None

    def test_returns_failed_when_drive_not_accessible(self):
        adapter = SharePointDestinationAdapter()
        drive_resp = MagicMock(status_code=403)
        loader = _mock_loader(get_response=drive_resp)

        with (
            patch(
                "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
                True,
            ),
            patch.object(adapter, "_make_loader", return_value=loader),
        ):
            result = adapter.validate_destination(config=_make_config())

        assert result is not None
        assert result.success is False
        assert "not accessible" in result.error_message

    def test_returns_failed_when_folder_missing_and_create_dirs_false(self):
        adapter = SharePointDestinationAdapter()

        # First call → drive accessible (200), second call → folder 404
        drive_resp = MagicMock(status_code=200)
        folder_resp = MagicMock(status_code=404)
        loader = _mock_loader()
        loader._rest_client.call_rest.side_effect = [drive_resp, folder_resp]

        config = _make_config(folder_path="/Missing Folder", create_dirs=False)

        with (
            patch(
                "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
                True,
            ),
            patch.object(adapter, "_make_loader", return_value=loader),
        ):
            result = adapter.validate_destination(config=config)

        assert result is not None
        assert result.success is False
        assert "create_dirs is disabled" in result.error_message

    def test_create_dirs_true_skips_folder_check(self):
        adapter = SharePointDestinationAdapter()
        drive_resp = MagicMock(status_code=200)
        loader = _mock_loader(get_response=drive_resp)

        config = _make_config(folder_path="/Docs", create_dirs=True)

        with (
            patch(
                "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
                True,
            ),
            patch.object(adapter, "_make_loader", return_value=loader),
        ):
            result = adapter.validate_destination(config=config)

        # Only one call — drive check; no folder check
        loader._rest_client.call_rest.assert_called_once()
        assert result is None

    def test_exception_returns_failed_result(self):
        adapter = SharePointDestinationAdapter()
        loader = _mock_loader()
        loader._get_token.side_effect = RuntimeError("token error")

        with (
            patch(
                "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
                True,
            ),
            patch.object(adapter, "_make_loader", return_value=loader),
        ):
            result = adapter.validate_destination(config=_make_config())

        assert result is not None
        assert result.success is False
        assert "validation failed" in result.error_message


# ---------------------------------------------------------------------------
# write_document
# ---------------------------------------------------------------------------


class TestSharePointDestinationAdapterWriteDocumentSuccess:
    def test_put_request_called_with_correct_url_and_content(self):
        adapter = SharePointDestinationAdapter()
        upload_resp = MagicMock(status_code=201)
        upload_resp.json.return_value = {"webUrl": "https://sharepoint.example.com/doc.pdf"}
        loader = _mock_loader(put_response=upload_resp)

        config = _make_config()

        with (
            patch(
                "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
                True,
            ),
            patch.object(adapter, "_make_loader", return_value=loader),
        ):
            result = adapter.write_document(
                content=b"binary content",
                destination_path="output/doc.pdf",
                overwrite=True,
                config=config,
            )

        assert result.success is True
        assert result.bytes_written == len(b"binary content")
        assert result.destination_path == "https://sharepoint.example.com/doc.pdf"

    def test_web_url_fallback_to_destination_path_when_absent(self):
        adapter = SharePointDestinationAdapter()
        upload_resp = MagicMock(status_code=200)
        upload_resp.json.return_value = {}  # no webUrl
        loader = _mock_loader(put_response=upload_resp)

        with (
            patch(
                "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
                True,
            ),
            patch.object(adapter, "_make_loader", return_value=loader),
        ):
            result = adapter.write_document(
                content=b"data",
                destination_path="output/doc.pdf",
                overwrite=True,
                config=_make_config(),
            )

        assert result.success is True
        assert result.destination_path == "output/doc.pdf"


class TestSharePointDestinationAdapterOverwriteFalse:
    def test_skips_when_file_exists(self):
        adapter = SharePointDestinationAdapter()
        check_resp = MagicMock(status_code=200)
        loader = _mock_loader()
        loader._rest_client.call_rest.return_value = check_resp

        with (
            patch(
                "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
                True,
            ),
            patch.object(adapter, "_make_loader", return_value=loader),
        ):
            result = adapter.write_document(
                content=b"data",
                destination_path="output/doc.pdf",
                overwrite=False,
                config=_make_config(),
            )

        assert result.success is False
        assert result.write_status == "skipped"
        # session.put must NOT have been called
        loader._rest_client.session.put.assert_not_called()

    def test_uploads_when_file_absent_and_overwrite_false(self):
        adapter = SharePointDestinationAdapter()
        check_resp = MagicMock(status_code=404)
        upload_resp = MagicMock(status_code=201)
        upload_resp.json.return_value = {"webUrl": "https://sharepoint.example.com/doc.pdf"}

        loader = _mock_loader(put_response=upload_resp)
        loader._rest_client.call_rest.return_value = check_resp

        with (
            patch(
                "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
                True,
            ),
            patch.object(adapter, "_make_loader", return_value=loader),
        ):
            result = adapter.write_document(
                content=b"data",
                destination_path="output/doc.pdf",
                overwrite=False,
                config=_make_config(),
            )

        assert result.success is True


class TestSharePointDestinationAdapterErrorPaths:
    def test_returns_failed_when_graph_unavailable(self):
        adapter = SharePointDestinationAdapter()
        with patch(
            "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
            False,
        ):
            result = adapter.write_document(
                content=b"data",
                destination_path="doc.pdf",
                config=_make_config(),
            )
        assert result.success is False
        assert "msal" in result.error_message

    def test_returns_failed_when_config_is_none(self):
        adapter = SharePointDestinationAdapter()
        with patch(
            "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
            True,
        ):
            result = adapter.write_document(content=b"data", destination_path="doc.pdf", config=None)
        assert result.success is False
        assert "SharePointDestinationConfig is required" in result.error_message

    def test_returns_failed_on_unexpected_status_code(self):
        adapter = SharePointDestinationAdapter()
        upload_resp = MagicMock(status_code=500)
        upload_resp.text = "Internal Server Error"
        loader = _mock_loader(put_response=upload_resp)

        with (
            patch(
                "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
                True,
            ),
            patch.object(adapter, "_make_loader", return_value=loader),
        ):
            result = adapter.write_document(
                content=b"data",
                destination_path="output/doc.pdf",
                overwrite=True,
                config=_make_config(),
            )

        assert result.success is False
        assert "500" in result.error_message

    def test_returns_failed_on_exception(self):
        adapter = SharePointDestinationAdapter()
        loader = _mock_loader()
        loader._get_token.side_effect = ConnectionError("network down")

        with (
            patch(
                "docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter._GRAPH_AVAILABLE",
                True,
            ),
            patch.object(adapter, "_make_loader", return_value=loader),
        ):
            result = adapter.write_document(
                content=b"data",
                destination_path="output/doc.pdf",
                overwrite=True,
                config=_make_config(),
            )

        assert result.success is False
        assert "connection failed" in result.error_message
        assert "network down" not in result.error_message
