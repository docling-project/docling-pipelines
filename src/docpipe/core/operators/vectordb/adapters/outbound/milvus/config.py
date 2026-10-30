"""Pydantic config model for the Milvus vector store adapter."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ADAPTER_NAME = "milvus"


class MilvusConfig(BaseModel):
    """User-facing configuration for the Milvus vector store adapter.

    Describes the fields the user writes inside ``provider_config`` when
    selecting the ``milvus`` provider in a VectorDB operator node.
    """

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
    index_type: Literal[
        "FLAT",
        "IVF_FLAT",
        "IVF_SQ8",
        "IVF_PQ",
        "HNSW",
        "HNSW_SQ",
        "HNSW_PQ",
        "HNSW_PRQ",
        "DISKANN",
        "AUTOINDEX",
        "GPU_FLAT",
        "GPU_IVF_FLAT",
        "GPU_IVF_PQ",
        "GPU_CAGRA",
        "GPU_BRUTE_FORCE",
        "SPARSE_INVERTED_INDEX",
        "SPARSE_WAND",
    ] = Field(
        default="HNSW",
        description=(
            "Vector index algorithm. Milvus Lite (auth_type='lite') only supports FLAT. "
            "Use HNSW, HNSW_SQ, HNSW_PQ for standalone/remote deployments, or "
            "GPU_CAGRA, GPU_IVF_FLAT, GPU_IVF_PQ for GPU-accelerated deployments."
        ),
    )
    metric_type: Literal["L2", "IP", "COSINE", "BM25"] = Field(
        default="L2",
        description="Vector similarity metric.",
    )
    index_parameters: dict = Field(
        default_factory=dict,
        description='Index-specific parameters (e.g. {"M": 16, "efConstruction": 256} for HNSW).',
    )
    quantization: Literal["SQ8", "PQ", "PRQ", "NONE"] | None = Field(
        default=None,
        description=(
            "Vector quantization method to reduce memory consumption. "
            "Options: 'SQ8' (Scalar Quantization, ~75% memory reduction), "
            "'PQ' (Product Quantization, up to 90%+ memory reduction), "
            "'PRQ' (Product Residual Quantization), or None."
        ),
    )
    quantization_parameters: dict = Field(
        default_factory=dict,
        description=(
            "Parameters for vector quantization, e.g. {'m': 16, 'nbits': 8} for PQ or {'sq_type': 'SQ8'} for SQ."
        ),
    )
    search_parameters: dict = Field(
        default_factory=dict,
        description=(
            "Search and query-time parameters (e.g. {'nprobe': 16} for IVF indexes, "
            "{'search_width': 4, 'itopk_size': 64} for GPU_CAGRA, or {'ef': 64} for HNSW)."
        ),
    )
    use_gpu: bool | None = Field(
        default=None,
        description=(
            "Whether to enable GPU acceleration. If true, auto-upgrades compatible CPU indexes "
            "to GPU equivalents if a GPU is available. If None, GPU is used when a GPU index_type is selected."
        ),
    )
    gpu_device_id: int | None = Field(
        default=None,
        description="Target GPU device index (e.g. 0). Defaults to first available GPU.",
    )
    add_sparse_vector: bool = Field(
        default=False,
        description="Enable sparse vector support using BM25. When true, a sparse vector field and BM25 function are added alongside dense vectors.",
    )
