# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for SharePointDestinationAdapter against a fake Graph REST client."""

import importlib.util
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
    DestinationAdapterFactory,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint import adapter as sp_module
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


class _FakeRestClient:
    """Fake Graph REST client answering GET calls from a status map and recording them."""

    def __init__(self, statuses: dict[str, int]) -> None:
        self._statuses = statuses
        self.calls: list[dict[str, Any]] = []

    def call_rest(self, **kwargs: Any) -> Any:
        """Return the configured status for the endpoint (404 when unknown)."""
        self.calls.append(kwargs)
        return SimpleNamespace(status_code=self._statuses.get(kwargs["url"], 404))


class _FakeLoader:
    """Stand-in for MicrosoftGraphLoader with a fixed token."""

    def __init__(self, rest_client: _FakeRestClient) -> None:
        self._rest_client = rest_client

    def _get_token(self) -> str:
        return "tok"


def _config(**overrides: Any) -> SharePointDestinationConfig:
    return SharePointDestinationConfig(**{**_VALID, **overrides})


class TestValidateExistingFolder:
    """With create_dirs disabled the target folder must exist."""

    def test_existing_folder_passes(self) -> None:
        """Drive and folder both answer 200, so validation succeeds after checking both."""
        rest = _FakeRestClient({"/drives/b!abc123": 200, "/drives/b!abc123/root:/Out/Sub": 200})
        adapter = SharePointDestinationAdapter()
        config = _config(folder_path="/Out/Sub/", create_dirs=False)

        with patch.object(adapter, "_make_loader", return_value=_FakeLoader(rest)):
            assert adapter.validate_destination(config=config) is None

        assert [c["url"] for c in rest.calls] == ["/drives/b!abc123", "/drives/b!abc123/root:/Out/Sub"]
        assert all(c["headers"] == {"Authorization": "Bearer tok"} for c in rest.calls)


class TestMakeLoader:
    """_make_loader builds a MicrosoftGraphLoader from the config."""

    def test_passes_credentials_and_drive(self) -> None:
        """The loader gets the app credentials and drive, with no folder and no recursion."""
        with patch.object(sp_module, "MicrosoftGraphLoader", return_value="loader") as loader_cls:
            assert SharePointDestinationAdapter()._make_loader(_config(folder_path="Out")) == "loader"

        loader_cls.assert_called_once_with(
            drive_id="b!abc123",
            client_id="app-client-id",
            client_secret="app-client-secret",  # pragma: allowlist secret
            tenant_id="tenant-id",
            folder_path=None,
            recursive=False,
        )


def _load_sharepoint_adapter_without_graph() -> ModuleType:
    """Load a fresh copy of the adapter module while the Graph loader cannot be imported."""
    spec = importlib.util.spec_from_file_location("_sharepoint_adapter_without_graph", sp_module.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with (
        patch.dict(sys.modules, {"docpipe.core.operators.ingest.ingest_source": None}),
        patch.dict(DestinationAdapterFactory._adapters),
    ):
        spec.loader.exec_module(module)
    return module


class TestMissingGraphDependencies:
    """Without the Graph dependencies the adapter loads and reports how to install them."""

    @pytest.fixture(scope="class")
    def module(self) -> ModuleType:
        """Return the adapter module loaded without the Graph dependencies."""
        return _load_sharepoint_adapter_without_graph()

    def test_graph_names_are_none(self, module: ModuleType) -> None:
        """The Graph symbols fall back to None."""
        assert module._GRAPH_AVAILABLE is False
        assert module.MicrosoftGraphLoader is None
        assert module.RestClient is None
        assert module.RestMethod is None

    def test_factory_registration_is_unchanged(self) -> None:
        """Loading the fallback copy does not replace the registered adapter."""
        _load_sharepoint_adapter_without_graph()
        assert DestinationAdapterFactory.create("sharepoint").__class__ is SharePointDestinationAdapter

    def test_validate_and_write_report_missing_dependencies(self, module: ModuleType) -> None:
        """Both entry points fail with the install hint."""
        adapter = module.SharePointDestinationAdapter()

        validation = adapter.validate_destination(config=_config())
        write = adapter.write_document(content=b"x", destination_path="Out/a.md", config=_config())

        assert validation.success is False
        assert "Microsoft Graph dependencies are not installed" in validation.error_message
        assert write.success is False
        assert write.doc_name == "Out/a.md"
        assert "Microsoft Graph dependencies are not installed" in write.error_message
