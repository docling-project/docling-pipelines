"""Generic PostgreSQL-based repository for all asset types.

PostgreSQL counterpart of ``DuckDBAssetRepository``: same port semantics, but
backed by a shared PostgreSQL server so that several processes (for example
multiple API replicas plus flow workers) can read and write asset metadata
concurrently.

Each asset is stored as one row in ``<schema>.asset_records`` keyed by
``(collection, asset_id)``. The serialised asset (``Asset.to_dict()``) is kept
in a JSONB column; ``name`` is duplicated into its own column with a
``UNIQUE (collection, name)`` constraint so name uniqueness is enforced by the
database rather than by a racy read-then-write.
"""

from typing import Any, cast

from sqlalchemy import Table, delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from docpipe.core.assets.common.adapters.repositories.postgres_storage_utils import (
    DEFAULT_ASSET_SCHEMA,
    PostgresStorageUtils,
)
from docpipe.core.assets.common.domain.models.asset import Asset
from docpipe.core.assets.common.domain.ports.asset_repository import AssetRepository
from docpipe.exceptions.docpipe_exceptions import (
    AssetAlreadyExistsException,
    AssetInvalidDataException,
    AssetNotFoundException,
    DocpipeException,
    RepositoryConfigurationException,
)
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# SQLSTATE for unique_violation
_UNIQUE_VIOLATION = "23505"


class PostgresAssetRepository[T: Asset](AssetRepository[T]):
    """Generic PostgreSQL repository for any Asset subclass.

    Behaviour mirrors ``DuckDBAssetRepository``:
        - ``save`` rejects duplicate IDs and duplicate names (AssetAlreadyExistsException)
        - ``update`` requires the asset to exist (AssetNotFoundException) and rejects
          a name owned by another asset (AssetInvalidDataException)
        - listing is newest-first by ``Asset.get_created_at()``

    Every write runs in its own transaction; inserts use
    ``INSERT ... ON CONFLICT DO NOTHING`` so concurrent writers never see
    partial state or raise raw driver errors.

    Attributes:
        _asset_type: The asset type class (DocumentSet, DocumentLibrary, etc.)
        _engine: SQLAlchemy engine (shared connection pool)
        _schema: PostgreSQL schema holding the asset tables
        _table: The ``asset_records`` table bound to ``_schema``
        _collection: Collection name derived from the asset type

    Usage:
        repo = PostgresAssetRepository.from_config(
            asset_type=DocumentSet,
            config={"postgres": {"host": "db", "password": "..."}},
        )
        saved = repo.save(asset=DocumentSet(name="my_set"))
    """

    def __init__(
        self,
        *,
        asset_type: type[T],
        engine: Engine,
        schema: str = DEFAULT_ASSET_SCHEMA,
        ensure_schema: bool = True,
    ) -> None:
        """Initialize the repository with an injected engine.

        Args:
            asset_type: The asset type class (DocumentSet, DocumentLibrary, etc.)
            engine: SQLAlchemy engine connected to the PostgreSQL database
            schema: PostgreSQL schema for the asset tables
            ensure_schema: Create the schema/tables if missing (idempotent, concurrency-safe)
        """
        self._asset_type = asset_type
        self._engine = engine
        self._schema = schema
        if ensure_schema:
            tables = PostgresStorageUtils.ensure_schema(engine=engine, schema=schema)
        else:
            tables = PostgresStorageUtils.get_tables(schema=schema)
        self._table: Table = tables.records
        if hasattr(asset_type, "get_collection_name"):
            self._collection = asset_type.get_collection_name()
        else:
            self._collection = f"{asset_type.__name__.lower()}s"
        logger.info(
            "PostgresAssetRepository initialized for %s with collection '%s' in schema '%s'",
            asset_type.__name__,
            self._collection,
            schema,
        )

    # ==================== CRUD Operations ====================

    def save(self, *, asset: T) -> T:
        """Save a new asset to the repository.

        Args:
            asset: The asset to save

        Returns:
            The saved asset

        Raises:
            AssetAlreadyExistsException: If an asset with the same ID or name already exists
            AssetInvalidDataException: If asset validation fails
            DocpipeException: If the repository is not accessible
        """
        asset.validate()

        if not asset.asset_id:
            raise AssetInvalidDataException(f"{self._asset_type.__name__} asset_id cannot be None")

        try:
            data = asset.to_dict()
            statement = (
                pg_insert(self._table)
                .values(
                    collection=self._collection,
                    asset_id=asset.asset_id,
                    name=asset.name,
                    data=data,
                    asset_created_at=asset.get_created_at(),
                )
                .on_conflict_do_nothing()
                .returning(self._table.c.asset_id)
            )
            with self._engine.begin() as connection:
                inserted = connection.execute(statement).first()
                if inserted is None:
                    self._raise_save_conflict(connection=connection, asset=asset)

            logger.info("Saved %s: %s (name: %s)", self._asset_type.__name__, asset.asset_id, asset.name)
            return asset

        except (AssetAlreadyExistsException, AssetInvalidDataException):
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to save {self._asset_type.__name__}: {e!s}",
                status_code=500,
            ) from e

    def find_by_id(self, *, asset_id: str) -> T | None:
        """Retrieve an asset by its unique identifier.

        Args:
            asset_id: The unique identifier of the asset

        Returns:
            The asset with the specified ID, or None if not found

        Raises:
            DocpipeException: If the repository is not accessible
        """
        try:
            statement = select(self._table.c.data).where(
                self._table.c.collection == self._collection,
                self._table.c.asset_id == asset_id,
            )
            with self._engine.connect() as connection:
                data = connection.execute(statement).scalar_one_or_none()

            if data is None:
                return None

            asset = self._to_asset(data=data)
            logger.debug("Retrieved %s: %s", self._asset_type.__name__, asset_id)
            return asset

        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to retrieve {self._asset_type.__name__}: {e!s}",
                status_code=500,
            ) from e

    def find_by_name(self, *, name: str) -> T | None:
        """Retrieve an asset by its name.

        Args:
            name: The name of the asset

        Returns:
            The asset with the specified name, or None if not found

        Raises:
            DocpipeException: If the repository is not accessible
        """
        try:
            statement = select(self._table.c.data).where(
                self._table.c.collection == self._collection,
                self._table.c.name == name,
            )
            with self._engine.connect() as connection:
                data = connection.execute(statement).scalar_one_or_none()

            if data is None:
                return None

            asset = self._to_asset(data=data)
            logger.debug("Retrieved %s by name: %s", self._asset_type.__name__, name)
            return asset

        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to retrieve {self._asset_type.__name__} by name: {e!s}",
                status_code=500,
            ) from e

    def update(self, *, asset: T) -> T:
        """Update an existing asset in the repository.

        The existence check, the name-conflict check and the write run in one
        transaction with the target row locked (``SELECT ... FOR UPDATE``).

        Args:
            asset: The asset with updated fields

        Returns:
            The updated asset

        Raises:
            AssetNotFoundException: If the asset does not exist
            AssetInvalidDataException: If the update would violate constraints
            DocpipeException: If the repository is not accessible
        """
        asset.validate()

        if not asset.asset_id:
            raise AssetInvalidDataException(f"{self._asset_type.__name__} asset_id cannot be None")

        try:
            with self._engine.begin() as connection:
                locked = connection.execute(
                    select(self._table.c.asset_id)
                    .where(
                        self._table.c.collection == self._collection,
                        self._table.c.asset_id == asset.asset_id,
                    )
                    .with_for_update()
                ).first()
                if locked is None:
                    raise AssetNotFoundException(
                        f"{self._asset_type.__name__} not found: {asset.asset_id}",
                        asset_id=asset.asset_id,
                        asset_type=self._asset_type.__name__,
                    )

                if self._name_taken_by_other(connection=connection, name=asset.name, asset_id=asset.asset_id):
                    raise self._name_conflict_on_update(name=asset.name)

                asset.update_timestamp()
                data = asset.to_dict()
                connection.execute(
                    update(self._table)
                    .where(
                        self._table.c.collection == self._collection,
                        self._table.c.asset_id == asset.asset_id,
                    )
                    .values(
                        name=asset.name,
                        data=data,
                        asset_created_at=asset.get_created_at(),
                        updated_at=func.now(),
                    )
                )

            logger.info("Updated %s: %s", self._asset_type.__name__, asset.asset_id)
            return asset

        except (AssetNotFoundException, AssetInvalidDataException):
            raise
        except IntegrityError as e:
            if getattr(e.orig, "pgcode", None) == _UNIQUE_VIOLATION:
                # A concurrent writer took the name between our check and the UPDATE.
                raise self._name_conflict_on_update(name=asset.name) from e
            raise DocpipeException(
                f"Failed to update {self._asset_type.__name__}: {e!s}",
                status_code=500,
            ) from e
        except Exception as e:
            raise DocpipeException(
                f"Failed to update {self._asset_type.__name__}: {e!s}",
                status_code=500,
            ) from e

    def delete(self, *, asset_id: str) -> bool:
        """Delete an asset from the repository.

        Args:
            asset_id: The unique identifier of the asset to delete

        Returns:
            True if the asset was deleted, False if it did not exist

        Raises:
            DocpipeException: If the repository is not accessible
        """
        try:
            statement = (
                delete(self._table)
                .where(
                    self._table.c.collection == self._collection,
                    self._table.c.asset_id == asset_id,
                )
                .returning(self._table.c.asset_id)
            )
            with self._engine.begin() as connection:
                deleted = connection.execute(statement).first() is not None

            if deleted:
                logger.info("Deleted %s: %s", self._asset_type.__name__, asset_id)
            else:
                logger.info("%s not found for deletion: %s", self._asset_type.__name__, asset_id)

            return deleted

        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to delete {self._asset_type.__name__}: {e!s}",
                status_code=500,
            ) from e

    def find_all(self) -> list[T]:
        """List all assets in the repository, newest first.

        Returns:
            A list of all assets, empty list if none exist

        Raises:
            DocpipeException: If the repository is not accessible
        """
        return self.list_all()

    def list_all(self, *, limit: int | None = None, offset: int | None = None) -> list[T]:
        """Retrieve assets newest-first, with sorting and pagination done by PostgreSQL.

        Same ordering rule as ``DuckDBAssetRepository``: newest-first by the asset's own
        creation timestamp (``Asset.get_created_at()``, stored in ``asset_created_at``);
        assets without one follow in insertion order.

        Args:
            limit: Maximum number of assets to return (None for all)
            offset: Number of assets to skip (None / 0 for none)

        Returns:
            List of assets sorted by creation date newest-first

        Raises:
            DocpipeException: If the repository is not accessible
        """
        try:
            statement = (
                select(self._table.c.data)
                .where(self._table.c.collection == self._collection)
                .order_by(
                    self._table.c.asset_created_at.desc().nulls_last(),
                    self._table.c.created_at,
                    self._table.c.asset_id,
                )
                .limit(limit)
                .offset(offset or None)
            )
            with self._engine.connect() as connection:
                rows = connection.execute(statement).scalars().all()

            assets = [self._to_asset(data=data) for data in rows]
            logger.debug("Retrieved %d %s assets", len(assets), self._asset_type.__name__)
            return assets

        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to list {self._asset_type.__name__} assets: {e!s}",
                status_code=500,
            ) from e

    # ==================== Existence Checks ====================

    def exists(self, *, asset_id: str) -> bool:
        """Check if an asset exists.

        Args:
            asset_id: The unique identifier to check

        Returns:
            True if an asset with the given ID exists, False otherwise

        Raises:
            DocpipeException: If the repository is not accessible
        """
        try:
            statement = select(
                exists().where(
                    self._table.c.collection == self._collection,
                    self._table.c.asset_id == asset_id,
                )
            )
            with self._engine.connect() as connection:
                return bool(connection.execute(statement).scalar())
        except DocpipeException:
            raise
        except Exception as e:
            raise DocpipeException(
                f"Failed to check {self._asset_type.__name__} existence: {e!s}",
                status_code=500,
            ) from e

    def exists_by_name(self, *, name: str) -> bool:
        """Check if an asset with the given name exists.

        Args:
            name: The name to check

        Returns:
            True if an asset with this name exists, False otherwise

        Raises:
            DocpipeException: If the repository is not accessible
        """
        return self.find_by_name(name=name) is not None

    # ==================== Model-specific Operations ====================

    def partial_update(self, asset: T, updates: dict[str, Any]) -> T:
        """Apply partial updates to an existing asset.

        Args:
            asset: Asset entity to update
            updates: Dictionary of field updates to apply

        Returns:
            Updated asset with refreshed timestamp

        Raises:
            AssetInvalidDataException: If validation fails after applying updates
            DocpipeException: If persistence fails
        """
        for field, value in updates.items():
            if hasattr(asset, field):
                setattr(asset, field, value)

        asset.validate()
        asset.update_timestamp()
        return self.update(asset=asset)

    def bulk_delete(self, *, asset_ids: list[str]) -> dict[str, Any]:
        """Delete multiple assets in a single transaction.

        Duplicate IDs in the request are reported once as deleted and then as
        "not found", matching the per-ID behaviour of the DuckDB adapter.

        Args:
            asset_ids: List of asset IDs to delete

        Returns:
            Dictionary with deletion results
        """
        unique_ids = list(dict.fromkeys(asset_ids))
        deleted: list[str] = []
        failed: list[dict[str, str]] = []

        try:
            removed: set[str] = set()
            if unique_ids:
                statement = (
                    delete(self._table)
                    .where(
                        self._table.c.collection == self._collection,
                        self._table.c.asset_id.in_(unique_ids),
                    )
                    .returning(self._table.c.asset_id)
                )
                with self._engine.begin() as connection:
                    removed = set(connection.execute(statement).scalars().all())
        except Exception as e:
            logger.warning("Bulk delete of %d %s assets failed: %s", len(unique_ids), self._asset_type.__name__, e)
            failed = [{"asset_id": asset_id, "error": str(e)} for asset_id in asset_ids]
            return self._bulk_delete_result(asset_ids=asset_ids, deleted=deleted, failed=failed)

        for asset_id in asset_ids:
            if asset_id in removed:
                deleted.append(asset_id)
                removed.discard(asset_id)
                logger.info("Deleted %s: %s", self._asset_type.__name__, asset_id)
            else:
                failed.append({"asset_id": asset_id, "error": self._asset_type.__name__ + " not found"})

        return self._bulk_delete_result(asset_ids=asset_ids, deleted=deleted, failed=failed)

    # ==================== Construction ====================

    @classmethod
    def from_config(cls, *, asset_type: type[T], config: dict[str, Any]) -> "PostgresAssetRepository[T]":
        """Create a PostgresAssetRepository from a repository config dict.

        Args:
            asset_type: The asset model class (DocumentSet, DocumentLibrary, etc.)
            config: Repository config. Connection settings live under ``postgres``
                (host, port, database, user, password, pool_size, max_overflow,
                pool_timeout, schema); missing values fall back to the
                ``DOCPIPE_POSTGRES_*`` environment variables. Keys meant for other
                backends (e.g. ``database_path``) are ignored.

        Returns:
            Configured PostgresAssetRepository instance

        Raises:
            RepositoryConfigurationException: If the config is invalid or no password is configured
            PostgresConnectionException: If the database cannot be reached
        """
        errors = cls.validate_config(config=config)
        if errors:
            raise RepositoryConfigurationException(
                f"Invalid config for {asset_type.__name__} postgres repository: {'; '.join(errors)}",
                repository_type="postgres",
            )

        engine = PostgresStorageUtils.get_engine(config=config, owner=f"{asset_type.__name__} repository")
        return cls(
            asset_type=asset_type,
            engine=engine,
            schema=PostgresStorageUtils.resolve_schema(config=config),
        )

    @classmethod
    def validate_config(cls, *, config: dict[str, Any]) -> list[str]:
        """Validate repository configuration.

        Args:
            config: Configuration dictionary to validate

        Returns:
            List of validation error strings (empty = valid)
        """
        return PostgresStorageUtils.validate_config(config=config)

    # ==================== Utility Operations ====================

    def health_check(self) -> dict[str, Any]:
        """Check the health status of the repository.

        Returns:
            A dictionary containing health status information
        """
        details: dict[str, Any] = {
            "backend": "postgres",
            "database": PostgresStorageUtils.describe_engine(engine=self._engine),
            "schema": self._schema,
            "collection": self._collection,
            "asset_type": self._asset_type.__name__,
        }
        try:
            statement = select(exists().where(self._table.c.collection == self._collection))
            with self._engine.connect() as connection:
                details["collection_exists"] = bool(connection.execute(statement).scalar())
            return {"status": "healthy", "message": "Repository is healthy", "details": details}
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"Health check failed: {e}",
                "details": {**details, "error": str(e)},
            }

    # ==================== Internal Helpers ====================

    def _to_asset(self, *, data: dict[str, Any]) -> T:
        """Deserialise a stored JSONB payload into the repository's asset type."""
        return cast(T, self._asset_type.from_dict(data=data))

    def _name_taken_by_other(self, *, connection: Connection, name: str, asset_id: str) -> bool:
        """Return True if another asset in this collection already uses ``name``."""
        statement = select(
            exists().where(
                self._table.c.collection == self._collection,
                self._table.c.name == name,
                self._table.c.asset_id != asset_id,
            )
        )
        return bool(connection.execute(statement).scalar())

    def _raise_save_conflict(self, *, connection: Connection, asset: T) -> None:
        """Raise the AssetAlreadyExistsException matching the conflicting unique key.

        Checked in the same order as the DuckDB adapter: ID first, then name.
        """
        id_taken = connection.execute(
            select(
                exists().where(
                    self._table.c.collection == self._collection,
                    self._table.c.asset_id == asset.asset_id,
                )
            )
        ).scalar()
        if id_taken:
            raise AssetAlreadyExistsException(
                f"{self._asset_type.__name__} with ID '{asset.asset_id}' already exists",
                asset_id=asset.asset_id,
                asset_type=self._asset_type.__name__,
            )
        raise AssetAlreadyExistsException(
            f"{self._asset_type.__name__} with name '{asset.name}' already exists",
            asset_name=asset.name,
            asset_type=self._asset_type.__name__,
        )

    @staticmethod
    def _name_conflict_on_update(*, name: str) -> AssetInvalidDataException:
        """Build the exception raised when an update would duplicate a name."""
        return AssetInvalidDataException(f"Update would violate constraints: name '{name}' already exists")

    @staticmethod
    def _bulk_delete_result(
        *, asset_ids: list[str], deleted: list[str], failed: list[dict[str, str]]
    ) -> dict[str, Any]:
        """Build the bulk delete result dictionary defined by the port."""
        return {
            "total_requested": len(asset_ids),
            "total_deleted": len(deleted),
            "total_failed": len(failed),
            "deleted": deleted,
            "failed": failed,
        }
