# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
PostgreSQL database utilities for the job stats store.

Provides the session factory and Alembic migration execution for PostgreSQL-backed
job stats storage. The connection string and engine helpers live in
``docpipe.storage.postgres.connection`` and are re-exported here.
"""

from pathlib import Path
from typing import Any, Callable

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from docpipe.exceptions.docpipe_exceptions import DatabaseMigrationException
from docpipe.storage.postgres.connection import create_postgres_engine, get_postgres_connection_string
from docpipe.utils.infrastructure.logging import get_logger

__all__ = [
    "ALEMBIC_INI_PATH",
    "MIGRATIONS_DIR",
    "create_postgres_engine",
    "create_session_factory",
    "get_postgres_connection_string",
    "run_migrations",
]

logger = get_logger("DOCPIPE_POSTGRES_DATABASE")

# Path to Alembic configuration
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
ALEMBIC_INI_PATH = MIGRATIONS_DIR / "alembic.ini"


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
