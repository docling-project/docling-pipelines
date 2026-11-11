# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Port for reading the intermediate output a node saved in an earlier job run."""

from abc import ABC, abstractmethod

import pyarrow as pa


class NodeOutputReader(ABC):
    """Reads rows of documents from the saved output of a node of a previous job run."""

    @abstractmethod
    def read_rows(
        self,
        *,
        job_run_id: str,
        node_name: str,
        output_index: int,
        doc_ids: list[str],
    ) -> pa.Table | None:
        """Return the saved rows of ``doc_ids`` from output ``output_index`` of ``node_name``.

        Returns ``None`` when the output is missing or holds none of the documents.
        """
