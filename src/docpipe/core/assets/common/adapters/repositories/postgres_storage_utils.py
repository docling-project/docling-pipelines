# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Shared PostgreSQL plumbing for the asset metadata and attachment repositories.

Holds the SQLAlchemy table definitions, a process-wide engine cache, and the
idempotent schema bootstrap used by ``PostgresAssetRepository`` and
``PostgresAttachmentRepository``.

Schema management:
    Tables live in a dedicated PostgreSQL schema (default ``docpipe_assets``) so
    they never collide with the job stats tables, and the job stats Alembic
    environment (``include_schemas=False``) never sees them during autogenerate.
    The tables are created with ``CREATE SCHEMA/TABLE IF NOT EXISTS`` semantics
    inside a single transaction that first takes a transaction-scoped advisory
    lock, so several processes (e.g. API replicas) can bootstrap concurrently.

Connection configuration (consistent with the PostgreSQL job stats store):
    config:
      postgres:
        host: localhost          # falls back to DOCPIPE_POSTGRES_HOST
        port: 5432               # falls back to DOCPIPE_POSTGRES_PORT
        database: docpipe        # falls back to DOCPIPE_POSTGRES_DB
        user: docpipe_user       # falls back to DOCPIPE_POSTGRES_USER
        password: secret         # falls back to DOCPIPE_POSTGRES_PASSWORD (required)
        pool_size: 5
        max_overflow: 10
        pool_timeout: 30
        schema: docpipe_assets   # optional, PostgreSQL schema for the asset tables
"""

import re
import threading
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy import Column, DateTime, Index, MetaData, Table, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateSchema

from docpipe.core.constants import DocpipeConfigKeys
from docpipe.exceptions.docpipe_exceptions import RepositoryConfigurationException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

DEFAULT_ASSET_SCHEMA = "docpipe_assets"
SCHEMA_CONFIG_KEY = "schema"
RECORDS_TABLE_NAME = "asset_records"
ATTACHMENTS_TABLE_NAME = "asset_attachments"
RECORDS_NAME_UNIQUE_CONSTRAINT = "uq_asset_records_collection_name"
RECORDS_LISTING_INDEX = "ix_asset_records_listing"

# Arbitrary but fixed key for pg_advisory_xact_lock; serialises schema bootstrap across processes.
_SCHEMA_BOOTSTRAP_LOCK_KEY = 5_400_054_054
_SCHEMA_NAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_POSTGRES_REPOSITORY_TYPE = "postgres"


@dataclass(frozen=True)
class PostgresAssetTables:
    """SQLAlchemy table definitions bound to one PostgreSQL schema.

    Attributes:
        schema: PostgreSQL schema the tables live in.
        metadata: MetaData holding both tables (used for ``create_all``).
        records: Asset metadata table, one row per (collection, asset_id).
        attachments: Attachment reference table, one row per (collection, asset_id).
    """

    schema: str
    metadata: MetaData
    records: Table
    attachments: Table


class PostgresStorageUtils:
    """Engine access, table registry and schema bootstrap for asset repositories.

    Engines come from ``get_shared_postgres_engine``, so every repository instance
    in a process, and every other PostgreSQL component with the same settings,
    shares one connection pool per distinct connection configuration. This
    matters because ``DocumentSetOperator`` builds its repositories on every
    ``transform()`` call.
    """

    _tables: ClassVar[dict[str, PostgresAssetTables]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @staticmethod
    def get_postgres_section(*, config: dict[str, Any]) -> dict[str, Any]:
        """Return the ``postgres`` sub-section of a repository config (empty if absent).

        Args:
            config: Repository config dict (``assets_management.<asset>_repository.config``).

        Returns:
            The ``postgres`` section as a dict.
        """
        section = config.get(DocpipeConfigKeys.POSTGRES)
        return section if isinstance(section, dict) else {}

    @classmethod
    def validate_config(cls, *, config: dict[str, Any]) -> list[str]:
        """Validate the PostgreSQL part of a repository config.

        The connection password is not checked here because it may come from the
        ``DOCPIPE_POSTGRES_PASSWORD`` environment variable; it is resolved (and a
        missing value reported) in ``get_engine``.

        Args:
            config: Repository config dict.

        Returns:
            List of validation error strings (empty = valid).
        """
        errors: list[str] = []
        section = config.get(DocpipeConfigKeys.POSTGRES)
        if section is not None and not isinstance(section, dict):
            errors.append("Configuration 'postgres' must be a mapping of connection settings")
            return errors

        schema = cls.get_postgres_section(config=config).get(SCHEMA_CONFIG_KEY, DEFAULT_ASSET_SCHEMA)
        if not isinstance(schema, str) or not _SCHEMA_NAME_PATTERN.match(schema):
            errors.append(
                "Configuration 'postgres.schema' must be a lowercase PostgreSQL identifier "
                "(letters, digits, underscores; max 63 characters)"
            )
        return errors

    @classmethod
    def resolve_schema(cls, *, config: dict[str, Any]) -> str:
        """Return the PostgreSQL schema configured for the asset tables.

        Args:
            config: Repository config dict.

        Returns:
            Schema name (default ``docpipe_assets``).
        """
        return str(cls.get_postgres_section(config=config).get(SCHEMA_CONFIG_KEY, DEFAULT_ASSET_SCHEMA))

    @classmethod
    def get_engine(cls, *, config: dict[str, Any], owner: str) -> Engine:
        """Return a cached SQLAlchemy engine for the given repository config.

        Uses the shared PostgreSQL connection helpers so that the YAML keys, the
        ``DOCPIPE_POSTGRES_*`` environment fallbacks and the pool settings behave
        identically for every PostgreSQL-backed component.

        Args:
            config: Repository config dict (may contain a ``postgres`` section).
            owner: Human-readable name of the component asking (used in errors).

        Returns:
            A connected SQLAlchemy engine (shared per connection configuration).

        Raises:
            RepositoryConfigurationException: If no PostgreSQL password is configured.
            PostgresConnectionException: If the database cannot be reached.
        """
        from docpipe.storage.postgres.connection import get_shared_postgres_engine

        engine = get_shared_postgres_engine(postgres=cls.get_postgres_section(config=config), owner=owner)
        if engine is None:
            raise RepositoryConfigurationException(
                f"PostgreSQL connection is not configured for {owner}: set 'postgres.password' in the "
                "repository config (docling-pipelines-config.yaml) or the DOCPIPE_POSTGRES_PASSWORD "
                "environment variable",
                repository_type=_POSTGRES_REPOSITORY_TYPE,
            )
        return engine

    @classmethod
    def get_tables(cls, *, schema: str) -> PostgresAssetTables:
        """Return (and cache) the table definitions bound to ``schema``.

        Args:
            schema: PostgreSQL schema name.

        Returns:
            PostgresAssetTables for that schema.
        """
        with cls._lock:
            tables = cls._tables.get(schema)
            if tables is None:
                tables = cls._build_tables(schema=schema)
                cls._tables[schema] = tables
        return tables

    @classmethod
    def ensure_schema(cls, *, engine: Engine, schema: str) -> PostgresAssetTables:
        """Create the schema and asset tables if they do not exist yet.

        Safe to call concurrently from several processes: the DDL runs in one
        transaction guarded by ``pg_advisory_xact_lock``, so only one bootstrap
        runs at a time and later callers see the committed tables.

        Args:
            engine: SQLAlchemy engine connected to the target database.
            schema: PostgreSQL schema name.

        Returns:
            PostgresAssetTables for that schema.
        """
        tables = cls.get_tables(schema=schema)
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SCHEMA_BOOTSTRAP_LOCK_KEY})
            connection.execute(CreateSchema(schema, if_not_exists=True))
            tables.metadata.create_all(connection, checkfirst=True)
        logger.debug("Ensured PostgreSQL asset tables exist in schema '%s'", schema)
        return tables

    @staticmethod
    def describe_engine(*, engine: Engine) -> str:
        """Return a password-free description of the engine's target database.

        Args:
            engine: SQLAlchemy engine.

        Returns:
            String like ``user@host:port/database``.
        """
        url = engine.url
        return f"{url.username}@{url.host}:{url.port}/{url.database}"

    @classmethod
    def dispose_engines(cls) -> None:
        """Dispose and forget every shared PostgreSQL engine (used on shutdown and in tests)."""
        from docpipe.storage.postgres.connection import dispose_shared_postgres_engines

        dispose_shared_postgres_engines()

    @staticmethod
    def _build_tables(*, schema: str) -> PostgresAssetTables:
        """Build the SQLAlchemy table definitions for one schema.

        Args:
            schema: PostgreSQL schema name.

        Returns:
            PostgresAssetTables with fresh MetaData.
        """
        metadata = MetaData(schema=schema)
        records = Table(
            RECORDS_TABLE_NAME,
            metadata,
            Column("collection", Text, primary_key=True),
            Column("asset_id", Text, primary_key=True),
            Column("name", Text, nullable=False),
            Column("data", JSONB, nullable=False),
            # The asset's own creation timestamp (Asset.get_created_at()), NULL for asset
            # types without one; created_at below is when the row was inserted.
            Column("asset_created_at", DateTime(timezone=True), nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
            Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
            UniqueConstraint("collection", "name", name=RECORDS_NAME_UNIQUE_CONSTRAINT),
        )
        # Matches the listing order of PostgresAssetRepository.list_all, so LIMIT/OFFSET
        # pages are read from the index instead of sorting the whole collection.
        Index(
            RECORDS_LISTING_INDEX,
            records.c.collection,
            records.c.asset_created_at.desc().nulls_last(),
            records.c.created_at,
            records.c.asset_id,
        )
        attachments = Table(
            ATTACHMENTS_TABLE_NAME,
            metadata,
            Column("collection", Text, primary_key=True),
            Column("asset_id", Text, primary_key=True),
            Column("data", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
            Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        )
        return PostgresAssetTables(schema=schema, metadata=metadata, records=records, attachments=attachments)
