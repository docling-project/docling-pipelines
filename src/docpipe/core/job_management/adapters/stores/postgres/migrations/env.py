# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Alembic environment script for docpipe PostgreSQL migrations.

Configures the Alembic migration context with the database URL resolved from
``DOCPIPE_POSTGRES_URL`` environment variable, ``docling-pipelines-config.yaml``,
or built-in defaults.  Supports both offline and online migration modes.
"""

import logging
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.sql.expression import text
from sqlmodel import SQLModel

from docpipe.core.constants import EnvironmentVariables

# Import database utilities to get connection string
from docpipe.core.job_management.adapters.stores.postgres.database import get_postgres_connection_string

# Import models so they are registered with SQLModel.metadata
from docpipe.core.job_management.adapters.stores.postgres.models import JobStatsModel, NodeStatsModel  # noqa: F401
from docpipe.utils.infrastructure.config_utils import DEFAULT_CONFIG_PATH

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Do not let Alembic reconfigure root/application logging when migrations are
# executed during server startup. Reusing the existing app logging configuration
# preserves console output, formatter setup, and logger levels.
migration_logger = logging.getLogger("DOCPIPE_POSTGRES_MIGRATIONS")
root_logger = logging.getLogger()

if not root_logger.handlers and config.config_file_name is not None:
    fileConfig(config.config_file_name)

for handler in root_logger.handlers:
    if handler not in migration_logger.handlers:
        migration_logger.addHandler(handler)

migration_logger.setLevel(logging.INFO)
migration_logger.propagate = False

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

# Get database URL from environment variable or config
database_url = os.getenv("DOCPIPE_POSTGRES_URL")
if not database_url:
    # Load config and build connection string
    import yaml

    config_path = os.environ.get(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(DEFAULT_CONFIG_PATH))
    try:
        with Path(config_path).open() as f:
            app_config = yaml.safe_load(f) or {}
    except Exception as e:
        logging.getLogger("alembic").warning("Could not load config from %s: %s", config_path, e)
        app_config = {}

    job_mgmt_config = app_config.get("job_management", {})
    store_config = job_mgmt_config.get("storage", {}).get("config", {})
    database_url = get_postgres_connection_string(config=store_config)

if database_url:
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    schema_name = os.getenv("DOCPIPE_POSTGRES_SCHEMA", "docpipe_oss")
    migration_logger.info("Starting online migrations for schema=%s", schema_name)

    existing_connection = config.attributes.get("connection")
    if existing_connection is not None:
        migration_logger.info("Using existing Alembic connection supplied by startup initialization")
        existing_connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        existing_connection.commit()
        migration_logger.info("Ensured schema exists: %s", schema_name)

        context.configure(
            connection=existing_connection,
            target_metadata=target_metadata,
            include_schemas=False,
            version_table_schema=schema_name,
        )
        migration_logger.info("Alembic context configured with existing connection")

        with context.begin_transaction():
            migration_logger.info("Running migration transaction")
            context.run_migrations()
            migration_logger.info("Migration transaction completed")
        return

    migration_logger.info("Creating Alembic engine from configuration")
    connect_args = config.attributes.get("connect_args", {})
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    with connectable.connect() as connection:
        migration_logger.info("Alembic engine connection established")
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        connection.commit()
        migration_logger.info("Ensured schema exists: %s", schema_name)

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=False,
            version_table_schema=schema_name,
        )
        migration_logger.info("Alembic context configured with new connection")

        with context.begin_transaction():
            migration_logger.info("Running migration transaction")
            context.run_migrations()
            migration_logger.info("Migration transaction completed")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
