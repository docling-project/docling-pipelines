"""Unit tests for document_set_utils helper functions."""

from datetime import UTC, datetime

import pyarrow as pa
import pytest

from docpipe.api.dto.document_set_dto import DocumentSetPreviewResponse, DocumentSetResponse
from docpipe.api.routes.document_set_utils import (
    document_set_to_response,
    make_json_serializable,
    table_to_preview_response,
)
from docpipe.core.assets.common.domain.models.attachment_ref import AttachmentRef
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_DS_ID_1 = "550e8400-e29b-41d4-a716-446655440001"
_DS_ID_2 = "550e8400-e29b-41d4-a716-446655440002"


@pytest.fixture
def minimal_document_set() -> DocumentSet:
    """DocumentSet with no timestamps."""
    return DocumentSet(
        asset_id=_DS_ID_1,
        name="Test Dataset",
        description="A test document set",
        storage_backend="duckdb",
        total_documents=0,
        total_size_bytes=0,
        total_pages=0,
        created_at=None,
        updated_at=None,
        metadata={},
    )


@pytest.fixture
def full_document_set() -> DocumentSet:
    """DocumentSet with timestamps."""
    return DocumentSet(
        asset_id=_DS_ID_2,
        name="Full Dataset",
        description="Full document set",
        storage_backend="duckdb",
        total_documents=42,
        total_size_bytes=1024,
        total_pages=5,
        created_at=datetime(2024, 3, 1, tzinfo=UTC),
        updated_at=datetime(2024, 3, 2, tzinfo=UTC),
        metadata={"source": "test"},
    )


@pytest.fixture
def duckdb_attachment_ref() -> AttachmentRef:
    """AttachmentRef as produced by DuckDBDocumentSetStorage."""
    return AttachmentRef(
        backend_type="duckdb",
        name="full_dataset",
        details={
            "database_path": "/data/docsets.duckdb",
            "table_name": "full_dataset",
        },
    )


# ---------------------------------------------------------------------------
# document_set_to_response
# ---------------------------------------------------------------------------


class TestDocumentSetToResponse:
    """Tests for document_set_to_response."""

    def test_returns_document_set_response_type(self, minimal_document_set):
        result = document_set_to_response(document_set=minimal_document_set)
        assert isinstance(result, DocumentSetResponse)

    def test_maps_basic_fields(self, full_document_set):
        result = document_set_to_response(document_set=full_document_set)

        assert result.id == _DS_ID_2
        assert result.name == "Full Dataset"
        assert result.description == "Full document set"
        assert result.storage_backend == "duckdb"
        assert result.total_documents == 42
        assert result.total_size_bytes == 1024
        assert result.total_pages == 5

    def test_maps_storage_coordinates_from_attachment_ref(self, full_document_set, duckdb_attachment_ref):
        result = document_set_to_response(document_set=full_document_set, attachment_ref=duckdb_attachment_ref)

        assert result.database_path == "/data/docsets.duckdb"
        assert result.table_name == "full_dataset"

    def test_no_attachment_ref_yields_null_storage_fields(self, minimal_document_set):
        result = document_set_to_response(document_set=minimal_document_set)

        assert result.database_path is None
        assert result.table_name is None

    def test_timestamps_default_when_none(self, minimal_document_set):
        """When created_at/updated_at are None, response fills in current time."""
        result = document_set_to_response(document_set=minimal_document_set)

        assert result.created_at is not None
        assert result.updated_at is not None

    def test_timestamps_preserved_when_set(self, full_document_set):
        result = document_set_to_response(document_set=full_document_set)

        assert result.created_at == datetime(2024, 3, 1, tzinfo=UTC)
        assert result.updated_at == datetime(2024, 3, 2, tzinfo=UTC)

    def test_metadata_defaults_to_empty_dict_when_none(self, minimal_document_set):
        minimal_document_set.metadata = None
        result = document_set_to_response(document_set=minimal_document_set)

        assert result.metadata == {}


# ---------------------------------------------------------------------------
# make_json_serializable
# ---------------------------------------------------------------------------


class TestMakeJsonSerializable:
    """Tests for make_json_serializable."""

    def test_none_returns_none(self):
        assert make_json_serializable(value=None) is None

    def test_string_passthrough(self):
        assert make_json_serializable(value="hello") == "hello"

    def test_int_passthrough(self):
        assert make_json_serializable(value=42) == 42

    def test_dict_recurses(self):
        result = make_json_serializable(value={"key": None, "nested": {"x": 1}})
        assert result == {"key": None, "nested": {"x": 1}}

    def test_list_recurses(self):
        result = make_json_serializable(value=[1, None, "a"])
        assert result == [1, None, "a"]

    def test_tuple_converts_to_list(self):
        result = make_json_serializable(value=(1, 2, 3))
        assert result == [1, 2, 3]

    def test_datetime_converts_to_isoformat(self):
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = make_json_serializable(value=dt)
        assert result == dt.isoformat()

    def test_bytes_decodes_to_utf8(self):
        result = make_json_serializable(value=b"hello bytes")
        assert result == "hello bytes"


# ---------------------------------------------------------------------------
# table_to_preview_response
# ---------------------------------------------------------------------------


class TestTableToPreviewResponse:
    """Tests for table_to_preview_response."""

    def test_returns_preview_response_type(self):
        table = pa.table({"col_a": [1, 2], "col_b": ["x", "y"]})
        result = table_to_preview_response(table=table)
        assert isinstance(result, DocumentSetPreviewResponse)

    def test_columns_populated(self):
        table = pa.table({"col_a": [1], "col_b": ["x"]})
        result = table_to_preview_response(table=table)
        assert result.columns == ["col_a", "col_b"]

    def test_total_rows_correct(self):
        table = pa.table({"id": [10, 20, 30]})
        result = table_to_preview_response(table=table)
        assert result.total_rows == 3

    def test_data_rows_serialized(self):
        table = pa.table({"id": [1, 2], "name": ["a", "b"]})
        result = table_to_preview_response(table=table)
        assert len(result.data) == 2
        assert result.data[0] == {"id": 1, "name": "a"}

    def test_empty_table(self):
        table = pa.table({"col": pa.array([], type=pa.int64())})
        result = table_to_preview_response(table=table)
        assert result.total_rows == 0
        assert result.data == []


def test_make_json_serializable_falls_back_when_isoformat_needs_arguments() -> None:
    """A value whose isoformat() cannot be called without arguments (here: the date class itself)
    is not treated as a timestamp and is returned unchanged."""
    from datetime import date

    assert make_json_serializable(value=date) is date
