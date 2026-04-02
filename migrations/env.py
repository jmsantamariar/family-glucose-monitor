"""Alembic environment script for family-glucose-monitor.

Configured for the ``alert_history.db`` SQLite database (the primary
application data store).  The ``sessions.db`` database (auth/sessions) is
managed separately because it has a different lifecycle.

Database URL resolution order
------------------------------
1. ``ALERT_HISTORY_DB`` environment variable (must be an absolute path).
2. ``sqlalchemy.url`` in ``alembic.ini`` (default: ``sqlite:///alert_history.db``
   relative to the working directory, i.e. the project root).

Usage examples
--------------
Apply all pending migrations::

    alembic upgrade head

Generate a new auto-migration after editing ``src/models/db_models.py``::

    alembic revision --autogenerate -m "add_column_foo_to_alerts"

Show current revision::

    alembic current
"""
import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# ---------------------------------------------------------------------------
# Alembic config object
# ---------------------------------------------------------------------------

config = context.config

# Set up Python logging from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Point to our ORM metadata for autogenerate support.
# Only the ``alerts`` table (alert_history.db) is managed here.
# ---------------------------------------------------------------------------

from src.models.db_models import Base  # noqa: E402

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Override the DB URL from the environment variable if set.
# ---------------------------------------------------------------------------

_db_path = os.environ.get("ALERT_HISTORY_DB", "")
if _db_path:
    # Ensure absolute path → valid sqlite:/// URL.
    _abs = str(Path(_db_path).resolve())
    config.set_main_option("sqlalchemy.url", f"sqlite:///{_abs}")


# ---------------------------------------------------------------------------
# Offline mode
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DB connection required).

    Emits SQL to stdout/script output without actually connecting to the DB.
    Useful for reviewing migrations before applying them.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite does not support transactional DDL — render non-transactional.
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode
# ---------------------------------------------------------------------------


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connects to the DB)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"check_same_thread": False},
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # render_as_batch enables ALTER TABLE emulation for SQLite,
            # which does not support most ALTER TABLE statements natively.
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
