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

**Decision:** In `MilvusIndexManager._create_schema_fields`, recognize binary vector columns (configured via `vector_type: "binary"` or feature type `binary_vector`) and generate `FieldSchema(name=field_name, dtype=DataType.BINARY_VECTOR, dim=dimension)`.
- Enforce validation rule: `dimension % 8 == 0`.
- Keep `FLOAT_VECTOR` as the default when `vector_type` is not `"binary"`.

*Alternatives considered:*
- Storing binary vectors as `DataType.ARRAY` of `INT8`: Rejected because Milvus vector indexes (`BIN_FLAT`, `BIN_IVF_FLAT`) and vector similarity search require native `DataType.BINARY_VECTOR`.

### 2. Binary Index and Metric Types Configuration

**Decision:** Extend `MilvusIndexTypes` and `MilvusMetricTypes` in `index_manager.py`:
- `MilvusIndexTypes`: add `BIN_FLAT = "BIN_FLAT"`, `BIN_IVF_FLAT = "BIN_IVF_FLAT"`.
- `MilvusMetricTypes`: add `HAMMING = "HAMMING"`, `JACCARD = "JACCARD"`, `TANIMOTO = "TANIMOTO"`, `SUBSTRUCTURE = "SUBSTRUCTURE"`, `SUPERSTRUCTURE = "SUPERSTRUCTURE"`.
- `INDEX_DEFAULT_PARAMETERS`: add `BIN_FLAT: {}`, `BIN_IVF_FLAT: {"nlist": 128}`.
- Validate metric compatibility: binary index types only allow binary metrics.

*Alternatives considered:*
- Allowing arbitrary index string names without validation: Rejected to prevent runtime Milvus RPC failures and provide early pipeline validation.

### 3. Binary Vector Serialization in `MilvusBatchProcessor`

**Decision:** Ensure vector values passed to `client.insert()` are converted to raw `bytes` if they are lists of integers, boolean arrays, or packed PyArrow binary buffers:
```python
if is_binary_vector:
    if isinstance(val, (bytes, bytearray)):
        doc[field_name] = bytes(val)
    elif isinstance(val, (list, np.ndarray)):
        doc[field_name] = bytes(val)
```

*Alternatives considered:*
- Expecting upstream operators to always pass Python `bytes`: While upstream can emit bytes, adding normalization in `prepare_document` ensures defensive handling of PyArrow binary buffers and uint8 lists.

### 4. Binary Quantization in `EmbeddingsOperator`

**Decision:** Add an optional `quantization` configuration key to `EmbeddingsOperator` (`"none" | "binary" | "ubinary"`).
- When `quantization: "binary"` or `"ubinary"`, apply 1-bit sign thresholding (`arr > 0`) followed by `np.packbits(..., axis=-1).tobytes()`.
- Store the resulting byte sequence in the output table column (as `pa.binary()` or Python `bytes`).

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
  *Mitigation:* Add strict assertions: `len(byte_vector) == dimension // 8` and `dimension % 8 == 0`.

## Migration Plan

- **Backward Compatibility:** Fully backward compatible. Default behavior for `FLOAT_VECTOR` and `SPARSE_FLOAT_VECTOR` remains unchanged.
- **Deprecations:** None.
