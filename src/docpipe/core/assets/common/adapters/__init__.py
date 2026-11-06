"""Common asset adapters.

Imports all adapter implementations to trigger their registration
with the factory classes.
"""

from docpipe.core.assets.common.adapters.repositories import (  # noqa: F401
    DuckDBAttachmentRepository,
    PostgresAttachmentRepository,
)
