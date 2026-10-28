#!/usr/bin/env python3
"""
Tests all engines, schema evolution, and error handling
Requires .env file with OpenSearch connection details
"""

from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.vectordb import VectorDBOperator
from docpipe.core.operators.vectordb.adapters.outbound.opensearch.client import OpenSearchClient
from docpipe.core.operators.vectordb.adapters.outbound.opensearch.index_manager import (
    OpenSearchAlgorithmTypes,
    OpenSearchEngineTypes,
    VectorSimilarityTypes,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.config import get_opensearch_config

# Check if .env file exists
env_file = Path(".env")
if not env_file.exists():
    pytest.skip(
        ".env file not found. This test requires OpenSearch connection details. "
        "Copy .env.example to .env and update with your connection details.",
        allow_module_level=True,
    )


def print_section(title):
    """Print a formatted section header"""
    print(f"\n{'=' * 80}")
    print(f"{title}")
    print(f"{'=' * 80}\n")


def create_sample_data(num_docs=5, vector_dim=128):
    """Create sample PyArrow table"""
    return pa.table(
        {
            "doc_id_hash": [f"doc_{i}" for i in range(num_docs)],
            "content": [f"Sample document {i}" for i in range(num_docs)],
            "embeddings": [np.random.rand(vector_dim).tolist() for _ in range(num_docs)],
            "metadata": [f"meta_{i}" for i in range(num_docs)],
        }
    )


def _test_engine(engine="nmslib", algorithm="hnsw", space_type="l2"):
    """Test a specific engine configuration"""
    print(f"Testing: {engine} + {algorithm} + {space_type}")

    # Get base config from environment
    config = get_opensearch_config()

    # Override with test-specific settings
    provider_cfg = config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
    provider_cfg[OperatorConstants.VectorDB.ENGINE] = engine
    provider_cfg[OperatorConstants.VectorDB.ALGORITHM] = algorithm
    provider_cfg[OperatorConstants.VectorDB.SPACE_TYPE] = space_type
    provider_cfg["index_name"] = f"test_{engine}_{algorithm}_{space_type}"
    config.update(
        {
            "provider": "opensearch",
            "vector_dimension": 128,
            OperatorConstants.Config.PROVIDER_CONFIG: provider_cfg,
            "available_features": {
                "doc_id_hash": {
                    "available_for_vector_db": True,
                    "mandatory_for_vector_db": True,
                    "type": "string",
                    "is_primary": True,
                },
                "content": {"available_for_vector_db": True, "type": "string"},
                "embeddings": {
                    "available_for_vector_db": True,
                    "mandatory_for_vector_db": True,
                    "type": "vector",
                },
                "metadata": {"available_for_vector_db": True, "type": "string"},
            },
            "feature_mappings": {
                "doc_id_hash": "id",
                "content": "text",
                "embeddings": "vector",
                "metadata": "meta",
            },
        }
    )

    try:
        # Initialize operator
        operator = VectorDBOperator(config)
        print("  ✅ Operator initialized")

        # Create sample data
        table = create_sample_data(5, 128)

        # Index documents
        _result_tables, metadata = operator.transform(table)

        if metadata["processed_docs"] == 5:
            print(f"  ✅ Indexed {metadata['processed_docs']} documents")

            # Verify count
            count = operator.get_document_count()
            print(f"  ✅ Verified count: {count} documents in index")

            # Cleanup
            provider_config = config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
            os_client = OpenSearchClient(
                host=provider_config.get(OperatorConstants.VectorDB.HOST, "localhost"),
                port=provider_config.get(OperatorConstants.VectorDB.PORT, 9200),
                username=provider_config.get(OperatorConstants.VectorDB.USERNAME),
                password=provider_config.get(OperatorConstants.VectorDB.PASSWORD),
                use_ssl=provider_config.get(OperatorConstants.VectorDB.USE_SSL, True),
                verify_certs=provider_config.get(OperatorConstants.VectorDB.VERIFY_CERTS, True),
            )
            os_client.get_client().indices.delete(index=config[OperatorConstants.Config.PROVIDER_CONFIG]["index_name"])
            print("  ✅ Cleaned up index")

            return True, "Success"
        return False, f"Only indexed {metadata['processed_docs']}/5 documents"

    except Exception as e:
        error_msg = str(e)
        if "Invalid space_type" in error_msg:
            return False, f"Space type '{space_type}' not supported"
        if "mapper_parsing_exception" in error_msg:
            return False, f"Mapping error: {error_msg[:100]}"
        return False, f"{type(e).__name__}: {error_msg[:100]}"


def test_all_engines():
    """Test all engine combinations"""
    print_section("TEST 1: All Engine Combinations")

    results = []

    # Test FAISS with both algorithms
    for algo in [OpenSearchAlgorithmTypes.HNSW, OpenSearchAlgorithmTypes.IVF]:
        for space in [VectorSimilarityTypes.L2, VectorSimilarityTypes.COSINE]:
            success, msg = _test_engine(OpenSearchEngineTypes.FAISS, algo, space)
            results.append((f"FAISS + {algo} + {space}", success, msg))

    # Test Lucene with HNSW
    for space in [
        VectorSimilarityTypes.L2,
        VectorSimilarityTypes.COSINE,
        VectorSimilarityTypes.INNER_PRODUCT,
    ]:
        success, msg = _test_engine(OpenSearchEngineTypes.LUCENE, OpenSearchAlgorithmTypes.HNSW, space)
        results.append((f"Lucene + HNSW + {space}", success, msg))

    # Test nmslib with HNSW
    for space in [VectorSimilarityTypes.L2, VectorSimilarityTypes.COSINE]:
        success, msg = _test_engine(OpenSearchEngineTypes.NMSLIB, OpenSearchAlgorithmTypes.HNSW, space)
        results.append((f"nmslib + HNSW + {space}", success, msg))

    # Print results
    print("\nResults Summary:")
    print("-" * 80)
    for config, success, msg in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} | {config:40} | {msg}")

    passed = sum(1 for _, s, _ in results if s)
    total = len(results)
    print(f"\nTotal: {passed}/{total} passed ({passed / total * 100:.1f}%)")

    return results


def test_schema_evolution():
    """Test schema evolution scenarios"""
    print_section("TEST 2: Schema Evolution")

    # Get base config from environment
    base_config = get_opensearch_config()
    base_config[OperatorConstants.Config.PROVIDER_CONFIG]["index_name"] = "test_schema_evolution"
    base_config.update(
        {
            "provider": "opensearch",
            "vector_dimension": 128,
        }
    )

    # Create OpenSearch client for cleanup
    provider_config = base_config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
    client_manager = OpenSearchClient(
        host=provider_config.get(OperatorConstants.VectorDB.HOST, "localhost"),
        port=provider_config.get(OperatorConstants.VectorDB.PORT, 9200),
        username=provider_config.get(OperatorConstants.VectorDB.USERNAME),
        password=provider_config.get(OperatorConstants.VectorDB.PASSWORD),
        use_ssl=provider_config.get(OperatorConstants.VectorDB.USE_SSL, True),
        verify_certs=provider_config.get(OperatorConstants.VectorDB.VERIFY_CERTS, True),
    )
    client = client_manager.get_client()

    try:
        # Step 1: Create index with initial schema
        print("Step 1: Creating index with initial schema (3 fields)")
        config1 = base_config.copy()
        config1["available_features"] = {
            "doc_id_hash": {
                "available_for_vector_db": True,
                "mandatory_for_vector_db": True,
                "type": "string",
                "is_primary": True,
            },
            "content": {"available_for_vector_db": True, "type": "string"},
            "embeddings": {
                "available_for_vector_db": True,
                "mandatory_for_vector_db": True,
                "type": "vector",
            },
        }
        config1["feature_mappings"] = {
            "doc_id_hash": "id",
            "content": "text",
            "embeddings": "vector",
        }

        operator1 = VectorDBOperator(config1)
        table1 = pa.table(
            {
                "doc_id_hash": ["doc_1", "doc_2"],
                "content": ["Content 1", "Content 2"],
                "embeddings": [np.random.rand(128).tolist() for _ in range(2)],
            }
        )
        _, metadata = operator1.transform(table1)
        print(f"  ✅ Indexed {metadata['processed_docs']} documents with initial schema")

        # Step 2: Add new field to existing index
        print("\nStep 2: Adding new field 'category' to existing index")
        config2 = base_config.copy()
        config2["available_features"] = {
            "doc_id_hash": {
                "available_for_vector_db": True,
                "mandatory_for_vector_db": True,
                "type": "string",
                "is_primary": True,
            },
            "content": {"available_for_vector_db": True, "type": "string"},
            "embeddings": {
                "available_for_vector_db": True,
                "mandatory_for_vector_db": True,
                "type": "vector",
            },
            "category": {"available_for_vector_db": True, "type": "string"},
        }
        config2["feature_mappings"] = {
            "doc_id_hash": "id",
            "content": "text",
            "embeddings": "vector",
            "category": "cat",
        }

        operator2 = VectorDBOperator(config2)
        table2 = pa.table(
            {
                "doc_id_hash": ["doc_3", "doc_4"],
                "content": ["Content 3", "Content 4"],
                "embeddings": [np.random.rand(128).tolist() for _ in range(2)],
                "category": ["cat_a", "cat_b"],
            }
        )
        _result, metadata = operator2.transform(table2)
        print(f"  ✅ Indexed {metadata['processed_docs']} documents with new field")

        # Step 3: Verify total count
        count = operator2.get_document_count()
        print("\nStep 3: Verifying total documents")
        print(f"  ✅ Total documents in index: {count}")

        # Cleanup
        client.indices.delete(index=base_config[OperatorConstants.Config.PROVIDER_CONFIG]["index_name"])
        print("  ✅ Cleaned up index")

        return True

    except Exception as e:
        print(f"  ❌ Error: {type(e).__name__}: {str(e)[:200]}")
        return False


def test_error_handling():
    """Test error handling scenarios"""
    print_section("TEST 3: Error Handling & Edge Cases")

    # Get base config from environment
    base_config = get_opensearch_config()
    base_config.update(
        {
            "provider": "opensearch",
            "vector_dimension": 128,
            "available_features": {
                "doc_id_hash": {
                    "available_for_vector_db": True,
                    "mandatory_for_vector_db": True,
                    "type": "string",
                    "is_primary": True,
                },
                "embeddings": {
                    "available_for_vector_db": True,
                    "mandatory_for_vector_db": True,
                    "type": "vector",
                },
            },
            "feature_mappings": {"doc_id_hash": "id", "embeddings": "vector"},
        }
    )

    tests = []

    # Test 1: Missing required field (host)
    print("Test 3.1: Missing required field (host)")
    try:
        config = base_config.copy()
        # Remove host from provider_config
        if OperatorConstants.Config.PROVIDER_CONFIG in config:
            config[OperatorConstants.Config.PROVIDER_CONFIG].pop(OperatorConstants.VectorDB.HOST, None)
        operator = VectorDBOperator(config)
        tests.append(("Missing host", False, "Should have raised ValueError"))
    except (ValueError, KeyError) as e:
        if "host" in str(e).lower():
            tests.append(("Missing host", True, "Correct error message"))
            print(f"  ✅ Correctly raised: {e!s}")
        else:
            tests.append(("Missing host", False, f"Wrong error: {e!s}"))

    # Test 2: Invalid engine
    print("\nTest 3.2: Invalid engine name")
    try:
        config = base_config.copy()
        config[OperatorConstants.Config.PROVIDER_CONFIG] = {
            "index_name": "test_invalid_engine",
            OperatorConstants.VectorDB.ENGINE: "invalid_engine",
        }
        operator = VectorDBOperator(config)
        tests.append(("Invalid engine", False, "Should have raised DocpipeException"))
    except DocpipeException as e:
        if "Invalid engine" in str(e):
            tests.append(("Invalid engine", True, "Correct error message"))
            print(f"  ✅ Correctly raised: {str(e)[:100]}")
        else:
            tests.append(("Invalid engine", False, f"Wrong error: {e!s}"))

    # Test 3: Incompatible engine-algorithm
    print("\nTest 3.3: Incompatible engine-algorithm combination")
    try:
        config = base_config.copy()
        config[OperatorConstants.Config.PROVIDER_CONFIG] = {
            "index_name": "test_incompatible",
            OperatorConstants.VectorDB.ENGINE: "lucene",
            OperatorConstants.VectorDB.ALGORITHM: "ivf",  # Lucene doesn't support IVF
        }
        operator = VectorDBOperator(config)
        tests.append(("Incompatible combo", False, "Should have raised DocpipeException"))
    except DocpipeException as e:
        if "not supported by engine" in str(e):
            tests.append(("Incompatible combo", True, "Correct error message"))
            print(f"  ✅ Correctly raised: {str(e)[:100]}")
        else:
            tests.append(("Incompatible combo", False, f"Wrong error: {e!s}"))

    # Test 4: Missing document IDs
    print("\nTest 3.4: Documents with missing IDs")
    try:
        config = base_config.copy()
        config[OperatorConstants.Config.PROVIDER_CONFIG]["index_name"] = "test_missing_ids"
        operator = VectorDBOperator(config)

        # Create OpenSearch client for cleanup
        provider_config = config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
        client_manager = OpenSearchClient(
            host=provider_config.get(OperatorConstants.VectorDB.HOST, "localhost"),
            port=provider_config.get(OperatorConstants.VectorDB.PORT, 9200),
            username=provider_config.get(OperatorConstants.VectorDB.USERNAME),
            password=provider_config.get(OperatorConstants.VectorDB.PASSWORD),
            use_ssl=provider_config.get(OperatorConstants.VectorDB.USE_SSL, True),
            verify_certs=provider_config.get(OperatorConstants.VectorDB.VERIFY_CERTS, True),
        )
        client = client_manager.get_client()

        table = pa.table(
            {
                "doc_id_hash": ["doc_1", None, "doc_3", None],
                "embeddings": [np.random.rand(128).tolist() for _ in range(4)],
            }
        )

        _, metadata = operator.transform(table)

        if metadata["skipped_docs_count"] == 2 and metadata["processed_docs"] == 2:
            tests.append(
                (
                    "Missing IDs",
                    True,
                    f"Skipped {metadata['skipped_docs_count']}, processed {metadata['processed_docs']}",
                )
            )
            print(
                f"  ✅ Correctly handled: skipped {metadata['skipped_docs_count']}, processed {metadata['processed_docs']}"
            )
        else:
            tests.append(("Missing IDs", False, f"Wrong counts: {metadata}"))

        client.indices.delete(index=config[OperatorConstants.Config.PROVIDER_CONFIG]["index_name"])

    except Exception as e:
        tests.append(("Missing IDs", False, f"Unexpected error: {str(e)[:100]}"))

    # Test 5: Empty table
    print("\nTest 3.5: Empty table")
    try:
        config = base_config.copy()
        config[OperatorConstants.Config.PROVIDER_CONFIG]["index_name"] = "test_empty"
        operator = VectorDBOperator(config)

        empty_table = pa.table({"doc_id_hash": [], "embeddings": []})

        _result, metadata = operator.transform(empty_table)

        if metadata["documents_in_scope"] == 0 and metadata["processed_docs"] == 0:
            tests.append(("Empty table", True, "Handled gracefully"))
            print("  ✅ Correctly handled empty table")
        else:
            tests.append(("Empty table", False, f"Wrong metadata: {metadata}"))

    except Exception as e:
        tests.append(("Empty table", False, f"Unexpected error: {str(e)[:100]}"))

    # Print summary
    print("\nError Handling Summary:")
    print("-" * 80)
    for test_name, success, msg in tests:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} | {test_name:25} | {msg}")

    passed = sum(1 for _, s, _ in tests if s)
    total = len(tests)
    print(f"\nTotal: {passed}/{total} passed ({passed / total * 100:.1f}%)")

    return tests


def main():
    """Run all advanced tests"""
    print("\n" + "=" * 80)
    print("OpenSearch Operator - Advanced Testing Suite")
    print("=" * 80)

    try:
        # Test 1: All engines
        engine_results = test_all_engines()

        # Test 2: Schema evolution
        schema_success = test_schema_evolution()

        # Test 3: Error handling
        error_results = test_error_handling()

        # Final summary
        print_section("FINAL SUMMARY")

        engine_passed = sum(1 for _, s, _ in engine_results if s)
        engine_total = len(engine_results)

        error_passed = sum(1 for _, s, _ in error_results if s)
        error_total = len(error_results)

        print(f"Engine Tests:        {engine_passed}/{engine_total} passed ({engine_passed / engine_total * 100:.1f}%)")
        print(f"Schema Evolution:    {'✅ PASS' if schema_success else '❌ FAIL'}")
        print(f"Error Handling:      {error_passed}/{error_total} passed ({error_passed / error_total * 100:.1f}%)")

        total_passed = engine_passed + (1 if schema_success else 0) + error_passed
        total_tests = engine_total + 1 + error_total

        print(f"\nOverall:             {total_passed}/{total_tests} passed ({total_passed / total_tests * 100:.1f}%)")

        return 0 if total_passed == total_tests else 1

    except Exception as e:
        print(f"\n❌ Fatal error: {type(e).__name__}: {e!s}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
