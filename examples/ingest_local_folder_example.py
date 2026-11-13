#!/usr/bin/env python3
"""
Example: Local Folder Ingestion via IngestSourceOperator

This example demonstrates how to ingest documents from a local folder
using the IngestSourceOperator with the filesystem provider.

Note: IngestLocalOperator was removed. Use IngestSourceOperator with
provider="filesystem" instead — see ingest_filesystem_example.py for the
full equivalent.
"""

import sys
from pathlib import Path
from typing import Any

import pyarrow as pa

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator


def main() -> None:  # pragma: no cover
    """Ingest documents from a local folder using IngestSourceOperator (filesystem provider)."""
    # 1. Construct the operator with the required configuration and input parameters
    operator: IngestSourceOperator = IngestSourceOperator(
        {
            "provider": "filesystem",
            "provider_config": {"paths": ["tests/fixtures/invoices"]},
            "include_filter": "pdf,txt",
        }
    )
    print(operator)

    # 2. Create an in-memory py-arrow table, as the input
    input_table: pa.Table | None = None

    # 3. Run the operator
    table_list: list[pa.Table]
    metadata: dict[str, Any]
    table_list, metadata = operator.transform(input_table)

    row_count = table_list[0].num_rows
    if metadata.get("node_status") != "Completed" or row_count == 0:
        raise RuntimeError(f"Local folder ingest failed: rows={row_count}, metadata={metadata}")

    # 4. Inspect and print the results after the operator is completed
    print(">>> completed the operator", operator)
    print(f"\noutput table has {row_count} rows")

    table: pa.Table = table_list[0]
    print(f"output metadata : {metadata}")
    if table_list[0].num_rows:  # avoid printing if table is empty
        print("Found docs: ", table["name"])


if __name__ == "__main__":  # pragma: no cover
    main()
