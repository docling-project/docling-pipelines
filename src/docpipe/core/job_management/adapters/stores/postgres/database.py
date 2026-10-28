"""
PostgreSQL database connection utilities.

Provides connection string building, engine creation, session factory,
and Alembic migration execution for PostgreSQL-backed job stats storage.

Configuration precedence:
1. Config dict passed to functions (from YAML)
2. Environment variables (fallback)
3. Built-in defaults
"""

import os
from pathlib import Path
from typing import Any, Callable

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from docpipe.core.constants import DocpipeConfigKeys, EnvironmentVariables
from docpipe.exceptions.docpipe_exceptions import DatabaseMigrationException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger("DOCPIPE_POSTGRES_DATABASE")

# Path to Alembic configuration
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
ALEMBIC_INI_PATH = MIGRATIONS_DIR / "alembic.ini"


def get_postgres_connection_string(*, config: dict[str, Any] | None = None) -> str | None:
    """
    Build PostgreSQL connection string from config or environment variables.

    Configuration precedence:
    1. Config dict (from YAML): config['postgres']['host'], etc.
    2. Environment variables: DOCPIPE_POSTGRES_HOST, etc.
    3. Built-in defaults

    Args:
        config: Optional configuration dict from YAML

    Environment Variables (fallback):
        DOCPIPE_POSTGRES_HOST: Database host (default: localhost)
        DOCPIPE_POSTGRES_PORT: Database port (default: 5432)
        DOCPIPE_POSTGRES_DB: Database name (default: docpipe)
        DOCPIPE_POSTGRES_USER: Database user (default: docpipe_user)
        DOCPIPE_POSTGRES_PASSWORD: Database password (required)

    Returns:
        Connection string if password is available, None otherwise
    """
    config = config or {}
    postgres_config = config.get(DocpipeConfigKeys.POSTGRES, {})

    # Get password (required) - check config first, then env
    password = postgres_config.get(DocpipeConfigKeys.PASSWORD) or os.getenv(
        EnvironmentVariables.DOCPIPE_POSTGRES_PASSWORD
    )
    if not password:
        logger.warning(
            "PostgreSQL password not configured (YAML or %s)", EnvironmentVariables.DOCPIPE_POSTGRES_PASSWORD
        )
        return None

    # Get other connection parameters with fallback chain: config -> env -> default
    host = postgres_config.get(DocpipeConfigKeys.HOST) or os.getenv(
        EnvironmentVariables.DOCPIPE_POSTGRES_HOST, "localhost"
    )
    port = postgres_config.get(DocpipeConfigKeys.PORT) or os.getenv(EnvironmentVariables.DOCPIPE_POSTGRES_PORT, "5432")
    database = postgres_config.get(DocpipeConfigKeys.DATABASE) or os.getenv(
        EnvironmentVariables.DOCPIPE_POSTGRES_DB, "docpipe"
    )
    user = postgres_config.get(DocpipeConfigKeys.USER) or os.getenv(
        EnvironmentVariables.DOCPIPE_POSTGRES_USER, "docpipe_user"
    )

    connection_string = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
    logger.info("PostgreSQL connection string built: %s@%s:%s/%s", user, host, port, database)

    return connection_string


def create_postgres_engine(*, connection_string: str, config: dict[str, Any] | None = None) -> Engine:
    """
    Create SQLAlchemy engine for PostgreSQL.

    Args:
        connection_string: PostgreSQL connection string
        config: Optional configuration dict for pool settings

    Returns:
        SQLAlchemy Engine instance

    Raises:
        PostgresConnectionException: If engine creation fails
    """
    from docpipe.exceptions.docpipe_exceptions import PostgresConnectionException

    config = config or {}
    postgres_config = config.get(DocpipeConfigKeys.POSTGRES, {})

    # Get pool settings from config or use defaults
    pool_size = postgres_config.get(DocpipeConfigKeys.POOL_SIZE, 5)
    max_overflow = postgres_config.get(DocpipeConfigKeys.MAX_OVERFLOW, 10)
    pool_timeout = postgres_config.get(DocpipeConfigKeys.POOL_TIMEOUT, 30)

    try:
        engine = create_engine(
            connection_string,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_pre_ping=True,  # Verify connections before using
            echo=False,  # Set to True for SQL debugging
        )

        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        logger.info(
            "PostgreSQL engine created: pool_size=%s, max_overflow=%s, pool_timeout=%s",
            pool_size,
            max_overflow,
            pool_timeout,
        )
        return engine
    except Exception as e:
        logger.error("Failed to create PostgreSQL engine: %s", e)
        raise PostgresConnectionException(
            message=f"PostgreSQL engine creation failed: {e}",
            host=postgres_config.get(DocpipeConfigKeys.HOST, "unknown"),
            database=postgres_config.get(DocpipeConfigKeys.DATABASE, "unknown"),
        ) from e


def create_session_factory(*, engine: Engine) -> Callable[[], Session]:
    """
    Create session factory for database operations.

    Args:
        engine: SQLAlchemy engine

    Returns:
        Session factory callable
    """
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    logger.debug("Session factory created")
    return session_factory


def run_migrations(*, connection_string: str, config: dict[str, Any] | None = None) -> None:
    """
    Run Alembic migrations to upgrade database schema to latest version.

    This function executes all pending migrations using the existing Alembic
    configuration. It's safe to call multiple times - Alembic tracks which
    migrations have been applied and only runs new ones.

    Args:
        connection_string: PostgreSQL connection string
        config: Optional configuration dict (currently unused, reserved for future)

    Raises:
        DatabaseMigrationException: If migration execution fails or config is missing

    Example:
        >>> connection_string = "postgresql+psycopg2://user:pass@localhost/db"  #pragma: allowlist secret
        >>> run_migrations(connection_string=connection_string)
        # Migrations applied successfully
    """
    config = config or {}

    # Verify Alembic configuration exists
    if not ALEMBIC_INI_PATH.exists():
        raise DatabaseMigrationException(
            message=f"Alembic configuration not found: {ALEMBIC_INI_PATH}. "
            "Migration scaffold may be missing or corrupted.",
            operation="verify_config",
        )

    try:
        # Create Alembic configuration
        alembic_cfg = AlembicConfig(str(ALEMBIC_INI_PATH))

        # Override database URL in Alembic config
        alembic_cfg.set_main_option("sqlalchemy.url", connection_string)

        # Set script location to migrations directory
        alembic_cfg.set_main_option("script_location", str(MIGRATIONS_DIR))

        # Pass a connection timeout so a bad host/credentials fails fast
        # instead of hanging indefinitely.
        alembic_cfg.attributes["connect_args"] = {"connect_timeout": 10}

        logger.info("Running Alembic migrations to upgrade database schema...")

        command.upgrade(alembic_cfg, "head")

        logger.info("Database migrations completed successfully")

    except SystemExit as e:
        logger.error("Alembic terminated startup with SystemExit: code=%s", e.code)
        raise DatabaseMigrationException(
            message=f"Database migration exited unexpectedly with code {e.code}",
            operation="upgrade",
        ) from e
    except BaseException as e:
        logger.error("Failed to run database migrations: %s", e)
        raise DatabaseMigrationException(message=f"Database migration failed: {e}", operation="upgrade") from e
