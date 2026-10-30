# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Document set adapters for various storage backends."""

from docpipe.core.assets.document_sets.adapters.duckdb import DuckDBDocumentSetStorage
from docpipe.core.assets.document_sets.adapters.postgres import PostgresDocumentSetStorage

__all__ = [
    "DuckDBDocumentSetStorage",
    "PostgresDocumentSetStorage",
]
