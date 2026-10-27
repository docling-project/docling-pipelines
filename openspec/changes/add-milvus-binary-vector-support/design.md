# Design: Milvus Binary Vector Index Support

## Context

The `VectorDBOperator` delegates vector database operations to `VectorStorePort` implementations, including `MilvusAdapter`. `MilvusAdapter` uses `MilvusIndexManager` to manage schema and index creation and `MilvusBatchProcessor` for document serialization and insertion. `EmbeddingsOperator` generates text embeddings as floating-point arrays.

See `proposal.md` for background and motivation.

## Goals / Non-Goals

**Goals:**
- Enable `MilvusIndexManager` to create collections with `DataType.BINARY_VECTOR` fields when binary vectors or quantization are configured.
- Support `BIN_FLAT` and `BIN_IVF_FLAT` index algorithms with binary metrics (`HAMMING`, `JACCARD`, `TANIMOTO`, `SUBSTRUCTURE`, `SUPERSTRUCTURE`).
- Support binary quantization in `EmbeddingsOperator` to produce byte-packed binary vectors from float embeddings using sign thresholding.
- Support multi-vector collections containing both binary vectors and dense float vectors.
- Reject binary vectors in `auth_type: "lite"` mode with clear, actionable validation errors.

**Non-Goals:**
- Building a standalone search query engine inside `docpipe` (search queries are executed by consumer applications or external search clients).
- Modifying `milvus-lite` C++ binary vector support.

## Decisions

### 1. DataType and Schema Definition for Binary Vectors

**Decision:** In `MilvusIndexManager._create_schema_fields`, recognize binary vector columns and generate `FieldSchema(name=field_name, dtype=DataType.BINARY_VECTOR, dim=dimension)`. Classification is **per field and decided only by the feature's own type** (`vector_binary`, alias `binary_vector`, or `vector_type: "binary"`), via the single helper `is_binary_vector_feature`. `index_type` / `metric_type` are never used to infer it.
- Enforce validation rule: `dimension % 8 == 0`.
- Keep `FLOAT_VECTOR` as the default when the feature is not binary.
- `EmbeddingsOperator` with `quantization: binary|ubinary` types its `embeddings` feature as `vector_binary` in `FeaturePropagator`, so the binary path is selected without extra user configuration.

*Alternatives considered:*
- Storing binary vectors as `DataType.ARRAY` of `INT8`: Rejected because Milvus vector indexes (`BIN_FLAT`, `BIN_IVF_FLAT`) and vector similarity search require native `DataType.BINARY_VECTOR`.

### 2. Binary Index and Metric Types Configuration

**Decision:** Extend `MilvusIndexTypes` and `MilvusMetricTypes` in `index_manager.py`:
- `MilvusIndexTypes`: add `BIN_FLAT = "BIN_FLAT"`, `BIN_IVF_FLAT = "BIN_IVF_FLAT"`.
- `MilvusMetricTypes`: add `HAMMING = "HAMMING"`, `JACCARD = "JACCARD"`, `TANIMOTO = "TANIMOTO"`, `SUBSTRUCTURE = "SUBSTRUCTURE"`, `SUPERSTRUCTURE = "SUPERSTRUCTURE"`.
- `INDEX_DEFAULT_PARAMETERS`: add `BIN_FLAT: {}`, `BIN_IVF_FLAT: {"nlist": 128}`.
- Validate metric compatibility: binary index types only allow binary metrics; dense index types reject binary-only metrics.
- **No separate binary configuration keys.** The existing `index_type` / `metric_type` / `index_parameters` are applied dynamically per field kind (`MilvusIndexManager._resolve_vector_index_config`):
  - Dense field + dense `index_type`: used as configured.
  - Binary field + `BIN_*` `index_type`: used as configured (metric must be binary; `index_parameters` applied).
  - Binary field + dense `index_type`: falls back to `BIN_FLAT` / `HAMMING` (a binary-only metric in `metric_type` is honoured).
  - Dense field + `BIN_*` `index_type` in a mixed collection: falls back to `HNSW` / `L2` with default HNSW parameters.
  - Dense field + `BIN_*` `index_type` with no binary field in the collection: rejected with `OPERATOR_CONFIGURATION_INVALID`.

*Alternatives considered:*
- Allowing arbitrary index string names without validation: Rejected to prevent runtime Milvus RPC failures and provide early pipeline validation.

### 3. Binary Vector Serialization in `MilvusBatchProcessor`

**Decision:** Binary vector values are expected to arrive as Python `bytes` / `bytearray` (produced by `EmbeddingsOperator` quantization, in memory or via the packed-bit memmap path). `MilvusBatchProcessor.prepare_document` passes them to `client.insert()` as raw `bytes` for any vector field (identified by `is_dense_or_binary_vector_feature`), and skips non-vector `bytes` columns that cannot be JSON serialized. `vectordb_utils.calculate_batch_size_bytes` counts `bytes` by length so batch sizing keeps working.

*Alternatives considered:*
- Normalising lists / ndarrays of ints to `bytes` inside `prepare_document`: Not implemented. The only producer in this repository emits `bytes`, so extra coercion would be speculative; revisit if another operator emits uint8 lists.
- Asserting `len(bytes) == dim / 8` per row: Not implemented. The dimension is derived from the data itself (`len(bytes) * 8`), so the check would be tautological; mismatches against an existing collection are caught by `validate_existing_collection`.

### 4. Binary Quantization in `EmbeddingsOperator`

**Decision:** Add an optional `quantization` configuration key to `EmbeddingsOperator` (`"none" | "binary" | "ubinary"`).
- When `quantization: "binary"` or `"ubinary"`, apply 1-bit sign thresholding (`arr > 0`) followed by `np.packbits(..., axis=-1).tobytes()`.
- Store the resulting byte sequence in the output table column (as `pa.binary()` or Python `bytes`).
- **File-backed (memmap) path:** `write_content_to_file` writes `bytes` rows verbatim and records the dimension in bits (`len(bytes) * 8`) with metadata `{"dim": N, "dtype": "packed_bits"}`; float files keep `{"dim": N}`. Readers (`yield_embeddings_from_memmap_file`, `load_embeddings_from_memmap_file`) return `bytes` rows for packed-bit files, so `VectorDBOperator` streams them to Milvus without `.tolist()`.

*Alternatives considered:*
- Creating a separate `BinaryQuantizationOperator`: Rejected to avoid unnecessary DAG node overhead; quantizing at embedding generation time is more performant and matches provider patterns (e.g. Cohere binary embeddings).

### 5. Milvus Lite Enforcement Safeguard

**Decision:** In `MilvusIndexManager._validate_index_type()`, raise `DocpipeException` with `ErrorCode.OPERATOR_CONFIGURATION_INVALID` if `is_lite` is `True` and `index_type in [MilvusIndexTypes.BIN_FLAT, MilvusIndexTypes.BIN_IVF_FLAT]` or if any binary vector field is configured.

## Risks / Trade-offs

- **[Risk]** Float embeddings with non-zero-centered distributions lose fidelity under standard sign thresholding.  
  *Mitigation:* Document that 1-bit quantization works best with zero-mean normalized embeddings (e.g. cosine-normalized modern embeddings).
- **[Risk]** Milvus Lite users attempting to use binary vectors encounter runtime RPC failures.  
  *Mitigation:* Add eager validation in `MilvusIndexManager` with a clear explanation directing users to standalone Milvus / watsonx.data.
- **[Risk]** Dimension mismatch between bit count and byte array length.  
  *Mitigation:* The dimension is always derived from the packed data (`len(bytes) * 8`), so it is a multiple of 8 by construction; `MilvusIndexManager` still rejects other values and `validate_existing_collection` compares the bit count with the existing schema.

## Migration Plan

- **Backward Compatibility:** Fully backward compatible. Default behavior for `FLOAT_VECTOR` and `SPARSE_FLOAT_VECTOR` remains unchanged.
- **Deprecations:** None.
