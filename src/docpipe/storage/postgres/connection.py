# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""PostgreSQL connection helpers shared by every PostgreSQL-backed component.

Builds the connection string from the ``postgres`` config section and the
``DOCPIPE_POSTGRES_*`` environment variables, and creates SQLAlchemy engines.
``get_shared_postgres_engine`` keeps one engine, and so one connection pool, per
connection configuration for the whole process.

Configuration precedence:
1. Config dict passed to functions (from YAML)
2. Environment variables (fallback)
3. Built-in defaults
"""

import os
import threading
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from docpipe.core.constants import DocpipeConfigKeys, EnvironmentVariables
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger("DOCPIPE_POSTGRES_DATABASE")

# One engine per (connection string, pool_size, max_overflow, pool_timeout).
_shared_engines: dict[tuple[str, int, int, int], Engine] = {}
_shared_engines_lock = threading.Lock()


def _postgres_settings(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract resolved PostgreSQL settings using nested-over-root precedence.

    Configuration precedence for each setting:
    1. Key in nested config['postgres'] (if config is a dict and has 'postgres' dict)
    2. Key in root config (if config is a dict)
    3. Environment variable fallback (DOCPIPE_POSTGRES_*)
    4. Built-in defaults
    """
    config = config or {}
    nested_value = config.get(DocpipeConfigKeys.POSTGRES)
    nested: dict[str, Any] = nested_value if isinstance(nested_value, dict) else {}

    def _resolve(key: str, env_var: str | None = None, default: Any = None) -> Any:
        if key in nested and nested[key] is not None:
            return nested[key]
        if key in config and config[key] is not None:
            return config[key]
        if env_var:
            env_val = os.getenv(env_var)
            if env_val is not None:
                return env_val
        return default

    # Database name can be specified as 'database' or 'db'
    database = (
        nested.get(DocpipeConfigKeys.DATABASE)
        or nested.get("db")
        or config.get(DocpipeConfigKeys.DATABASE)
        or config.get("db")
        or os.getenv(EnvironmentVariables.DOCPIPE_POSTGRES_DB, "docpipe")
    )

    password = _resolve(DocpipeConfigKeys.PASSWORD, EnvironmentVariables.DOCPIPE_POSTGRES_PASSWORD, None)
    host = _resolve(DocpipeConfigKeys.HOST, EnvironmentVariables.DOCPIPE_POSTGRES_HOST, "localhost")
    port = _resolve(DocpipeConfigKeys.PORT, EnvironmentVariables.DOCPIPE_POSTGRES_PORT, "5432")
    user = _resolve(DocpipeConfigKeys.USER, EnvironmentVariables.DOCPIPE_POSTGRES_USER, "docpipe_user")
    schema = _resolve("schema", None, None)
    pool_size = _resolve(DocpipeConfigKeys.POOL_SIZE, None, 5)
    max_overflow = _resolve(DocpipeConfigKeys.MAX_OVERFLOW, None, 10)
    pool_timeout = _resolve(DocpipeConfigKeys.POOL_TIMEOUT, None, 30)

    return {
        DocpipeConfigKeys.HOST: str(host),
        DocpipeConfigKeys.PORT: str(port),
        DocpipeConfigKeys.DATABASE: str(database),
        "db": str(database),
        DocpipeConfigKeys.USER: str(user),
        DocpipeConfigKeys.PASSWORD: password,
        "schema": schema,
        DocpipeConfigKeys.POOL_SIZE: int(pool_size),
        DocpipeConfigKeys.MAX_OVERFLOW: int(max_overflow),
        DocpipeConfigKeys.POOL_TIMEOUT: int(pool_timeout),
    }


def get_postgres_pool_settings(*, config: dict[str, Any] | None = None) -> dict[str, int]:
    """Get pool settings (pool_size, max_overflow, pool_timeout) from config or defaults."""
    settings = _postgres_settings(config)
    return {
        DocpipeConfigKeys.POOL_SIZE: int(settings[DocpipeConfigKeys.POOL_SIZE]),
        DocpipeConfigKeys.MAX_OVERFLOW: int(settings[DocpipeConfigKeys.MAX_OVERFLOW]),
        DocpipeConfigKeys.POOL_TIMEOUT: int(settings[DocpipeConfigKeys.POOL_TIMEOUT]),
    }


def get_postgres_connection_string(*, config: dict[str, Any] | None = None) -> str | None:
    """Build PostgreSQL connection string from config or environment variables.

    Configuration precedence:
    1. Nested config: config['postgres']['host'], etc.
    2. Root config: config['host'], etc.
    3. Environment variables: DOCPIPE_POSTGRES_HOST, etc.
    4. Built-in defaults

    Args:
        config: Optional configuration dict from YAML (flat, nested, or mixed)

    Environment Variables (fallback):
        DOCPIPE_POSTGRES_HOST: Database host (default: localhost)
        DOCPIPE_POSTGRES_PORT: Database port (default: 5432)
        DOCPIPE_POSTGRES_DB: Database name (default: docpipe)
        DOCPIPE_POSTGRES_USER: Database user (default: docpipe_user)
        DOCPIPE_POSTGRES_PASSWORD: Database password (required)

    Returns:
        Connection string if password is available, None otherwise
    """
    settings = _postgres_settings(config)

    password = settings.get(DocpipeConfigKeys.PASSWORD)
    if not password:
        logger.warning(
            "PostgreSQL password not configured (YAML or %s)", EnvironmentVariables.DOCPIPE_POSTGRES_PASSWORD
        )
        return None

    host = settings[DocpipeConfigKeys.HOST]
    port = settings[DocpipeConfigKeys.PORT]
    database = settings[DocpipeConfigKeys.DATABASE]
    user = settings[DocpipeConfigKeys.USER]

    connection_string = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
    logger.info("PostgreSQL connection string built: %s@%s:%s/%s", user, host, port, database)

    return connection_string


def create_postgres_engine(*, connection_string: str, config: dict[str, Any] | None = None) -> Engine:
    """Create SQLAlchemy engine for PostgreSQL.

    Args:
        connection_string: PostgreSQL connection string
        config: Optional configuration dict for pool settings

    Returns:
        SQLAlchemy Engine instance

    Raises:
        PostgresConnectionException: If engine creation fails
    """
    from docpipe.exceptions.docpipe_exceptions import PostgresConnectionException

    settings = _postgres_settings(config)
    pool_size = settings[DocpipeConfigKeys.POOL_SIZE]
    max_overflow = settings[DocpipeConfigKeys.MAX_OVERFLOW]
    pool_timeout = settings[DocpipeConfigKeys.POOL_TIMEOUT]

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
            host=settings.get(DocpipeConfigKeys.HOST, "unknown"),
            database=settings.get(DocpipeConfigKeys.DATABASE, "unknown"),
        ) from e


def get_shared_postgres_engine(
    *, postgres: dict[str, Any] | None = None, owner: str = "PostgreSQL storage"
) -> Engine | None:
    """Return the engine for these connection settings, shared by the whole process.

    The first call for a connection string and pool settings creates and checks the
    engine with ``create_postgres_engine``; later calls return the same engine, so
    every component that connects with the same settings uses one connection pool.
    A cached engine is returned without taking the lock, so a slow or failing
    connection attempt never blocks the components whose engine already exists.

    Args:
        postgres: The storage configuration or ``postgres`` section. A setting that is not given falls
            back to its ``DOCPIPE_POSTGRES_*`` environment variable.
        owner: Human-readable name of the component asking, for the log messages.

    Returns:
        The shared engine, or None if no password is configured.

    Raises:
        PostgresConnectionException: If a new engine cannot connect.
    """
    connection_string = get_postgres_connection_string(config=postgres)
    if not connection_string:
        return None

    settings = _postgres_settings(postgres)
    cache_key = (
        connection_string,
        settings[DocpipeConfigKeys.POOL_SIZE],
        settings[DocpipeConfigKeys.MAX_OVERFLOW],
        settings[DocpipeConfigKeys.POOL_TIMEOUT],
    )
    url = make_url(connection_string)
    target = f"{url.username}@{url.host}:{url.port}/{url.database}"

    # Fast path without the lock: a cached engine is only removed by dispose_shared_postgres_engines().
    engine = _shared_engines.get(cache_key)
    if engine is not None:
        logger.debug("Reusing shared PostgreSQL engine for %s: %s", owner, target)
        return engine

    with _shared_engines_lock:
        # Another thread may have created the engine while this one waited for the lock.
        engine = _shared_engines.get(cache_key)
        if engine is None:
            engine = create_postgres_engine(connection_string=connection_string, config=postgres)
            _shared_engines[cache_key] = engine
            logger.info("Created shared PostgreSQL engine for %s: %s", owner, target)
    return engine


def dispose_shared_postgres_engines() -> None:
    """Dispose and forget every shared engine (used on shutdown and in tests)."""
    with _shared_engines_lock:
        engines = list(_shared_engines.values())
        _shared_engines.clear()
    for engine in engines:
        engine.dispose()
