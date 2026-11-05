# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pydantic config model for the Milvus vector store adapter."""

from typing import Any, Literal

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
        "GPU_IVF_FLAT",
        "GPU_IVF_PQ",
        "GPU_CAGRA",
        "GPU_BRUTE_FORCE",
        "SPARSE_INVERTED_INDEX",
        "SPARSE_WAND",
        "BIN_FLAT",
        "BIN_IVF_FLAT",
    ] = Field(
        default="HNSW",
        description=(
            "Vector index algorithm. Milvus Lite (auth_type='lite') only supports FLAT. "
            "Use HNSW, HNSW_SQ, HNSW_PQ for standalone/remote deployments, "
            "GPU_CAGRA, GPU_IVF_FLAT, GPU_IVF_PQ for GPU-accelerated deployments, "
            "or BIN_FLAT / BIN_IVF_FLAT for binary vectors."
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
    quantization: Literal["SQ8", "PQ", "PRQ", "NONE"] | None = Field(
        default=None,
        description=(
            "Vector quantization method to reduce memory consumption. "
            "Options: 'SQ8' (Scalar Quantization, ~75% memory reduction), "
            "'PQ' (Product Quantization, up to 90%+ memory reduction), "
            "'PRQ' (Product Residual Quantization), or None."
        ),
    )
    quantization_parameters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Parameters for vector quantization, e.g. {'m': 16, 'nbits': 8} for PQ or {'sq_type': 'SQ8'} for SQ."
        ),
    )
    use_gpu: bool | None = Field(
        default=None,
        description=(
            "Whether to use a GPU index. If true, a CPU index (including a quantized one) is upgraded to its "
            "GPU equivalent (HNSW -> GPU_CAGRA, IVF_FLAT -> GPU_IVF_FLAT, IVF_PQ/HNSW_PQ -> GPU_IVF_PQ, "
            "FLAT -> GPU_BRUTE_FORCE). If false, a GPU index is downgraded to its CPU equivalent. "
            "If None, index_type is used as given. The Milvus server must be a GPU build."
        ),
    )
    fallback_to_cpu: bool = Field(
        default=False,
        description=(
            "If true and the Milvus server rejects a GPU index during index creation (for example a CPU-only "
            "Milvus image), retry with the CPU equivalent index instead of failing. Off by default so an "
            "explicitly requested GPU index is never silently downgraded."
        ),
    )
    add_sparse_vector: bool = Field(
        default=False,
        description="Enable sparse vector support using BM25. When true, a sparse vector field and BM25 function are added alongside dense vectors.",
    )
