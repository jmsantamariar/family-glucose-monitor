"""Backward-compatible shim — use :mod:`src.paths` for new code.

:func:`get_readings_cache_path` is kept for existing callers; it now
delegates to :func:`src.paths.get_cache_path`.
"""
from src.paths import (  # noqa: F401 — re-exported for callers
    DEFAULT_CACHE_FILENAME,
    PROJECT_ROOT,
    get_cache_path as get_readings_cache_path,
)
