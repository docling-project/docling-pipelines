# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Measure the cost of process isolation for untrusted custom operators (design D12, task D.3 gate).

Each sample starts a fresh worker, loads a minimal operator, and round-trips a 1000-row Arrow table. The first
batch is the gate figure (worker start plus one round-trip); later batches on the same worker show the steady-state
cost. The script exits non-zero when the p95 of the first batch exceeds ``--budget`` (default 2.0 seconds), so CI can
use it as the blocking check.

Usage::

    python scripts/benchmark_isolation_worker.py --samples 20 --budget 2.0
"""

import argparse
import json
import math
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

import pyarrow as pa

from docpipe.core.orchestration.operator_loader.isolation.worker_client import IsolatedWorker

OPERATOR_SOURCE = """
import pyarrow as pa
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory


class BenchOp(AbstractOperator):
    short_name = "bench_op"
    category = OperatorCategory.Functional
    owner = DocpipeConstants.OWNER_CUSTOM

    def transform(self, table: pa.Table, file_name=None):
        return [table.append_column("n", pa.array([len(str(v)) for v in table.column(0).to_pylist()]))], {"rows": table.num_rows}

    @staticmethod
    def get_metadata():
        return {"label": "Bench"}
"""


def _percentile(*, values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]


def measure(*, samples: int, rows: int, later_batches: int) -> dict[str, list[float]]:
    """Return per-sample first-batch and later-batch seconds."""
    table = pa.table({"text": [f"document number {i}" for i in range(rows)]})
    first: list[float] = []
    later: list[float] = []
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "bench_op.py"
        source.write_text(OPERATOR_SOURCE, encoding="utf-8")
        header = {
            "class_name": "BenchOp",
            "short_name": "bench_op",
            "module_path": "bench_op.py",
            "category": "Functional",
            "source_file": str(source),
        }
        for _ in range(samples):
            started = time.perf_counter()
            worker = IsolatedWorker(label="bench_op", source_file=str(source), load_header=header)
            try:
                tables, metadata, _ = worker.run(config={"doc_column": "text"}, table=table)
                first.append(time.perf_counter() - started)
                if tables[0].num_rows != rows or metadata.get("rows") != rows:
                    raise RuntimeError("round-trip returned unexpected data")
                for _ in range(later_batches):
                    batch_started = time.perf_counter()
                    worker.run(config={"doc_column": "text"}, table=table)
                    later.append(time.perf_counter() - batch_started)
            finally:
                worker.stop()
    return {"first": first, "later": later}


def main() -> int:
    """Run the measurement and return the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--later-batches", type=int, default=3)
    parser.add_argument("--budget", type=float, default=2.0, help="p95 limit in seconds for start plus first batch")
    args = parser.parse_args()

    result = measure(samples=args.samples, rows=args.rows, later_batches=args.later_batches)
    p95_first = _percentile(values=result["first"], fraction=0.95)
    p95_later = _percentile(values=result["later"], fraction=0.95) if result["later"] else 0.0
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "samples": args.samples,
        "rows": args.rows,
        "first_batch_seconds": {
            "p50": round(statistics.median(result["first"]), 3),
            "p95": round(p95_first, 3),
            "max": round(max(result["first"]), 3),
        },
        "later_batch_seconds": {"p95": round(p95_later, 3)},
        "budget_seconds": args.budget,
        "within_budget": p95_first <= args.budget and p95_later <= args.budget,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["within_budget"] else 1


if __name__ == "__main__":
    sys.exit(main())
