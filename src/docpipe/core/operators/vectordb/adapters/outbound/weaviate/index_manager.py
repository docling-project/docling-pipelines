"""Weaviate Index Manager for collection creation, schema validation, and lifecycle management."""

import re
from typing import Any

import weaviate
from weaviate.classes.config import (
    Configure,
    DataType,
    Property,
    Tokenization,
    VectorDistances,
)

from docpipe.core.constants import OperatorConstants
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.client import WeaviateClient
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.vectordb_utils import build_mapping_dict

logger = get_logger()

# Reserved Weaviate property names and prefixes
RESERVED_PROPERTY_NAMES: frozenset[str] = frozenset(
    {
        "id",
        "_id",
        "vector",
        "_vector",
        "_creationTimeUnix",
        "_lastUpdateTimeUnix",
        "_additional",
        "_featureProjection",
    }
)

RESERVED_SUFFIXES: tuple[str, ...] = (
    "_searchable",
    "_rangeable",
    "_temp",
    "__meta_count",
    "_propertyLength",
    "_nullState",
)

PROPERTY_NAME_REGEX = re.compile(r"^[a-zA-Z][_0-9a-zA-Z]*$")

DISTANCE_METRIC_MAP: dict[str, VectorDistances] = {
    "cosine": VectorDistances.COSINE,
    "dot": VectorDistances.DOT,
    "l2-squared": VectorDistances.L2_SQUARED,
    "manhattan": VectorDistances.MANHATTAN,
    "hamming": VectorDistances.HAMMING,
}


def map_feature_type(feature_type: str | None) -> DataType:
    """Map a docpipe feature type string to a Weaviate DataType."""
    if not feature_type:
        return DataType.TEXT
    ft = feature_type.lower()
    if ft in ("int8", "int16", "int32", "int64", "integer", "long", "short", "byte"):
        return DataType.INT
    if ft in ("float", "double", "number"):
        return DataType.NUMBER
    if ft in ("bool", "boolean"):
        return DataType.BOOL
    return DataType.TEXT


def tokenization_for(
    feature_name: str,
    column_name: str,
    feature_type: str | None,
) -> Tokenization:
    """Determine Weaviate Tokenization for a property based on identity vs content semantics."""
    if column_name == "pk":
        return Tokenization.FIELD
    if feature_name in ("id", "doc_id", "name", "doc_name") or column_name in ("id", "name"):
        return Tokenization.FIELD
    if feature_type and feature_type.lower() == "keyword":
        return Tokenization.FIELD
    return Tokenization.WORD


def validate_property_names(property_names: list[str]) -> None:
    """Validate property names against Weaviate naming conventions and server normalization rules.

    Raises DocpipeException on:
    - Invalid regex
    - First character uppercase (server would store lowercased, leading to divergence)
    - Reserved property names
    - Reserved suffixes
    - Case-folded duplicates
    """
    seen_casefolded: dict[str, str] = {}
    for name in property_names:
        if name in RESERVED_PROPERTY_NAMES:
            raise DocpipeException(
                message=f"Property name '{name}' is reserved in Weaviate",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        if not PROPERTY_NAME_REGEX.match(name):
            raise DocpipeException(
                message=f"Property name '{name}' is invalid; must start with a letter and contain only ASCII letters, digits, and underscores",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        if name[0].isupper():
            suggested = name[0].lower() + name[1:]
            raise DocpipeException(
                message=f"Property name '{name}' starts with an uppercase letter; please use '{suggested}' instead",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        for suffix in RESERVED_SUFFIXES:
            if name.endswith(suffix):
                raise DocpipeException(
                    message=f"Property name '{name}' ends with reserved suffix '{suffix}'",
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                )

        folded = name.casefold()
        if folded in seen_casefolded:
            existing = seen_casefolded[folded]
            raise DocpipeException(
                message=f"Duplicate property names when case-folded: '{existing}' and '{name}'",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )
        seen_casefolded[folded] = name


def validate_primary_key_mapping(
    *,
    feature_mappings: list[dict[str, str]],
    available_features: dict[str, Any] | None = None,
) -> None:
    """Validate primary key mapping rules.

    The primary feature must map to 'pk', and no other feature may map to 'pk'.
    """
    features = available_features or {}
    primary_feature: str | None = None

    for name, meta in features.items():
        if isinstance(meta, dict) and (meta.get("is_primary") is True or "primary" in meta.get("tags", [])):
            primary_feature = name
            break

    if not primary_feature and "doc_id_hash" in features:
        primary_feature = "doc_id_hash"
    if not primary_feature:
        primary_feature = "doc_id_hash"

    for entry in feature_mappings:
        feat_name = entry.get(OperatorConstants.Misc.FEATURE_NAME, entry.get("feature_name"))
        col_name = entry.get(
            OperatorConstants.Misc.MAPPED_COLUMN_NAME,
            entry.get("collection_column", entry.get("mapped_column_name")),
        )
        if not feat_name or not col_name:
            continue

        if feat_name == primary_feature and col_name != "pk":
            raise DocpipeException(
                message=f"Primary feature '{primary_feature}' must be mapped to column 'pk', got '{col_name}'",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        if feat_name != primary_feature and col_name == "pk":
            raise DocpipeException(
                message=f"Only the primary feature '{primary_feature}' can be mapped to column 'pk', but feature '{feat_name}' is mapped to 'pk'",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )


class WeaviateIndexManager:
    """Manages Weaviate collection creation, validation, and lifecycle."""

    def __init__(
        self,
        *,
        client: WeaviateClient | weaviate.WeaviateClient,
        collection_name: str,
        index_type: str = "hnsw",
        distance_metric: str = "cosine",
        index_parameters: dict[str, Any] | None = None,
        add_sparse_vector: bool = False,
        feature_mappings: list[dict[str, str]] | None = None,
        available_features: dict[str, Any] | None = None,
    ) -> None:
        self.client_wrapper = client if isinstance(client, WeaviateClient) else None
        self._raw_client = client if not isinstance(client, WeaviateClient) else None
        self.collection_name = collection_name
        self.index_type = index_type
        self.distance_metric = distance_metric
        self.index_parameters = index_parameters or {}
        self.add_sparse_vector = add_sparse_vector
        self.feature_mappings = feature_mappings or []
        self.available_features = available_features or {}
        self._mapping_dict = build_mapping_dict(self.feature_mappings)

    def _vector_name(self, feature_name: str) -> str:
        """Return the named-vector name for a dense vector feature (its mapped column, else the feature)."""
        return self._mapping_dict.get(feature_name, feature_name)

    @property
    def client(self) -> weaviate.WeaviateClient:
        if self._raw_client is not None:
            return self._raw_client
        if self.client_wrapper is not None:
            return self.client_wrapper.get_client()
        raise DocpipeException(
            message="No Weaviate client available",
            status_code=500,
            error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
        )

    def collection_exists(self) -> bool:
        """Check if collection exists in Weaviate."""
        try:
            return bool(self.client.collections.exists(self.collection_name))
        except Exception as exc:
            logger.warning("Error checking collection existence: %s", exc)
            return False

    def drop_collection(self) -> bool:
        """Drop collection from Weaviate."""
        try:
            self.client.collections.delete(self.collection_name)
            return True
        except Exception as exc:
            logger.warning("Error deleting collection '%s': %s", self.collection_name, exc)
            return False

    def _build_properties(self, *, dimension_mapping: dict[str, int]) -> list[Property]:
        """Build Weaviate Property schema from feature mappings."""
        properties: list[Property] = [
            Property(
                name="pk",
                data_type=DataType.TEXT,
                tokenization=Tokenization.FIELD,
                index_filterable=True,
                index_searchable=True,
            )
        ]

        added_props: set[str] = {"pk"}
        content_mapped = False

        for entry in self.feature_mappings:
            feat_name = entry.get(OperatorConstants.Misc.FEATURE_NAME, entry.get("feature_name"))
            col_name = entry.get(
                OperatorConstants.Misc.MAPPED_COLUMN_NAME,
                entry.get("collection_column", entry.get("mapped_column_name")),
            )
            if not feat_name or not col_name:
                continue

            if col_name == "pk" or feat_name == "sparse_embeddings":
                continue

            if feat_name in dimension_mapping or col_name in dimension_mapping:
                continue

            if col_name in added_props:
                continue

            feat_meta = self.available_features.get(feat_name, {})
            feat_type = feat_meta.get("type", "text") if isinstance(feat_meta, dict) else "text"
            data_type = map_feature_type(feat_type)
            tokenization = tokenization_for(feat_name, col_name, feat_type)
            is_content = feat_name in ("content", "text") or col_name in ("content", "text")

            if is_content:
                content_mapped = True
                tokenization = Tokenization.WORD

            properties.append(
                Property(
                    name=col_name,
                    data_type=data_type,
                    tokenization=tokenization if data_type == DataType.TEXT else None,
                    index_filterable=True,
                    index_searchable=True if data_type == DataType.TEXT else None,
                )
            )
            added_props.add(col_name)

        if not content_mapped and "content" in self.available_features and "content" not in added_props:
            properties.append(
                Property(
                    name="content",
                    data_type=DataType.TEXT,
                    tokenization=Tokenization.WORD,
                    index_filterable=True,
                    index_searchable=True,
                )
            )

        return properties

    def create_collection(self, *, dimension_mapping: dict[str, int]) -> None:
        """Create a new Weaviate collection with configured properties and vectors."""
        if self.collection_exists():
            raise DocpipeException(
                message=f"Collection '{self.collection_name}' already exists",
                status_code=409,
                error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
            )

        properties = self._build_properties(dimension_mapping=dimension_mapping)

        dist = DISTANCE_METRIC_MAP.get(self.distance_metric, VectorDistances.COSINE)
        vector_config: list[Any] = []

        if not dimension_mapping:
            # Sparse-only run: single non-indexed named vector
            vector_config.append(
                Configure.Vectors.self_provided(
                    name="keyword_only",
                    vector_index_config=Configure.VectorIndex.none(),
                )
            )
        else:
            for vec_feature in dimension_mapping:
                vec_name = self._vector_name(vec_feature)
                idx_cfg: Any
                try:
                    if self.index_type == "hnsw":
                        idx_cfg = Configure.VectorIndex.hnsw(distance_metric=dist, **self.index_parameters)
                    elif self.index_type == "flat":
                        idx_cfg = Configure.VectorIndex.flat(distance_metric=dist, **self.index_parameters)
                    elif self.index_type == "dynamic":
                        idx_cfg = Configure.VectorIndex.dynamic(distance_metric=dist, **self.index_parameters)
                    else:
                        idx_cfg = Configure.VectorIndex.hnsw(distance_metric=dist, **self.index_parameters)
                except (TypeError, ValueError) as exc:
                    raise DocpipeException(
                        message=f"Invalid index_parameters for index_type '{self.index_type}': {exc}",
                        status_code=400,
                        error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                    ) from None

                vector_config.append(
                    Configure.Vectors.self_provided(
                        name=vec_name,
                        vector_index_config=idx_cfg,
                    )
                )

        inverted_index_config = None
        if self.add_sparse_vector:
            inverted_index_config = Configure.inverted_index(bm25_k1=1.2, bm25_b=0.75)

        try:
            self.client.collections.create(
                name=self.collection_name,
                properties=properties,
                vector_config=vector_config,
                inverted_index_config=inverted_index_config,
            )
            logger.info("Successfully created Weaviate collection '%s'", self.collection_name)
        except Exception as exc:
            err_str = str(exc)
            if "422" in err_str and self.index_type == "dynamic":
                raise DocpipeException(
                    message=(
                        "index_type 'dynamic' requires async indexing enabled on the Weaviate server "
                        "(ASYNC_INDEXING=true for self-hosted, or enabled in Weaviate Cloud console). "
                        "Please enable async indexing or use 'hnsw' or 'flat'."
                    ),
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                ) from None

            raise DocpipeException(
                message=f"Failed to create collection '{self.collection_name}': {exc}",
                status_code=500,
                error_code=ErrorCode.OPERATOR_EXECUTION_FAILED,
            ) from None

    def validate_existing_collection(self, *, dimension_mapping: dict[str, int]) -> None:
        """Validate existing collection against runtime schema and add any missing scalar properties."""
        if not self.collection_exists():
            raise DocpipeException(
                message=f"Collection '{self.collection_name}' does not exist",
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        collection = self.client.collections.get(self.collection_name)
        coll_cfg = collection.config.get()
        errors: list[str] = []

        existing_vector_configs = coll_cfg.vector_config or {}

        # 1-3. Vector validation (skipped when dimension_mapping is empty for sparse-only runs)
        if dimension_mapping:
            indexed_vectors = {
                name: cfg
                for name, cfg in existing_vector_configs.items()
                if not getattr(cfg.vector_index_config, "skip", False)
            }

            if not indexed_vectors:
                # Check legacy or keyword-only shape
                has_named_vectors = bool(existing_vector_configs)
                if has_named_vectors:
                    errors.append(
                        f"Collection '{self.collection_name}' is a keyword-only collection and has no indexed vector for dense embeddings"
                    )
                else:
                    errors.append(
                        f"Collection '{self.collection_name}' is a legacy collection with no named vector configurations; docpipe requires self-provided named vectors"
                    )

            for vec_feature in dimension_mapping:
                vec_name = self._vector_name(vec_feature)
                if vec_name not in indexed_vectors:
                    errors.append(
                        f"Vector '{vec_name}' is missing or not indexed in collection '{self.collection_name}'"
                    )

            # Sample dimension check if collection has objects
            try:
                total_count = collection.aggregate.over_all(total_count=True).total_count
                if total_count and total_count > 0:
                    sample_objs = collection.query.fetch_objects(
                        limit=1,
                        include_vector=[self._vector_name(feature) for feature in dimension_mapping],
                    )
                    if sample_objs.objects:
                        sample_obj = sample_objs.objects[0]
                        for vec_feature, expected_dim in dimension_mapping.items():
                            vec_name = self._vector_name(vec_feature)
                            if sample_obj.vector and vec_name in sample_obj.vector:
                                actual_dim = len(sample_obj.vector[vec_name])
                                if actual_dim != expected_dim:
                                    errors.append(
                                        f"Vector dimension mismatch for '{vec_name}': collection has dimension {actual_dim}, but runtime embedding has dimension {expected_dim}"
                                    )
            except Exception as exc:
                logger.warning("Could not sample vector dimension for collection '%s': %s", self.collection_name, exc)

        # 4-6. Scalar properties and tokenization checks (runs for all runs)
        existing_props = {prop.name.lower(): prop for prop in (coll_cfg.properties or [])}

        missing_props_to_add: list[Property] = []
        expected_properties = self._build_properties(dimension_mapping=dimension_mapping)

        for expected_prop in expected_properties:
            prop_key = expected_prop.name.lower()
            if prop_key not in existing_props:
                missing_props_to_add.append(expected_prop)
                continue

            existing_prop = existing_props[prop_key]
            expected_data_type = getattr(expected_prop, "data_type", None) or getattr(expected_prop, "dataType", None)
            actual_data_type = getattr(existing_prop, "data_type", None) or getattr(existing_prop, "dataType", None)

            # Type check
            if actual_data_type != expected_data_type:
                expected_val = str(getattr(expected_data_type, "value", expected_data_type))
                actual_val = str(getattr(actual_data_type, "value", actual_data_type))
                errors.append(
                    f"Property '{expected_prop.name}' data type mismatch: expected {expected_val}, found {actual_val}"
                )

            # Identity property check
            is_identity = (
                expected_prop.name == "pk" or getattr(expected_prop, "tokenization", None) == Tokenization.FIELD
            )
            if is_identity:
                actual_tokenization = getattr(existing_prop, "tokenization", None)
                actual_filterable = getattr(
                    existing_prop, "index_filterable", getattr(existing_prop, "indexFilterable", False)
                )
                if actual_tokenization != Tokenization.FIELD or not actual_filterable:
                    errors.append(
                        f"Identity property '{expected_prop.name}' must have field tokenization and index_filterable=True, "
                        f"but found tokenization='{actual_tokenization.value if actual_tokenization else 'none'}' and filterable={actual_filterable}. "
                        f"Please recreate the collection with field tokenization or use a new collection name."
                    )

            # Content property check
            is_content = expected_prop.name in ("content", "text")
            if is_content:
                actual_tokenization = getattr(existing_prop, "tokenization", None)
                actual_searchable = getattr(
                    existing_prop, "index_searchable", getattr(existing_prop, "indexSearchable", False)
                )
                if actual_tokenization != Tokenization.WORD or not actual_searchable:
                    errors.append(
                        f"Content property '{expected_prop.name}' must be searchable (index_searchable=True) and word-tokenized, "
                        f"but found tokenization='{actual_tokenization.value if actual_tokenization else 'none'}' and searchable={actual_searchable}. "
                        f"Please recreate the collection with word tokenization or use a new collection name."
                    )

        if errors:
            raise DocpipeException(
                message="\n".join(errors),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        # 7. Add missing properties if all validations passed
        for missing_prop in missing_props_to_add:
            try:
                collection.config.add_property(missing_prop)
                logger.info("Added missing property '%s' to collection '%s'", missing_prop.name, self.collection_name)
            except Exception as exc:
                logger.warning(
                    "Failed to add property '%s' to collection '%s': %s", missing_prop.name, self.collection_name, exc
                )
