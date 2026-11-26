#!/usr/bin/env python3
"""
Milvus Integration Example
Demonstrates end-to-end usage of the Milvus operator with real data.
Uses exported environment variables or a repository .env file for configuration.
"""

import sys
import time
from pathlib import Path

import numpy as np
import pyarrow as pa

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.vectordb import VectorDBOperator
from docpipe.utils.infrastructure.config import get_milvus_config


def create_sample_documents(num_docs=10, vector_dim=384):
    """Create sample documents with embeddings"""
    doc_ids = [f"doc_{i}" for i in range(num_docs)]
    contents = [f"This is sample document number {i} with some content." for i in range(num_docs)]
    embeddings = [np.random.rand(vector_dim).tolist() for _ in range(num_docs)]

    return pa.table(
        {
            "doc_id_hash": doc_ids,
            "content": contents,
            "embeddings": embeddings,
            "metadata": [f"metadata_{i}" for i in range(num_docs)],
        }
    )


def example_1_basic_indexing():
    """Example 1: Basic document indexing with HNSW index"""
    print("\n" + "=" * 80)
    print("Example 1: Basic Document Indexing")
    print("=" * 80)

    # Get base config from environment variables
    config = get_milvus_config()

    # Override with example-specific settings
    config.update(
        {
            OperatorConstants.Config.PROVIDER: "milvus",
            OperatorConstants.VectorDB.INDEX_NAME: "docpipe_example_basic",
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
                "metadata": {
                    "name": "Metadata",
                    "available_for_vector_db": True,
                    "type": "string",
                },
            },
            OperatorConstants.Config.FEATURE_MAPPINGS: {
                "doc_id_hash": "pk",
                "content": "text",
                "embeddings": "vector",
                "metadata": "meta",
            },
        }
    )

    # Create sample data
    print("\n1. Creating sample documents...")
    table = create_sample_documents(num_docs=10)
    print(f"   Created {table.num_rows} documents")

    # Initialize operator
    print("\n2. Initializing Milvus operator...")
    operator = VectorDBOperator(config)
    print("   Operator initialized successfully")

    # Index documents
    print("\n3. Indexing documents...")
    _result_tables, metadata = operator.transform(table=table)

    print("\n4. Indexing Results:")
    print(f"   Total documents: {metadata['documents_in_scope']}")
    print(f"   Processed: {metadata['processed_docs']}")
    print(f"   Failed: {metadata['failed_docs_count']}")
    print(f"   Skipped: {metadata['skipped_docs_count']}")
    print(f"   Batches: {metadata.get('number_of_batches', 0)}")

    # Get document count (wait a moment for data to be available)
    print("\n5. Verifying collection...")
    time.sleep(1)  # Brief wait for Milvus to make data available
    count = operator.get_document_count()
    print(f"   Total documents in collection: {count}")

    return operator


def example_2_ivf_flat_index():
    """Example 2: Using IVF_FLAT index for large datasets"""
    print("\n" + "=" * 80)
    print("Example 2: IVF_FLAT Index for Large Datasets")
    print("=" * 80)

    # Get base config from environment variables
    config = get_milvus_config()

    # Override with example-specific settings
    config.update(
        {
            OperatorConstants.Config.PROVIDER: "milvus",
            OperatorConstants.VectorDB.INDEX_NAME: "docpipe_example_ivf",
            OperatorConstants.Config.BATCH_SIZE: 50,
            OperatorConstants.Config.PROVIDER_CONFIG: {
                **config.get(OperatorConstants.Config.PROVIDER_CONFIG, {}),
                OperatorConstants.VectorDB.INDEX_TYPE: "IVF_FLAT",
                OperatorConstants.VectorDB.METRIC_TYPE: "L2",
                OperatorConstants.VectorDB.INDEX_PARAMETERS: {
                    "nlist": 128,
                },
            },
            OperatorConstants.Config.AVAILABLE_FEATURES: {
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
            },
            OperatorConstants.Config.FEATURE_MAPPINGS: {
                "doc_id_hash": "pk",
                "content": "text",
                "embeddings": "vector",
            },
        }
    )

    print("\n1. Creating sample documents...")
    table = create_sample_documents(num_docs=20)

    print("\n2. Initializing Milvus operator with IVF_FLAT index...")
    operator = VectorDBOperator(config)
    provider_config = config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
    print(f"   Index Type: {provider_config.get(OperatorConstants.VectorDB.INDEX_TYPE, 'N/A')}")
    print(f"   Metric Type: {provider_config.get(OperatorConstants.VectorDB.METRIC_TYPE, 'N/A')}")
    print(f"   Index Parameters: {provider_config.get(OperatorConstants.VectorDB.INDEX_PARAMETERS, {})}")

    print("\n3. Indexing documents...")
    _result_tables, metadata = operator.transform(table=table)

    print("\n4. Results:")
    print(f"   Processed: {metadata['processed_docs']}/{metadata['documents_in_scope']}")
    print(f"   Batches: {metadata.get('number_of_batches', 0)}")

    return operator


def example_3_cosine_similarity():
    """Example 3: Using COSINE similarity metric"""
    print("\n" + "=" * 80)
    print("Example 3: COSINE Similarity Metric")
    print("=" * 80)

    # Get base config from environment variables
    config = get_milvus_config()

    # Override with example-specific settings
    config.update(
        {
            OperatorConstants.Config.PROVIDER: "milvus",
            OperatorConstants.VectorDB.INDEX_NAME: "docpipe_example_cosine",
            OperatorConstants.Config.PROVIDER_CONFIG: {
                **config.get(OperatorConstants.Config.PROVIDER_CONFIG, {}),
                OperatorConstants.VectorDB.INDEX_TYPE: "HNSW",
                OperatorConstants.VectorDB.METRIC_TYPE: "COSINE",
                OperatorConstants.VectorDB.INDEX_PARAMETERS: {
                    "M": 16,
                    "efConstruction": 200,
                },
            },
            OperatorConstants.Config.AVAILABLE_FEATURES: {
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
            },
            OperatorConstants.Config.FEATURE_MAPPINGS: {
                "doc_id_hash": "pk",
                "content": "text",
                "embeddings": "vector",
            },
        }
    )

    print("\n1. Creating sample documents...")
    table = create_sample_documents(num_docs=15)

    print("\n2. Initializing Milvus operator with COSINE similarity...")
    operator = VectorDBOperator(config)
    provider_config = config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
    print(f"   Index Type: {provider_config.get(OperatorConstants.VectorDB.INDEX_TYPE, 'N/A')}")
    print(f"   Metric Type: {provider_config.get(OperatorConstants.VectorDB.METRIC_TYPE, 'N/A')}")

    print("\n3. Indexing documents...")
    _result_tables, metadata = operator.transform(table=table)

    print("\n4. Results:")
    print(f"   Processed: {metadata['processed_docs']}/{metadata['documents_in_scope']}")

    return operator


def example_4_query_operations(*, operator):
    """Example 4: Query and delete operations"""
    print("\n" + "=" * 80)
    print("Example 4: Query and Delete Operations")
    print("=" * 80)

    # Query documents (only request fields that exist in the collection)
    print("\n1. Querying documents by names...")
    doc_names = ["doc_0", "doc_1", "doc_2"]
    docs = operator.query_by_doc_names(doc_names=doc_names, fields=["pk", "text", "meta"])
    print(f"   Found {len(docs)} documents")
    for doc in docs[:3]:
        doc_id = doc.get("pk", "N/A")
        content = doc.get("text", "N/A")
        if isinstance(content, str) and len(content) > 50:
            content = content[:50] + "..."
        print(f"   - {doc_id}: {content}")

    # Get document count
    print("\n2. Getting document count...")
    count_before = operator.get_document_count()
    print(f"   Documents before deletion: {count_before}")

    # Delete documents
    print("\n3. Deleting documents...")
    doc_ids_to_delete = ["doc_0", "doc_1"]
    success, failed = operator.delete_documents_by_ids(doc_ids=doc_ids_to_delete)
    print(f"   Deleted: {success}, Failed: {failed}")

    # Verify deletion
    print("\n4. Verifying deletion...")
    count_after = operator.get_document_count()
    print(f"   Documents after deletion: {count_after}")
    print(f"   Difference: {count_before - count_after}")


def example_5_batch_processing():
    """Example 5: Large batch processing"""
    print("\n" + "=" * 80)
    print("Example 5: Large Batch Processing")
    print("=" * 80)

    # Get base config from environment variables
    config = get_milvus_config()

    # Override with example-specific settings
    config.update(
        {
            OperatorConstants.Config.PROVIDER: "milvus",
            OperatorConstants.VectorDB.INDEX_NAME: "docpipe_example_batch",
            OperatorConstants.Config.BATCH_SIZE: 50,  # Smaller batch size for demonstration
            OperatorConstants.Config.AVAILABLE_FEATURES: {
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
            },
            OperatorConstants.Config.FEATURE_MAPPINGS: {
                "doc_id_hash": "pk",
                "content": "text",
                "embeddings": "vector",
            },
        }
    )

    print("\n1. Creating large dataset...")
    table = create_sample_documents(num_docs=150)
    print(f"   Created {table.num_rows} documents")

    print("\n2. Initializing operator with batch size 50...")
    operator = VectorDBOperator(config)

    print("\n3. Processing in batches...")
    _result_tables, metadata = operator.transform(table=table)

    print("\n4. Batch Processing Results:")
    print(f"   Total documents: {metadata['documents_in_scope']}")
    print(f"   Processed: {metadata['processed_docs']}")
    print(f"   Number of batches: {metadata.get('number_of_batches', 0)}")
    print(f"   Average batch size: {metadata['processed_docs'] / max(metadata.get('number_of_batches', 1), 1):.1f}")

    return operator


def example_6_error_handling():
    """Example 6: Error handling and recovery"""
    print("\n" + "=" * 80)
    print("Example 6: Error Handling")
    print("=" * 80)

    # Get base config from environment variables
    config = get_milvus_config()

    # Override with example-specific settings
    config.update(
        {
            OperatorConstants.Config.PROVIDER: "milvus",
            OperatorConstants.VectorDB.INDEX_NAME: "docpipe_example_errors",
            OperatorConstants.Config.AVAILABLE_FEATURES: {
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
            OperatorConstants.Config.FEATURE_MAPPINGS: {"doc_id_hash": "pk", "embeddings": "vector"},
        }
    )

    # Create data with some missing doc IDs
    print("\n1. Creating data with missing doc IDs...")
    doc_ids = ["doc_1", None, "doc_3", None, "doc_5"]  # Some None values
    embeddings = [np.random.rand(384).tolist() for _ in range(5)]

    table = pa.table({"doc_id_hash": doc_ids, "embeddings": embeddings})

    print("\n2. Processing documents with errors...")
    operator = VectorDBOperator(config)
    _result_tables, metadata = operator.transform(table=table)

    print("\n3. Error Handling Results:")
    print(f"   Total documents: {metadata['documents_in_scope']}")
    print(f"   Processed: {metadata['processed_docs']}")
    print(f"   Skipped: {metadata['skipped_docs_count']}")
    print(f"   Failed: {metadata['failed_docs_count']}")

    if metadata["skipped_docs"]:
        print("\n4. Skipped Documents:")
        for doc in metadata["skipped_docs"][:5]:
            print(f"   - {doc['name']}: {doc['reason']}")


def example_7_sparse_vectors():
    """Example 7: Sparse + Dense vector mode with BM25"""
    print("\n" + "=" * 80)
    print("Example 7: Sparse + Dense Vector Mode (BM25)")
    print("=" * 80)

    # Get base config from environment variables
    config = get_milvus_config()

    # Override with sparse vector settings
    config.update(
        {
            OperatorConstants.Config.PROVIDER: "milvus",
            OperatorConstants.VectorDB.INDEX_NAME: "docpipe_example_sparse",
            OperatorConstants.Config.PROVIDER_CONFIG: {
                **config.get(OperatorConstants.Config.PROVIDER_CONFIG, {}),
                OperatorConstants.VectorDB.ADD_SPARSE_VECTOR: True,
                OperatorConstants.VectorDB.INDEX_TYPE: "SPARSE_INVERTED_INDEX",
                OperatorConstants.VectorDB.METRIC_TYPE: "BM25",
            },
            OperatorConstants.Config.AVAILABLE_FEATURES: {
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
                "sparse_embeddings": {
                    "available_for_vector_db": True,
                    "type": "sparse_vector",
                },
            },
            OperatorConstants.Config.FEATURE_MAPPINGS: {
                "doc_id_hash": "pk",
                "content": "text",
                "embeddings": "vector",
                "sparse_embeddings": "sparse_vector",
            },
        }
    )

    print("\n1. Creating sample documents...")
    table = create_sample_documents(num_docs=15)

    print("\n2. Initializing Milvus operator with sparse + dense vectors...")
    operator = VectorDBOperator(config)
    provider_config = config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
    print(f"   Index Type: {provider_config.get(OperatorConstants.VectorDB.INDEX_TYPE, 'N/A')}")
    print(f"   Metric Type: {provider_config.get(OperatorConstants.VectorDB.METRIC_TYPE, 'N/A')}")
    print(f"   Sparse Mode: {provider_config.get(OperatorConstants.VectorDB.ADD_SPARSE_VECTOR, False)}")

    print("\n3. Indexing documents with dual vectors...")
    print("   Note: BM25 sparse vectors are auto-generated from text content")
    _result_tables, metadata = operator.transform(table=table)

    print("\n4. Results:")
    print(f"   Processed: {metadata['processed_docs']}/{metadata['documents_in_scope']}")
    print("   Collection stores both dense embeddings and BM25 sparse vectors")

    return operator


def main():
    print("\n" + "=" * 80)
    print("Milvus Operator Integration Examples")
    print("=" * 80)
    print("\nThese examples demonstrate the Milvus operator capabilities:")
    print("1. Basic document indexing with HNSW")
    print("2. IVF_FLAT index for large datasets")
    print("3. COSINE similarity metric")
    print("4. Query and delete operations")
    print("5. Batch processing")
    print("6. Error handling")
    print("7. Sparse + Dense vector mode with BM25")

    try:
        # Example 1: Basic indexing
        operator1 = example_1_basic_indexing()

        # Example 2: IVF_FLAT index
        _operator2 = example_2_ivf_flat_index()

        # Example 3: COSINE similarity
        _operator3 = example_3_cosine_similarity()

        # Example 4: Query operations (using operator from example 1)
        example_4_query_operations(operator=operator1)

        # Example 5: Batch processing
        _operator5 = example_5_batch_processing()

        # Example 6: Error handling
        example_6_error_handling()

        # Example 7: Sparse vectors
        _operator7 = example_7_sparse_vectors()

        print("\n" + "=" * 80)
        print("All examples completed successfully!")
        print("=" * 80)

    except Exception as e:
        print(f"\nError running examples: {e!s}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
