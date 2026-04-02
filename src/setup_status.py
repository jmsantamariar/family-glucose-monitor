"""Setup completeness helpers.

Determines whether the application has been fully configured and is ready
for normal operation.  A "complete" setup requires a ``config.yaml`` that:

1. Exists on disk.
2. Can be parsed as valid YAML.
3. Is a non-empty YAML mapping (not ``None``).
4. Passes full schema validation (:func:`~src.config_schema.validate_config`
   returns no errors).

These checks are deliberately stricter than the simple file-existence test
in :func:`src.auth.is_configured`, which is kept solely for auth-protection
purposes (i.e. requiring a login before overwriting an existing config file).

Typical call sites
------------------
* ``src.api`` — auth middleware redirect logic, ``/api/setup/status`` endpoint.
* ``src.main`` — startup gate: enter setup-only mode vs. normal operation.
* Tests — verify the helper against various config states.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.config_schema import validate_config

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class SetupStatus:
    """Result of a setup completeness check.

    Attributes
    ----------
    complete:
        ``True`` when all checks pass and the application is ready to run.
    errors:
        Human-readable descriptions of why setup is incomplete.  Empty when
        *complete* is ``True``.
    """

    complete: bool
    errors: list[str] = field(default_factory=list)


def check_setup(config_path: Path | None = None) -> SetupStatus:
    """Return a :class:`SetupStatus` describing whether setup is complete.

    Parameters
    ----------
    config_path:
        Explicit path to the configuration file.  Defaults to
        ``PROJECT_ROOT/config.yaml``.  Pass a custom path in tests to avoid
        touching the real file system.
    """
    path = config_path if config_path is not None else PROJECT_ROOT / "config.yaml"

    if not path.exists():
        return SetupStatus(
            complete=False,
            errors=[f"config.yaml not found at {path}"],
        )

    try:
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        return SetupStatus(
            complete=False,
            errors=[f"config.yaml parse error: {exc}"],
        )
    except OSError as exc:
        return SetupStatus(
            complete=False,
            errors=[f"config.yaml read error: {exc}"],
        )

    if not isinstance(config, dict):
        return SetupStatus(
            complete=False,
            errors=["config.yaml is empty or not a YAML mapping"],
        )

    errors = validate_config(config)
    if errors:
        return SetupStatus(complete=False, errors=errors)

    return SetupStatus(complete=True)


def is_setup_complete(config_path: Path | None = None) -> bool:
    """Return ``True`` if setup is complete, ``False`` otherwise.

    Convenience wrapper around :func:`check_setup` for call sites that only
    need a boolean answer.
    """
    return check_setup(config_path).complete
