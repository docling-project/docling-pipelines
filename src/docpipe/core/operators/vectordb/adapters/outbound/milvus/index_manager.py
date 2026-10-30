#!/usr/bin/env python3
"""
Milvus Index Manager
Handles collection creation, validation, and schema management for Milvus.
"""

from typing import Any, ClassVar

from pymilvus import CollectionSchema, DataType, FieldSchema, Function, FunctionType, MilvusClient

from docpipe.core.constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.vectordb_utils import build_mapping_dict, feature_mapping_items

logger = get_logger()


class MilvusMetricTypes:
    """Vector similarity metrics supported by Milvus"""

    L2: str = "L2"
    IP: str = "IP"  # Inner Product
    COSINE: str = "COSINE"
    BM25: str = "BM25"  # BM25 for sparse vectors
    ALL_TYPES: ClassVar[list[str]] = [L2, IP, COSINE, BM25]


class MilvusIndexTypes:
    """Index types supported by Milvus"""

    # Dense vector index types - CPU
    FLAT: str = "FLAT"
    IVF_FLAT: str = "IVF_FLAT"
    IVF_SQ8: str = "IVF_SQ8"
    IVF_PQ: str = "IVF_PQ"
    HNSW: str = "HNSW"
    HNSW_SQ: str = "HNSW_SQ"
    HNSW_PQ: str = "HNSW_PQ"
    HNSW_PRQ: str = "HNSW_PRQ"
    DISKANN: str = "DISKANN"
    AUTOINDEX: str = "AUTOINDEX"

    # Dense vector index types - GPU
    GPU_FLAT: str = "GPU_FLAT"
    GPU_IVF_FLAT: str = "GPU_IVF_FLAT"
    GPU_IVF_PQ: str = "GPU_IVF_PQ"
    GPU_CAGRA: str = "GPU_CAGRA"
    GPU_BRUTE_FORCE: str = "GPU_BRUTE_FORCE"

    # Sparse vector index types
    SPARSE_INVERTED_INDEX: str = "SPARSE_INVERTED_INDEX"
    SPARSE_WAND: str = "SPARSE_WAND"

    ALL_CPU_DENSE_TYPES: ClassVar[list[str]] = [
        FLAT,
        IVF_FLAT,
        IVF_SQ8,
        IVF_PQ,
        HNSW,
        HNSW_SQ,
        HNSW_PQ,
        HNSW_PRQ,
        DISKANN,
        AUTOINDEX,
    ]
    ALL_GPU_TYPES: ClassVar[list[str]] = [
        GPU_FLAT,
        GPU_IVF_FLAT,
        GPU_IVF_PQ,
        GPU_CAGRA,
        GPU_BRUTE_FORCE,
    ]
    ALL_DENSE_TYPES: ClassVar[list[str]] = ALL_CPU_DENSE_TYPES + ALL_GPU_TYPES
    ALL_SPARSE_TYPES: ClassVar[list[str]] = [SPARSE_INVERTED_INDEX, SPARSE_WAND]
    ALL_TYPES: ClassVar[list[str]] = ALL_DENSE_TYPES + ALL_SPARSE_TYPES
    # Milvus Lite only supports FLAT for dense vectors
    LITE_SUPPORTED_DENSE_TYPES: ClassVar[list[str]] = [FLAT]


# Fallback mapping from GPU index types to their optimal CPU counterparts
GPU_TO_CPU_FALLBACK_MAP: dict[str, str] = {
    MilvusIndexTypes.GPU_CAGRA: MilvusIndexTypes.HNSW,
    MilvusIndexTypes.GPU_IVF_FLAT: MilvusIndexTypes.IVF_FLAT,
    MilvusIndexTypes.GPU_IVF_PQ: MilvusIndexTypes.IVF_PQ,
    MilvusIndexTypes.GPU_FLAT: MilvusIndexTypes.FLAT,
    MilvusIndexTypes.GPU_BRUTE_FORCE: MilvusIndexTypes.FLAT,
}

# Optional upgrade mapping from CPU index types to GPU counterparts when use_gpu is explicitly enabled
CPU_TO_GPU_UPGRADE_MAP: dict[str, str] = {
    MilvusIndexTypes.HNSW: MilvusIndexTypes.GPU_CAGRA,
    MilvusIndexTypes.IVF_FLAT: MilvusIndexTypes.GPU_IVF_FLAT,
    MilvusIndexTypes.IVF_PQ: MilvusIndexTypes.GPU_IVF_PQ,
    MilvusIndexTypes.FLAT: MilvusIndexTypes.GPU_FLAT,
}

# Default parameters for index types
INDEX_DEFAULT_PARAMETERS: dict[str, dict[str, Any]] = {
    # Dense vector index parameters - CPU
    MilvusIndexTypes.FLAT: {},
    MilvusIndexTypes.IVF_FLAT: {"nlist": 128},
    MilvusIndexTypes.IVF_SQ8: {"nlist": 128},
    MilvusIndexTypes.IVF_PQ: {"nlist": 128, "m": 8, "nbits": 8},
    MilvusIndexTypes.HNSW: {"M": 16, "efConstruction": 200},
    MilvusIndexTypes.HNSW_SQ: {"M": 16, "efConstruction": 200, "sq_type": "SQ8"},
    MilvusIndexTypes.HNSW_PQ: {"M": 16, "efConstruction": 200, "m": 16, "nbits": 8},
    MilvusIndexTypes.HNSW_PRQ: {"M": 16, "efConstruction": 200, "m": 16, "nbits": 8},
    MilvusIndexTypes.DISKANN: {},
    MilvusIndexTypes.AUTOINDEX: {},
    # Dense vector index parameters - GPU
    MilvusIndexTypes.GPU_FLAT: {},
    MilvusIndexTypes.GPU_IVF_FLAT: {"nlist": 1024},
    MilvusIndexTypes.GPU_IVF_PQ: {"nlist": 1024, "m": 16, "nbits": 8},
    MilvusIndexTypes.GPU_CAGRA: {
        "intermediate_graph_degree": 64,
        "graph_degree": 32,
        "build_algo": "IVF_PQ",
        "cache_dataset_on_device": False,
    },
    MilvusIndexTypes.GPU_BRUTE_FORCE: {},
    # Sparse vector index parameters
    MilvusIndexTypes.SPARSE_INVERTED_INDEX: {"drop_ratio_build": 0.2},
    MilvusIndexTypes.SPARSE_WAND: {"drop_ratio_build": 0.2},
}


class MilvusIndexManager:
    """
    Manages Milvus collection operations including creation, validation, and schema management.

    Responsibilities:
    - Collection creation with proper schema and index configuration
    - Collection validation and compatibility checking
    - Schema mapping generation
    - Index-specific parameter management
    - Vector dimension detection
    - Automatic GPU detection and graceful CPU fallback
    - Quantization resolution and configuration
    """

    @staticmethod
    def detect_gpu_available(*, device_id: int | None = None) -> bool:
        """Detect whether GPU resources are available on the host system.

        Probes environment overrides first (DOCPIPE_DISABLE_GPU, DOCPIPE_FORCE_GPU),
        followed by torch.cuda, pynvml, and nvidia-smi.

        Args:
            device_id: Optional zero-based GPU device index to probe.

        Returns:
            True if GPU resources are available, False otherwise.
        """
        import os

        # Check explicit overrides
        if os.getenv("DOCPIPE_DISABLE_GPU", "").strip().lower() in ("true", "1", "yes"):
            return False
        if os.getenv("DOCPIPE_FORCE_GPU", "").strip().lower() in ("true", "1", "yes"):
            return True

        # 1. Probe PyTorch CUDA
        try:
            import torch

            if torch.cuda.is_available():
                if device_id is not None:
                    return 0 <= device_id < torch.cuda.device_count()
                return torch.cuda.device_count() > 0
        except (ImportError, Exception):
            pass

        # 2. Probe pynvml if installed
        try:
            import pynvml

            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            pynvml.nvmlShutdown()
            if count > 0:
                if device_id is not None:
                    return 0 <= device_id < count
                return True
        except (ImportError, Exception):
            pass

        # 3. Probe nvidia-smi command
        try:
            import shutil
            import subprocess  # nosec B404

            if shutil.which("nvidia-smi") is not None:
                res = subprocess.run(  # nosec B603 B607
                    ["nvidia-smi", "-L"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if res.returncode == 0 and "GPU " in res.stdout:
                    if device_id is not None:
                        gpu_lines = [line for line in res.stdout.strip().split("\n") if line.startswith("GPU ")]
                        return 0 <= device_id < len(gpu_lines)
                    return True
        except Exception:  # nosec B110
            pass

        return False

    @staticmethod
    def resolve_quantized_index_type(
        *,
        base_index_type: str,
        quantization: str | None,
    ) -> str:
        """Resolve base index type and quantization setting into the appropriate index algorithm.

        Args:
            base_index_type: Base index type (e.g. 'HNSW', 'IVF_FLAT', 'GPU_IVF_FLAT').
            quantization: Quantization option ('SQ8', 'PQ', 'PRQ', 'NONE', or None).

        Returns:
            Resolved index type string.
        """
        if not quantization or quantization.upper() in ("NONE", ""):
            return base_index_type

        q_upper = quantization.upper()
        if q_upper == "SQ8":
            if base_index_type == MilvusIndexTypes.HNSW:
                return MilvusIndexTypes.HNSW_SQ
            if base_index_type in (MilvusIndexTypes.IVF_FLAT, MilvusIndexTypes.FLAT):
                return MilvusIndexTypes.IVF_SQ8
        elif q_upper == "PQ":
            if base_index_type == MilvusIndexTypes.HNSW:
                return MilvusIndexTypes.HNSW_PQ
            if base_index_type in (MilvusIndexTypes.IVF_FLAT, MilvusIndexTypes.FLAT):
                return MilvusIndexTypes.IVF_PQ
            if base_index_type in (MilvusIndexTypes.GPU_IVF_FLAT, MilvusIndexTypes.GPU_FLAT):
                return MilvusIndexTypes.GPU_IVF_PQ
        elif q_upper == "PRQ":
            if base_index_type == MilvusIndexTypes.HNSW:
                return MilvusIndexTypes.HNSW_PRQ

        return base_index_type

    @staticmethod
    def adapt_fallback_parameters(
        *,
        gpu_index_type: str,
        cpu_index_type: str,
        current_parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Adapt index parameters when falling back from a GPU index to a CPU index.

        Args:
            gpu_index_type: The original GPU index type.
            cpu_index_type: The fallback CPU index type.
            current_parameters: Custom or default index parameters.

        Returns:
            Adapted parameters dict suitable for the CPU index type.
        """
        adapted = INDEX_DEFAULT_PARAMETERS.get(cpu_index_type, {}).copy()
        user_params = current_parameters.copy()

        # Remove CAGRA specific parameters that have no meaning on CPU HNSW
        cagra_keys = {
            "intermediate_graph_degree",
            "graph_degree",
            "build_algo",
            "cache_dataset_on_device",
            "adapt_for_cpu",
        }
        for k in cagra_keys:
            user_params.pop(k, None)

        adapted.update(user_params)
        return adapted

    def __init__(
        self,
        *,
        client: MilvusClient,
        collection_name: str,
        index_type: str = MilvusIndexTypes.HNSW,
        metric_type: str = MilvusMetricTypes.L2,
        index_parameters: dict[str, Any] | None = None,
        available_features: dict[str, Any] | None = None,
        feature_mappings: list[dict[str, str]] | None = None,
        primary_key_field: str = OperatorConstants.VectorDB.DEFAULT_PRIMARY_KEY_FIELD,
        auto_id: bool = False,
        add_sparse_vector: bool = False,
        is_lite: bool = False,
        quantization: str | None = None,
        quantization_parameters: dict[str, Any] | None = None,
        search_parameters: dict[str, Any] | None = None,
        use_gpu: bool | None = None,
        gpu_device_id: int | None = None,
    ) -> None:
        """
        Initialize the index manager.

        Args:
            client: Milvus client instance
            collection_name: Name of the collection
            index_type: Index type (FLAT, IVF_FLAT, HNSW, GPU_CAGRA, etc.)
            metric_type: Similarity metric (L2, IP, COSINE)
            index_parameters: Custom index-specific parameters
            available_features: Feature configuration
            feature_mappings: Column to field mappings
            primary_key_field: Name of primary key field
            auto_id: Whether to auto-generate IDs
            add_sparse_vector: Whether to use sparse vectors instead of dense vectors
            is_lite: Whether running against Milvus Lite (.db file)
            quantization: Quantization option ('SQ8', 'PQ', 'PRQ', 'NONE')
            quantization_parameters: Quantization tuning parameters
            search_parameters: Search-time parameters (e.g. nprobe, search_width)
            use_gpu: Explicit GPU acceleration flag
            gpu_device_id: Target GPU device index
        """
        self.client = client
        self.collection_name = collection_name
        self.requested_index_type = index_type
        self.metric_type = metric_type
        self.index_parameters = (index_parameters or {}).copy()
        self.available_features = available_features or {}
        self.feature_mappings: list[dict[str, str]] = feature_mappings or []
        self._mapping_dict: dict[str, str] = build_mapping_dict(self.feature_mappings)
        self.primary_key_field = primary_key_field
        self.auto_id = auto_id
        self.add_sparse_vector = add_sparse_vector
        self.is_lite = is_lite
        self.quantization = quantization
        self.quantization_parameters = quantization_parameters or {}
        self.search_parameters = search_parameters or {}
        self.use_gpu = use_gpu
        self.gpu_device_id = gpu_device_id
        self.gpu_fallback_triggered: bool = False
        self.gpu_fallback_reason: str | None = None

        # 1. Merge quantization parameters if provided
        if self.quantization_parameters:
            self.index_parameters.update(self.quantization_parameters)

        # 2. Resolve quantized index type if quantization option is provided
        resolved_index_type = self.resolve_quantized_index_type(
            base_index_type=index_type,
            quantization=quantization,
        )
        self.index_type = resolved_index_type

        # 3. Handle explicit use_gpu flag
        if self.use_gpu is True and self.index_type in CPU_TO_GPU_UPGRADE_MAP:
            if not self.is_lite:
                self.index_type = CPU_TO_GPU_UPGRADE_MAP[self.index_type]
        elif self.use_gpu is False and self.index_type in GPU_TO_CPU_FALLBACK_MAP:
            self.index_type = GPU_TO_CPU_FALLBACK_MAP[self.index_type]

        # 4. Enforce Milvus Lite restrictions on GPU index types
        if self.is_lite and self.index_type in MilvusIndexTypes.ALL_GPU_TYPES:
            raise DocpipeException(
                message=(
                    f"MilvusDB Error: GPU index type '{self.index_type}' is not supported by Milvus Lite. "
                    "Milvus Lite runs as an embedded local database without GPU acceleration. "
                    "Set index_type to 'FLAT' or use a standalone/remote Milvus deployment with GPU."
                ),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        # 5. Automatic GPU detection and graceful fallback
        if not self.is_lite and self.index_type in MilvusIndexTypes.ALL_GPU_TYPES:
            has_gpu = self.detect_gpu_available(device_id=self.gpu_device_id)
            if not has_gpu:
                fallback_type = GPU_TO_CPU_FALLBACK_MAP.get(self.index_type, MilvusIndexTypes.FLAT)
                logger.warning(
                    "GPU not available for index type '%s'. Falling back to CPU index '%s'.",
                    self.index_type,
                    fallback_type,
                )
                self.index_parameters = self.adapt_fallback_parameters(
                    gpu_index_type=self.index_type,
                    cpu_index_type=fallback_type,
                    current_parameters=self.index_parameters,
                )
                self.index_type = fallback_type
                self.gpu_fallback_triggered = True
                self.gpu_fallback_reason = "No GPU detected during initialization"
            else:
                logger.info(
                    "GPU acceleration enabled for index_type '%s' (device_id=%s)",
                    self.index_type,
                    self.gpu_device_id if self.gpu_device_id is not None else "default",
                )

        self._validate_index_type()
        self._validate_metric_type()

    def _validate_index_type(self) -> None:
        """Validate index type. Skip validation in sparse mode as index type is set programmatically."""
        logger.info(
            "Validating index type: index_type=%s, add_sparse_vector=%s, is_lite=%s",
            self.index_type,
            self.add_sparse_vector,
            self.is_lite,
        )

        # Skip validation in sparse mode
        if self.add_sparse_vector:
            logger.info("Sparse mode enabled, skipping index type validation (using %s)", self.index_type)
            return

        # Milvus Lite only supports FLAT
        if self.is_lite and self.index_type not in MilvusIndexTypes.LITE_SUPPORTED_DENSE_TYPES:
            raise DocpipeException(
                message=(
                    f"MilvusDB Error: index_type '{self.index_type}' is not supported by Milvus Lite. "
                    f"Supported index types for Lite: {MilvusIndexTypes.LITE_SUPPORTED_DENSE_TYPES}. "
                    "Set index_type to 'FLAT' in your provider_config when using auth_type='lite'."
                ),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        # Validate dense index types
        if self.index_type not in MilvusIndexTypes.ALL_DENSE_TYPES:
            raise DocpipeException(
                message=f"MilvusDB Error: Invalid index type '{self.index_type}'. Supported: {MilvusIndexTypes.ALL_DENSE_TYPES}",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

    def _validate_metric_type(self) -> None:
        """Validate metric type and ensure sparse mode uses BM25."""
        if self.metric_type not in MilvusMetricTypes.ALL_TYPES:
            raise DocpipeException(
                message=f"MilvusDB Error: Invalid metric type '{self.metric_type}'. Supported: {MilvusMetricTypes.ALL_TYPES}",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        # Note: In sparse mode, metric_type applies to dense vectors only
        # Sparse vectors always use BM25 (hardcoded in create_collection)

    def _get_index_parameters(self) -> dict[str, Any]:
        """Get index parameters, merging defaults with custom parameters."""
        default_params = INDEX_DEFAULT_PARAMETERS.get(self.index_type, {}).copy()

        if self.index_parameters:
            default_params.update(self.index_parameters)

        # Remove dimension for sparse vectors (not needed for BM25)
        if self.add_sparse_vector and "dim" in default_params:
            del default_params["dim"]

        return default_params

    def _create_schema_fields(self, *, dimension_mapping: dict[str, int]) -> list[FieldSchema]:
        """
        Create schema fields based on available features and dimension mapping.
        Handles both dense and sparse vector modes, supporting multiple vector columns.

        Args:
            dimension_mapping: Dictionary mapping vector column names to their dimensions

        Returns:
            List of FieldSchema objects
        """
        fields: list[FieldSchema] = []

        # Add primary key field
        fields.append(
            FieldSchema(
                name=self.primary_key_field,
                dtype=DataType.VARCHAR,
                is_primary=True,
                auto_id=self.auto_id,
                max_length=512,
            )
        )

        # Track which vector columns have been added
        added_vector_columns: set[str] = set()

        # Add sparse vector field if in sparse mode
        if self.add_sparse_vector:
            # Sparse vector field - auto-generated by BM25 function
            # Get Milvus field name (sparse_embeddings -> sparse_vector)
            sparse_vector_field_name = self._mapping_dict.get(
                OperatorConstants.Columns.SPARSE_EMBEDDINGS_COLUMN_DEFAULT,
                OperatorConstants.VectorDB.SPARSE_VECTOR_FIELD_NAME,
            )
            fields.append(
                FieldSchema(
                    name=sparse_vector_field_name,
                    dtype=DataType.SPARSE_FLOAT_VECTOR,
                    description="Sparse text embeddings generated by BM25",
                )
            )

        # Add ALL dense vector fields from dimension_mapping (supports multi-model)
        for vector_column, dimension in dimension_mapping.items():
            # Get the mapped field name for this vector column
            vector_field_name = self._mapping_dict.get(vector_column, vector_column)

            logger.info(
                "Adding dense vector field: source_column='%s', milvus_field='%s', dimension=%s",
                vector_column,
                vector_field_name,
                dimension,
            )

            fields.append(
                FieldSchema(
                    name=vector_field_name,
                    dtype=DataType.FLOAT_VECTOR,
                    dim=dimension,
                )
            )
            added_vector_columns.add(vector_column)

        # Add content field (always needed, but enable_analyzer only for sparse mode).
        # In dense mode the content value comes from per-chunk data and may be absent
        # for some rows, so mark it nullable to avoid insert failures.
        content_field_name = self._mapping_dict.get(
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
            OperatorConstants.VectorDB.DEFAULT_TEXT_FIELD_NAME,
        )
        content_field_params: dict[str, Any] = {
            "name": content_field_name,
            "dtype": DataType.VARCHAR,
            "max_length": 65535,
            "enable_analyzer": self.add_sparse_vector,  # Enable analyzer only for BM25 sparse mode
        }
        if not self.add_sparse_vector:
            # BM25 sparse mode requires the field to be non-nullable (analyser needs it);
            # dense mode allows NULL so chunk rows without text can still be inserted.
            content_field_params["nullable"] = True
        fields.append(FieldSchema(**content_field_params))

        # Add other fields from feature_mappings (only fields that are actually mapped)
        for source_column_name, milvus_field_name in feature_mapping_items(self.feature_mappings):
            # Skip vector columns (already added)
            if source_column_name in added_vector_columns:
                continue

            # Skip content field (already added)
            if source_column_name == OperatorConstants.Columns.DOC_COLUMN_DEFAULT:
                continue

            # Skip sparse embeddings field (already added in sparse mode)
            if source_column_name == OperatorConstants.Columns.SPARSE_EMBEDDINGS_COLUMN_DEFAULT:
                continue

            # Skip if this field maps to the primary key (already added)
            if milvus_field_name == self.primary_key_field:
                continue

            # Skip if this field maps to vector or sparse_vector (already added)
            if milvus_field_name in (
                OperatorConstants.VectorDB.DENSE_VECTOR_FIELD_NAME,
                OperatorConstants.VectorDB.SPARSE_VECTOR_FIELD_NAME,
            ):
                continue

            # Get feature config for type information
            feature_config = self.available_features.get(source_column_name, {})

            # Skip if explicitly marked as unavailable for vector db
            if not feature_config.get(OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB, True):
                continue

            # Skip vector type features (should have been in dimension_mapping)
            feature_type = feature_config.get(OperatorConstants.Misc.TYPE, OperatorConstants.Types.TYPE_TEXT)
            if feature_type == OperatorConstants.Types.TYPE_VECTOR:
                continue

            # Map feature type to Milvus DataType
            dtype = self._map_feature_type_to_milvus_dtype(feature_type=feature_type)

            if dtype:
                field_params: dict[str, Any] = {"name": milvus_field_name, "dtype": dtype}

                # Add max_length for VARCHAR fields
                if dtype == DataType.VARCHAR:
                    field_params["max_length"] = 65535

                # Make field nullable if not mandatory
                # Milvus requires all fields to be present unless nullable=True or default_value is set
                is_mandatory = feature_config.get(OperatorConstants.Config.MANDATORY_FOR_VECTOR_DB, False)
                if not is_mandatory:
                    field_params["nullable"] = True

                fields.append(FieldSchema(**field_params))

        return fields

    def _map_feature_type_to_milvus_dtype(self, *, feature_type: str) -> DataType | None:
        """
        Map feature type to Milvus DataType.

        Args:
            feature_type: Feature type string

        Returns:
            Milvus DataType or None if not supported
        """
        type_mapping: dict[str, DataType] = {
            "text": DataType.VARCHAR,
            "string": DataType.VARCHAR,
            "keyword": DataType.VARCHAR,
            "long": DataType.INT64,
            "integer": DataType.INT32,
            "short": DataType.INT16,
            "byte": DataType.INT8,
            "double": DataType.DOUBLE,
            "float": DataType.FLOAT,
            "boolean": DataType.BOOL,
            "date": DataType.VARCHAR,  # Store as string
            "json": DataType.JSON,
        }

        return type_mapping.get(feature_type)

    def collection_exists(self) -> bool:
        """
        Check if collection exists.

        Returns:
            True if collection exists, False otherwise
        """
        try:
            return self.client.has_collection(collection_name=self.collection_name)  # type: ignore[return-value]
        except Exception as e:
            logger.error("Error checking collection existence: %s", e)
            return False

    def validate_existing_collection(self, *, dimension_mapping: dict[str, int]) -> None:
        """Validate existing Milvus collection schema against runtime vector dimensions."""
        try:
            collection_description: dict[str, Any] = self.client.describe_collection(
                collection_name=self.collection_name
            )  # type: ignore[assignment]
            fields = collection_description.get("fields", [])

            existing_dimensions: dict[str, Any] = {}
            for field in fields:
                field_name = field.get("name")
                if not field_name:
                    continue

                field_params = field.get("params", {})
                if "dim" in field_params:
                    existing_dimensions[field_name] = field_params.get("dim")

            mismatches: list[str] = []
            for vector_column, runtime_dimension in dimension_mapping.items():
                mapped_field_name = self._mapping_dict.get(vector_column, vector_column)
                existing_dimension = existing_dimensions.get(mapped_field_name)

                if existing_dimension is None:
                    mismatches.append(
                        f"field '{mapped_field_name}' (source '{vector_column}') is missing from existing collection schema"
                    )
                    continue

                if existing_dimension != runtime_dimension:
                    mismatches.append(
                        f"field '{mapped_field_name}' (source '{vector_column}') has existing dimension "
                        f"{existing_dimension} but current run produced {runtime_dimension}"
                    )

            if mismatches:
                raise DocpipeException(
                    message=(
                        f"Vector dimension mismatch for existing Milvus collection '{self.collection_name}': "
                        + "; ".join(mismatches)
                    ),
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
                )
        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                message=f"MilvusDB Error: Failed to validate collection '{self.collection_name}': {e}",
                status_code=500,
                error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
            ) from e

    def _create_bm25_function(self) -> Any:
        """
        Create BM25 function for sparse vector generation.

        Returns:
            Function object for BM25 text-to-sparse-vector conversion
        """

        content_field_name = self._mapping_dict.get(
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
            OperatorConstants.VectorDB.DEFAULT_TEXT_FIELD_NAME,
        )
        vector_field_name = self._mapping_dict.get(
            OperatorConstants.Columns.SPARSE_EMBEDDINGS_COLUMN_DEFAULT,
            OperatorConstants.VectorDB.SPARSE_VECTOR_FIELD_NAME,
        )

        return Function(
            name="text_bm25_emb",
            function_type=FunctionType.BM25,
            input_field_names=[content_field_name],
            output_field_names=[vector_field_name],
            params={},
        )

    def create_collection(self, *, dimension_mapping: dict[str, int]) -> None:
        """
        Create the Milvus collection if it doesn't exist.
        Handles both dense and sparse vector modes, supporting multiple vector columns.

        Args:
            dimension_mapping: Dictionary mapping vector column names to their dimensions

        For sparse mode with BM25:
        - Creates collection with schema (NO index during creation)
        - Index must be created separately after data insertion

        Raises:
            DocpipeException: If collection creation fails
        """
        if self.collection_exists():
            raise DocpipeException(
                message=f"Collection '{self.collection_name}' already exists. Please use a different collection name or delete the existing collection.",
                status_code=409,
                error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
            )

        try:
            # Create schema fields with dimension mapping
            fields = self._create_schema_fields(dimension_mapping=dimension_mapping)

            # Log schema field details
            field_names = [f.name for f in fields]
            logger.info(
                "[MILVUS COLLECTION] Creating collection '%s' with %s fields: %s",
                self.collection_name,
                len(fields),
                field_names,
            )

            # Create collection schema
            if self.add_sparse_vector:
                logger.info(
                    "[MILVUS COLLECTION] Sparse vector mode enabled - creating BM25 function for text-to-sparse-vector conversion"
                )
                bm25_function = self._create_bm25_function()

                # Log BM25 function details
                content_field = self._mapping_dict.get(
                    OperatorConstants.Columns.DOC_COLUMN_DEFAULT, OperatorConstants.VectorDB.DEFAULT_TEXT_FIELD_NAME
                )
                sparse_field = OperatorConstants.VectorDB.SPARSE_VECTOR_FIELD_NAME
                logger.info("BM25 function: '%s' -> '%s'", content_field, sparse_field)

                schema = CollectionSchema(
                    fields=fields,
                    description=f"Collection for {self.collection_name}",
                    functions=[bm25_function],
                )
            else:
                logger.info(
                    "[MILVUS COLLECTION] Dense vector mode - creating collection with %s vector field(s)",
                    len(dimension_mapping),
                )
                schema = CollectionSchema(
                    fields=fields,
                    description=f"Collection for {self.collection_name}",
                )

            # Create collection with schema (no indexes yet)
            self.client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
            )

            logger.info("[MILVUS COLLECTION] Collection '%s' created successfully", self.collection_name)

            # Create sparse vector index if in sparse mode
            if self.add_sparse_vector:
                sparse_vector_field_name = self._mapping_dict.get(
                    OperatorConstants.Columns.SPARSE_EMBEDDINGS_COLUMN_DEFAULT,
                    OperatorConstants.VectorDB.SPARSE_VECTOR_FIELD_NAME,
                )

                # Prepare and create index for sparse vector with hardcoded parameters
                sparse_index_params = self.client.prepare_index_params()
                sparse_index_params.add_index(
                    field_name=sparse_vector_field_name,
                    index_type=MilvusIndexTypes.SPARSE_INVERTED_INDEX,
                    metric_type=MilvusMetricTypes.BM25,
                    params={
                        "inverted_index_algo": "DAAT_MAXSCORE",
                        "bm25_k1": 1.2,
                        "bm25_b": 0.75,
                    },
                )

                self.client.create_index(
                    collection_name=self.collection_name,
                    index_params=sparse_index_params,
                )

                logger.info(
                    "[MILVUS COLLECTION] Sparse vector index created on '%s' (index_type=%s, metric=%s)",
                    sparse_vector_field_name,
                    MilvusIndexTypes.SPARSE_INVERTED_INDEX,
                    MilvusMetricTypes.BM25,
                )

            # Create dense vector indexes for ALL vector fields (both sparse and dense modes)
            params_dict = self._get_index_parameters()
            dense_index_params = self.client.prepare_index_params()

            for vector_column, dimension in dimension_mapping.items():
                # Get the mapped field name for this vector column
                vector_field_name = self._mapping_dict.get(vector_column, vector_column)

                logger.info(
                    "[MILVUS COLLECTION] Creating index on dense vector field '%s' (source: '%s', dimension: %s)",
                    vector_field_name,
                    vector_column,
                    dimension,
                )

                dense_index_params.add_index(
                    field_name=vector_field_name,
                    index_type=self.index_type,
                    metric_type=self.metric_type,
                    params=params_dict,
                )

            # Create indexes for dense vector fields
            self.client.create_index(
                collection_name=self.collection_name,
                index_params=dense_index_params,
            )

            logger.info(
                "[MILVUS COLLECTION] Dense vector indexes created for %s field(s) (index_type=%s, metric=%s)",
                len(dimension_mapping),
                self.index_type,
                self.metric_type,
            )

        except Exception as e:
            raise DocpipeException(
                message=f"MilvusDB Error: Failed to create collection '{self.collection_name}': {e}",
                status_code=500,
                error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
            ) from e

    def get_collection_info(self) -> dict[str, Any]:
        """
        Get collection information.

        Returns:
            Dictionary with collection details

        Raises:
            DocpipeException: If collection doesn't exist or retrieval fails
        """
        if not self.collection_exists():
            raise DocpipeException(
                message=f"MilvusDB Error: Collection '{self.collection_name}' does not exist",
                status_code=404,
                error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
            )

        try:
            stats = self.client.get_collection_stats(collection_name=self.collection_name)
            return {
                "name": self.collection_name,
                "row_count": stats.get("row_count", 0),
                "exists": True,
            }
        except Exception as e:
            raise DocpipeException(
                message=f"MilvusDB Error: Failed to get collection info for '{self.collection_name}': {e}",
                status_code=500,
                error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
            ) from e

    def drop_collection(self) -> None:
        """
        Drop the collection.

        Raises:
            DocpipeException: If collection drop fails
        """
        try:
            if self.collection_exists():
                self.client.drop_collection(collection_name=self.collection_name)
                logger.info("Dropped collection '%s'", self.collection_name)
            else:
                logger.warning("Collection '%s' does not exist, nothing to drop", self.collection_name)
        except Exception as e:
            raise DocpipeException(
                message=f"MilvusDB Error: Failed to drop collection '{self.collection_name}': {e}",
                status_code=500,
                error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
            ) from e
