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
from docpipe.utils.operators.vectordb_utils import (
    build_mapping_dict,
    feature_mapping_items,
    is_binary_vector_feature,
)

logger = get_logger()


class MilvusMetricTypes:
    """Vector similarity metrics supported by Milvus"""

    # Dense vector similarity metrics
    L2: str = "L2"
    IP: str = "IP"  # Inner Product
    COSINE: str = "COSINE"
    BM25: str = "BM25"  # BM25 for sparse vectors
    ALL_DENSE_METRIC_TYPES: ClassVar[list[str]] = [L2, IP, COSINE]

    # Binary vector similarity metrics
    HAMMING: str = "HAMMING"
    JACCARD: str = "JACCARD"
    TANIMOTO: str = "TANIMOTO"
    SUBSTRUCTURE: str = "SUBSTRUCTURE"
    SUPERSTRUCTURE: str = "SUPERSTRUCTURE"
    ALL_BINARY_METRIC_TYPES: ClassVar[list[str]] = [
        HAMMING,
        JACCARD,
        TANIMOTO,
        SUBSTRUCTURE,
        SUPERSTRUCTURE,
    ]

    ALL_TYPES: ClassVar[list[str]] = [L2, IP, COSINE, BM25, *ALL_BINARY_METRIC_TYPES]


class MilvusIndexTypes:
    """Index types supported by Milvus"""

    # Dense vector index types
    FLAT: str = "FLAT"
    IVF_FLAT: str = "IVF_FLAT"
    IVF_SQ8: str = "IVF_SQ8"
    IVF_PQ: str = "IVF_PQ"
    HNSW: str = "HNSW"
    DISKANN: str = "DISKANN"
    AUTOINDEX: str = "AUTOINDEX"

    # Sparse vector index types
    SPARSE_INVERTED_INDEX: str = "SPARSE_INVERTED_INDEX"
    SPARSE_WAND: str = "SPARSE_WAND"

    # Binary vector index types
    BIN_FLAT: str = "BIN_FLAT"
    BIN_IVF_FLAT: str = "BIN_IVF_FLAT"

    ALL_DENSE_TYPES: ClassVar[list[str]] = [FLAT, IVF_FLAT, IVF_SQ8, IVF_PQ, HNSW, DISKANN, AUTOINDEX]
    ALL_SPARSE_TYPES: ClassVar[list[str]] = [SPARSE_INVERTED_INDEX, SPARSE_WAND]
    ALL_BINARY_TYPES: ClassVar[list[str]] = [BIN_FLAT, BIN_IVF_FLAT]
    ALL_TYPES: ClassVar[list[str]] = ALL_DENSE_TYPES + ALL_SPARSE_TYPES + ALL_BINARY_TYPES
    # Milvus Lite only supports FLAT for dense vectors
    LITE_SUPPORTED_DENSE_TYPES: ClassVar[list[str]] = [FLAT]


# Default parameters for index types
INDEX_DEFAULT_PARAMETERS: dict[str, dict[str, Any]] = {
    # Dense vector index parameters
    MilvusIndexTypes.FLAT: {},
    MilvusIndexTypes.IVF_FLAT: {"nlist": 128},
    MilvusIndexTypes.IVF_SQ8: {"nlist": 128},
    MilvusIndexTypes.IVF_PQ: {"nlist": 128, "m": 8, "nbits": 8},
    MilvusIndexTypes.HNSW: {"M": 16, "efConstruction": 200},
    MilvusIndexTypes.DISKANN: {},
    MilvusIndexTypes.AUTOINDEX: {},
    # Sparse vector index parameters
    MilvusIndexTypes.SPARSE_INVERTED_INDEX: {"drop_ratio_build": 0.2},
    MilvusIndexTypes.SPARSE_WAND: {"drop_ratio_build": 0.2},
    # Binary vector index parameters
    MilvusIndexTypes.BIN_FLAT: {},
    MilvusIndexTypes.BIN_IVF_FLAT: {"nlist": 128},
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
    """

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
    ) -> None:
        """
        Initialize the index manager.

        Whether a vector field is dense (``FLOAT_VECTOR``) or binary (``BINARY_VECTOR``) is decided
        only by the feature's own type. ``index_type`` / ``metric_type`` / ``index_parameters`` are
        applied to each field according to its kind: dense fields use them as configured; binary
        fields use them when ``index_type`` is a ``BIN_*`` type, otherwise ``BIN_FLAT`` / ``HAMMING``.

        Args:
            client: Milvus client instance
            collection_name: Name of the collection
            index_type: Index type for dense fields (FLAT, IVF_FLAT, HNSW, etc.), or a BIN_* type
                for collections that only hold binary vectors
            metric_type: Similarity metric for dense fields (L2, IP, COSINE), or a binary metric
            index_parameters: Custom index-specific parameters
            available_features: Feature configuration
            feature_mappings: Column to field mappings
            primary_key_field: Name of primary key field
            auto_id: Whether to auto-generate IDs
            add_sparse_vector: Whether to use sparse vectors instead of dense vectors
            is_lite: Whether the collection lives in Milvus Lite
        """
        self.client = client
        self.collection_name = collection_name
        self.index_type = index_type
        self.metric_type = metric_type
        self.index_parameters = index_parameters or {}
        self.available_features = available_features or {}
        self.feature_mappings: list[dict[str, str]] = feature_mappings or []
        self._mapping_dict: dict[str, str] = build_mapping_dict(self.feature_mappings)
        self.primary_key_field = primary_key_field
        self.auto_id = auto_id
        self.add_sparse_vector = add_sparse_vector
        self.is_lite = is_lite

        self._validate_metric_type()
        self._validate_index_type()

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

        # Milvus Lite does not support binary vector indexes
        if self.is_lite and self.index_type in MilvusIndexTypes.ALL_BINARY_TYPES:
            raise DocpipeException(
                message=(
                    f"MilvusDB Error: Binary vector index type '{self.index_type}' is not supported by Milvus Lite. "
                    "Milvus Lite only supports dense vectors with FLAT index. "
                    "Use standalone Milvus or watsonx.data for binary vector indexing."
                ),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

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

        # Validate index types
        if self.index_type not in MilvusIndexTypes.ALL_TYPES:
            raise DocpipeException(
                message=(
                    f"MilvusDB Error: Invalid index type '{self.index_type}'. Supported: {MilvusIndexTypes.ALL_TYPES}"
                ),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        # Validate binary index type pairs with binary metric type
        if (
            self.index_type in MilvusIndexTypes.ALL_BINARY_TYPES
            and self.metric_type not in MilvusMetricTypes.ALL_BINARY_METRIC_TYPES
        ):
            raise DocpipeException(
                message=(
                    f"MilvusDB Error: Binary index type '{self.index_type}' requires a binary metric type. "
                    f"Supported binary metrics: {MilvusMetricTypes.ALL_BINARY_METRIC_TYPES}, got: '{self.metric_type}'"
                ),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        # Dense index types must not be paired with a binary-only metric
        if (
            self.index_type in MilvusIndexTypes.ALL_DENSE_TYPES
            and self.metric_type in MilvusMetricTypes.ALL_BINARY_METRIC_TYPES
        ):
            raise DocpipeException(
                message=(
                    f"MilvusDB Error: Dense index type '{self.index_type}' cannot use binary metric "
                    f"'{self.metric_type}'. Use a dense metric ({MilvusMetricTypes.ALL_DENSE_METRIC_TYPES})."
                ),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

    def validate_vector_feature_types(self, *, feature_types: dict[str, str | None]) -> None:
        """Check the index configuration against the vector feature types known before the run.

        A ``BIN_*`` ``index_type`` needs at least one binary vector feature, which only exists when an
        upstream operator emits one (e.g. embeddings with ``quantization: binary``). Without it the
        collection cannot be created, so the mismatch is reported at validation time.

        Args:
            feature_types: Mapping of input feature name to its propagated feature type.

        Raises:
            DocpipeException: A ``BIN_*`` index type is configured but no binary vector feature is available.
        """
        if self.add_sparse_vector or self.index_type not in MilvusIndexTypes.ALL_BINARY_TYPES:
            return
        if any(is_binary_vector_feature(feature_config={"type": ftype}) for ftype in feature_types.values()):
            return
        raise DocpipeException(
            message=(
                f"MilvusDB Error: Binary index type '{self.index_type}' requires a binary vector feature, but none "
                "is available from upstream operators. Set 'quantization' to 'binary' or 'ubinary' on the "
                "embeddings operator, or set 'index_type' to a dense index (e.g. HNSW)."
            ),
            status_code=400,
            error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
        )

    def _has_binary_field(self, *, dimension_mapping: dict[str, int]) -> bool:
        """Return True when any vector column in the mapping is a binary vector feature."""
        return any(
            is_binary_vector_feature(feature_config=self.available_features.get(column, {}))
            for column in dimension_mapping
        )

    def _resolve_vector_index_config(
        self, *, vector_field_name: str, is_binary: bool, has_binary_field: bool
    ) -> tuple[str, str, dict[str, Any]]:
        """Resolve the (index_type, metric_type, params) used to index one vector field.

        The configured ``index_type`` / ``metric_type`` / ``index_parameters`` are applied to the fields
        they are valid for; the other kind of field gets a safe default derived from its own data type:

        - Dense index type (HNSW, ...): dense fields use the configuration as-is; binary fields use
          ``BIN_FLAT`` / ``HAMMING``.
        - Binary index type (BIN_*): binary fields use the configuration as-is; dense fields (only possible
          in a mixed collection) use ``HNSW`` / ``L2`` defaults.

        Args:
            vector_field_name: Milvus field name (for error messages)
            is_binary: Whether the field is a binary vector
            has_binary_field: Whether the collection holds at least one binary vector field

        Returns:
            Tuple of (index_type, metric_type, index parameters)

        Raises:
            DocpipeException: A BIN_* index type is configured but the collection has no binary vector field.
        """
        config_is_binary = self.index_type in MilvusIndexTypes.ALL_BINARY_TYPES

        if is_binary and config_is_binary:
            return self.index_type, self.metric_type, self._get_index_parameters()

        if is_binary:
            metric = (
                self.metric_type if self.metric_type in MilvusMetricTypes.ALL_BINARY_METRIC_TYPES else None
            ) or MilvusMetricTypes.HAMMING
            return MilvusIndexTypes.BIN_FLAT, metric, INDEX_DEFAULT_PARAMETERS.get(MilvusIndexTypes.BIN_FLAT, {}).copy()

        if not config_is_binary:
            return self.index_type, self.metric_type, self._get_index_parameters()

        if not has_binary_field:
            raise DocpipeException(
                message=(
                    f"MilvusDB Error: Dense vector field '{vector_field_name}' cannot use binary index type "
                    f"'{self.index_type}' and the collection has no binary vector field. "
                    "Set 'index_type' to a dense index (e.g. HNSW)."
                ),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )
        return (
            MilvusIndexTypes.HNSW,
            MilvusMetricTypes.L2,
            INDEX_DEFAULT_PARAMETERS.get(MilvusIndexTypes.HNSW, {}).copy(),
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

        has_binary_field = self._has_binary_field(dimension_mapping=dimension_mapping)

        # Add ALL vector fields from dimension_mapping (supports dense, binary, and multi-model)
        for vector_column, dimension in dimension_mapping.items():
            # Get the mapped field name for this vector column
            vector_field_name = self._mapping_dict.get(vector_column, vector_column)
            is_binary = is_binary_vector_feature(feature_config=self.available_features.get(vector_column, {}))

            # Fail before any schema/collection is created if this field cannot be indexed as configured
            self._resolve_vector_index_config(
                vector_field_name=vector_field_name, is_binary=is_binary, has_binary_field=has_binary_field
            )

            if is_binary:
                if self.is_lite:
                    raise DocpipeException(
                        message=(
                            f"MilvusDB Error: Binary vector field '{vector_field_name}' is not supported by "
                            "Milvus Lite. "
                            "Use standalone Milvus or watsonx.data for binary vector indexing."
                        ),
                        status_code=400,
                        error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                    )
                if dimension % 8 != 0:
                    raise DocpipeException(
                        message=(
                            f"MilvusDB Error: Binary vector field '{vector_field_name}' dimension must be a "
                            f"multiple of 8 (got {dimension})."
                        ),
                        status_code=400,
                        error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                    )

                logger.info(
                    "Adding binary vector field: source_column='%s', milvus_field='%s', dimension=%s bits",
                    vector_column,
                    vector_field_name,
                    dimension,
                )
                fields.append(
                    FieldSchema(
                        name=vector_field_name,
                        dtype=DataType.BINARY_VECTOR,
                        dim=dimension,
                    )
                )
            else:
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
        if feature_type in (
            "binary_vector",
            "vector_binary",
            OperatorConstants.Types.TYPE_VECTOR_BINARY,
        ):
            return DataType.BINARY_VECTOR

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

            # Create vector indexes for ALL vector fields (dense, binary, and multi-model)
            dense_index_params = self.client.prepare_index_params()
            has_binary_field = self._has_binary_field(dimension_mapping=dimension_mapping)

            for vector_column, dimension in dimension_mapping.items():
                # Get the mapped field name for this vector column
                vector_field_name = self._mapping_dict.get(vector_column, vector_column)
                is_binary = is_binary_vector_feature(feature_config=self.available_features.get(vector_column, {}))
                field_index_type, field_metric_type, field_params = self._resolve_vector_index_config(
                    vector_field_name=vector_field_name, is_binary=is_binary, has_binary_field=has_binary_field
                )

                logger.info(
                    "[MILVUS COLLECTION] Creating index on %s vector field '%s' "
                    "(source: '%s', dimension: %s, index_type=%s, metric=%s)",
                    "binary" if is_binary else "dense",
                    vector_field_name,
                    vector_column,
                    dimension,
                    field_index_type,
                    field_metric_type,
                )
                dense_index_params.add_index(
                    field_name=vector_field_name,
                    index_type=field_index_type,
                    metric_type=field_metric_type,
                    params=field_params,
                )

            # Create indexes for vector fields
            self.client.create_index(
                collection_name=self.collection_name,
                index_params=dense_index_params,
            )

            logger.info(
                "[MILVUS COLLECTION] Vector indexes created for %s field(s)",
                len(dimension_mapping),
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
