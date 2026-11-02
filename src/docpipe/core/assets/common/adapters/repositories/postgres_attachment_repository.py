"""PostgreSQL adapter for AttachmentRepository.

Persists AttachmentRef records as JSONB rows in ``<schema>.asset_attachments``
under the collection ``"document_set_attachments"``, next to the asset rows
written by ``PostgresAssetRepository``.
"""

from typing import Any

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from docpipe.core.assets.common.adapters.repositories.postgres_storage_utils import (
    DEFAULT_ASSET_SCHEMA,
    PostgresStorageUtils,
)
from docpipe.core.assets.common.domain.models.attachment_ref import AttachmentRef
from docpipe.core.assets.common.domain.ports.attachment_repository import AttachmentRepository
from docpipe.core.assets.common.factories.attachment_repository_factory import AttachmentRepositoryFactory
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@AttachmentRepositoryFactory.register(name=OperatorConstants.DocumentSet.ADAPTER_POSTGRES, display_name="PostgreSQL")
class PostgresAttachmentRepository(AttachmentRepository):
    """PostgreSQL implementation of the AttachmentRepository port.

    Stores each AttachmentRef as a single row keyed by (collection, asset_id).
    ``save`` is an upsert (``INSERT ... ON CONFLICT DO UPDATE``), matching the
    overwrite semantics of the DuckDB adapter.

    Attributes:
        COLLECTION_NAME: Collection name; identical to the DuckDB adapter's.
        _engine: SQLAlchemy engine (shared connection pool).
        _schema: PostgreSQL schema holding the asset tables.
    """

    COLLECTION_NAME = "document_set_attachments"

    def __init__(self, *, engine: Engine, schema: str = DEFAULT_ASSET_SCHEMA, ensure_schema: bool = True) -> None:
        """Initialise with an injected engine.

        Args:
            engine: SQLAlchemy engine connected to the PostgreSQL database.
            schema: PostgreSQL schema for the asset tables.
            ensure_schema: Create the schema/tables if missing (idempotent, concurrency-safe).
        """
        self._engine = engine
        self._schema = schema
        if ensure_schema:
            tables = PostgresStorageUtils.ensure_schema(engine=engine, schema=schema)
        else:
            tables = PostgresStorageUtils.get_tables(schema=schema)
        self._table = tables.attachments
        logger.info("PostgresAttachmentRepository initialised in schema: %s", schema)

    @classmethod
    def create(cls, *, config: dict[str, Any]) -> "PostgresAttachmentRepository":
        """Instantiate with an engine wired from config.

        Args:
            config: Repository config; connection settings under ``postgres``
                with ``DOCPIPE_POSTGRES_*`` environment fallbacks. Other keys
                (e.g. ``database_path``) are ignored.

        Returns:
            Fully initialised ``PostgresAttachmentRepository``.

        Raises:
            RepositoryConfigurationException: If no PostgreSQL password is configured.
            DocpipeException: If the database cannot be reached or initialised.
        """
        try:
            engine = PostgresStorageUtils.get_engine(config=config, owner="document set attachment repository")
            return cls(engine=engine, schema=PostgresStorageUtils.resolve_schema(config=config))
        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to initialise PostgresAttachmentRepository: {e!s}",
                status_code=500,
                error_code=ErrorCode.DOCUMENT_SET_REPOSITORY_ERROR,
            ) from e

    def save(self, *, asset_id: str, data: AttachmentRef) -> None:
        """Persist (insert or overwrite) an AttachmentRef for the given asset.

        Args:
            asset_id: Unique identifier of the owning asset.
            data: AttachmentRef to persist.

        Raises:
            DocpipeException: If the write fails.
        """
        try:
            payload = data.to_dict()
            insert_statement = pg_insert(self._table).values(
                collection=self.COLLECTION_NAME, asset_id=asset_id, data=payload
            )
            statement = insert_statement.on_conflict_do_update(
                index_elements=[self._table.c.collection, self._table.c.asset_id],
                set_={"data": insert_statement.excluded.data, "updated_at": func.now()},
            )
            with self._engine.begin() as connection:
                connection.execute(statement)
            logger.debug("Saved attachment ref for asset: %s", asset_id)
        except Exception as e:
            raise DocpipeException(
                f"Failed to save attachment ref for asset '{asset_id}': {e!s}",
                status_code=500,
                error_code=ErrorCode.DOCUMENT_SET_REPOSITORY_ERROR,
            ) from e

    def get(self, *, asset_id: str) -> AttachmentRef | None:
        """Retrieve the AttachmentRef for the given asset.

        Args:
            asset_id: Unique identifier of the owning asset.

        Returns:
            The persisted AttachmentRef, or None if no record exists.

        Raises:
            DocpipeException: If the read fails.
        """
        try:
            statement = select(self._table.c.data).where(
                self._table.c.collection == self.COLLECTION_NAME,
                self._table.c.asset_id == asset_id,
            )
            with self._engine.connect() as connection:
                raw = connection.execute(statement).scalar_one_or_none()
            if raw is None:
                return None
            return AttachmentRef.from_dict(raw)
        except Exception as e:
            raise DocpipeException(
                f"Failed to get attachment ref for asset '{asset_id}': {e!s}",
                status_code=500,
                error_code=ErrorCode.DOCUMENT_SET_REPOSITORY_ERROR,
            ) from e

    def delete(self, *, asset_id: str) -> bool:
        """Delete the AttachmentRef record for the given asset.

        Args:
            asset_id: Unique identifier of the owning asset.

        Returns:
            True if the record existed and was deleted, False if it was absent.

        Raises:
            DocpipeException: If the deletion fails.
        """
        try:
            statement = (
                delete(self._table)
                .where(
                    self._table.c.collection == self.COLLECTION_NAME,
                    self._table.c.asset_id == asset_id,
                )
                .returning(self._table.c.asset_id)
            )
            with self._engine.begin() as connection:
                deleted = connection.execute(statement).first() is not None
            if deleted:
                logger.debug("Deleted attachment ref for asset: %s", asset_id)
            return deleted
        except Exception as e:
            raise DocpipeException(
                f"Failed to delete attachment ref for asset '{asset_id}': {e!s}",
                status_code=500,
                error_code=ErrorCode.DOCUMENT_SET_REPOSITORY_ERROR,
            ) from e

    def exists(self, *, asset_id: str) -> bool:
        """Check whether an AttachmentRef record exists for the given asset.

        Args:
            asset_id: Unique identifier of the owning asset.

        Returns:
            True if a record exists, False otherwise.

        Raises:
            DocpipeException: If the check fails.
        """
        try:
            statement = select(
                exists().where(
                    self._table.c.collection == self.COLLECTION_NAME,
                    self._table.c.asset_id == asset_id,
                )
            )
            with self._engine.connect() as connection:
                return bool(connection.execute(statement).scalar())
        except Exception as e:
            raise DocpipeException(
                f"Failed to check attachment ref existence for asset '{asset_id}': {e!s}",
                status_code=500,
                error_code=ErrorCode.DOCUMENT_SET_REPOSITORY_ERROR,
            ) from e

    @classmethod
    def validate_config(cls, *, config: dict[str, Any]) -> list[str]:
        """Validate PostgreSQL attachment repository configuration.

        Args:
            config: Repository config dict.

        Returns:
            List of validation error messages; empty if configuration is valid.
        """
        return PostgresStorageUtils.validate_config(config=config)
