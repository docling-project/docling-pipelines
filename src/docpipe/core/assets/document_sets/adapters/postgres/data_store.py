# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""PostgreSQL implementation of DocumentSetStorage.

Writes PyArrow table data to one table per document set in a dedicated
PostgreSQL schema (``content_schema``, default ``docpipe_document_sets``) through
``PostgresTableStorage``. The returned AttachmentRef has the table name in the
common ``name`` field and the schema and table name in ``details``.

Configuration (``assets_management.documentset_repository.config``):
    content_schema: docpipe_document_sets   # schema of the content tables
    postgres:                                # same keys as the metadata repository
      host: localhost                        # falls back to DOCPIPE_POSTGRES_HOST
      ...
      password: ...                          # falls back to DOCPIPE_POSTGRES_PASSWORD

The ``schema`` key inside ``postgres`` is the schema of the metadata tables and is
not used for the content tables, so a document set table can never take the name
of a metadata table.
"""

import re
from typing import Any

from docpipe.core.assets.document_sets.adapters.table_data_store import TableDocumentSetStorage
from docpipe.core.assets.document_sets.factories.data_store_factory import DataStoreFactory
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.storage.interfaces.table_storage_port import TableStoragePort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# PostgreSQL identifiers: letters, digits and underscores, at most 63 characters.
_SCHEMA_NAME_RE = re.compile(r"^\w{1,63}$")


@DataStoreFactory.register(name=OperatorConstants.DocumentSet.ADAPTER_POSTGRES, display_name="PostgreSQL")
class PostgresDocumentSetStorage(TableDocumentSetStorage):
    """PostgreSQL implementation of the DocumentSetStorage port.

    The table operations are shared with the other TableStoragePort backends
    in TableDocumentSetStorage.

    Attributes:
        _storage: PostgresTableStorage of the content schema.
        _schema: PostgreSQL schema of the content tables; embedded in returned AttachmentRefs.
    """

    BACKEND_TYPE = OperatorConstants.DocumentSet.ADAPTER_POSTGRES
    BACKEND_DISPLAY_NAME = "PostgreSQL"

    def __init__(self, *, table_storage: TableStoragePort, schema: str) -> None:
        """Initialise with injected storage and the content schema.

        Args:
            table_storage: TableStoragePort implementation (PostgreSQL-based) of ``schema``.
            schema: PostgreSQL schema of the content tables; stored so it can be
                embedded in returned AttachmentRefs.
        """
        super().__init__(table_storage=table_storage)
        self._schema = schema
        logger.info("PostgresDocumentSetStorage initialised with schema: %s", schema)

    def _backend_details(self) -> dict[str, str]:
        """Return the content schema for AttachmentRef and health check details."""
        return {OperatorConstants.DocumentSet.SCHEMA: self._schema}

    @classmethod
    def from_config(cls, *, config: dict[str, Any]) -> "PostgresDocumentSetStorage":
        """Create a PostgresDocumentSetStorage from a config dict.

        Validates config, creates the PostgresTableStorage, and returns a fully
        initialised instance.

        Args:
            config: Optional ``content_schema`` string and optional ``postgres``
                connection settings. Other keys, such as ``database_path``, are ignored.

        Returns:
            Configured PostgresDocumentSetStorage instance.

        Raises:
            DocpipeException: If config is invalid or storage creation fails.
        """
        from docpipe.storage import StorageFactory

        errors = cls.validate_config(config=config)
        if errors:
            raise DocpipeException(
                "; ".join(errors),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            )

        schema = config.get(OperatorConstants.DocumentSet.CONTENT_SCHEMA) or (
            OperatorConstants.DocumentSet.DEFAULT_CONTENT_SCHEMA
        )
        # The schema key in the connection settings belongs to the metadata tables.
        postgres = {
            key: value
            for key, value in (config.get(OperatorConstants.DocumentSet.POSTGRES) or {}).items()
            if key != OperatorConstants.DocumentSet.SCHEMA
        }
        table_storage = StorageFactory.create_table_storage(
            storage_type=OperatorConstants.DocumentSet.ADAPTER_POSTGRES,
            schema=schema,
            postgres=postgres,
        )
        return cls(table_storage=table_storage, schema=schema)

    @classmethod
    def validate_config(cls, *, config: dict[str, Any]) -> list[str]:
        """Validate PostgreSQL storage configuration.

        Args:
            config: Optional ``content_schema`` string and optional ``postgres`` mapping.

        Returns:
            List of validation error messages; empty if configuration is valid.
        """
        errors = []
        schema_key = OperatorConstants.DocumentSet.CONTENT_SCHEMA
        schema = config.get(schema_key)
        if schema is not None and (not isinstance(schema, str) or not _SCHEMA_NAME_RE.match(schema)):
            errors.append(
                f"Configuration '{schema_key}' must be a PostgreSQL schema name of at most 63 letters, "
                "digits and underscores"
            )
        postgres_key = OperatorConstants.DocumentSet.POSTGRES
        postgres = config.get(postgres_key)
        if postgres is not None and not isinstance(postgres, dict):
            errors.append(f"Configuration '{postgres_key}' must be a mapping of connection settings")
        return errors
