# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Branch tests for ingest_source: MicrosoftGraphLoader listing and IngestSourceOperator helpers."""

from typing import cast
from unittest.mock import patch

import pytest
from langchain_core.documents import Document

from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator, MicrosoftGraphLoader
from docpipe.integrations.rest_client import RestClient


class FakeGraphRestClient:
    """Fake Graph RestClient returning folder listings by URL."""

    def __init__(self, responses: dict[str, dict]):
        self.responses = responses
        self.urls: list[str] = []

    def call_rest_json(self, *, method, url, headers):
        """Return the canned listing for ``url``."""
        self.urls.append(url)
        return self.responses[url]


def _custom_operator(**overrides) -> IngestSourceOperator:
    """Build an operator for the non adapter-managed 'custom' provider."""
    config = {"provider": "custom", "provider_config": {"loader_class_path": "pkg.Loader"}}
    config.update(overrides)
    return IngestSourceOperator(config)


class TestMicrosoftGraphLoaderNonRecursive:
    """Listing a drive with recursion disabled."""

    def test_folders_are_not_descended_when_not_recursive(self):
        """With recursive=False, folder items are dropped and never listed."""
        loader = MicrosoftGraphLoader(
            drive_id="drive-1",
            client_id="client",
            client_secret="secret",  # pragma: allowlist secret
            tenant_id="tenant",
            recursive=False,
        )
        loader._token = "tok"  # type: ignore[assignment]  # skip MSAL with a cached token
        fake = FakeGraphRestClient(
            {
                "/drives/drive-1/root/children": {
                    "value": [{"id": "folder-1", "folder": {}}, {"id": "file-1", "name": "a.txt"}],
                }
            }
        )
        loader._rest_client = cast(RestClient, fake)

        files = loader._list_files()

        assert [item["id"] for item in files] == ["file-1"]
        assert fake.urls == ["/drives/drive-1/root/children"]


class TestValidateNonAdapterProvider:
    """validate() for providers that are not adapter-managed."""

    def test_custom_provider_skips_adapter_config_validation(self):
        """A custom provider is not validated through an adapter config."""
        operator = _custom_operator()
        errors: list = []

        with patch.object(operator, "_build_adapter_config") as build:
            operator.validate(errors=errors, warnings=[], available_features=[])

        build.assert_not_called()
        assert errors == []


class TestValidateExtensionsWithEmptyInclude:
    """_validate_extensions when the include filter is an empty list."""

    def test_empty_include_list_still_checks_exclude_filter(self):
        """An empty include list skips the include check but unsupported excludes are still rejected."""
        with pytest.raises(ValueError, match=r"Unsupported file extensions in exclude_filter: \.nope"):
            _custom_operator(include_filter=[], exclude_filter=".nope")

    def test_empty_include_list_with_supported_exclude_is_accepted(self):
        """An empty include list and a supported exclude filter pass validation."""
        operator = _custom_operator(include_filter=[], exclude_filter=".pdf")

        assert operator.included_extensions == []
        assert operator.excluded_extensions == [".pdf"]


class TestDocumentIteratorEagerLoader:
    """_get_document_iterator with a loader that only implements load()."""

    def test_loader_without_lazy_load_uses_load(self):
        """A loader without lazy_load is consumed through load()."""

        class EagerLoader:
            """Loader exposing only the eager load() API."""

            def load(self):
                """Return all documents at once."""
                return [Document(page_content="x", metadata={"source": "a.txt"})]

        operator = _custom_operator()

        with patch.object(operator, "_get_loader", return_value=EagerLoader()):
            docs = list(operator._get_document_iterator())

        assert [doc.metadata["source"] for doc in docs] == ["a.txt"]
