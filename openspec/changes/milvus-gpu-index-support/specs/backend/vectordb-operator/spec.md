# Spec Delta

## Purpose

Extends the VectorDB operator specification for the Milvus adapter with GPU index types, quantized index types, and the `quantization`, `quantization_parameters`, `use_gpu` and `fallback_to_cpu` configuration fields.

## ADDED Requirements

### Requirement: Milvus GPU index types

The Milvus adapter SHALL accept the dense index types `GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ` and `GPU_BRUTE_FORCE` for standalone and remote Milvus deployments. The adapter SHALL NOT probe the host running the pipeline for a GPU and SHALL NOT change an explicitly configured index type based on local hardware.

#### Scenario: GPU index type is sent to the server as configured
- **WHEN** `index_type="GPU_CAGRA"` is configured and `use_gpu` and `fallback_to_cpu` are unset
- **THEN** the collection index is created with `GPU_CAGRA` and its default or configured parameters, regardless of the GPU hardware on the pipeline host

#### Scenario: GPU index type rejected for Milvus Lite
- **WHEN** a GPU index type is configured with `auth_type="lite"`
- **THEN** the adapter raises a `DocpipeException` (status 400) stating that GPU indexes are not supported by Milvus Lite

### Requirement: Milvus GPU index metric and parameter validation

The adapter SHALL validate GPU index configuration before any collection is created.

#### Scenario: GPU index rejects COSINE
- **WHEN** a GPU index type is configured with `metric_type="COSINE"`
- **THEN** the adapter raises a `DocpipeException` (status 400, `OPERATOR_CONFIGURATION_INVALID`) suggesting `IP` on normalized vectors or `L2`

#### Scenario: GPU_CAGRA graph degree constraint violated
- **WHEN** `index_type="GPU_CAGRA"` is configured with `graph_degree` greater than `intermediate_graph_degree` after merging defaults and user parameters
- **THEN** the adapter raises a `DocpipeException` (status 400, `OPERATOR_CONFIGURATION_INVALID`)

#### Scenario: GPU_CAGRA valid parameters accepted
- **WHEN** `index_type="GPU_CAGRA"` is configured with `graph_degree` less than or equal to `intermediate_graph_degree`
- **THEN** the adapter accepts the configuration

### Requirement: Milvus use_gpu index selection

The adapter SHALL support `use_gpu` to select between CPU and GPU index families. The upgrade SHALL be applied after `quantization` is resolved.

#### Scenario: use_gpu upgrades a CPU index
- **WHEN** `use_gpu=true` and `index_type` is `HNSW`, `IVF_FLAT`, `IVF_PQ` or `FLAT`
- **THEN** the index type becomes `GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ` or `GPU_BRUTE_FORCE` respectively

#### Scenario: use_gpu with quantization
- **WHEN** `use_gpu=true`, `index_type="HNSW"` and `quantization="PQ"`
- **THEN** the index type becomes `GPU_IVF_PQ`

#### Scenario: use_gpu without a GPU equivalent
- **WHEN** `use_gpu=true` and the resolved index type has no GPU equivalent (for example `HNSW_SQ`)
- **THEN** the adapter raises a `DocpipeException` (status 400)

#### Scenario: use_gpu false downgrades a GPU index
- **WHEN** `use_gpu=false` and a GPU index type is configured
- **THEN** the index type becomes its CPU equivalent

#### Scenario: Parameters follow the index type
- **WHEN** `use_gpu` changes the index type
- **THEN** `index_parameters` that are not valid for the new index type are dropped and a warning lists them

### Requirement: Milvus opt-in CPU fallback

The adapter SHALL provide `fallback_to_cpu` (default `false`). The fallback SHALL be triggered only by an error from the Milvus server during index creation.

#### Scenario: Fallback disabled
- **WHEN** the server rejects a GPU index and `fallback_to_cpu` is `false`
- **THEN** collection creation fails with a `DocpipeException` carrying the server error and the index type is unchanged

#### Scenario: Fallback enabled
- **WHEN** the server rejects a GPU index and `fallback_to_cpu` is `true`
- **THEN** the adapter logs a warning, creates the index with the CPU equivalent (`GPU_CAGRA` -> `HNSW`, `GPU_IVF_FLAT` -> `IVF_FLAT`, `GPU_IVF_PQ` -> `IVF_PQ`, `GPU_BRUTE_FORCE` -> `FLAT`) without GPU-only parameters, and records the fallback on the index manager

#### Scenario: CPU index failures are not retried
- **WHEN** index creation fails for a CPU index type and `fallback_to_cpu` is `true`
- **THEN** the error is raised without a retry

### Requirement: Milvus index quantization

The adapter SHALL resolve `quantization` (`SQ8`, `PQ`, `PRQ`, `NONE`) together with `index_type` to a quantized index type, and merge `quantization_parameters` into `index_parameters`.

#### Scenario: Supported combination
- **WHEN** `index_type="HNSW"` and `quantization="PQ"`
- **THEN** the index type becomes `HNSW_PQ` and `quantization_parameters` are merged into the index parameters

#### Scenario: Unsupported combination
- **WHEN** `quantization` has no quantized variant for the configured `index_type` (for example `DISKANN` with `PQ`)
- **THEN** the adapter logs a warning, keeps the configured index type and ignores `quantization_parameters`
