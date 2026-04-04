"""Central bootstrap: create and validate persistent storage on startup.

Call :func:`bootstrap_storage` early in the startup sequence (after config
is loaded) to ensure all required files and directories exist before any
module tries to read or write them.

Raises :class:`BootstrapError` with a human-readable message when a fatal
problem is detected (e.g. the alert-history DB has an incompatible schema or
a required directory cannot be created).
"""
import json
import logging
import os
from pathlib import Path

from src.alert_history import init_db, validate_schema
from src.paths import get_cache_path, get_db_path, get_state_path
import src.push_subscriptions as _push_subs

logger = logging.getLogger(__name__)


class BootstrapError(RuntimeError):
    """Raised when startup storage validation fails fatally."""


def bootstrap_storage(config: dict) -> None:
    """Create and validate all persistent-storage files required at runtime.

    Actions
    -------
    * Ensure the parent directories for state.json, alert_history.db, and
      readings_cache.json exist (``mkdir -p``).
    * Initialise ``alert_history.db`` via :func:`src.alert_history.init_db`
      (idempotent ``CREATE TABLE IF NOT EXISTS``).
    * Validate the schema of an **existing** ``alert_history.db``; raises
      :class:`BootstrapError` if required columns are missing.
    * Create an empty ``state.json`` (``{}``) if it does not yet exist.
    * Create an empty ``readings_cache.json`` if it does not yet exist.

    Parameters
    ----------
    config:
        The already-validated configuration dictionary.  Paths inside the
        config (``state_file``, ``alert_history_db``, ``api.cache_file``) are
        resolved through :mod:`src.paths`, which honours the matching
        environment-variable overrides.
    """
    state_path = get_state_path(config)
    db_path = get_db_path(config)
    cache_path = get_cache_path(config)

    # --- Ensure parent directories exist ---
    for file_path in (state_path, db_path, cache_path):
        try:
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BootstrapError(
                f"Cannot create storage directory for {file_path}: {exc}"
            ) from exc

    # --- Preflight: validate existing alert_history.db schema ---
    schema_errors = validate_schema(db_path)
    if schema_errors:
        detail = "\n  ".join(schema_errors)
        raise BootstrapError(
            f"alert_history.db schema mismatch — cannot start:\n  {detail}\n"
            "Delete the database file and restart to re-initialise it, "
            "or run Alembic migrations to upgrade the schema."
        )

    # --- Initialise alert_history.db (idempotent) ---
    try:
        init_db(db_path)
    except Exception as exc:
        raise BootstrapError(f"Failed to initialise alert_history.db at {db_path}: {exc}") from exc

    # --- Create state.json if absent ---
    state_file = Path(state_path)
    if not state_file.exists():
        try:
            state_file.write_text("{}\n", encoding="utf-8")
            logger.debug("Created empty state file at %s", state_path)
        except OSError as exc:
            raise BootstrapError(
                f"Cannot create state file at {state_path}: {exc}"
            ) from exc

    # --- Create empty readings_cache.json if absent ---
    cache_file = Path(cache_path)
    if not cache_file.exists():
        try:
            cache_file.write_text(
                json.dumps({"readings": [], "updated_at": None}) + "\n",
                encoding="utf-8",
            )
            logger.debug("Created empty readings cache at %s", cache_path)
        except OSError as exc:
            # Non-fatal: the daemon will write it on the first polling cycle.
            logger.warning("Could not pre-create readings cache at %s: %s", cache_path, exc)

    # --- Initialise push_subscriptions.db (idempotent) ---
    push_db_path = str(Path(db_path).parent / "push_subscriptions.db")
    try:
        _push_subs.init_db(push_db_path)
    except Exception as exc:
        # Non-fatal: browser push notifications will be skipped if the DB is
        # unavailable, but other alerting channels continue to work.
        logger.warning("Could not initialise push_subscriptions.db at %s: %s", push_db_path, exc)


def check_config_writable(config_path: Path) -> str | None:
    """Return an error message if *config_path* is not writable, else ``None``.

    Used by the setup wizard to emit a clear error before attempting to write
    the configuration when the file (or its parent directory) is read-only.
    """
    if config_path.exists():
        if not os.access(config_path, os.W_OK):
            return (
                f"config.yaml at {config_path} is read-only. "
                "Remove the read-only flag (e.g. 'chmod u+w config.yaml') "
                "or mount the file with write permissions before using the setup wizard."
            )
    else:
        parent = config_path.parent
        if not os.access(parent, os.W_OK):
            return (
                f"Cannot create config.yaml: directory {parent} is not writable. "
                "Ensure the application has write access to its working directory."
            )
    return None
