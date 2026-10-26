# Proposal

## Why

Milvus supports binary vectors (`DataType.BINARY_VECTOR`), enabling up to 32× storage reduction and orders-of-magnitude faster similarity search via hardware-accelerated bitwise operations (`XOR` + `POPCNT`) for large-scale retrieval, document deduplication, and multimedia/perceptual matching. Currently, the `VectorDBOperator` and its `MilvusAdapter` only expose dense 32-bit floating-point vectors and BM25 sparse vectors, preventing users from creating binary vector collections, indexing quantized embeddings, or configuring binary index types and metrics.

## What Changes

- **Binary Vector Field Support in Milvus Adapter**: Enable Milvus collection creation and schema generation with `DataType.BINARY_VECTOR` when binary vector configuration or byte-encoded embeddings are specified.
- **Binary Index Types and Metrics Configuration**: Add support for `BIN_FLAT` and `BIN_IVF_FLAT` index algorithms, along with binary similarity metrics: `HAMMING`, `JACCARD`, `TANIMOTO`, `SUBSTRUCTURE`, and `SUPERSTRUCTURE`.
- **Binary Quantization Integration**: Support 1-bit sign thresholding (`v > 0`) and bit-packing (`numpy.packbits`) in embeddings workflows or vector database transformation to convert float embeddings into compact byte-encoded binary vectors.
- **Multi-Vector / Hybrid Indexing Support**: Support collections containing both float and binary vector fields (e.g. `dense_vector` and `binary_vector`) for two-stage coarse-to-fine retrieval and hybrid search workflows.
- **Milvus Lite Safeguard Validation**: Explicitly validate and reject `DataType.BINARY_VECTOR` and binary index types when using `auth_type: "lite"` with an actionable error message, reflecting Milvus Lite's architectural constraints.
- **Documentation & Configuration Reference**: Update operator documentation with binary vector parameters, configuration examples, and trade-offs.

## Non-goals

- **Milvus Lite Engine Implementation**: We will not attempt to implement binary vector operations inside the C++ `milvus-lite` engine itself, as upstream Milvus Lite does not support `BinaryVector`.
- **Client-side Search Execution Engine**: We will not replace external vector database search clients or build a custom vector query engine in `docpipe`; the focus is on schema management, ingestion, indexing, and vector data transformation within the pipeline.
- **Non-Milvus Vector DB Binary Quantization**: This proposal does not add binary indexing to OpenSearch or other backends.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `backend/vectordb-operator`: Add requirements and validation for binary vector storage (`DataType.BINARY_VECTOR`), binary index algorithms (`BIN_FLAT`, `BIN_IVF_FLAT`), binary similarity metrics (`HAMMING`, `JACCARD`, `TANIMOTO`, `SUBSTRUCTURE`, `SUPERSTRUCTURE`), and Milvus Lite restriction checks.

## Impact

- **Layer**: Backend-only (`src/docpipe/core/operators/vectordb/adapters/outbound/milvus/` and `src/docpipe/core/operators/functional/embeddings/`).
- **Affected Components**:
  - `MilvusIndexManager`: Index types, metric types, index parameter defaults, schema creation, and Milvus Lite validation.
  - `MilvusBatchProcessor`: Document preparation and binary byte formatting for PyMilvus insert calls.
  - `EmbeddingsOperator`: Quantization parameter support (`quantization: "binary"`) for float-to-packed-bytes conversion.
- **Dependencies**: Uses existing `pymilvus` (>=2.4.0) and `numpy`. No new external package dependencies required.
