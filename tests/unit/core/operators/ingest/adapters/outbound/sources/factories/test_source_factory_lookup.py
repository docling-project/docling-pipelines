# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for SourceAdapterFactory.get_adapter_class."""

from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import SourceAdapterFactory
from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.adapter import GoogleDriveSourceAdapter


class TestGetAdapterClass:
    """Class lookup without instantiation."""

    def test_returns_registered_class(self):
        """A registered source name returns its adapter class."""
        assert SourceAdapterFactory.get_adapter_class("google_drive") is GoogleDriveSourceAdapter

    def test_resolves_ibm_cos_alias_to_s3_adapter(self):
        """The 'ibm_cos' alias resolves to the class registered as 's3'."""
        s3_class = SourceAdapterFactory.get_adapter_class("s3")

        assert s3_class is not None
        assert SourceAdapterFactory.get_adapter_class("ibm_cos") is s3_class

    def test_unknown_name_returns_none(self):
        """An unknown name returns None instead of raising."""
        assert SourceAdapterFactory.get_adapter_class("no-such-source") is None
