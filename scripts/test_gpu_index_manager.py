#!/usr/bin/env python3
"""
Quick smoke test for the GPU index manager changes.
No real GPU, no Milvus server, no Docker required.

Tests:
  1. GPU_CAGRA falls back to HNSW when no GPU available
  2. GPU_CAGRA stays as GPU_CAGRA when GPU is forced available
  3. HNSW + use_gpu=True upgrades to GPU_CAGRA
  4. use_gpu=False forces CPU even when a GPU index_type is passed
  5. GPU_IVF_FLAT falls back to IVF_FLAT
  6. GPU_BRUTE_FORCE falls back to FLAT
  7. Milvus Lite rejects GPU index types with a clear error
  8. Quantization resolution: SQ8, PQ, PRQ across CPU and GPU base types
  9. adapt_fallback_parameters strips CAGRA-specific keys
 10. Default parameters exist for every GPU index type
"""

import os
import sys
from unittest.mock import MagicMock

# ── Bootstrap path ────────────────────────────────────────────────────────────
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from docpipe.core.operators.vectordb.adapters.outbound.milvus.index_manager import (
    INDEX_DEFAULT_PARAMETERS,
    MilvusIndexManager,
    MilvusIndexTypes,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException

PASS = "\033[32m[PASS]\033[0m"
FAIL = "\033[31m[FAIL]\033[0m"
errors: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"{PASS} {label}")
    else:
        msg = f"{label}" + (f" — {detail}" if detail else "")
        print(f"{FAIL} {msg}")
        errors.append(msg)


def mock_client() -> MagicMock:
    c = MagicMock()
    c.has_collection.return_value = False
    return c


# ── 1. GPU_CAGRA falls back to HNSW when GPU disabled ────────────────────────
os.environ["DOCPIPE_DISABLE_GPU"] = "true"
os.environ.pop("DOCPIPE_FORCE_GPU", None)

mgr = MilvusIndexManager(
    client=mock_client(),
    collection_name="test",
    index_type="GPU_CAGRA",
    metric_type="L2",
)
check("GPU_CAGRA -> HNSW fallback (no GPU)", mgr.index_type == "HNSW", f"got {mgr.index_type}")
check("gpu_fallback_triggered=True", mgr.gpu_fallback_triggered is True)
check(
    "requested_index_type preserved as GPU_CAGRA",
    mgr.requested_index_type == "GPU_CAGRA",
    f"got {mgr.requested_index_type}",
)

# ── 2. GPU_CAGRA stays when GPU forced available ──────────────────────────────
os.environ["DOCPIPE_FORCE_GPU"] = "true"
os.environ.pop("DOCPIPE_DISABLE_GPU", None)

mgr2 = MilvusIndexManager(
    client=mock_client(),
    collection_name="test",
    index_type="GPU_CAGRA",
    metric_type="L2",
)
check("GPU_CAGRA stays as GPU_CAGRA (GPU available)", mgr2.index_type == "GPU_CAGRA", f"got {mgr2.index_type}")
check("gpu_fallback_triggered=False", mgr2.gpu_fallback_triggered is False)

# ── 3. use_gpu=True upgrades HNSW -> GPU_CAGRA ───────────────────────────────
mgr3 = MilvusIndexManager(
    client=mock_client(),
    collection_name="test",
    index_type="HNSW",
    use_gpu=True,
)
check("HNSW + use_gpu=True -> GPU_CAGRA", mgr3.index_type == "GPU_CAGRA", f"got {mgr3.index_type}")

# ── 4. use_gpu=False forces CPU even when GPU type passed ─────────────────────
mgr4 = MilvusIndexManager(
    client=mock_client(),
    collection_name="test",
    index_type="GPU_CAGRA",
    use_gpu=False,
)
check("GPU_CAGRA + use_gpu=False -> HNSW (explicit, not fallback)", mgr4.index_type == "HNSW", f"got {mgr4.index_type}")
check("gpu_fallback_triggered=False for explicit use_gpu=False", mgr4.gpu_fallback_triggered is False)

# ── 5. GPU_IVF_FLAT falls back to IVF_FLAT ───────────────────────────────────
os.environ["DOCPIPE_DISABLE_GPU"] = "true"
os.environ.pop("DOCPIPE_FORCE_GPU", None)

mgr5 = MilvusIndexManager(
    client=mock_client(),
    collection_name="test",
    index_type="GPU_IVF_FLAT",
    metric_type="L2",
)
check("GPU_IVF_FLAT -> IVF_FLAT fallback", mgr5.index_type == "IVF_FLAT", f"got {mgr5.index_type}")

# ── 6. GPU_BRUTE_FORCE falls back to FLAT ────────────────────────────────────
mgr6 = MilvusIndexManager(
    client=mock_client(),
    collection_name="test",
    index_type="GPU_BRUTE_FORCE",
    metric_type="L2",
)
check("GPU_BRUTE_FORCE -> FLAT fallback", mgr6.index_type == "FLAT", f"got {mgr6.index_type}")

# ── 7. Milvus Lite rejects GPU index types ───────────────────────────────────
os.environ.pop("DOCPIPE_DISABLE_GPU", None)
os.environ.pop("DOCPIPE_FORCE_GPU", None)

try:
    MilvusIndexManager(
        client=mock_client(),
        collection_name="test",
        index_type="GPU_CAGRA",
        is_lite=True,
    )
    check("Lite rejects GPU_CAGRA with DocpipeException", False, "no exception raised")
except DocpipeException as e:
    check("Lite rejects GPU_CAGRA with DocpipeException", True)
    check("Error message mentions Milvus Lite", "Lite" in str(e), f"message: {e}")

# ── 8. Quantization resolution ───────────────────────────────────────────────
cases = [
    ("HNSW", "SQ8", "HNSW_SQ"),
    ("HNSW", "PQ", "HNSW_PQ"),
    ("HNSW", "PRQ", "HNSW_PRQ"),
    ("IVF_FLAT", "SQ8", "IVF_SQ8"),
    ("IVF_FLAT", "PQ", "IVF_PQ"),
    ("FLAT", "SQ8", "IVF_SQ8"),
    ("GPU_IVF_FLAT", "PQ", "GPU_IVF_PQ"),
    ("GPU_FLAT", "PQ", "GPU_IVF_PQ"),
    ("HNSW", None, "HNSW"),
    ("HNSW", "NONE", "HNSW"),
]
for base, quant, expected in cases:
    result = MilvusIndexManager.resolve_quantized_index_type(base_index_type=base, quantization=quant)
    check(f"quantization: {base} + {quant!r} -> {expected}", result == expected, f"got {result}")

# ── 9. adapt_fallback_parameters strips CAGRA-specific keys ──────────────────
adapted = MilvusIndexManager.adapt_fallback_parameters(
    gpu_index_type="GPU_CAGRA",
    cpu_index_type="HNSW",
    current_parameters={
        "intermediate_graph_degree": 64,
        "graph_degree": 32,
        "build_algo": "IVF_PQ",
        "cache_dataset_on_device": False,
        "M": 24,
    },
)
check("adapt_fallback_parameters strips intermediate_graph_degree", "intermediate_graph_degree" not in adapted)
check("adapt_fallback_parameters strips graph_degree", "graph_degree" not in adapted)
check("adapt_fallback_parameters strips build_algo", "build_algo" not in adapted)
check("adapt_fallback_parameters keeps user M override", adapted.get("M") == 24, f"got M={adapted.get('M')}")
check("adapt_fallback_parameters keeps efConstruction default", "efConstruction" in adapted, f"keys: {list(adapted)}")

# ── 10. Default parameters exist for all GPU index types ─────────────────────
for gpu_type in MilvusIndexTypes.ALL_GPU_TYPES:
    check(f"INDEX_DEFAULT_PARAMETERS has entry for {gpu_type}", gpu_type in INDEX_DEFAULT_PARAMETERS)

# ── Summary ───────────────────────────────────────────────────────────────────
print()
if errors:
    print(f"\033[31m{len(errors)} check(s) FAILED:\033[0m")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    total = 10 + len(cases) + len(MilvusIndexTypes.ALL_GPU_TYPES) + 8
    print("\033[32mAll checks passed.\033[0m")
