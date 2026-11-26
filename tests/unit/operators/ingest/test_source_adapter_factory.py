#!/usr/bin/env python3

# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

import pytest
from pydantic import BaseModel

from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import (
    SourceAdapterFactory,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.filesystem.adapter import (
    FilesystemSourceAdapter,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.adapter import (
    GoogleDriveSourceAdapter,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter import (
    OneDriveSourceAdapter,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter import (
    S3SourceAdapter,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter import (
    SharePointSourceAdapter,
)
from docpipe.core.operators.ingest.domain.models import Document
from docpipe.core.operators.ingest.ports.outbound.document_source import DocumentSourcePort


class DummyConfig(BaseModel):
    value: str = "x"


@pytest.fixture(autouse=True)
def _restore_source_adapter_registry():
    """Put every registered source back after a test that clears the registry, for the tests that run later."""
    saved = dict(SourceAdapterFactory._adapters)
    yield
    SourceAdapterFactory._adapters.clear()
    SourceAdapterFactory._adapters.update(saved)


class TestSourceAdapterFactory:
    def test_registered_names_include_default_adapters(self):
        names = SourceAdapterFactory.get_registered_names()
        assert "filesystem" in names
        assert "google_drive" in names
        assert "onedrive" in names
        assert "sharepoint" in names
        assert "s3" in names

    def test_create_unknown_adapter_raises(self):
        with pytest.raises(ValueError, match="Unknown source adapter"):
            SourceAdapterFactory.create("missing")

    def test_register_requires_source_name(self):
        class InvalidAdapter(DocumentSourcePort):
            async def fetch_documents(self, config: BaseModel):  # type: ignore[override]
                if False:
                    yield Document(id="1", name="n", content=b"x", source_url="s")

            async def test_connection(self, config: BaseModel) -> tuple[bool, str]:
                return True, "ok"

            def get_config_schema(self) -> type[BaseModel]:
                return DummyConfig

            def build_config_from_operator_params(
                self,
                connection_params: dict,
                credentials: dict,
                included_extensions: list[str] | None = None,
            ) -> BaseModel:
                return DummyConfig()

        SourceAdapterFactory.clear_registry()
        try:
            with pytest.raises(ValueError, match="must define SOURCE_NAME"):
                SourceAdapterFactory.register(InvalidAdapter)
        finally:
            SourceAdapterFactory.register(FilesystemSourceAdapter)
            SourceAdapterFactory.register(GoogleDriveSourceAdapter)
            SourceAdapterFactory.register(OneDriveSourceAdapter)
            SourceAdapterFactory.register(SharePointSourceAdapter)
            SourceAdapterFactory.register(S3SourceAdapter)

    def test_list_sources_returns_metadata(self):
        sources = SourceAdapterFactory.list_sources()
        names = {source["name"] for source in sources}
        assert "filesystem" in names
        assert "google_drive" in names
