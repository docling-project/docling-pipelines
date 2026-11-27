# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pydantic config model for the Milvus vector store adapter."""

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

ADAPTER_NAME = "milvus"


class MilvusConfig(BaseModel):
    """User-facing configuration for the Milvus vector store adapter.

    Describes the fields the user writes inside ``provider_config`` when
    selecting the ``milvus`` provider in a VectorDB operator node.
    """

    # Secret-capable keys (design D2); see docpipe.core.operators.secret_fields.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "host",
        "uri",
        "token",
        "username",
        "password",
        "database",
    )

    model_config = ConfigDict(extra="ignore")

    collection_name: str = Field(
        description="Name of the Milvus collection to write to.",
    )
    host: str = Field(
        default="localhost",
        description="Milvus server hostname or IP address.",
    )
    port: int = Field(
        default=19530,
        description="Milvus server port.",
    )
    uri: str | None = Field(
        default=None,
        description=(
            "Connection URI. Use a local file path ending in '.db' for Milvus Lite "
            "(e.g. './data/milvus/docs.db') or a remote URI (e.g. https://xxx.zillizcloud.com). "
            "Required when auth_type is 'uri' or 'lite'."
        ),
    )
    token: str | None = Field(
        default=None,
        description="API token for Milvus cloud or wx.data deployments.",
    )
    username: str | None = Field(
        default=None,
        description="Username for password-based authentication.",
    )
    password: str | None = Field(
        default=None,
        description="Password for password-based authentication.",
    )
    database: str = Field(
        default="default",
        description="Milvus database name.",
    )
    auth_type: str | None = Field(
        default=None,
        description=(
            "Authentication type. Options: 'standalone' (host/port + username/password), "
            "'grpc' (IBM wx.data via gRPC), 'uri' (pre-built remote URI), "
            "'token' (IAM token), 'lite' (local Milvus Lite .db file — no external service required). "
            "Use 'lite' with a local 'uri' path for container-free operation."
        ),
    )
    secure: bool = Field(
        default=False,
        description="Whether to use a TLS/SSL connection.",
    )
    batch_size: int = Field(
        default=100,
        description="Number of documents to insert per batch.",
    )
    vector_mode: Literal["dense", "sparse", "binary", "gpu"] | None = Field(
        default=None,
        description="Vector indexing mode: 'dense' (default CPU), 'sparse' (BM25), 'binary' (1-bit), or 'gpu' (GPU-accelerated).",
    )
    index_type: Literal[
        "FLAT",
        "IVF_FLAT",
        "IVF_SQ8",
        "IVF_PQ",
        "HNSW",
        "DISKANN",
        "AUTOINDEX",
        "GPU_IVF_FLAT",
        "GPU_IVF_PQ",
        "GPU_CAGRA",
        "GPU_BRUTE_FORCE",
        "BIN_FLAT",
        "BIN_IVF_FLAT",
    ] = Field(
        default="HNSW",
        description=(
            "Vector index algorithm for the dense, GPU or binary vector field. "
            "Milvus Lite (auth_type='lite') only supports FLAT and uses it when this is not set. "
            "Use HNSW for standalone/remote deployments, "
            "GPU_CAGRA, GPU_IVF_FLAT, GPU_IVF_PQ, GPU_BRUTE_FORCE for GPU-accelerated deployments, "
            "or BIN_FLAT / BIN_IVF_FLAT for binary vectors. "
            "The sparse (BM25) field always uses a fixed SPARSE_INVERTED_INDEX and is not configurable."
        ),
    )
    metric_type: Literal[
        "L2",
        "IP",
        "COSINE",
        "BM25",
        "HAMMING",
        "JACCARD",
    ] = Field(
        default="L2",
        description="Vector similarity metric. HAMMING and JACCARD are for binary vectors (Milvus 2.6).",
    )
    index_parameters: dict = Field(
        default_factory=dict,
        description='Index-specific parameters (e.g. {"M": 16, "efConstruction": 256} for HNSW).',
    )
    add_sparse_vector: bool = Field(
        default=False,
        description="Enable sparse vector support using BM25. Kept for backward compatibility (maps to vector_mode='sparse').",
    )

    @staticmethod
    def applicability() -> dict[str, Any]:
        """Describe which index types, metrics and feature types apply together.

        Built from the same constants the index manager validates against, so the
        operator metadata and the runtime rules cannot drift apart.
        """
        # Imported lazily: the index manager pulls in pymilvus, which config import should not require.
        from docpipe.core.constants.operator_constants import OperatorConstants
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.index_manager import (
            MilvusIndexTypes,
            MilvusMetricTypes,
        )

        dense_feature = OperatorConstants.Types.TYPE_VECTOR
        binary_feature = OperatorConstants.Types.TYPE_VECTOR_BINARY
        return {
            "index_families": [
                {
                    "id": "cpu_dense",
                    "index_types": list(MilvusIndexTypes.ALL_DENSE_TYPES),
                    "metric_types": list(MilvusMetricTypes.ALL_DENSE_METRIC_TYPES),
                    "feature_types": [dense_feature],
                },
                {
                    "id": "gpu",
                    "index_types": list(MilvusIndexTypes.ALL_GPU_TYPES),
                    "metric_types": list(MilvusMetricTypes.GPU_VALID_METRICS),
                    "feature_types": [dense_feature],
                },
                {
                    "id": "binary",
                    "index_types": list(MilvusIndexTypes.ALL_BINARY_TYPES),
                    "metric_types": list(MilvusMetricTypes.ALL_BINARY_METRIC_TYPES),
                    "feature_types": [binary_feature],
                },
            ],
            "lite": {
                "index_types": list(MilvusIndexTypes.LITE_SUPPORTED_DENSE_TYPES),
                "default": MilvusIndexTypes.FLAT,
            },
        }
