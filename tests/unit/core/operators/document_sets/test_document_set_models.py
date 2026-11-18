"""Unit tests for DocumentSet domain models.

Tests cover:
- DocumentSet creation and validation
- DataCard serialization
- Statistics update methods
- Invalid data handling
"""

from datetime import datetime

import pytest

from docpipe.core.assets.document_sets.domain.models.data_card import DataCard
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet
from docpipe.exceptions.docpipe_exceptions import DocpipeException


class TestDocumentSetCreation:
    """Test DocumentSet creation and initialization."""

    def test_document_set_creation(self):
        """Test creating a DocumentSet with valid data."""
        doc_set = DocumentSet(
            name="Test Documents",
            description="Test description",
        )

        assert doc_set.name == "Test Documents"
        assert doc_set.description == "Test description"
        assert doc_set.asset_id is not None
        assert doc_set.storage_backend == "duckdb"
        assert doc_set.total_documents == 0
        assert doc_set.total_size_bytes == 0
        assert doc_set.total_pages == 0
        assert isinstance(doc_set.created_at, datetime)
        assert isinstance(doc_set.updated_at, datetime)
        assert isinstance(doc_set.metadata, dict)

    def test_document_set_with_custom_id(self):
        """Test creating a DocumentSet with custom asset_id."""
        custom_id = "custom-id-123"
        doc_set = DocumentSet(
            asset_id=custom_id,
            name="Test Documents",
        )

        assert doc_set.asset_id == custom_id

    def test_document_set_with_metadata(self):
        """Test creating a DocumentSet with custom metadata."""
        metadata = {"source": "test", "version": "1.0"}
        doc_set = DocumentSet(
            name="Test Documents",
            metadata=metadata,
        )

        assert doc_set.metadata == metadata

    def test_document_set_with_statistics(self):
        """Test creating a DocumentSet with statistics."""
        doc_set = DocumentSet(
            name="Test Documents",
            total_documents=100,
            total_size_bytes=1024000,
            total_pages=500,
        )

        assert doc_set.total_documents == 100
        assert doc_set.total_size_bytes == 1024000
        assert doc_set.total_pages == 500


class TestDocumentSetValidation:
    """Test DocumentSet validation rules."""

    def test_document_set_validation_success(self):
        """Test validation passes with valid data."""
        doc_set = DocumentSet(name="Valid Name")

        doc_set.validate()  # Should not raise

    def test_validation_empty_name(self):
        """Test validation fails with empty name."""
        doc_set = DocumentSet(name="")

        with pytest.raises(DocpipeException) as exc_info:
            doc_set.validate()
        assert "name cannot be empty" in str(exc_info.value)

    def test_validation_name_starts_with_number(self):
        """Test validation fails when name starts with number."""
        doc_set = DocumentSet(name="123 Documents")

        with pytest.raises(DocpipeException) as exc_info:
            doc_set.validate()
        assert "must start with an alphabetic character" in str(exc_info.value)

    def test_validation_name_invalid_characters(self):
        """Test validation fails with invalid characters in name."""
        doc_set = DocumentSet(
            name="Test@Documents!",
        )

        with pytest.raises(DocpipeException) as exc_info:
            doc_set.validate()
        assert "can only contain letters, digits, spaces, and underscores" in str(exc_info.value)

    def test_validation_name_too_long(self):
        """Test validation fails when name exceeds max length."""
        long_name = "A" * 129  # Max is 128
        doc_set = DocumentSet(name=long_name)

        with pytest.raises(DocpipeException) as exc_info:
            doc_set.validate()
        assert "cannot exceed 128 characters" in str(exc_info.value)

    def test_validation_description_too_long(self):
        """Test validation fails when description exceeds max length."""
        long_desc = "A" * 2001  # Max is 2000
        doc_set = DocumentSet(
            name="Test Documents",
            description=long_desc,
        )

        with pytest.raises(DocpipeException) as exc_info:
            doc_set.validate()
        assert "description cannot exceed 2000 characters" in str(exc_info.value)

    def test_validation_negative_documents(self):
        """Test validation fails with negative document count."""
        doc_set = DocumentSet(
            name="Test Documents",
            total_documents=-1,
        )

        with pytest.raises(DocpipeException) as exc_info:
            doc_set.validate()
        assert "Total documents cannot be negative" in str(exc_info.value)

    def test_validation_negative_size(self):
        """Test validation fails with negative size."""
        doc_set = DocumentSet(
            name="Test Documents",
            total_size_bytes=-1,
        )

        with pytest.raises(DocpipeException) as exc_info:
            doc_set.validate()
        assert "Total size bytes cannot be negative" in str(exc_info.value)

    def test_validation_negative_pages(self):
        """Test validation fails with negative pages."""
        doc_set = DocumentSet(
            name="Test Documents",
            total_pages=-1,
        )

        with pytest.raises(DocpipeException) as exc_info:
            doc_set.validate()
        assert "Total pages cannot be negative" in str(exc_info.value)


class TestDataCardSerialization:
    """Test DataCard serialization and deserialization."""

    def test_data_card_to_dict(self):
        """Test DataCard to_dict method."""
        data_card = DataCard(
            flow_id="flow-123",
            flow_name="Test Flow",
            job_id="job-456",
            job_run_id="run-789",
            operators=["IngestOperator", "ExtractOperator"],
            lineage_metadata={"source": "test"},
        )

        result = data_card.to_dict()

        assert result["flow_id"] == "flow-123"
        assert result["flow_name"] == "Test Flow"
        assert result["job_id"] == "job-456"
        assert result["job_run_id"] == "run-789"
        assert result["operators"] == ["IngestOperator", "ExtractOperator"]
        assert result["lineage_metadata"] == {"source": "test"}

    def test_data_card_from_dict(self):
        """Test DataCard from_dict method."""
        data = {
            "flow_id": "flow-123",
            "flow_name": "Test Flow",
            "job_id": "job-456",
            "job_run_id": "run-789",
            "operators": ["IngestOperator", "ExtractOperator"],
            "lineage_metadata": {"source": "test"},
        }

        data_card = DataCard.from_dict(data)

        assert data_card.flow_id == "flow-123"
        assert data_card.flow_name == "Test Flow"
        assert data_card.job_id == "job-456"
        assert data_card.job_run_id == "run-789"
        assert data_card.operators == ["IngestOperator", "ExtractOperator"]
        assert data_card.lineage_metadata == {"source": "test"}

    def test_data_card_roundtrip(self):
        """Test DataCard serialization roundtrip."""
        original = DataCard(flow_id="flow-123", flow_name="Test Flow", operators=["Op1", "Op2"])

        data = original.to_dict()
        restored = DataCard.from_dict(data)

        assert restored.flow_id == original.flow_id
        assert restored.flow_name == original.flow_name
        assert restored.operators == original.operators


class TestDocumentSetUpdateStatistics:
    """Test DocumentSet statistics update methods."""

    def test_update_statistics(self):
        """Test update_statistics method."""
        doc_set = DocumentSet(
            name="Test Documents",
        )

        original_updated_at = doc_set.updated_at

        doc_set.update_statistics(total_documents=100, total_size_bytes=1024000, total_pages=500)

        assert doc_set.total_documents == 100
        assert doc_set.total_size_bytes == 1024000
        assert doc_set.total_pages == 500
        assert doc_set.updated_at > original_updated_at

    def test_update_statistics_partial(self):
        """Test update_statistics with partial updates."""
        doc_set = DocumentSet(
            name="Test Documents",
            total_documents=50,
            total_size_bytes=512000,
            total_pages=250,
        )

        doc_set.update_statistics(total_documents=100)

        assert doc_set.total_documents == 100
        assert doc_set.total_size_bytes == 512000  # Unchanged
        assert doc_set.total_pages == 250  # Unchanged

    def test_update_timestamp(self):
        """Test update_timestamp method."""
        doc_set = DocumentSet(
            name="Test Documents",
        )

        original_updated_at = doc_set.updated_at

        doc_set.update_timestamp()

        assert doc_set.updated_at >= original_updated_at


class TestDocumentSetSerialization:
    """Test DocumentSet serialization and deserialization."""

    def test_document_set_to_dict(self):
        """Test DocumentSet to_dict method."""
        doc_set = DocumentSet(
            name="Test Documents",
            description="Test description",
            total_documents=100,
            metadata={"source": "test"},
        )

        result = doc_set.to_dict()

        assert result["name"] == "Test Documents"
        assert result["description"] == "Test description"
        assert result["total_documents"] == 100
        assert result["metadata"] == {"source": "test"}
        assert "asset_id" in result
        assert "created_at" in result
        assert "updated_at" in result

    def test_document_set_from_dict(self):
        """Test DocumentSet from_dict method."""
        data = {
            "asset_id": "test-id-123",
            "name": "Test Documents",
            "description": "Test description",
            "total_documents": 100,
            "total_size_bytes": 1024000,
            "total_pages": 500,
            "metadata": {"source": "test"},
        }

        doc_set = DocumentSet.from_dict(data=data)

        assert doc_set.asset_id == "test-id-123"
        assert doc_set.name == "Test Documents"
        assert doc_set.description == "Test description"
        assert doc_set.total_documents == 100
        assert doc_set.metadata == {"source": "test"}

    def test_document_set_roundtrip(self):
        """Test DocumentSet serialization roundtrip."""
        original = DocumentSet(
            name="Test Documents",
            description="Test description",
            total_documents=100,
        )

        data = original.to_dict()
        restored = DocumentSet.from_dict(data=data)

        assert restored.asset_id == original.asset_id
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.total_documents == original.total_documents


class TestDocumentSetAccessors:
    """Backward-compatible id alias, defaults and the timestamp accessors used for sorting."""

    def test_id_aliases_asset_id(self):
        doc_set = DocumentSet(name="Alias Set", asset_id="first-id")

        assert doc_set.id == "first-id"
        doc_set.id = "second-id"
        assert doc_set.asset_id == "second-id"

    def test_metadata_none_becomes_empty_dict(self):
        assert DocumentSet(name="No Metadata", metadata=None).metadata == {}

    def test_timestamp_accessors(self):
        doc_set = DocumentSet(name="Timed Set")

        assert doc_set.get_created_at() == doc_set.created_at
        assert doc_set.get_updated_at() == doc_set.updated_at

    def test_update_statistics_keeps_document_count_when_not_given(self):
        doc_set = DocumentSet(name="Counted Set", total_documents=5)

        doc_set.update_statistics(total_size_bytes=2048)

        assert (doc_set.total_documents, doc_set.total_size_bytes) == (5, 2048)

    def test_from_dict_restores_data_card(self):
        card = DataCard(flow_id="flow-1", flow_name="Ingest", operators=["ingest_source", "document_set"])
        data = DocumentSet(name="Carded Set", data_card=card).to_dict()

        restored = DocumentSet.from_dict(data=data)

        assert restored.data_card == card
