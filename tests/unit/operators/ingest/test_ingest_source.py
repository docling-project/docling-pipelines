#!/usr/bin/env python3
"""
Unit tests for IngestSourceOperator.
Tests the operator with various providers and configurations using mocks.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch

import pyarrow as pa
import pytest
from langchain_core.documents import Document


@pytest.fixture
def mock_documents():
    """Fixture providing sample LangChain documents."""
    return [
        Document(
            page_content="This is the first document content.",
            metadata={"source": "file1.txt", "page": 1},
        ),
        Document(
            page_content="This is the second document content.",
            metadata={"source": "file2.txt", "page": 1},
        ),
        Document(
            page_content="This is the third document content.",
            metadata={"source": "file3.txt", "page": 2},
        ),
    ]


@pytest.fixture
def empty_input_table():
    """Fixture providing an empty PyArrow table as input trigger."""
    return pa.Table.from_arrays([])


class TestIngestSourceOperatorInitialization:
    """Test cases for operator initialization."""

    def test_init_with_s3_provider(self):
        """Test initialization with S3 provider."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "s3",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "test-prefix/",
                "access_key": "test-access-key",  # pragma: allowlist secret
                "secret_key": "test-secret-key",  # pragma: allowlist secret
            },
        }

        operator = IngestSourceOperator(config)

        assert operator.provider == "s3"
        assert operator.provider_config["bucket"] == "test-bucket"
        assert operator.provider_config["prefix"] == "test-prefix/"
        assert operator.provider_config["access_key"] == "test-access-key"

    def test_init_with_ibm_cos_provider(self):
        """Test initialization with IBM COS provider."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "ibm_cos",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "test-prefix/",
                "endpoint_url": "https://s3.us-south.cloud-object-storage.appdomain.cloud",
                "access_key": "test-access-key",  # pragma: allowlist secret
                "secret_key": "test-secret-key",  # pragma: allowlist secret
            },
        }

        operator = IngestSourceOperator(config)

        assert operator.provider == "ibm_cos"
        assert operator.provider_config["endpoint_url"] == "https://s3.us-south.cloud-object-storage.appdomain.cloud"

    def test_init_with_google_drive_provider(self):
        """Test initialization with Google Drive provider."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "google_drive",
            "provider_config": {
                "folder_id": "test-folder-id",
                "recursive": True,
                "credentials_json_path": "/path/to/credentials.json",
                "token_path": "/path/to/token.json",
                "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
            },
        }

        operator = IngestSourceOperator(config)

        assert operator.provider == "google_drive"
        assert operator.provider_config["folder_id"] == "test-folder-id"
        assert operator.provider_config["recursive"] is True
        assert operator.provider_config["scopes"] == ["https://www.googleapis.com/auth/drive.readonly"]

    def test_init_with_sharepoint_provider(self):
        """Test initialization with SharePoint provider."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "sharepoint",
            "provider_config": {
                "document_library_id": "test-library-id",
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",  # pragma: allowlist secret
            },
        }

        operator = IngestSourceOperator(config)

        assert operator.provider == "sharepoint"
        assert operator.provider_config["document_library_id"] == "test-library-id"

    def test_init_with_onedrive_provider(self):
        """Test initialization with OneDrive provider."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "onedrive",
            "provider_config": {
                "drive_id": "test-drive-id",
                "folder_path": "/Documents",
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",  # pragma: allowlist secret
            },
        }

        operator = IngestSourceOperator(config)

        assert operator.provider == "onedrive"
        assert operator.provider_config["drive_id"] == "test-drive-id"
        assert operator.provider_config["folder_path"] == "/Documents"

    def test_init_with_custom_provider(self):
        """Test initialization with custom provider."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "custom",
            "provider_config": {
                "loader_class_path": "my_package.loaders.CustomLoader",
                "custom_param": "value",
                "api_key": "test-api-key",  # pragma: allowlist secret
            },
        }

        operator = IngestSourceOperator(config)

        assert operator.provider == "custom"
        assert operator.provider_config["loader_class_path"] == "my_package.loaders.CustomLoader"


class TestGetMetadata:
    """Test cases for get_metadata method."""

    def test_all_adapter_managed_providers_are_consistent(self):
        """Every provider in ADAPTER_MANAGED_PROVIDERS must be consistent across three surfaces:
        1. Registered in SourceAdapterFactory (or covered by a factory alias)
        2. Listed in get_metadata() provider valid_values
        3. Has a schema entry in get_metadata() provider_config.providers

        This is a single regression guard that will catch any future provider that
        is added to one place but forgotten in another.
        """
        import docpipe.core.operators.ingest.adapters.outbound.sources  # noqa: F401 — triggers adapter registration
        from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import (
            SourceAdapterFactory,
        )
        from docpipe.core.operators.ingest.ingest_source import (
            ADAPTER_MANAGED_PROVIDERS,
            IngestSourceOperator,
        )

        metadata = IngestSourceOperator.get_metadata()
        valid_values = set(metadata["attributes"]["provider"]["valid_values"])
        provider_schemas = metadata["attributes"]["provider_config"]["providers"]
        registered = set(SourceAdapterFactory.get_registered_names())

        missing_from_factory: list[str] = []
        missing_from_valid_values: list[str] = []
        missing_from_schemas: list[str] = []

        for provider in sorted(ADAPTER_MANAGED_PROVIDERS):
            if provider not in registered:
                missing_from_factory.append(provider)
            if provider not in valid_values:
                missing_from_valid_values.append(provider)
            if provider not in provider_schemas:
                missing_from_schemas.append(provider)

        assert not missing_from_factory, (
            f"Providers in ADAPTER_MANAGED_PROVIDERS but not registered in SourceAdapterFactory: {missing_from_factory}"
        )
        assert not missing_from_valid_values, (
            f"Providers in ADAPTER_MANAGED_PROVIDERS but missing from get_metadata() valid_values: "
            f"{missing_from_valid_values}"
        )
        assert not missing_from_schemas, (
            f"Providers in ADAPTER_MANAGED_PROVIDERS but missing from get_metadata() provider_config.providers: "
            f"{missing_from_schemas}"
        )

    def test_get_metadata_declares_all_output_columns(self):
        """Operator metadata must declare every column produced at runtime.

        The validator uses declared features to check downstream operator compatibility
        (e.g. document_set requires 'id'). A missing declaration causes a false
        FLOW VALIDATION FAILED even when the column is present in the actual output.
        """
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        metadata = IngestSourceOperator.get_metadata()
        declared = set(metadata["features"].keys())
        runtime_columns = {
            "id",
            "name",
            "path",
            "document_format",
            "metadata",
            "source_id",
            "modified_time",
            "doc_id_hash",
        }

        assert runtime_columns.issubset(declared), (
            f"Columns produced at runtime but missing from metadata: {runtime_columns - declared}"
        )

    def test_get_metadata_document_id_is_filterable(self):
        """Document ID must be marked available_for_filter so it can be used as a join/filter key downstream."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        metadata = IngestSourceOperator.get_metadata()

        assert metadata["features"]["id"]["available_for_filter"] is True


class TestGetLoader:
    """Test cases for _get_loader method."""

    def test_get_loader_s3(self):
        """Test _get_loader raises error for S3 provider (should use _load_s3_documents instead)."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "s3",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "test-prefix/",
                "access_key": "test-access-key",  # pragma: allowlist secret
                "secret_key": "test-secret-key",  # pragma: allowlist secret
            },
        }

        operator = IngestSourceOperator(config)

        with pytest.raises(ValueError, match="provider should use _process_documents_from_adapter"):
            operator._get_loader()

    def test_get_loader_ibm_cos(self):
        """Test _get_loader raises error for IBM COS provider (should use _load_s3_documents instead)."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "ibm_cos",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "test-prefix/",
                "endpoint_url": "https://s3.us-south.cloud-object-storage.appdomain.cloud",
                "access_key": "test-access-key",  # pragma: allowlist secret
                "secret_key": "test-secret-key",  # pragma: allowlist secret
            },
        }

        operator = IngestSourceOperator(config)

        with pytest.raises(ValueError, match="provider should use _process_documents_from_adapter"):
            operator._get_loader()

    def test_get_loader_google_drive(self):
        """Test Google Drive provider uses new adapter architecture (no _get_loader)."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "google_drive",
            "provider_config": {
                "folder_id": "test-folder-id",
                "recursive": True,
                "credentials_json_path": "/path/to/credentials.json",
                "token_path": "/path/to/token.json",
                "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
            },
        }

        operator = IngestSourceOperator(config)

        # Google Drive uses adapter architecture via SourceAdapterFactory
        # Calling _get_loader() should raise ValueError
        with pytest.raises(
            ValueError,
            match="google_drive provider should use _process_documents_from_adapter",
        ):
            operator._get_loader()

    def test_get_loader_sharepoint(self):
        """Test _get_loader raises ValueError for SharePoint provider (should use adapter)."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "sharepoint",
            "provider_config": {
                "document_library_id": "test-library-id",
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",  # pragma: allowlist secret
                "tenant_id": "test-tenant-id",
            },
        }

        operator = IngestSourceOperator(config)

        with pytest.raises(
            ValueError,
            match="sharepoint provider should use _process_documents_from_adapter",
        ):
            operator._get_loader()

    def test_get_loader_onedrive(self):
        """Test _get_loader raises ValueError for OneDrive provider (should use adapter)."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "onedrive",
            "provider_config": {
                "drive_id": "test-drive-id",
                "folder_path": "/Documents",
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",  # pragma: allowlist secret
                "tenant_id": "test-tenant-id",
            },
        }

        operator = IngestSourceOperator(config)

        with pytest.raises(ValueError, match="onedrive provider should use _process_documents_from_adapter"):
            operator._get_loader()

    @patch("importlib.import_module")
    def test_get_loader_custom(self, mock_import):
        """Test _get_loader returns custom loader for custom provider."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        # Mock the custom loader class
        mock_loader_class = Mock()
        mock_module = Mock()
        mock_module.CustomLoader = mock_loader_class
        mock_import.return_value = mock_module

        config = {
            "provider": "custom",
            "provider_config": {
                "loader_class_path": "my_package.loaders.CustomLoader",
                "custom_param": "value",
                "api_key": "test-api-key",  # pragma: allowlist secret
            },
        }

        operator = IngestSourceOperator(config)
        _loader = operator._get_loader()

        mock_import.assert_called_once_with("my_package.loaders")
        mock_loader_class.assert_called_once()

    def test_get_loader_custom_passes_merged_init_kwargs(self):
        """Test _get_loader passes all provider_config params to custom loaders."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        mock_loader_class = Mock()
        mock_module = Mock()
        mock_module.CustomLoader = mock_loader_class

        config = {
            "provider": "custom",
            "provider_config": {
                "loader_class_path": "my_package.loaders.CustomLoader",
                "custom_param": "value",
                "api_key": "test-api-key",  # pragma: allowlist secret
            },
        }

        with patch("importlib.import_module", return_value=mock_module):
            operator = IngestSourceOperator(config)
            operator._get_loader()

        mock_loader_class.assert_called_once_with(
            loader_class_path="my_package.loaders.CustomLoader",
            custom_param="value",
            api_key="test-api-key",  # pragma: allowlist secret
        )

    def test_get_loader_custom_missing_path(self):
        """Test _get_loader raises error when custom provider missing loader_class_path."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {"provider": "custom", "provider_config": {}}

        operator = IngestSourceOperator(config)

        with pytest.raises(ValueError, match="Provider is 'custom' but 'loader_class_path' is missing"):
            operator._get_loader()

    def test_get_loader_unsupported_provider(self):
        """Test _get_loader raises error for unsupported provider."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "unsupported_provider",
            "provider_config": {},
        }

        operator = IngestSourceOperator(config)

        with pytest.raises(ValueError, match="Provider 'unsupported_provider' is not supported"):
            operator._get_loader()


class TestTransform:
    """Test cases for transform method."""

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    @patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.S3SourceAdapter.fetch_documents")
    def test_transform_success(
        self,
        mock_fetch_documents,
        mock_get_service,
        mock_documents,
        empty_input_table,
    ):
        """Test transform successfully processes documents."""
        from datetime import datetime

        from docpipe.core.operators.ingest.domain.models import Document as DomainDocument
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        # Mock incremental update service
        mock_service = Mock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        # Create domain documents for the new adapter (lazy loading - no binary content)
        domain_docs = [
            DomainDocument(
                id="file1.txt",
                name="file1.txt",
                content=b"",  # Empty - lazy loading
                source_url="s3://test-bucket/test-prefix/file1.txt",
                modified_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                metadata={"bucket": "test-bucket", "key": "test-prefix/file1.txt"},
            ),
            DomainDocument(
                id="file2.txt",
                name="file2.txt",
                content=b"",  # Empty - lazy loading
                source_url="s3://test-bucket/test-prefix/file2.txt",
                modified_time=datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC),
                metadata={"bucket": "test-bucket", "key": "test-prefix/file2.txt"},
            ),
            DomainDocument(
                id="file3.txt",
                name="file3.txt",
                content=b"",  # Empty - lazy loading
                source_url="s3://test-bucket/test-prefix/file3.txt",
                modified_time=datetime(2024, 1, 3, 12, 0, 0, tzinfo=UTC),
                metadata={"bucket": "test-bucket", "key": "test-prefix/file3.txt"},
            ),
        ]

        # Mock async generator for fetch_documents
        async def mock_async_gen():
            for doc in domain_docs:
                yield doc

        # Return the coroutine function, not the result
        mock_fetch_documents.return_value = mock_async_gen()

        config = {
            "provider": "s3",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "test-prefix/",
                "access_key": "test-access-key",  # pragma: allowlist secret
                "secret_key": "test-secret-key",  # pragma: allowlist secret
            },
            "job_id": "test-job-123",
            "job_run_id": "test-run-456",
            "force_ingest": True,
        }

        operator = IngestSourceOperator(config)
        result_tables, metadata = operator.transform(empty_input_table)

        # Assertions
        assert len(result_tables) == 1
        result_table = result_tables[0]

        assert result_table.num_rows == 3
        assert "id" in result_table.column_names
        assert "name" in result_table.column_names
        assert "document_format" in result_table.column_names
        assert "metadata" in result_table.column_names
        assert "source_id" in result_table.column_names
        assert "path" in result_table.column_names
        assert "modified_time" in result_table.column_names
        # binary_content column should NOT be present (lazy loading)
        assert "binary_content" not in result_table.column_names

        # Check metadata is JSON serialized
        metadata_list = result_table["metadata"].to_pylist()
        assert len(metadata_list) == 3

        # Check source_id
        source_ids = result_table["source_id"].to_pylist()
        assert len(source_ids) == 3

        # Check metadata - now follows AbstractOperator pattern
        assert metadata["node_status"] == "Completed"
        assert metadata["processed_docs"] == 3
        assert metadata["documents_in_scope"] == 3

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    @patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.S3SourceAdapter.fetch_documents")
    def test_transform_empty_documents(
        self,
        mock_fetch_documents,
        mock_get_service,
        empty_input_table,
    ):
        """Test transform handles empty document list."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        # Mock incremental update service
        mock_service = Mock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        # Mock async generator that yields no documents
        async def mock_async_gen():
            # Empty async generator - no yields
            if False:  # pragma: no cover
                yield  # Make it a generator but never execute

        mock_fetch_documents.return_value = mock_async_gen()

        config = {
            "provider": "s3",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "test-prefix/",
                "access_key": "test-access-key",  # pragma: allowlist secret
                "secret_key": "test-secret-key",  # pragma: allowlist secret
            },
            "job_id": "test-job-123",
            "job_run_id": "test-run-456",
            "force_ingest": True,
        }

        operator = IngestSourceOperator(config)
        result_tables, metadata = operator.transform(empty_input_table)

        # Assertions
        assert len(result_tables) == 1
        result_table = result_tables[0]

        assert result_table.num_rows == 0
        assert metadata["node_status"] == "Completed"
        assert metadata["processed_docs"] == 0

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    @patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.S3SourceAdapter.fetch_documents")
    def test_transform_error_handling(
        self,
        mock_fetch_documents,
        mock_get_service,
        empty_input_table,
    ):
        """Test transform handles errors gracefully with S3 adapter."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        # Mock incremental update service
        mock_service = Mock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        # Mock adapter to raise exception immediately
        async def failing_fetch():
            raise Exception("Connection failed")
            if False:  # pragma: no cover
                yield  # Make it a generator but never execute

        mock_fetch_documents.return_value = failing_fetch()

        config = {
            "provider": "s3",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "test-prefix/",
                "access_key": "test-access-key",  # pragma: allowlist secret
                "secret_key": "test-secret-key",  # pragma: allowlist secret
            },
            "job_id": "test-job-123",
            "job_run_id": "test-run-456",
            "force_ingest": True,
        }

        operator = IngestSourceOperator(config)
        result_tables, metadata = operator.transform(empty_input_table)

        # Assertions - should return empty table with error metadata
        assert len(result_tables) == 1
        result_table = result_tables[0]

        assert result_table.num_rows == 0
        # When all documents fail (processed=0, failed>0), status should be "Failed"
        assert metadata["node_status"] == "Failed"
        assert metadata["failed_docs_count"] == 1

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    @patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.S3SourceAdapter.fetch_documents")
    def test_transform_schema_validation(
        self,
        mock_fetch_documents,
        mock_get_service,
        mock_documents,
        empty_input_table,
    ):
        """Test transform output has correct schema with S3 adapter."""
        from datetime import datetime

        from docpipe.core.operators.ingest.domain.models import Document as DomainDocument
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        # Mock incremental update service
        mock_service = Mock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        # Create domain document from mock LangChain document (lazy loading - no binary)
        domain_doc = DomainDocument(
            id="test-id",
            name="file1.txt",
            content=b"",  # Empty - lazy loading
            source_url="s3://test-bucket/file1.txt",
            mimetype="text/plain",
            extension=".txt",
            size=len(mock_documents[0].page_content),
            modified_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        )

        # Mock async generator for fetch_documents
        async def mock_async_gen():
            yield domain_doc

        mock_fetch_documents.return_value = mock_async_gen()

        config = {
            "provider": "s3",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "test-prefix/",
                "access_key": "test-access-key",  # pragma: allowlist secret
                "secret_key": "test-secret-key",  # pragma: allowlist secret
            },
            "job_id": "test-job-123",
            "job_run_id": "test-run-456",
            "force_ingest": True,
        }

        operator = IngestSourceOperator(config)
        result_tables, _ = operator.transform(empty_input_table)

        result_table = result_tables[0]
        schema = result_table.schema

        # Verify schema - NO binary_content column (lazy loading)
        assert len(schema) == 7
        assert schema.field("id").type == pa.string()
        assert schema.field("name").type == pa.string()
        assert schema.field("document_format").type == pa.string()
        assert schema.field("metadata").type == pa.string()
        assert schema.field("source_id").type == pa.string()
        assert schema.field("path").type == pa.string()
        assert schema.field("modified_time").type == pa.int64()
        # binary_content should NOT be in schema
        with pytest.raises(KeyError):
            schema.field("binary_content")

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    @patch("os.path.exists")
    @patch("os.makedirs")
    def test_transform_google_drive(
        self,
        mock_makedirs,
        mock_path_exists,
        mock_get_service,
        mock_documents,
        empty_input_table,
    ):
        """Test transform with Google Drive provider using new adapter architecture."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        # Mock os.path.exists to return True
        mock_path_exists.return_value = True

        # Mock incremental update service
        mock_service = Mock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        # Create properly mocked LangChain Documents with _binary_content attribute
        def mock_load_documents_via_adapter():
            """Mock implementation that returns LangChain Documents with _binary_content"""
            langchain_docs = []
            for idx, doc in enumerate(mock_documents):
                # Create a mock LangChain Document that allows attribute assignment
                langchain_doc = Mock(spec=Document)
                langchain_doc.page_content = ""
                langchain_doc.metadata = {
                    "source": doc.metadata.get("source", f"test-file-{idx}.txt"),
                    "name": doc.metadata.get("source", f"test-file-{idx}.txt"),
                    "id": f"test-id-{idx}",
                    "last_modified": None,
                    "size": 100,
                    "mimetype": "text/plain",
                    "extension": ".txt",
                    "has_binary_content": True,
                    **doc.metadata,
                }
                # Set the _binary_content attribute that the operator expects
                langchain_doc._binary_content = doc.page_content.encode("utf-8")
                langchain_docs.append(langchain_doc)
            return langchain_docs

        config = {
            "provider": "google_drive",
            "provider_config": {
                "folder_id": "test-folder-id",
                "recursive": True,
                "credentials_json_path": "/path/to/credentials.json",
                "token_path": "/path/to/token.json",
                "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
            },
            "job_id": "test-job-123",
            "job_run_id": "test-run-456",
            "force_ingest": True,
        }

        operator = IngestSourceOperator(config)

        # Patch the _process_documents_from_adapter method to return our mocked documents
        # This is the new method used for adapter-based providers with batch-fetch logic
        def mock_process_from_adapter(metadata_dict):
            """Mock the new _process_documents_from_adapter method"""
            docs = mock_load_documents_via_adapter()
            doc_data = []
            for idx, doc in enumerate(docs):
                processed_doc = operator.process_document(doc, idx, metadata_dict)
                if processed_doc:
                    doc_data.append(processed_doc)
            return doc_data

        with patch.object(operator, "_process_documents_from_adapter", mock_process_from_adapter):
            # Also need to mock SourceAdapterFactory.is_registered to return True
            with patch(
                "docpipe.core.operators.ingest.ingest_source.SourceAdapterFactory.is_registered",
                return_value=True,
            ):
                result_tables, metadata = operator.transform(empty_input_table)

        assert len(result_tables) == 1
        assert result_tables[0].num_rows == 3
        assert metadata["node_status"] == "Completed"

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    @patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.S3SourceAdapter.fetch_documents")
    def test_transform_document_without_source(
        self,
        mock_fetch_documents,
        mock_get_service,
        empty_input_table,
    ):
        """Test transform handles documents without source in metadata."""
        from docpipe.core.operators.ingest.domain.models import Document as DomainDocument
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        # Mock incremental update service
        mock_service = Mock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        # Document without source (domain model, lazy loading)
        doc_no_source = DomainDocument(
            id="test-doc-1",
            name="file1.txt",
            content=b"",  # Empty - lazy loading
            source_url="s3://test-bucket/file1.txt",
            metadata={"page": 1},
        )

        # Mock S3SourceAdapter.fetch_documents to return async generator
        async def mock_async_gen():
            yield doc_no_source

        mock_fetch_documents.return_value = mock_async_gen()

        config = {
            "provider": "s3",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "",
                "access_key": "key",
                "secret_key": "secret",  # pragma: allowlist secret
            },
            "job_id": "test-job-123",
            "job_run_id": "test-run-456",
            "force_ingest": True,
        }

        operator = IngestSourceOperator(config)
        result_tables, _ = operator.transform(empty_input_table)

        result_table = result_tables[0]
        source_ids = result_table["source_id"].to_pylist()
        # With the new adapter architecture, source_url is always provided
        assert source_ids[0] == "s3://test-bucket/file1.txt"

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    def test_transform_google_drive_single_file_uses_adapter_path(
        self,
        mock_get_service,
        empty_input_table,
    ):
        """Test transform routes single-file Google Drive ingestion through the adapter path."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        mock_service = Mock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        config = {
            "provider": "google_drive",
            "provider_config": {
                "file_id": "doc123",
                "folder_id": "test-folder-id",
                "recursive": False,
                "credentials_path": "/path/to/credentials.json",
                "token_path": "/path/to/token.json",
                "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
            },
            "job_id": "test-job-123",
            "job_run_id": "test-run-456",
            "force_ingest": True,
        }

        operator = IngestSourceOperator(config)

        processed_doc = {
            "id": "hash123",
            "name": "single.pdf",
            "document_format": ".pdf",
            "metadata": "{}",
            "source_id": "doc123",
            "path": "https://drive.google.com/file/d/doc123",
            "modified_time": 0,
        }

        with (
            patch.object(operator, "_process_documents_from_adapter", return_value=[processed_doc]) as mock_process,
            patch(
                "docpipe.core.operators.ingest.ingest_source.SourceAdapterFactory.is_registered",
                return_value=True,
            ),
        ):
            result_tables, metadata = operator.transform(empty_input_table)

        mock_process.assert_called_once()
        assert len(result_tables) == 1
        assert result_tables[0].num_rows == 1
        assert result_tables[0]["source_id"].to_pylist() == ["doc123"]
        assert metadata["processed_docs"] == 1
        assert metadata["node_status"] == "Completed"


class TestIntegrationScenarios:
    """Integration test scenarios for common use cases."""

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    @patch("docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter.S3SourceAdapter.fetch_documents")
    def test_s3_to_pyarrow_pipeline(
        self,
        mock_fetch_documents,
        mock_get_service,
        empty_input_table,
    ):
        """Test complete S3 ingestion to PyArrow table pipeline."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        # Mock incremental update service
        mock_service = Mock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        from datetime import datetime

        from docpipe.core.operators.ingest.domain.models import Document as DomainDocument

        # Create domain documents for the new adapter (lazy loading - no binary)
        domain_docs = [
            DomainDocument(
                id="invoices/inv_001.pdf",
                name="inv_001.pdf",
                content=b"",  # Empty - lazy loading
                source_url="s3://my-bucket/invoices/inv_001.pdf",
                modified_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                metadata={"bucket": "my-bucket", "key": "invoices/inv_001.pdf"},
            ),
            DomainDocument(
                id="invoices/inv_002.pdf",
                name="inv_002.pdf",
                content=b"",  # Empty - lazy loading
                source_url="s3://my-bucket/invoices/inv_002.pdf",
                modified_time=datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC),
                metadata={"bucket": "my-bucket", "key": "invoices/inv_002.pdf"},
            ),
        ]

        # Mock async generator for fetch_documents
        async def mock_async_gen():
            for doc in domain_docs:
                yield doc

        mock_fetch_documents.return_value = mock_async_gen()

        config = {
            "provider": "s3",
            "provider_config": {
                "bucket": "my-bucket",
                "prefix": "invoices/",
                "access_key": "AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
                "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
            },
            "job_id": "test-job-123",
            "job_run_id": "test-run-456",
            "force_ingest": True,
        }

        operator = IngestSourceOperator(config)
        result_tables, metadata = operator.transform(empty_input_table)

        result_table = result_tables[0]

        # Verify pipeline output
        assert result_table.num_rows == 2
        assert metadata["node_status"] == "Completed"
        assert metadata["processed_docs"] == 2

        # Verify data can be converted to pandas for downstream processing
        df = result_table.to_pandas()
        assert len(df) == 2
        assert "id" in df.columns
        assert "name" in df.columns
        assert "metadata" in df.columns
        assert "source_id" in df.columns
        assert "path" in df.columns
        assert "modified_time" in df.columns
        # binary_content should NOT be present (lazy loading)
        assert "binary_content" not in df.columns


class TestIngestSourceOperatorProcessDocumentUrlExtensionFallback:
    """Test process_document fallback to metadata['name'] for URL-based sources without extension."""

    def _make_operator(self, include_filter: str | None = None):
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config: dict = {
            "provider": "s3",
            "provider_config": {
                "bucket": "test-bucket",
                "prefix": "",
                "access_key": "key",
                "secret_key": "secret",  # pragma: allowlist secret
            },
        }
        if include_filter:
            config["include_filter"] = include_filter
        return IngestSourceOperator(config)

    def test_box_url_with_pdf_name_accepted_when_pdf_included(self):
        """Box URL as source + 'name' = .pdf → document passes the .pdf include filter."""
        operator = self._make_operator(include_filter=".pdf")
        metadata = operator.create_base_metadata(total_docs_count=1)

        doc = Document(
            page_content="content",
            metadata={
                "source": "https://app.box.com/file/2350816183103",
                "name": "TR-INV_001.pdf",
            },
        )

        result = operator.process_document(doc, 0, metadata)
        assert result is not None, "Document should not be filtered out"

    def test_box_url_with_unsupported_name_filtered_when_pdf_included(self):
        """Box URL as source + 'name' = .xyz → document is filtered out when only .pdf is included."""
        operator = self._make_operator(include_filter=".pdf")
        metadata = operator.create_base_metadata(total_docs_count=1)

        doc = Document(
            page_content="content",
            metadata={
                "source": "https://app.box.com/file/9999",
                "name": "unsupported.xyz",
            },
        )

        result = operator.process_document(doc, 0, metadata)
        assert result is None, "Document with unsupported extension via name should be filtered"

    def test_plain_filepath_source_uses_source_directly(self):
        """Regular filepath source (has extension) is filtered on the path directly."""
        operator = self._make_operator(include_filter=".pdf")
        metadata = operator.create_base_metadata(total_docs_count=1)

        doc = Document(
            page_content="content",
            metadata={
                "source": "/data/report.pdf",
                "name": "report.pdf",
            },
        )

        result = operator.process_document(doc, 0, metadata)
        assert result is not None

    def test_box_url_with_no_name_metadata_falls_through(self):
        """Box URL with no 'name' in metadata should not raise — filter runs on the URL itself."""
        operator = self._make_operator(include_filter=".pdf")
        metadata = operator.create_base_metadata(total_docs_count=1)

        doc = Document(
            page_content="content",
            metadata={
                "source": "https://app.box.com/file/2350816183103",
                # no 'name' key
            },
        )

        # Should not raise; the URL has no extension so it won't match .pdf — document is skipped
        result = operator.process_document(doc, 0, metadata)
        assert result is None


class TestMicrosoftGraphLoader:
    @patch("docpipe.core.operators.ingest.ingest_source.RestClient")
    def test_get_token_returns_cached_value(self, mock_rest_client):
        from docpipe.core.operators.ingest.ingest_source import MicrosoftGraphLoader

        loader = MicrosoftGraphLoader(
            drive_id="drive1",
            client_id="client",
            client_secret="secret",  # pragma: allowlist secret
            tenant_id="tenant",
        )
        loader._token = "cached-token"

        assert loader._get_token() == "cached-token"
        # __init__ now creates two RestClient instances: one for the Graph API
        # (_rest_client) and one for direct downloads (_download_client).
        assert mock_rest_client.call_count == 2

    def test_process_items_splits_files_and_folders(self):
        from docpipe.core.operators.ingest.ingest_source import MicrosoftGraphLoader

        loader = MicrosoftGraphLoader(
            drive_id="drive1",
            client_id="client",
            client_secret="secret",  # pragma: allowlist secret
            tenant_id="tenant",
        )
        files: list[dict[str, object]] = []

        folder_ids = loader._process_items(
            items=[
                {"id": "folder1", "folder": {}},
                {"id": "file1", "name": "doc.txt"},
            ],
            files=files,
        )

        assert folder_ids == ["folder1"]
        assert files == [{"id": "file1", "name": "doc.txt"}]

    @patch("docpipe.core.operators.ingest.ingest_source.RestClient")
    def test_download_file_uses_content_endpoint_without_download_url(self, mock_rest_client_cls):
        from docpipe.core.operators.ingest.ingest_source import MicrosoftGraphLoader

        rest_client = Mock()
        response = Mock()
        response.content = b"payload"
        rest_client.call_rest.return_value = response
        mock_rest_client_cls.return_value = rest_client

        loader = MicrosoftGraphLoader(
            drive_id="drive1",
            client_id="client",
            client_secret="secret",  # pragma: allowlist secret
            tenant_id="tenant",
        )
        loader._token = "token"

        content = loader._download_file({"id": "item123"})

        assert content == b"payload"
        rest_client.call_rest.assert_called_once()

    @patch("docpipe.core.operators.ingest.ingest_source.RestClient")
    def test_list_files_handles_pagination_and_recursion(self, mock_rest_client_cls):
        from docpipe.core.operators.ingest.ingest_source import MicrosoftGraphLoader

        rest_client = Mock()
        rest_client.call_rest_json.side_effect = [
            {
                "value": [
                    {"id": "folder1", "folder": {}},
                    {"id": "file1", "name": "doc1.txt"},
                ],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/drives/drive1/root/children?$skiptoken=abc",
            },
            {
                "value": [{"id": "file2", "name": "doc2.txt"}],
            },
            {
                "value": [{"id": "nested", "name": "nested.txt"}],
            },
        ]
        mock_rest_client_cls.return_value = rest_client

        loader = MicrosoftGraphLoader(
            drive_id="drive1",
            client_id="client",
            client_secret="secret",  # pragma: allowlist secret
            tenant_id="tenant",
            recursive=True,
        )
        loader._token = "token"

        files = loader._list_files()

        assert [item["id"] for item in files] == ["file1", "file2", "nested"]

    @patch("docpipe.core.operators.ingest.ingest_source.RestClient")
    def test_lazy_load_yields_error_document_on_download_failure(self, mock_rest_client_cls):
        from docpipe.core.operators.ingest.ingest_source import MicrosoftGraphLoader

        rest_client = Mock()
        mock_rest_client_cls.return_value = rest_client

        loader = MicrosoftGraphLoader(
            drive_id="drive1",
            client_id="client",
            client_secret="secret",  # pragma: allowlist secret
            tenant_id="tenant",
        )
        loader._token = "token"
        loader._list_files = Mock(return_value=[{"id": "file1", "name": "doc1.txt"}])
        loader._download_file = Mock(side_effect=RuntimeError("download failed"))

        docs = list(loader.lazy_load())

        assert len(docs) == 1
        assert docs[0].metadata["error"] == "download failed"
        assert docs[0].metadata["item_id"] == "file1"


class TestIngestSourceOperatorAdditionalCoverage:
    def _make_operator(self, **overrides):
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "custom",
            "provider_config": {"loader_class_path": "pkg.Loader"},
        }
        config.update(overrides)
        return IngestSourceOperator(config)

    def test_validate_appends_adapter_validation_messages(self):
        operator = self._make_operator(provider="onedrive")
        errors: list[str] = []
        warnings: list[str] = []

        with patch.object(operator, "_build_adapter_config", side_effect=ValueError("validation error: bad field")):
            operator.validate(errors=errors, warnings=warnings, available_features=[])

        assert "Configuration validation failed" in errors[0]

        errors.clear()
        with patch.object(operator, "_build_adapter_config", side_effect=RuntimeError("bad config")):
            operator.validate(errors=errors, warnings=warnings, available_features=[])

        assert "Invalid configuration" in errors[0]

    def test_validate_extensions_rejects_unsupported_filters(self):
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        with pytest.raises(ValueError, match="Unsupported file extensions in include_filter"):
            IngestSourceOperator(
                {
                    "provider": "custom",
                    "provider_config": {"loader_class_path": "pkg.Loader"},
                    "include_filter": ".unsupported",
                }
            )

        with pytest.raises(ValueError, match="Unsupported file extensions in exclude_filter"):
            IngestSourceOperator(
                {
                    "provider": "custom",
                    "provider_config": {"loader_class_path": "pkg.Loader"},
                    "exclude_filter": ".unsupported",
                }
            )

    def test_process_document_handles_excluded_and_previously_processed(self):
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        operator = IngestSourceOperator(
            {
                "provider": "custom",
                "provider_config": {"loader_class_path": "pkg.Loader"},
                "include_filter": ".txt",
                "exclude_filter": ".pdf",
            }
        )
        metadata = operator.create_base_metadata(total_docs_count=1)
        excluded_doc = Document(page_content="", metadata={"source": "file.pdf", "name": "file.pdf"})

        assert operator.process_document(excluded_doc, 0, metadata) is None
        assert metadata["skipped_docs_count"] == 1

        operator.previously_processed_docs_dict = {"dummy": {}}
        processed_metadata = operator.create_base_metadata(total_docs_count=1)
        already_done_doc = Document(
            page_content="",
            metadata={
                "source": "file.txt",
                "name": "file.txt",
                "last_modified": datetime(2024, 1, 1, tzinfo=UTC).isoformat(),
            },
        )

        with patch(
            "docpipe.core.operators.ingest.ingest_source.is_doc_previously_processed",
            return_value=True,
        ):
            assert operator.process_document(already_done_doc, 1, processed_metadata) is None

        assert processed_metadata["skipped_docs_count"] == 1

    def test_process_document_handles_processing_exception(self):

        operator = self._make_operator(include_filter=".txt")
        metadata = operator.create_base_metadata(total_docs_count=1)

        class BrokenMetadata:
            def __init__(self):
                self.failed = False

            def get(self, key, default=None):
                if key == "source":
                    return "file.txt"
                if not self.failed:
                    self.failed = True
                    raise RuntimeError("boom")
                return default

        doc = Mock()
        doc.metadata = BrokenMetadata()

        assert operator.process_document(doc, 2, metadata) is None
        assert metadata["failed_docs_count"] == 1

    def test_is_hidden_path_detects_hidden_components(self):
        operator = self._make_operator()

        assert operator._is_hidden_path("a/.hidden/file.txt") is True
        assert operator._is_hidden_path("a/visible/file.txt") is False

    def test_process_documents_non_adapter_loader_batches_results(self):
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        operator = IngestSourceOperator(
            {
                "provider": "custom",
                "provider_config": {"loader_class_path": "pkg.Loader"},
                "max_files": 2,
                "include_filter": ".txt",
            }
        )
        metadata = operator.create_base_metadata(total_docs_count=0)
        loader = Mock()
        loader.lazy_load.return_value = iter(
            [
                Document(page_content="", metadata={"source": "a.txt", "name": "a.txt"}),
                Document(page_content="", metadata={"source": "b.txt", "name": "b.txt"}),
                Document(page_content="", metadata={"source": "c.txt", "name": "c.txt"}),
            ]
        )

        with patch.object(operator, "_get_loader", return_value=loader):
            result = operator.process_documents(metadata)

        assert len(result) == 2
        assert [item["name"] for item in result] == ["a.txt", "b.txt"]

    def test_process_documents_records_loader_errors(self):
        operator = self._make_operator()
        metadata = operator.create_base_metadata(total_docs_count=0)

        with patch.object(operator, "_get_loader", side_effect=RuntimeError("loader failed")):
            result = operator.process_documents(metadata)

        assert result == []
        assert metadata["failed_docs_count"] == 1

    def test_process_documents_from_adapter_processes_final_batch(self):
        operator = self._make_operator(provider="google_drive", max_files=5, include_filter=".txt")
        metadata = operator.create_base_metadata(total_docs_count=0)
        from docpipe.core.operators.ingest.domain.models import Document as DomainDocument

        domain_docs = [
            DomainDocument(
                id="1",
                name="a.txt",
                content=b"a",
                source_url="https://example/a.txt",
                modified_time=datetime(2024, 1, 1, tzinfo=UTC),
                mimetype="text/plain",
                size=10,
                extension=".txt",
                metadata={"tag": "a"},
            ),
            DomainDocument(
                id="2",
                name="b.txt",
                content=b"b",
                source_url="https://example/b.txt",
                modified_time=datetime(2024, 1, 2, tzinfo=UTC),
                mimetype="text/plain",
                size=20,
                extension=".txt",
                metadata={"tag": "b"},
            ),
        ]

        async def fetch_documents(_config):
            for doc in domain_docs:
                yield doc

        adapter = Mock()
        adapter.fetch_documents = fetch_documents

        with patch.object(operator, "_build_adapter_config", return_value=(adapter, Mock())):
            result = operator._process_documents_from_adapter(metadata)

        assert len(result) == 2
        assert [item["name"] for item in result] == ["a.txt", "b.txt"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestValidateExtensions:
    """Tests for _validate_extensions — covers lines 363-378."""

    def test_invalid_include_extension_raises(self):
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        with pytest.raises(ValueError, match="Unsupported file extensions in include_filter"):
            IngestSourceOperator(
                {
                    "provider": "s3",
                    "connection_params": {"bucket": "b"},
                    "credentials": {},
                    "include_filter": ".xyz_unsupported_ext",
                }
            )

    def test_invalid_exclude_extension_raises(self):
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        with pytest.raises(ValueError, match="Unsupported file extensions in exclude_filter"):
            IngestSourceOperator(
                {
                    "provider": "s3",
                    "connection_params": {"bucket": "b"},
                    "credentials": {},
                    "exclude_filter": ".xyz_unsupported_ext",
                }
            )


class TestIsHiddenPath:
    """Tests for _is_hidden_path — covers lines 825-828."""

    def _operator(self):
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        return IngestSourceOperator({"provider": "s3", "connection_params": {"bucket": "b"}, "credentials": {}})

    def test_hidden_component_is_hidden(self):
        assert self._operator()._is_hidden_path("docs/.hidden/file.pdf") is True

    def test_no_hidden_component_is_not_hidden(self):
        assert self._operator()._is_hidden_path("docs/public/file.pdf") is False


class TestProcessDocumentStringModifiedTime:
    """Cover the modified_time string-parsing branch (lines 755-762)."""

    def test_iso_string_modified_time_parsed(self):
        from langchain_core.documents import Document

        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        operator = IngestSourceOperator({"provider": "s3", "connection_params": {"bucket": "b"}, "credentials": {}})
        metadata = operator.create_base_metadata(total_docs_count=1)

        doc = Document(
            page_content="",
            metadata={
                "source": "file.pdf",
                "name": "file.pdf",
                "last_modified": "2024-01-15T12:00:00Z",
            },
        )

        result = operator.process_document(doc, 0, metadata)
        assert result is not None
        # modified_time should have been parsed from string to int
        assert isinstance(result["modified_time"], int)
        assert result["modified_time"] > 0

    def test_unparseable_modified_time_defaults_to_zero(self):
        from langchain_core.documents import Document

        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        operator = IngestSourceOperator({"provider": "s3", "connection_params": {"bucket": "b"}, "credentials": {}})
        metadata = operator.create_base_metadata(total_docs_count=1)

        doc = Document(
            page_content="",
            metadata={
                "source": "file.pdf",
                "name": "file.pdf",
                "last_modified": "not-a-date",
            },
        )

        result = operator.process_document(doc, 0, metadata)
        assert result is not None
        assert result["modified_time"] == 0


class TestProcessDocumentsCustomLoader:
    """Cover the non-adapter (custom loader) code path in process_documents."""

    @patch("docpipe.core.incremental_metadata.get_incremental_update_service")
    def test_process_documents_via_custom_loader(self, mock_get_service):
        from unittest.mock import patch as _patch

        from langchain_core.documents import Document

        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        mock_service = MagicMock()
        mock_service.get_all_processed_docs.return_value = {}
        mock_get_service.return_value = mock_service

        operator = IngestSourceOperator(
            {
                "provider": "custom",
                "connection_params": {"loader_class_path": "fake.Loader"},
                "credentials": {},
                "force_ingest": True,
            }
        )

        mock_loader = MagicMock()
        mock_loader.lazy_load.return_value = iter(
            [
                Document(page_content="", metadata={"source": "doc.pdf", "name": "doc.pdf"}),
            ]
        )

        with _patch.object(operator, "_get_loader", return_value=mock_loader):
            doc_data = operator.process_documents({})

        assert len(doc_data) == 1
        assert doc_data[0]["name"] == "doc.pdf"


# ---------------------------------------------------------------------------
# MicrosoftGraphLoader tests — covers lines 56-227
# ---------------------------------------------------------------------------


class TestMicrosoftGraphLoaderInit:
    def _make_loader(self, folder_path=None):
        from docpipe.core.operators.ingest.ingest_source import MicrosoftGraphLoader

        return MicrosoftGraphLoader(
            drive_id="drive-1",
            client_id="client-1",
            client_secret="secret",  # pragma: allowlist secret
            tenant_id="tenant-1",
            folder_path=folder_path,
            recursive=True,
        )

    def test_init_stores_params(self):
        loader = self._make_loader()
        assert loader.drive_id == "drive-1"
        assert loader.client_id == "client-1"
        assert loader.recursive is True
        assert loader._token is None

    @patch("msal.ConfidentialClientApplication")
    def test_get_token_success(self, mock_msal_cls):
        loader = self._make_loader()
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "tok123"}
        mock_msal_cls.return_value = mock_app

        token = loader._get_token()

        assert token == "tok123"
        assert loader._token == "tok123"  # cached

    @patch("msal.ConfidentialClientApplication")
    def test_get_token_returns_cached(self, mock_msal_cls):
        loader = self._make_loader()
        loader._token = "cached-tok"

        token = loader._get_token()

        assert token == "cached-tok"
        mock_msal_cls.assert_not_called()

    @patch("msal.ConfidentialClientApplication")
    def test_get_token_missing_access_token_raises(self, mock_msal_cls):
        loader = self._make_loader()
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"error": "invalid_client"}
        mock_msal_cls.return_value = mock_app

        with pytest.raises(ValueError, match="Failed to acquire Microsoft Graph token"):
            loader._get_token()

    def test_list_files_no_folder(self):
        loader = self._make_loader()
        loader._token = "tok"
        loader._rest_client = MagicMock()
        loader._rest_client.call_rest_json.return_value = {
            "value": [
                {"name": "file.pdf", "id": "f1", "size": 100},
            ]
        }

        files = loader._list_files()

        assert len(files) == 1
        assert files[0]["name"] == "file.pdf"

    def test_list_files_with_folder_item_id(self):
        loader = self._make_loader()
        loader._token = "tok"
        loader._rest_client = MagicMock()
        loader._rest_client.call_rest_json.return_value = {"value": []}

        files = loader._list_files(folder_item_id="folder-123")

        assert files == []
        call_url = loader._rest_client.call_rest_json.call_args.kwargs["url"]
        assert "folder-123" in call_url

    def test_list_files_recursive_subfolder(self):
        loader = self._make_loader()
        loader._token = "tok"
        loader._rest_client = MagicMock()
        # First call returns a folder item; second call returns a real file
        loader._rest_client.call_rest_json.side_effect = [
            {"value": [{"folder": {}, "id": "sub1", "name": "subfolder"}]},
            {"value": [{"name": "nested.pdf", "id": "n1", "size": 50}]},
        ]

        files = loader._list_files()

        assert len(files) == 1
        assert files[0]["name"] == "nested.pdf"

    def test_list_files_pagination(self):
        loader = self._make_loader()
        loader._token = "tok"
        loader._rest_client = MagicMock()
        loader._rest_client.call_rest_json.side_effect = [
            {
                "value": [{"name": "page1.pdf", "id": "p1"}],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/drives/drive-1/root/children?$skiptoken=xxx",
            },
            {"value": [{"name": "page2.pdf", "id": "p2"}]},
        ]

        files = loader._list_files()

        assert len(files) == 2

    def test_download_file_with_direct_url(self):
        loader = self._make_loader()
        loader._token = "tok"
        mock_response = MagicMock()
        mock_response.content = b"pdf bytes"

        # _download_file now uses self._download_client (created once in __init__),
        # so patch the instance attribute directly instead of the class constructor.
        loader._download_client = MagicMock()
        loader._download_client.call_rest.return_value = mock_response

        result = loader._download_file({"@microsoft.graph.downloadUrl": "https://cdn.example.com/file.pdf"})

        assert result == b"pdf bytes"

    def test_download_file_without_direct_url(self):
        loader = self._make_loader()
        loader._token = "tok"
        loader._rest_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = b"fallback bytes"
        loader._rest_client.call_rest.return_value = mock_response

        result = loader._download_file({"id": "item-1"})

        assert result == b"fallback bytes"

    def test_load_returns_list_of_documents(self):
        loader = self._make_loader()
        loader._token = "tok"
        loader._rest_client = MagicMock()
        loader._rest_client.call_rest_json.return_value = {"value": [{"name": "doc.pdf", "id": "d1", "size": 10}]}
        mock_response = MagicMock()
        mock_response.content = b"content"
        loader._rest_client.call_rest.return_value = mock_response

        docs = loader.load()

        assert len(docs) == 1

    def test_lazy_load_with_folder_path(self):
        loader = self._make_loader(folder_path="/Documents/Reports")
        loader._token = "tok"
        loader._rest_client = MagicMock()
        # First call: resolve folder path
        loader._rest_client.call_rest_json.side_effect = [
            {"id": "folder-id-resolved"},  # folder path resolution
            {"value": []},  # list files in resolved folder
        ]

        docs = list(loader.lazy_load())

        assert docs == []

    def test_lazy_load_file_download_error_yields_error_doc(self):
        loader = self._make_loader()
        loader._token = "tok"
        loader._rest_client = MagicMock()
        loader._rest_client.call_rest_json.return_value = {"value": [{"name": "bad.pdf", "id": "b1"}]}

        with patch.object(loader, "_download_file", side_effect=Exception("download failed")):
            docs = list(loader.lazy_load())

        assert len(docs) == 1
        assert docs[0].metadata.get("error") == "download failed"


class TestIngestSourceValidateErrors:
    """Tests for validate() error branches in IngestSourceOperator — covers lines 291-303."""

    def test_validate_non_pydantic_error_appended(self):
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        config = {
            "provider": "filesystem",
            "connection_params": {},
            "credentials": {},
            "validating_flow": True,
        }
        operator = IngestSourceOperator(config)
        errors: list = []
        warnings: list = []

        with patch.object(operator, "_build_adapter_config", side_effect=RuntimeError("bad config")):
            operator.validate(errors=errors, warnings=warnings, available_features=[])

        assert any("Invalid configuration" in str(e) for e in errors)


class TestMicrosoftGraphLoaderLazyLoad:
    """Tests for MicrosoftGraphLoader.lazy_load covering lines 56-228."""

    def _make_loader(self, *, folder_path=None, recursive=True):
        from docpipe.core.operators.ingest.ingest_source import MicrosoftGraphLoader

        with (
            patch("docpipe.core.operators.ingest.ingest_source.RestClient"),
            patch("docpipe.core.operators.ingest.ingest_source.RestClientConfig"),
        ):
            return MicrosoftGraphLoader(
                drive_id="drive-id",
                client_id="client-id",
                client_secret="client-secret",  # pragma: allowlist secret
                tenant_id="tenant-id",
                folder_path=folder_path,
                recursive=recursive,
            )

    def test_init_sets_attributes(self):
        """Covers lines 56-72."""
        loader = self._make_loader()
        assert loader.drive_id == "drive-id"
        assert loader.client_id == "client-id"
        assert loader.tenant_id == "tenant-id"
        assert loader._token is None

    def test_get_token_raises_on_missing_msal(self):
        """Covers lines 79-81: ImportError branch."""
        loader = self._make_loader()
        with patch.dict("sys.modules", {"msal": None}):
            with pytest.raises(ImportError, match="msal"):
                loader._get_token()

    def test_get_token_returns_cached(self):
        """Covers line 76-77: cached token branch."""
        loader = self._make_loader()
        loader._token = "cached-token"
        result = loader._get_token()
        assert result == "cached-token"

    def test_get_token_raises_on_empty_access_token(self):
        """Covers lines 92-96: no access_token in result."""
        loader = self._make_loader()
        mock_msal = MagicMock()
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"error": "invalid_client", "error_description": "bad creds"}
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        with patch.dict("sys.modules", {"msal": mock_msal}):
            with pytest.raises(ValueError, match="Failed to acquire"):
                loader._get_token()

    def test_get_token_raises_on_non_dict_response(self):
        """Covers lines 89-90: non-dict response."""
        loader = self._make_loader()
        mock_msal = MagicMock()
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = "bad_response"
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        with patch.dict("sys.modules", {"msal": mock_msal}):
            with pytest.raises(TypeError):
                loader._get_token()

    def test_get_token_stores_and_returns(self):
        """Covers lines 98-99: success path stores token."""
        loader = self._make_loader()
        mock_msal = MagicMock()
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "my-token"}
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        with patch.dict("sys.modules", {"msal": mock_msal}):
            result = loader._get_token()
        assert result == "my-token"
        assert loader._token == "my-token"

    def test_list_files_no_folder(self):
        """Covers lines 101-135: _list_files without folder, no pagination."""
        loader = self._make_loader()
        loader._token = "tok"
        with patch.object(loader, "_get_token", return_value="tok"):
            loader._rest_client = MagicMock()
            loader._rest_client.call_rest_json.return_value = {"value": [{"name": "file.pdf", "id": "f1"}]}
            files = loader._list_files()
        assert len(files) == 1
        assert files[0]["name"] == "file.pdf"

    def test_list_files_with_folder_recursive(self):
        """Covers lines 106-107 + 121-123: folder path + recursive subfolder."""
        loader = self._make_loader(recursive=True)
        loader._token = "tok"
        with patch.object(loader, "_get_token", return_value="tok"):
            loader._rest_client = MagicMock()
            # First call: returns a folder + file, second call (recursive): returns a file
            loader._rest_client.call_rest_json.side_effect = [
                {"value": [{"folder": {}, "id": "subfolder1"}, {"name": "file.pdf", "id": "f2"}]},
                {"value": [{"name": "nested.pdf", "id": "f3"}]},
            ]
            files = loader._list_files(folder_item_id="folder-id")
        assert len(files) == 2

    def test_list_files_with_pagination(self):
        """Covers lines 128-133: @odata.nextLink pagination."""
        loader = self._make_loader()
        with patch.object(loader, "_get_token", return_value="tok"):
            loader._rest_client = MagicMock()
            loader._rest_client.call_rest_json.side_effect = [
                {
                    "value": [{"name": "p1.pdf", "id": "f1"}],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/drives/drive-id/root/children?$skip=1",
                },
                {"value": [{"name": "p2.pdf", "id": "f2"}]},
            ]
            files = loader._list_files()
        assert len(files) == 2

    def test_download_file_with_direct_url(self):
        """Covers lines 156-167: download via direct download URL."""
        loader = self._make_loader()
        # _download_file uses self._download_client (created once in __init__).
        # Patch the instance attribute directly — patching the class constructor
        # no longer has any effect on an already-constructed loader.
        mock_download_client = MagicMock()
        mock_download_client.call_rest.return_value.content = b"file bytes"
        loader._download_client = mock_download_client

        with patch.object(loader, "_get_token", return_value="tok"):
            result = loader._download_file(
                {"@microsoft.graph.downloadUrl": "https://download.example.com/file.pdf", "id": "f1"}
            )
        assert result == b"file bytes"

    def test_download_file_fallback_endpoint(self):
        """Covers lines 143-152: no downloadUrl, fallback via API."""
        loader = self._make_loader()
        with patch.object(loader, "_get_token", return_value="tok"):
            loader._rest_client = MagicMock()
            loader._rest_client.call_rest.return_value.content = b"api bytes"
            result = loader._download_file({"id": "f1"})
        assert result == b"api bytes"

    def test_load_returns_list(self):
        """Covers lines 226-228: load() wraps lazy_load()."""
        loader = self._make_loader()
        with patch.object(loader, "lazy_load", return_value=iter([])):
            result = loader.load()
        assert result == []

    def test_lazy_load_yields_document(self):
        """Covers lines 169-210: lazy_load happy path without folder."""
        loader = self._make_loader()
        with (
            patch.object(loader, "_get_token", return_value="tok"),
            patch.object(loader, "_list_files", return_value=[{"name": "f.pdf", "id": "f1", "size": 100}]),
            patch.object(loader, "_download_file", return_value=b"content"),
        ):
            docs = list(loader.lazy_load())
        assert len(docs) == 1
        assert docs[0].metadata["source"] == "f.pdf"

    def test_lazy_load_handles_download_error(self):
        """Covers lines 211-224: download error yields error document."""
        loader = self._make_loader()
        with (
            patch.object(loader, "_get_token", return_value="tok"),
            patch.object(loader, "_list_files", return_value=[{"name": "bad.pdf", "id": "f1", "size": 100}]),
            patch.object(loader, "_download_file", side_effect=RuntimeError("timeout")),
        ):
            docs = list(loader.lazy_load())
        assert len(docs) == 1
        assert "error" in docs[0].metadata

    def test_lazy_load_with_folder_path(self):
        """Covers lines 172-188: folder_path resolution."""
        from docpipe.core.operators.ingest.ingest_source import MicrosoftGraphLoader

        with (
            patch("docpipe.core.operators.ingest.ingest_source.RestClient"),
            patch("docpipe.core.operators.ingest.ingest_source.RestClientConfig"),
        ):
            loader = MicrosoftGraphLoader(
                drive_id="d1",
                client_id="c1",
                client_secret="cs",  # pragma: allowlist secret
                tenant_id="t1",
                folder_path="/docs",
            )
        with (
            patch.object(loader, "_get_token", return_value="tok"),
            patch.object(loader, "_list_files", return_value=[]),
            patch.object(loader._rest_client, "call_rest_json", return_value={"id": "folder-item-id"}),
        ):
            docs = list(loader.lazy_load())
        assert docs == []

    def test_lazy_load_folder_path_not_found_raises(self):
        """Covers lines 187-188: folder path not found -> ValueError."""
        from docpipe.core.operators.ingest.ingest_source import MicrosoftGraphLoader

        with (
            patch("docpipe.core.operators.ingest.ingest_source.RestClient"),
            patch("docpipe.core.operators.ingest.ingest_source.RestClientConfig"),
        ):
            loader = MicrosoftGraphLoader(
                drive_id="d1",
                client_id="c1",
                client_secret="cs",  # pragma: allowlist secret
                tenant_id="t1",
                folder_path="/nonexistent",
            )
        with (
            patch.object(loader, "_get_token", return_value="tok"),
            patch.object(loader._rest_client, "call_rest_json", side_effect=RuntimeError("not found")),
        ):
            with pytest.raises(ValueError, match="not found"):
                list(loader.lazy_load())


@pytest.mark.parametrize("running_loop", [False, True])
def test_async_runner_preserves_original_runtime_error(*, running_loop):
    """Adapter RuntimeErrors must propagate without retrying a consumed coroutine."""
    import asyncio

    from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

    operator = IngestSourceOperator({"provider": "filesystem"})
    failure = RuntimeError("adapter connection failed")
    calls = []

    async def fail():
        calls.append(True)
        raise failure

    def run():
        with pytest.raises(RuntimeError) as exc:
            operator._run_async_generator_in_sync_context(fail())
        assert exc.value is failure

    async def run_with_loop():
        run()

    if running_loop:
        asyncio.run(run_with_loop())
    else:
        run()
    assert calls == [True]


@pytest.mark.asyncio
async def test_adapter_error_in_running_loop_is_recorded():
    """Transform records the original adapter error even inside an event loop."""
    from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

    operator = IngestSourceOperator({"provider": "filesystem", "force_ingest": True})
    adapter = Mock()

    async def fetch_documents(config):
        raise RuntimeError("adapter connection failed")
        yield  # pragma: no cover

    adapter.fetch_documents = fetch_documents
    with (
        patch.object(operator, "_build_adapter_config", return_value=(adapter, Mock())),
        patch.object(operator, "record_failed_document", wraps=operator.record_failed_document) as record,
    ):
        tables, metadata = operator.transform(None)

    assert tables[0].num_rows == 0
    assert metadata["node_status"] == "Failed"
    assert metadata["failed_docs_count"] == 1
    assert "adapter connection failed" in record.call_args.kwargs["reason"]


@pytest.mark.parametrize("provider", ["custom", "filesystem"])
def test_batches_skip_filtered_documents_and_stop_at_limit(*, provider):
    """Both ingestion paths count accepted documents and preserve global indexes."""
    from docpipe.core.operators.ingest.domain.models import Document as DomainDocument
    from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

    operator = IngestSourceOperator({"provider": provider, "include_filter": ".txt", "max_files": 2})
    names = ["skip.pdf", "first.txt", "second.txt", "extra.txt", "unfetched.txt"]
    metadata = operator.create_base_metadata(total_docs_count=0)
    loader = Mock()
    loader.lazy_load.return_value = iter(Document(page_content="", metadata={"source": name}) for name in names)
    fetched = []

    async def fetch_documents(config):
        for name in names:
            fetched.append(name)
            yield DomainDocument(id=name, name=name, content=b"", source_url=name, extension=name.split(".")[-1])

    adapter = Mock()
    adapter.fetch_documents = fetch_documents
    with (
        patch.object(operator, "_get_loader", return_value=loader),
        patch.object(operator, "_build_adapter_config", return_value=(adapter, Mock())),
        patch.object(operator, "process_document", wraps=operator.process_document) as process,
    ):
        result = operator.process_documents(metadata)

    assert [doc["name"] for doc in result] == ["first.txt", "second.txt"]
    assert metadata["skipped_docs_count"] == 1
    assert [call.args[1] for call in process.call_args_list] == [0, 1, 2]
    if provider == "filesystem":
        assert fetched == names[:4]


def test_float_timestamp_does_not_skip_a_changed_document():
    """Custom loaders may return timestamp() floats for incremental comparisons."""
    import hashlib

    from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

    operator = IngestSourceOperator({"provider": "custom", "include_filter": ".txt"})
    source = "changed.txt"
    doc_id = hashlib.md5(source.encode(), usedforsecurity=False).hexdigest()
    operator.previously_processed_docs_dict = {doc_id: {"modified_time": 100}}
    metadata = operator.create_base_metadata(total_docs_count=0)
    document = Document(page_content="", metadata={"source": source, "last_modified": 100.5})

    result = operator.process_document(document, 0, metadata)

    assert result is not None
    assert metadata["skipped_docs_count"] == 0
    # Preserve the existing integer-only output schema for custom loader metadata.
    assert result["modified_time"] == 0
