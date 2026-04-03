"""Centralized helper to resolve the readings cache file path."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_FILENAME = "readings_cache.json"


def get_readings_cache_path(config: dict | None = None) -> str:
    """Return the absolute path to the readings cache file.

    Reads ``api.cache_file`` from *config*. Falls back to
    ``readings_cache.json`` relative to the project root when the key
    is missing or *config* is ``None``.
    """
    if config is None:
        config = {}
    cache_path = config.get("api", {}).get("cache_file", DEFAULT_CACHE_FILENAME)
    if not os.path.isabs(cache_path):
        cache_path = str(PROJECT_ROOT / cache_path)
    return cache_path
