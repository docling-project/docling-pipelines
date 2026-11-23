# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the ingest domain models."""

import pytest

from docpipe.core.operators.ingest.domain.models import Document, DocumentACL, IngestionResult


class TestDocumentACL:
    """Defaults and explicit values of DocumentACL."""

    def test_missing_lists_default_to_empty(self):
        """None users/groups are replaced by fresh empty lists."""
        acl = DocumentACL()

        assert acl.allowed_users == []
        assert acl.allowed_groups == []
        assert acl.allowed_users is not DocumentACL().allowed_users

    def test_explicit_lists_are_kept(self):
        """Provided users and groups are not overwritten."""
        acl = DocumentACL(allowed_users=["alice"], allowed_groups=["staff"])

        assert acl.allowed_users == ["alice"]
        assert acl.allowed_groups == ["staff"]


class TestDocument:
    """Computed fields in Document.__post_init__."""

    def test_size_extension_and_acl_are_derived(self):
        """Size comes from the content, the extension from the name, and an empty ACL is attached."""
        doc = Document(id="1", name="Report.PDF", content=b"abcd", source_url="file:///r.pdf")

        assert doc.size == 4
        assert doc.extension == ".pdf"
        assert doc.acl == DocumentACL()

    def test_explicit_values_are_not_overwritten(self):
        """Explicit size, extension and ACL win over derived values."""
        acl = DocumentACL(allowed_users=["bob"])
        doc = Document(
            id="1",
            name="report.pdf",
            content=b"abcd",
            source_url="s3://b/report.pdf",
            size=99,
            extension=".docx",
            acl=acl,
        )

        assert doc.size == 99
        assert doc.extension == ".docx"
        assert doc.acl is acl

    def test_empty_content_and_name_leave_size_and_extension_unset(self):
        """Without content or name there is nothing to derive size or extension from."""
        doc = Document(id="1", name="", content=b"", source_url="")

        assert doc.size is None
        assert doc.extension is None


class TestIngestionResult:
    """Counters, success rate and serialization of IngestionResult."""

    def test_add_error_records_failure(self):
        """add_error increments the failure counter and stores the error details."""
        result = IngestionResult()

        result.add_error("d1", "a.pdf", "corrupt")

        assert result.failed_documents == 1
        assert result.failed_doc_ids == ["d1"]
        assert result.errors == [{"doc_id": "d1", "doc_name": "a.pdf", "error": "corrupt"}]

    def test_add_warning_does_not_touch_counters(self):
        """add_warning only appends a warning entry."""
        result = IngestionResult()

        result.add_warning("d1", "a.pdf", "slow")

        assert result.warnings == [{"doc_id": "d1", "doc_name": "a.pdf", "warning": "slow"}]
        assert (result.failed_documents, result.skipped_documents, result.processed_documents) == (0, 0, 0)

    def test_add_skipped_records_skip_with_reason(self):
        """add_skipped increments the skip counter and stores the reason as a warning."""
        result = IngestionResult()

        result.add_skipped("d2", "b.txt", "excluded")

        assert result.skipped_documents == 1
        assert result.skipped_doc_ids == ["d2"]
        assert result.warnings == [{"doc_id": "d2", "doc_name": "b.txt", "reason": "excluded"}]

    def test_success_rate_is_zero_without_documents(self):
        """An empty run reports 0% instead of dividing by zero."""
        assert IngestionResult().success_rate == 0.0

    def test_success_rate_is_percentage_of_processed(self):
        """The success rate is processed / total as a percentage."""
        result = IngestionResult(total_documents=4)
        result.increment_processed()

        assert result.processed_documents == 1
        assert result.success_rate == pytest.approx(25.0)

    def test_to_dict_contains_all_fields(self):
        """to_dict serializes counters, id lists, messages, metadata and the success rate."""
        result = IngestionResult(total_documents=2, metadata={"source": "s3"})
        result.increment_processed()
        result.add_error("d1", "a.pdf", "corrupt")

        assert result.to_dict() == {
            "total_documents": 2,
            "processed_documents": 1,
            "failed_documents": 1,
            "skipped_documents": 0,
            "success_rate": 50.0,
            "failed_doc_ids": ["d1"],
            "skipped_doc_ids": [],
            "errors": [{"doc_id": "d1", "doc_name": "a.pdf", "error": "corrupt"}],
            "warnings": [],
            "metadata": {"source": "s3"},
        }
