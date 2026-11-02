# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""In-memory buffer holding operator output tables and metadata until execution ends."""

from dataclasses import dataclass
from uuid import UUID

import pyarrow as pa

from docpipe.types import OperatorOutputMetadata


@dataclass
class OperatorOutput:
    """Tables and metadata returned by one operator invocation."""

    tables: list[pa.Table]
    metadata: OperatorOutputMetadata


class OutputBuffer:
    """Buffers operator outputs by UUID until cleared."""

    def __init__(self):
        self.data_buffer: dict[UUID, OperatorOutput] = {}

    def put_output(self, node_id: UUID, output: OperatorOutput) -> None:
        """Store a node's output tables and metadata."""
        self.data_buffer[node_id] = output

    def get_output(self, node_id: UUID) -> OperatorOutput:
        """Return a buffered node output without removing it."""
        return self.data_buffer[node_id]

    def clear(self) -> None:
        """Release all buffered outputs at the end of an execution."""
        self.data_buffer.clear()
