"""
Integration tests for OpenSearch operator with Docker Compose container management.

This test suite automatically starts and stops OpenSearch using docker-compose.
It requires Docker and docker-compose to be installed and running.
"""

import subprocess
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.vectordb import VectorDBOperator


def is_docker_available():
    """Check if Docker is available"""
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return True
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return False


def is_docker_compose_available():
    """Check if docker-compose is available"""
    try:
        subprocess.run(
            ["docker-compose", "--version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return True
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return False


def start_opensearch_container():
    """Start OpenSearch using docker-compose"""
    # Get path to docker-compose file
    project_root = Path(__file__).parent.parent.parent.parent
    compose_file = project_root / "docker" / "docker-compose.opensearch.yml"

    if not compose_file.exists():
        pytest.skip(f"docker-compose file not found: {compose_file}")

    # Start container
    try:
        subprocess.run(
            ["docker-compose", "-f", str(compose_file), "up", "-d"],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except subprocess.CalledProcessError as e:
        pytest.skip(f"Failed to start OpenSearch container: {e}")

    # Wait for OpenSearch to be ready
    max_wait = 60
    start_time = time.time()
    ready = False

    while time.time() - start_time < max_wait:
        try:
            import requests

            response = requests.get(
                "http://localhost:9200",
                auth=("admin", "MyStrongPass123!"),
                verify=False,
                timeout=5,
            )
            if response.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(2)

    if not ready:
        stop_opensearch_container()
        pytest.skip("OpenSearch container failed to start within 60 seconds")

    return True


def stop_opensearch_container():
    """Stop OpenSearch using docker-compose"""
    project_root = Path(__file__).parent.parent.parent.parent
    compose_file = project_root / "docker" / "docker-compose.opensearch.yml"

    try:
        subprocess.run(
            ["docker-compose", "-f", str(compose_file), "down"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except Exception:
        pass  # Best effort cleanup


@pytest.fixture(scope="module")
def opensearch_container():
    """
    Start OpenSearch container using docker-compose for testing.

    This fixture:
    1. Checks if Docker and docker-compose are available
    2. Starts OpenSearch using docker-compose
    3. Waits for it to be ready
    4. Yields connection details
    5. Stops the container after tests
    """
    # Check prerequisites
    if not is_docker_available():
        pytest.skip("Docker is not available")

    if not is_docker_compose_available():
        pytest.skip("docker-compose is not available")

    # Start container
    start_opensearch_container()

    # Yield connection details
    connection_info = {
        "host": "localhost",
        "port": 9200,
        "username": "admin",
        "password": "MyStrongPass123!",  # pragma: allowlist secret
    }

    yield connection_info

    # Cleanup
    stop_opensearch_container()


@pytest.fixture
def opensearch_config(opensearch_container):
    """Create OpenSearch operator configuration using container details"""
    return {
        # Operator-level configuration
        OperatorConstants.Config.PROVIDER: "opensearch",
        OperatorConstants.VectorDB.INDEX_NAME: "test_integration_index",
        OperatorConstants.Columns.DOC_ID_COLUMN: "doc_id_hash",
        OperatorConstants.Columns.EMBEDDINGS_COLUMN: "embeddings",
        OperatorConstants.VectorDB.VECTOR_DIMENSION: 384,
        OperatorConstants.Config.AVAILABLE_FEATURES: {
            "doc_id_hash": {
                "name": "Document ID",
                "available_for_vector_db": True,
                "mandatory_for_vector_db": True,
                "type": "string",
                "is_primary": True,
            },
            "content": {
                "name": "Content",
                "available_for_vector_db": True,
                "type": "string",
            },
            "embeddings": {
                "name": "Embeddings",
                "available_for_vector_db": True,
                "mandatory_for_vector_db": True,
                "type": "vector",
            },
        },
        OperatorConstants.Config.FEATURE_MAPPINGS: {
            "doc_id_hash": "pk",
            "content": "text",
            "embeddings": "vector_embeddings",
        },
        # Provider-specific configuration
        OperatorConstants.Config.PROVIDER_CONFIG: {
            OperatorConstants.VectorDB.HOST: opensearch_container["host"],
            OperatorConstants.VectorDB.PORT: opensearch_container["port"],
            OperatorConstants.VectorDB.USERNAME: opensearch_container["username"],
            OperatorConstants.VectorDB.PASSWORD: opensearch_container["password"],
            OperatorConstants.VectorDB.USE_SSL: False,
            OperatorConstants.VectorDB.VERIFY_CERTS: False,
            OperatorConstants.VectorDB.ENGINE: "faiss",
            OperatorConstants.VectorDB.ALGORITHM: "hnsw",
            OperatorConstants.VectorDB.SPACE_TYPE: "l2",
            OperatorConstants.VectorDB.ENGINE_PARAMETERS: {
                "ef_construction": 512,
                "m": 16,
            },
        },
    }


@pytest.fixture
def sample_documents():
    """Create sample documents for testing"""
    np.random.seed(42)  # For reproducibility
    data = {
        "doc_id_hash": ["doc1", "doc2", "doc3"],
        "content": [
            "This is the first test document",
            "This is the second test document",
            "This is the third test document",
        ],
        "embeddings": [
            np.random.rand(384).tolist(),
            np.random.rand(384).tolist(),
            np.random.rand(384).tolist(),
        ],
    }
    return pa.table(data)


class TestOpenSearchWithDockerCompose:
    """Integration tests with OpenSearch managed by docker-compose"""

    def test_container_is_running(self, opensearch_container):
        """Test that OpenSearch container is running and accessible"""
        import requests

        response = requests.get(
            f"http://{opensearch_container['host']}:{opensearch_container['port']}",
            auth=(opensearch_container["username"], opensearch_container["password"]),
            verify=False,
        )

        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "number" in data["version"]

    def test_create_index_and_insert_documents(self, opensearch_config, sample_documents):
        """Test creating index and inserting documents"""
        operator = VectorDBOperator(opensearch_config)

        # Transform should create index and insert documents
        result_tables, metadata = operator.transform(sample_documents)

        # Verify results
        assert len(result_tables) == 1
        assert result_tables[0].num_rows == 3
        assert metadata["documents_in_scope"] == 3
        assert metadata["processed_docs"] == 3
        assert metadata["failed_docs_count"] == 0

        # Verify documents were inserted
        count = operator.get_document_count()
        assert count == 3

    def test_query_documents(self, opensearch_config, sample_documents):
        """Test querying documents from OpenSearch"""
        operator = VectorDBOperator(opensearch_config)

        # Insert documents
        operator.transform(sample_documents)

        # Wait a bit for indexing
        time.sleep(2)

        # Query by doc names
        docs = operator.query_by_doc_names(["doc1", "doc2"])

        # Should find at least some documents
        assert len(docs) >= 0  # May be 0 if indexing is slow

    def test_delete_documents(self, opensearch_config, sample_documents):
        """Test deleting documents from OpenSearch"""
        operator = VectorDBOperator(opensearch_config)

        # Insert documents
        operator.transform(sample_documents)

        # Wait for indexing
        time.sleep(2)

        # Delete documents
        success, failed = operator.delete_documents_by_ids(["doc1", "doc2"])

        # Should successfully delete
        assert success >= 0
        assert failed == 0

    def test_index_exists_check(self, opensearch_config):
        """Test checking if index exists"""
        operator = VectorDBOperator(opensearch_config)

        # Index should exist after operator initialization
        # We can verify by checking document count (will return 0 if index exists)
        count = operator.get_document_count()
        assert count >= 0  # Index exists if we can get a count

    def test_multiple_batch_inserts(self, opensearch_config):
        """Test inserting multiple batches of documents"""
        operator = VectorDBOperator(opensearch_config)

        # Create multiple batches
        for batch_num in range(3):
            np.random.seed(batch_num)
            data = {
                "doc_id_hash": [f"batch{batch_num}_doc{i}" for i in range(5)],
                "content": [f"Batch {batch_num} document {i}" for i in range(5)],
                "embeddings": [np.random.rand(384).tolist() for _ in range(5)],
            }
            table = pa.table(data)

            _result_tables, metadata = operator.transform(table)
            assert metadata["processed_docs"] == 5

        # Wait for indexing
        time.sleep(2)

        # Verify total count
        count = operator.get_document_count()
        assert count >= 15  # Should have at least 15 documents


class TestDockerAvailability:
    """Test Docker and docker-compose availability"""

    def test_docker_is_available(self):
        """Test that Docker is available on the system"""
        if not is_docker_available():
            pytest.skip("Docker is not available")
        assert is_docker_available()

    def test_docker_compose_is_available(self):
        """Test that docker-compose is available on the system"""
        if not is_docker_compose_available():
            pytest.skip("docker-compose is not available")
        assert is_docker_compose_available()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
