# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Branch tests for the Box source adapter.

The Box SDK client is replaced by an in-process fake folder tree, so no test contacts Box.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from docpipe.core.operators.ingest.adapters.outbound.sources.box.adapter import BoxSourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.box.config import BoxSourceConfig


class FakeBoxClient:
    """Fake BoxClient serving a folder tree.

    ``tree`` maps a folder id to its child entries as ``(type, id)`` tuples; ``files`` maps a
    file id to its file info.
    """

    def __init__(self, *, tree: dict[str, list[tuple[str, str]]], files: dict[str, SimpleNamespace]):
        self.tree = tree
        self.file_infos = files
        self.visited_folders: list[str] = []
        self.folders = SimpleNamespace(get_folder_by_id=self._get_folder, get_folder_items=self._get_items)
        self.files = SimpleNamespace(get_file_by_id=self.file_infos.__getitem__)

    def _get_folder(self, folder_id: str) -> SimpleNamespace:
        """Return the folder object and record the visit."""
        self.visited_folders.append(folder_id)
        return SimpleNamespace(id=folder_id)

    def _get_items(self, folder_id: str) -> SimpleNamespace:
        """Return the folder's children."""
        return SimpleNamespace(
            entries=[SimpleNamespace(type=item_type, id=item_id) for item_type, item_id in self.tree[folder_id]]
        )


def _file_info(file_id: str, name: str) -> SimpleNamespace:
    """Build a Box file info object."""
    return SimpleNamespace(id=file_id, name=name, size=10, path_collection=None)


def _config(**overrides) -> BoxSourceConfig:
    """Build a Box config rooted at folder 100."""
    params = {"credentials_json": {"boxAppSettings": {}}, "folder_id": "100"}
    params.update(overrides)
    return BoxSourceConfig(**params)


class TestIterBoxFiles:
    """_iter_box_files traversal."""

    def test_defaults_to_configured_folder_and_recurses(self):
        """Without an explicit folder the configured one is used and sub-folders are walked."""
        client = FakeBoxClient(
            tree={"100": [("file", "f1"), ("folder", "200")], "200": [("file", "f2")]},
            files={"f1": _file_info("f1", "a.pdf"), "f2": _file_info("f2", "b.pdf")},
        )

        files = list(BoxSourceAdapter()._iter_box_files(client=client, config=_config(recursive=True)))

        assert [info.id for info in files] == ["f1", "f2"]
        assert client.visited_folders == ["100", "200"]


class TestFetchDocuments:
    """fetch_documents error wrapping."""

    def test_missing_sdk_dependency_is_reraised_as_import_error(self):
        """An ImportError from the SDK is surfaced with an install hint."""
        adapter = BoxSourceAdapter()

        async def consume():
            return [doc async for doc in adapter.fetch_documents(_config())]

        with (
            patch.object(adapter, "_get_box_client", side_effect=ImportError("box_sdk_gen")),
            pytest.raises(ImportError, match="docling-pipelines\\[box\\]"),
        ):
            asyncio.run(consume())


class TestBuildConfig:
    """build_config_from_operator_params optional keys."""

    def test_file_id_is_forwarded(self):
        """A file_id in provider_config selects single-file mode."""
        config = BoxSourceAdapter().build_config_from_operator_params(
            provider_config={"credentials_json": {"boxAppSettings": {}}, "file_id": "f-9"}
        )

        assert config.file_id == "f-9"
        assert config.folder_id == "0"
