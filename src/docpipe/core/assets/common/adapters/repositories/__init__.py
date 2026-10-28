"""Common repository adapters."""

from .duckdb_attachment_repository import DuckDBAttachmentRepository
from .postgres_attachment_repository import PostgresAttachmentRepository

__all__ = ["DuckDBAttachmentRepository", "PostgresAttachmentRepository"]
