# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for OutputBuffer."""

from uuid import uuid4

import pyarrow as pa
import pytest

from docpipe.core.orchestration.streaming.graph.output_buffer import (
    OperatorOutput,
    OutputBuffer,
)


class TestOutputBuffer:
    # OutputBuffer stores, retrieves, and clears operator outputs by UUID.

    def test_put_and_get_output(self):
        buffer = OutputBuffer()
        node_id = uuid4()
        table = pa.Table.from_arrays([pa.array([1, 2, 3])], names=["col"])
        output = OperatorOutput(tables=[table], metadata={"status": "success"})

        buffer.put_output(node_id=node_id, output=output)
        retrieved = buffer.get_output(node_id)

        assert retrieved is output
        assert retrieved.tables == [table]
        assert retrieved.metadata == {"status": "success"}

    def test_get_output_missing_key_raises_key_error(self):
        buffer = OutputBuffer()
        node_id = uuid4()

        with pytest.raises(KeyError):
            buffer.get_output(node_id)

    def test_clear_removes_all_outputs(self):
        buffer = OutputBuffer()
        node_1 = uuid4()
        node_2 = uuid4()
        output_1 = OperatorOutput(tables=[], metadata={"id": 1})
        output_2 = OperatorOutput(tables=[], metadata={"id": 2})

        buffer.put_output(node_id=node_1, output=output_1)
        buffer.put_output(node_id=node_2, output=output_2)

        buffer.clear()

        with pytest.raises(KeyError):
            buffer.get_output(node_1)
        with pytest.raises(KeyError):
            buffer.get_output(node_2)
        assert len(buffer.data_buffer) == 0
