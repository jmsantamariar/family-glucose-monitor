"""Stale readings must not be re-logged to reading_history on every poll.

When a patient's sensor goes silent, every poll cycle re-delivers the same
last reading. _load_and_enrich_cache used to log it to reading_history.db
each time, producing fake flat segments in the dashboard charts and
inflating n_readings/TIR/CV in the history metrics. Readings are now
deduplicated by the sensor's own timestamp.
"""
import json
import os
from unittest.mock import MagicMock

import pytest

import src.api as api_module


@pytest.fixture()
def cache_env(tmp_path, monkeypatch):
    """Point the api module at a temp cache file and a mocked history DB."""
    cache_file = tmp_path / "readings_cache.json"
    config = {"api": {"cache_file": str(cache_file)}}
    monkeypatch.setattr(api_module, "_config", config)
    monkeypatch.setattr(api_module, "_last_mtime", 0.0)
    monkeypatch.setattr(api_module, "_last_logged_source_ts", {})
    api_module._readings_cache.clear()

    log_reading = MagicMock()
    monkeypatch.setattr(
        api_module,
        "_reading_history",
        type(
            "Stub",
            (),
            {
                "init_db": staticmethod(lambda *a, **k: None),
                "log_reading": staticmethod(log_reading),
            },
        )(),
    )

    mtime = [1000.0]

    def write_cache(readings):
        cache_file.write_text(json.dumps({"readings": readings}))
        # Force a distinct mtime so the loader re-reads the file each time.
        mtime[0] += 10
        os.utime(cache_file, (mtime[0], mtime[0]))

    return {"write": write_cache, "log_reading": log_reading}


def _reading(pid, value, ts):
    return {
        "patient_id": pid,
        "patient_name": f"Patient {pid}",
        "value": value,
        "trend_arrow": "→",
        "timestamp": ts,
    }


def test_same_sensor_timestamp_logged_once(cache_env):
    cache_env["write"]([_reading("p1", 110, "2026-06-06 10:00:00+00:00")])
    api_module._load_and_enrich_cache()
    cache_env["write"]([_reading("p1", 110, "2026-06-06 10:00:00+00:00")])
    api_module._load_and_enrich_cache()
    assert cache_env["log_reading"].call_count == 1


def test_new_sensor_timestamp_logged_again(cache_env):
    cache_env["write"]([_reading("p1", 110, "2026-06-06 10:00:00+00:00")])
    api_module._load_and_enrich_cache()
    cache_env["write"]([_reading("p1", 112, "2026-06-06 10:05:00+00:00")])
    api_module._load_and_enrich_cache()
    assert cache_env["log_reading"].call_count == 2


def test_dedup_is_per_patient(cache_env):
    ts = "2026-06-06 10:00:00+00:00"
    cache_env["write"]([_reading("p1", 110, ts), _reading("p2", 95, ts)])
    api_module._load_and_enrich_cache()
    # p1 stale, p2 advanced
    cache_env["write"]([_reading("p1", 110, ts), _reading("p2", 99, "2026-06-06 10:05:00+00:00")])
    api_module._load_and_enrich_cache()
    logged_pids = [c.args[1] for c in cache_env["log_reading"].call_args_list]
    assert logged_pids.count("p1") == 1
    assert logged_pids.count("p2") == 2


def test_missing_timestamp_still_logged(cache_env):
    """Readings without a sensor timestamp fall back to always logging."""
    r = _reading("p1", 110, "")
    cache_env["write"]([r])
    api_module._load_and_enrich_cache()
    cache_env["write"]([r])
    api_module._load_and_enrich_cache()
    assert cache_env["log_reading"].call_count == 2
