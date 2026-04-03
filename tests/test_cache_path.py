"""Tests for the centralized cache path resolver."""
from src.cache_path import get_readings_cache_path, PROJECT_ROOT, DEFAULT_CACHE_FILENAME


def test_default_path_when_no_config():
    result = get_readings_cache_path(None)
    assert result == str(PROJECT_ROOT / DEFAULT_CACHE_FILENAME)


def test_default_path_when_empty_config():
    result = get_readings_cache_path({})
    assert result == str(PROJECT_ROOT / DEFAULT_CACHE_FILENAME)


def test_custom_relative_path():
    config = {"api": {"cache_file": "custom/my_cache.json"}}
    result = get_readings_cache_path(config)
    assert result == str(PROJECT_ROOT / "custom" / "my_cache.json")


def test_custom_absolute_path():
    config = {"api": {"cache_file": "/var/data/readings.json"}}
    result = get_readings_cache_path(config)
    assert result == "/var/data/readings.json"


def test_consistency_between_default_calls():
    """Two calls with the same config must return the same path."""
    config = {"api": {"cache_file": "readings_cache.json"}}
    assert get_readings_cache_path(config) == get_readings_cache_path(config)
