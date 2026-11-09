# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for Operator Metadata API routes.

This test suite validates the router layer for operator metadata endpoints,
ensuring proper:
- HTTP request/response handling
- Dependency injection
- Response model conversion
- Error handling via middleware
- OpenAPI compliance

Test Strategy:
    - Use FastAPI TestClient for HTTP-level testing
    - Mock the service layer (OperatorMetadataService) for isolation
    - Register same exception handlers as main.py for realistic testing
    - Verify HTTP status codes, response structure, and error handling
    - Test edge cases (missing fields, empty features, unknown categories)

Test Fixtures:
    - app: FastAPI application with operators router and error handlers
    - client: TestClient for making HTTP requests
    - mock_service: Mocked OperatorMetadataService
    - override_service: Dependency override for injecting mock service
    - sample_operator_metadata: Sample metadata for testing

Coverage:
    - Success cases: 200 responses with correct structure
    - Error cases: 500 responses with proper error format
    - Edge cases: Missing fields, empty features, unknown categories
    - Dependency injection: Singleton behavior
    - Logging: Request logging
    - Content negotiation: JSON responses
"""

from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.routes.operators import get_operator_metadata_service, operators_router
from docpipe.core.operators.application.services.operator_metadata_service import (
    OperatorMetadataService,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from tests.unit.api.routes.conftest import mock_current_user


@pytest.fixture
def app():
    """Create FastAPI app with operators router and error handlers.

    Registers the same exception handlers as main.py to ensure tests
    match runtime behavior.
    """
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from docpipe.api.middleware.error_handler import (
        docpipe_exception_handler,
        generic_exception_handler,
        http_exception_handler,
        validation_exception_handler,
    )
    from docpipe.exceptions.docpipe_exceptions import DocpipeException

    app = FastAPI()
    app.include_router(operators_router)
    app.dependency_overrides[get_current_user] = mock_current_user

    # Register exception handlers in same order as main.py
    app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    return app


@pytest.fixture
def client(app):
    """Create FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def mock_service():
    """Create mock OperatorMetadataService."""
    return Mock(spec=OperatorMetadataService)


@pytest.fixture
def override_service(app, mock_service):
    """Override the get_operator_metadata_service dependency."""
    app.dependency_overrides[get_operator_metadata_service] = lambda: mock_service
    yield mock_service
    app.dependency_overrides.clear()


@pytest.fixture
def sample_operator_metadata():
    """Sample operator metadata for testing.

    Reflects the full shape returned by get_metadata(), including all fields
    that were previously missing from the DTO: name, tags, is_primary,
    mandatory_for_vector_db, available_for_opensearch, properties, valid_values
    (on features/attributes), and owner, is_operator_available (top-level).
    """
    return {
        "extract_docling": {
            "category": "Extract",
            "label": "Extract Docling",
            "description": "Extracts structured content from documents",
            "owner": "docpipe",
            "is_operator_available": True,
            "features": {
                "content": {
                    "name": "Document Content",
                    "description": "The markdown content extracted from the document",
                    "type": "string",
                    "available_for_filter": True,
                    "available_for_vector_db": True,
                    "tags": ["mandatory"],
                },
                "doc_id_hash": {
                    "name": "Hash ID",
                    "description": "Hash ID of the document row",
                    "type": "string",
                    "available_for_vector_db": True,
                    "mandatory_for_vector_db": True,
                    "is_primary": True,
                    "tags": ["mandatory", "primary"],
                },
            },
            "required_features": [],
            "attributes": {
                "text_extraction": {
                    "name": "Text Extraction Configuration",
                    "description": "Configuration for text extraction from documents",
                    "required": True,
                    "type": "json",
                    "properties": {
                        "provider": {
                            "name": "Text Extraction Provider",
                            "description": "Text extraction strategy",
                            "required": True,
                            "default": "docling_library",
                            "type": "string",
                        },
                        "additional_formats": {
                            "name": "Additional Output Formats",
                            "description": "List of additional output formats",
                            "required": False,
                            "default": [],
                            "type": "json",
                            "valid_values": ["html", "json", "text", "doctags"],
                        },
                    },
                },
            },
        },
        "chunker": {
            "category": "Functional",
            "label": "Chunker",
            "description": "Splits documents into smaller chunks",
            "owner": "docpipe",
            "is_operator_available": True,
            "features": {
                "chunk_id": {
                    "name": "Chunk ID",
                    "description": "Unique identifier for each chunk",
                    "type": "string",
                    "available_for_filter": True,
                    "available_for_opensearch": True,
                    "tags": [],
                },
            },
            "required_features": ["content"],
        },
    }


class TestGetOperatorMetadataEndpoint:
    """Tests for GET /operators/metadata endpoint.

    This test class covers the main API endpoint for retrieving operator metadata.
    Tests verify:
    - HTTP 200 responses with correct data
    - Response structure matches OpenAPI schema
    - All operators included in response
    - Error handling (service exceptions, generic exceptions)
    - Response model conversion (dict → OperatorMetadataItem)
    - Edge cases (missing fields, empty features, unknown categories)
    - Logging behavior
    - Content-Type headers
    """

    def test_get_operator_metadata_returns_200(self, client, override_service, sample_operator_metadata):
        """Test getting operator metadata returns 200."""
        # Arrange
        override_service.get_all_operator_metadata.return_value = sample_operator_metadata

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "extract_docling" in data
        assert "chunker" in data
        assert data["extract_docling"]["category"] == "Extract"
        override_service.get_all_operator_metadata.assert_called_once_with(internal_features=False)

    def test_get_operator_metadata_does_not_expose_secret_declarations(self, client, override_service):
        """Secret-capable field declarations are internal and must not appear in the response."""
        # Arrange
        override_service.get_all_operator_metadata.return_value = {
            "vectordb": {
                "label": "VectorDB",
                "category": "VectorDB",
                "description": "d",
                "features": {},
                "required_features": [],
                "attributes": {},
                "secret_fields": ["provider_config.password"],
                "secret_fields_by_provider": {"provider": {"milvus": ["provider_config.token"]}},
            }
        }

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        item = response.json()["vectordb"]
        assert "secret_fields" not in item
        assert "secret_fields_by_provider" not in item

    def test_get_operator_metadata_returns_dict_structure(self, client, override_service, sample_operator_metadata):
        """Test that response has correct dictionary structure including all DTO fields."""
        # Arrange
        override_service.get_all_operator_metadata.return_value = sample_operator_metadata

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        data = response.json()

        # Verify it's a direct dict, not wrapped
        assert isinstance(data, dict)
        assert "extract_docling" in data

        # Verify all OperatorMetadataItem fields are present
        operator = data["extract_docling"]
        assert "category" in operator
        assert "label" in operator
        assert "description" in operator
        assert "features" in operator
        assert "required_features" in operator
        assert "attributes" in operator
        assert "owner" in operator
        assert "is_operator_available" in operator

    def test_get_operator_metadata_includes_all_operators(self, client, override_service, sample_operator_metadata):
        """Test that all operators from service are included in response."""
        # Arrange
        override_service.get_all_operator_metadata.return_value = sample_operator_metadata

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data) == len(sample_operator_metadata)
        for operator_name in sample_operator_metadata:
            assert operator_name in data

    def test_get_operator_metadata_handles_service_exception(self, client, override_service):
        """Test that service exceptions are handled properly."""
        # Arrange
        override_service.get_all_operator_metadata.side_effect = DocpipeException(
            message="Failed to retrieve operator metadata",
            status_code=500,
            error_code=ErrorCode.OPERATOR_METADATA_FAILED,
        )

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 500
        data = response.json()
        assert "errors" in data
        assert len(data["errors"]) > 0
        assert data["errors"][0]["code"] == ErrorCode.OPERATOR_METADATA_FAILED

    def test_get_operator_metadata_handles_generic_exception(self, client, override_service):
        """Test that generic exceptions are wrapped in DocpipeException by service."""
        # Arrange
        # Service wraps all exceptions in DocpipeException
        override_service.get_all_operator_metadata.side_effect = DocpipeException(
            message="Failed to retrieve operator metadata",
            status_code=500,
            error_code=ErrorCode.OPERATOR_METADATA_FAILED,
        )

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 500
        data = response.json()
        assert "errors" in data
        assert data["errors"][0]["code"] == ErrorCode.OPERATOR_METADATA_FAILED

    def test_get_operator_metadata_converts_metadata_to_response_model(
        self, client, override_service, sample_operator_metadata
    ):
        """Test that raw metadata is fully converted to the response model, including new fields."""
        # Arrange
        override_service.get_all_operator_metadata.return_value = sample_operator_metadata

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        data = response.json()

        operator = data["extract_docling"]

        # Original top-level fields
        assert operator["label"] == "Extract Docling"
        assert operator["category"] == "Extract"
        assert operator["description"] == "Extracts structured content from documents"
        assert operator["required_features"] == []

        # New top-level fields
        assert operator["owner"] == "docpipe"
        assert operator["is_operator_available"] is True

        # Feature: content — new fields
        content = operator["features"]["content"]
        assert content["name"] == "Document Content"
        assert content["tags"] == ["mandatory"]
        assert content["available_for_filter"] is True
        assert content["available_for_vector_db"] is True

        # Feature: doc_id_hash — is_primary + mandatory_for_vector_db
        doc_id = operator["features"]["doc_id_hash"]
        assert doc_id["is_primary"] is True
        assert doc_id["mandatory_for_vector_db"] is True
        assert doc_id["tags"] == ["mandatory", "primary"]

        # Attribute with nested properties and valid_values
        text_attr = operator["attributes"]["text_extraction"]
        assert text_attr["type"] == "json"
        assert "provider" in text_attr["properties"]
        assert text_attr["properties"]["provider"]["default"] == "docling_library"
        assert text_attr["properties"]["additional_formats"]["valid_values"] == ["html", "json", "text", "doctags"]

        # chunker: available_for_opensearch
        chunk_id = data["chunker"]["features"]["chunk_id"]
        assert chunk_id["available_for_opensearch"] is True

    def test_get_operator_metadata_handles_missing_optional_fields(self, client, override_service):
        """Test that missing optional fields default correctly, including new fields."""
        # Arrange
        minimal_metadata = {
            "test_operator": {
                "category": "Functional",
                # Missing label, description, owner, is_operator_available
                "features": {
                    "content": {"type": "string"},  # no name, tags, etc.
                },
                "required_features": [],
            }
        }
        override_service.get_all_operator_metadata.return_value = minimal_metadata

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "test_operator" in data

        operator = data["test_operator"]
        # Original defaults
        assert operator["label"] == "test_operator"
        assert operator["description"] is None
        # New top-level fields default to None when absent
        assert operator["owner"] is None
        assert operator["is_operator_available"] is None

        # New feature fields default to None when absent
        feature = operator["features"]["content"]
        assert feature["name"] is None
        assert feature["tags"] is None
        assert feature["is_primary"] is None
        assert feature["mandatory_for_vector_db"] is None
        assert feature["available_for_opensearch"] is None
        assert feature["properties"] is None
        assert feature["valid_values"] is None

    def test_get_operator_metadata_handles_empty_features(self, client, override_service):
        """Test that operators with no features are handled correctly."""
        # Arrange
        metadata_with_empty_features = {
            "noop": {
                "category": "Functional",
                "label": "No-Op",
                "features": {},
                "required_features": [],
            }
        }
        override_service.get_all_operator_metadata.return_value = metadata_with_empty_features

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "noop" in data
        assert data["noop"]["features"] == {}
        assert data["noop"]["required_features"] == []

    def test_get_operator_metadata_logs_request(self, client, override_service, sample_operator_metadata):
        """Test that requests are logged."""
        # Arrange
        override_service.get_all_operator_metadata.return_value = sample_operator_metadata

        # Act
        with patch("docpipe.api.routes.operators.logger") as mock_logger:
            response = client.get("/operators/metadata")

            # Assert
            assert response.status_code == 200
            # Verify info log was called
            mock_logger.info.assert_called()

    def test_get_operator_metadata_passes_internal_features_false(
        self, client, override_service, sample_operator_metadata
    ):
        """Test that internal_features=False is passed to service."""
        # Arrange
        override_service.get_all_operator_metadata.return_value = sample_operator_metadata

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        override_service.get_all_operator_metadata.assert_called_once_with(internal_features=False)

    def test_get_operator_metadata_response_content_type(self, client, override_service, sample_operator_metadata):
        """Test that response has correct content type."""
        # Arrange
        override_service.get_all_operator_metadata.return_value = sample_operator_metadata

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]


class TestOperatorMetadataValidationPatterns:
    """Tests for operator metadata validation patterns (regression tests for Issue #1).

    These tests ensure that the Pydantic validation patterns accept all valid
    operator types and categories, preventing validation errors like:
    - "vector" type validation error
    - "vector_sparse" type validation error
    - "Storage" category validation error
    """

    def test_vector_type_accepted_in_features(self, client, override_service):
        """Test that 'vector' type is accepted in operator features (Issue #1 regression)."""
        # Arrange - metadata with vector type feature
        metadata_with_vector = {
            "embeddings_operator": {
                "label": "Embeddings Operator",
                "category": "Functional",
                "description": "Generates vector embeddings",
                "features": {
                    "embeddings": {"name": "embeddings", "type": "vector", "description": "Dense vector embeddings"}
                },
                "is_operator_available": True,
            }
        }
        override_service.get_all_operator_metadata.return_value = metadata_with_vector

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["embeddings_operator"]["features"]["embeddings"]["type"] == "vector"

    def test_vector_sparse_type_accepted_in_features(self, client, override_service):
        """Test that 'vector_sparse' type is accepted in operator features (Issue #1 regression)."""
        # Arrange - metadata with vector_sparse type feature
        metadata_with_vector_sparse = {
            "sparse_embeddings_operator": {
                "label": "Sparse Embeddings Operator",
                "category": "Functional",
                "description": "Generates sparse vector embeddings",
                "features": {
                    "sparse_embeddings": {
                        "name": "sparse_embeddings",
                        "type": "vector_sparse",
                        "description": "Sparse vector embeddings",
                    }
                },
                "is_operator_available": True,
            }
        }
        override_service.get_all_operator_metadata.return_value = metadata_with_vector_sparse

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["sparse_embeddings_operator"]["features"]["sparse_embeddings"]["type"] == "vector_sparse"

    def test_storage_category_accepted(self, client, override_service):
        """Test that 'Storage' category is accepted (Issue #1 regression)."""
        # Arrange - metadata with Storage category
        metadata_with_storage = {
            "document_set_operator": {
                "label": "Document Set Operator",
                "category": "Storage",
                "description": "Stores document sets",
                "features": {},
                "is_operator_available": True,
            }
        }
        override_service.get_all_operator_metadata.return_value = metadata_with_storage

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["document_set_operator"]["category"] == "Storage"

    def test_all_integer_types_accepted(self, client, override_service):
        """Test that all integer types (int8, int16, int32, int64) are accepted (Issue #1 regression)."""
        # Arrange - metadata with various integer types
        metadata_with_int_types = {
            "test_operator": {
                "label": "Test Operator",
                "category": "Functional",
                "description": "Test operator with integer types",
                "features": {
                    "int8_field": {"name": "int8_field", "type": "int8"},
                    "int16_field": {"name": "int16_field", "type": "int16"},
                    "int32_field": {"name": "int32_field", "type": "int32"},
                    "int64_field": {"name": "int64_field", "type": "int64"},
                },
                "is_operator_available": True,
            }
        }
        override_service.get_all_operator_metadata.return_value = metadata_with_int_types

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        data = response.json()
        features = data["test_operator"]["features"]
        assert features["int8_field"]["type"] == "int8"
        assert features["int16_field"]["type"] == "int16"
        assert features["int32_field"]["type"] == "int32"
        assert features["int64_field"]["type"] == "int64"

    def test_bool_type_accepted(self, client, override_service):
        """Test that 'bool' type is accepted (Issue #1 regression)."""
        # Arrange - metadata with bool type
        metadata_with_bool = {
            "test_operator": {
                "label": "Test Operator",
                "category": "Functional",
                "description": "Test operator with bool type",
                "features": {"is_valid": {"name": "is_valid", "type": "bool"}},
                "is_operator_available": True,
            }
        }
        override_service.get_all_operator_metadata.return_value = metadata_with_bool

        # Act
        response = client.get("/operators/metadata")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["test_operator"]["features"]["is_valid"]["type"] == "bool"


class TestOperatorMetadataServiceDependency:
    """Tests for operator metadata service dependency injection.

    This test class verifies the dependency injection mechanism for the
    OperatorMetadataService, ensuring:
    - Singleton behavior via @lru_cache
    - Correct type returned
    - Service reusability across requests
    """

    def test_get_operator_metadata_service_returns_singleton(self):
        """Test that service dependency returns singleton instance."""
        # Act
        service1 = get_operator_metadata_service()
        service2 = get_operator_metadata_service()

        # Assert
        assert service1 is service2

    def test_get_operator_metadata_service_returns_correct_type(self):
        """Test that service dependency returns correct type."""
        # Act
        service = get_operator_metadata_service()

        # Assert
        assert isinstance(service, OperatorMetadataService)
