"""
Pytest configuration and fixtures for docling-pipelines tests.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest


# Centralized path setup - automatically adds backend to Python path
@pytest.fixture(scope="session", autouse=True)
def setup_python_path():
    """
    Automatically setup Python path for all tests.
    This runs once per test session and ensures imports work correctly.
    """
    backend_dir = Path(__file__).parent.parent / "src" / "docpipe_app" / "backend"
    if backend_dir.exists() and str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    yield
    # Cleanup: Remove from path after tests complete
    if str(backend_dir) in sys.path:
        sys.path.remove(str(backend_dir))


# ============================================================================
# Directory Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def src_dir(project_root):
    """Return the src directory."""
    return project_root / "src"


@pytest.fixture(scope="session")
def backend_dir(src_dir):
    """Return the backend directory."""
    return src_dir / "docpipe_app" / "backend"


@pytest.fixture(scope="session")
def tests_dir():
    """Return the tests directory."""
    return Path(__file__).parent


@pytest.fixture(scope="session")
def test_data_dir(tests_dir):
    """Return the path to test fixtures directory."""
    return tests_dir / "fixtures"


@pytest.fixture(scope="session")
def temp_test_dir():
    """Create a temporary directory with test files from fixtures"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        test_dir = Path(tmpdir)

        # Create a text file
        txt_file = test_dir / "test.txt"
        txt_file.write_text("This is a test text file.")

        # Copy a sample PDF from fixtures instead of creating hardcoded content
        fixtures_dir = Path(__file__).parent.parent.parent / "fixtures" / "invoices"
        if fixtures_dir.exists():
            sample_pdfs = list(fixtures_dir.glob("*.pdf"))
            if sample_pdfs:
                # Copy the first PDF to temp directory
                shutil.copy(sample_pdfs[0], test_dir / "test.pdf")

        yield str(test_dir)


@pytest.fixture(scope="session")
def fixtures_invoices_dir(test_data_dir):
    """Return path to invoice fixtures."""
    return test_data_dir / "invoices"


@pytest.fixture(scope="session")
def fixtures_customer_support_dir(test_data_dir):
    """Return path to customer support fixtures."""
    return test_data_dir / "customer_support_docs"


@pytest.fixture(scope="session")
def temp_dir(tmp_path_factory):
    """Create a temporary directory for test outputs."""
    return tmp_path_factory.mktemp("test_outputs")


# ============================================================================
# PyArrow Table Fixtures
# ============================================================================


@pytest.fixture
def sample_pyarrow_table():
    """
    Create a sample PyArrow table for testing.
    Useful for testing operators that expect PyArrow tables as input.
    """
    import pyarrow as pa

    data = {
        "id": ["doc1", "doc2", "doc3"],
        "name": ["file1.txt", "file2.txt", "file3.txt"],
        "content": ["Sample content 1", "Sample content 2", "Sample content 3"],
        "path": ["/path/to/file1.txt", "/path/to/file2.txt", "/path/to/file3.txt"],
    }

    return pa.table(data)


@pytest.fixture
def empty_pyarrow_table():
    """Create an empty PyArrow table for testing edge cases."""
    import pyarrow as pa

    schema = pa.schema(
        [
            ("id", pa.string()),
            ("name", pa.string()),
            ("content", pa.string()),
            ("path", pa.string()),
        ]
    )

    return pa.table({}, schema=schema)


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def sample_pdf_files(fixtures_invoices_dir, tmp_path):
    """
    Return lightweight sample PDF files for tests.

    Copies fixture PDFs into a per-test temporary directory and truncates the
    returned list to a single file to avoid repeated large in-memory payloads
    across extract tests. This preserves the existing single test module while
    reducing memory pressure from Docling-based conversions.
    """
    if not fixtures_invoices_dir.exists():
        pytest.skip(f"Fixtures directory not found: {fixtures_invoices_dir}")

    pdf_files = sorted(fixtures_invoices_dir.glob("*.pdf"))
    if not pdf_files:
        pytest.skip(f"No PDF files found in {fixtures_invoices_dir}")

    selected_files = pdf_files[:1]
    copied_files = []
    for source_file in selected_files:
        target_file = tmp_path / source_file.name
        shutil.copy2(source_file, target_file)
        copied_files.append(target_file)

    return copied_files


@pytest.fixture
def sample_text_files(fixtures_customer_support_dir):
    """
    Return a list of sample text files from fixtures.
    Skips test if no text files are found.
    """
    if not fixtures_customer_support_dir.exists():
        pytest.skip(f"Fixtures directory not found: {fixtures_customer_support_dir}")

    text_files = list(fixtures_customer_support_dir.glob("*.txt"))
    if not text_files:
        pytest.skip(f"No text files found in {fixtures_customer_support_dir}")

    return text_files


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_ollama_client(mocker):
    """
    Mock Ollama client with standard responses.
    Useful for testing embeddings and LLM operations without actual API calls.
    """
    mock_client = mocker.Mock()
    mock_client.embeddings.return_value = {
        "embedding": [0.1] * 384  # Standard embedding dimension
    }
    return mock_client


# ============================================================================
# Configuration Fixtures
# ============================================================================


@pytest.fixture
def basic_operator_config():
    """
    Return a basic operator configuration for testing.
    Can be extended by individual tests.
    """
    return {"max_files": 10, "force_ingest": True}


@pytest.fixture
def temp_duckdb_path(tmp_path):
    """
    Create a temporary DuckDB database path for testing.
    Used for document sets and DuckDB storage tests.
    """
    db_path = tmp_path / "test.duckdb"
    yield str(db_path)
    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def cleanup_test_document_sets():
    """
    Clean up test document sets after each test.
    Only removes document sets with test-related names to avoid deleting user data.
    """
    from pathlib import Path

    import duckdb

    yield  # Run test first

    # Clean up after test
    backend_dir = Path(__file__).parent.parent / "src" / "docpipe_app" / "backend"
    db_path = backend_dir / "document_sets.duckdb"

    if db_path.exists():
        try:
            conn = duckdb.connect(str(db_path))

            # Get all test document sets (those with "Test" in the name)
            result = conn.execute("""
                SELECT id, table_name FROM document_sets
                WHERE name LIKE '%Test%'
            """).fetchall()

            for doc_set_id, table_name in result:
                # Drop the data table
                try:
                    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
                except Exception:
                    pass

                # Delete from metadata table
                try:
                    conn.execute("DELETE FROM document_sets WHERE id = ?", [doc_set_id])
                except Exception:
                    pass

            conn.close()
        except Exception:
            pass  # Ignore errors if database doesn't exist or is locked


# ============================================================================
# Cache Cleanup Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def clear_singleton_caches():
    """
    Clear singleton caches before each test to prevent memory leaks and
    cross-test contamination.

    Resets:
    - LRUCache singleton (prevents OOM in CI from accumulated cache entries)
    - IncrementalMetadataFactory singleton (prevents a factory created in one
      test from leaking its store/service into the next test, and avoids any
      test accidentally triggering a real filesystem or database connection)
    """
    yield  # Run test first

    # Clear LRUCache singleton after each test
    try:
        from docpipe.utils.core.patterns import Singleton
        from docpipe.utils.infrastructure.caching import LRUCache

        if LRUCache in Singleton._instances:
            cache_instance = Singleton._instances[LRUCache]
            if isinstance(cache_instance, LRUCache) and hasattr(cache_instance, "clear"):
                cache_instance.clear()
    except (ImportError, AttributeError, KeyError):
        pass

    # Reset the incremental metadata factory singleton after each test so no
    # test leaks a real store/service into the next one.
    try:
        import docpipe.core.incremental_metadata.adapters.config.incremental_metadata_factory as _inc_factory_mod

        _inc_factory_mod._default_factory = None
    except (ImportError, AttributeError):
        pass

    # Drop the process-wide Docling converter pool so pooled (often mocked)
    # converters/extractors from one test are never reused by the next.
    _pool_mod = sys.modules.get("docpipe.integrations.docling.converter_pool")
    if _pool_mod is not None:
        _pool_mod.reset_docling_pool()


# ============================================================================
# Pytest Hooks for Enhanced Output
# ============================================================================


def pytest_configure(config):
    """
    Configure pytest with custom markers and settings.
    This runs before test collection.
    """
    # Register custom markers
    config.addinivalue_line("markers", "fast: marks tests as fast (< 1 second)")
    config.addinivalue_line("markers", "performance: marks tests as performance tests")


def pytest_collection_modifyitems(config, items):
    """
    Modify test items after collection.
    Automatically adds markers based on test location.
    """
    for item in items:
        # Auto-mark unit tests
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)

        # Auto-mark integration tests: anything under an "integration" directory, or a
        # file with "integration" in its name. Do not match the full path as a
        # substring: that also hits tests/unit/integrations/, and CI's
        # "-m 'unit and not integration'" then silently deselects those unit tests.
        if "integration" in item.path.parent.parts or "integration" in item.path.name:
            item.add_marker(pytest.mark.integration)

        # Auto-mark slow tests based on name
        if "slow" in item.nodeid.lower() or "performance" in item.nodeid.lower():
            item.add_marker(pytest.mark.slow)
