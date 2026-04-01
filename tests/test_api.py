"""Tests for FastAPI endpoints in src/api.py."""
import json

import pytest
from fastapi.testclient import TestClient

import src.api as api_module
from src.api import app, _get_color

# ── Minimal config used to make alert_engine calls succeed ────────────────────

_MINIMAL_CONFIG = {
    "api": {},  # cache_file will be injected by tmp_cache fixture
    "alerts": {
        "low_threshold": 70,
        "high_threshold": 180,
        "trend": {"enabled": False},
    },
}


# ── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Disable auth middleware and reset cache state before/after each test."""
    # Patch the module-level flag that the auth middleware reads at request time
    monkeypatch.setattr(api_module, "_ALLOW_AUTH_DISABLED", True)
    # Reset in-memory cache
    with api_module._cache_lock:
        api_module._readings_cache.clear()
    api_module._last_mtime = 0.0
    yield
    with api_module._cache_lock:
        api_module._readings_cache.clear()
    api_module._last_mtime = 0.0


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    """Create a temporary cache file and patch api.py to use it.

    Provides a ``pathlib.Path`` pointing to the temp ``readings_cache.json``.
    The fixture also injects a minimal config so that ``alert_engine`` calls
    inside ``_load_and_enrich_cache()`` do not raise ``KeyError``.
    """
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text('{"readings": [], "updated_at": null}')
    config = dict(_MINIMAL_CONFIG)
    config["api"] = {"cache_file": str(cache_file)}
    monkeypatch.setattr(api_module, "_config", config)
    api_module._last_mtime = 0.0
    return cache_file


def _write_readings(cache_file, readings):
    """Write *readings* to *cache_file* and reset mtime tracker to force reload."""
    payload = {"readings": readings, "updated_at": "2024-01-01T00:00:00+00:00"}
    cache_file.write_text(json.dumps(payload))
    api_module._last_mtime = 0.0


@pytest.fixture
def client():
    return TestClient(app)


# ── /api/health ──────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_200(self, client, tmp_cache):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_status_is_ok(self, client, tmp_cache):
        resp = client.get("/api/health")
        assert resp.json()["status"] == "ok"

    def test_has_timestamp(self, client, tmp_cache):
        resp = client.get("/api/health")
        assert "timestamp" in resp.json()

    def test_patients_monitored_zero_when_empty(self, client, tmp_cache):
        resp = client.get("/api/health")
        assert resp.json()["patients_monitored"] == 0

    def test_patients_monitored_counts_cache(self, client, tmp_cache):
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "Ana", "value": 100, "trend_arrow": "→"},
            {"patient_id": "p2", "patient_name": "Juan", "value": 120, "trend_arrow": "→"},
        ])
        resp = client.get("/api/health")
        assert resp.json()["patients_monitored"] == 2


# ── /api/patients ────────────────────────────────────────────────────────────

class TestPatientsListEndpoint:
    def test_returns_200(self, client, tmp_cache):
        resp = client.get("/api/patients")
        assert resp.status_code == 200

    def test_empty_cache_returns_empty_list(self, client, tmp_cache):
        resp = client.get("/api/patients")
        data = resp.json()
        assert data["patients"] == []
        assert data["count"] == 0

    def test_returns_all_patients(self, client, tmp_cache):
        _write_readings(tmp_cache, [
            {"patient_id": "abc", "patient_name": "Ana", "value": 100, "trend_arrow": "→"},
            {"patient_id": "xyz", "patient_name": "Juan", "value": 120, "trend_arrow": "→"},
        ])
        resp = client.get("/api/patients")
        data = resp.json()
        assert data["count"] == 2
        ids = {p["patient_id"] for p in data["patients"]}
        assert ids == {"abc", "xyz"}


# ── /api/patients/{patient_id} ───────────────────────────────────────────────

class TestPatientDetailEndpoint:
    def test_404_for_unknown_patient(self, client, tmp_cache):
        resp = client.get("/api/patients/nonexistent")
        assert resp.status_code == 404

    def test_returns_patient_data(self, client, tmp_cache):
        _write_readings(tmp_cache, [
            {"patient_id": "p42", "patient_name": "María", "value": 120, "trend_arrow": "→"},
        ])
        resp = client.get("/api/patients/p42")
        assert resp.status_code == 200
        data = resp.json()
        assert data["patient_id"] == "p42"
        assert data["patient_name"] == "María"

    def test_404_detail_message(self, client, tmp_cache):
        resp = client.get("/api/patients/no-such-id")
        assert "not found" in resp.json()["detail"].lower()


# ── / (dashboard HTML) ───────────────────────────────────────────────────────

class TestDashboardEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_content_type_is_html(self, client):
        resp = client.get("/")
        assert "text/html" in resp.headers["content-type"]

    def test_html_contains_title(self, client):
        resp = client.get("/")
        assert "Monitor de Glucosa Familiar" in resp.text

    def test_html_contains_disclaimer(self, client):
        resp = client.get("/")
        assert "dispositivo médico" in resp.text

    def test_html_contains_fetch_script(self, client):
        resp = client.get("/")
        assert "fetchPatients" in resp.text


# ── _get_color helper ────────────────────────────────────────────────────────

class TestGetColor:
    def test_low_level_returns_red(self):
        assert _get_color("low", "normal") == "red"

    def test_high_level_returns_red(self):
        assert _get_color("high", "normal") == "red"

    def test_falling_fast_trend_returns_red(self):
        assert _get_color("normal", "falling_fast") == "red"

    def test_falling_trend_returns_yellow(self):
        assert _get_color("normal", "falling") == "yellow"

    def test_rising_fast_trend_returns_yellow(self):
        assert _get_color("normal", "rising_fast") == "yellow"

    def test_normal_level_and_trend_returns_green(self):
        assert _get_color("normal", "normal") == "green"

    def test_normal_level_stable_trend_returns_green(self):
        assert _get_color("normal", "stable") == "green"

    def test_normal_level_rising_trend_returns_green(self):
        # "rising" alone (not "rising_fast") → green (approaching but not urgent)
        assert _get_color("normal", "rising") == "green"


# ── Cache file loading behaviour ─────────────────────────────────────────────

class TestLoadAndEnrichCache:
    """Verify file-based cache loading and enrichment."""

    def test_missing_file_yields_empty_cache(self, tmp_path, monkeypatch):
        """When the cache file does not exist the cache must be empty."""
        config = dict(_MINIMAL_CONFIG)
        config["api"] = {"cache_file": str(tmp_path / "nonexistent.json")}
        monkeypatch.setattr(api_module, "_config", config)
        api_module._last_mtime = 0.0

        api_module._load_and_enrich_cache()

        with api_module._cache_lock:
            assert api_module._readings_cache == {}

    def test_valid_file_populates_cache(self, tmp_cache):
        """Readings from the cache file are loaded and enriched."""
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "Ana", "value": 100, "trend_arrow": "→"},
        ])
        api_module._load_and_enrich_cache()

        with api_module._cache_lock:
            assert "p1" in api_module._readings_cache
            entry = api_module._readings_cache["p1"]
        assert entry["glucose_value"] == 100
        assert "level" in entry
        assert "trend_alert" in entry
        assert "color" in entry
        assert "fetched_at" in entry

    def test_unchanged_file_not_reloaded(self, tmp_cache, monkeypatch):
        """A second call with the same mtime must not re-read the file."""
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "Ana", "value": 100, "trend_arrow": "→"},
        ])
        api_module._load_and_enrich_cache()

        # Modify in-memory cache to detect if reload happens
        with api_module._cache_lock:
            api_module._readings_cache["sentinel"] = {"patient_id": "sentinel"}

        # Call again without touching the file — mtime unchanged
        api_module._load_and_enrich_cache()

        with api_module._cache_lock:
            assert "sentinel" in api_module._readings_cache, (
                "Cache was unexpectedly reloaded despite unchanged mtime"
            )

    def test_removed_patient_evicted_on_new_file(self, tmp_cache):
        """A patient absent from the new cache file must be evicted."""
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "A", "value": 100, "trend_arrow": "→"},
            {"patient_id": "p2", "patient_name": "B", "value": 120, "trend_arrow": "→"},
        ])
        api_module._load_and_enrich_cache()

        # Overwrite the file with only p1
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "A", "value": 100, "trend_arrow": "→"},
        ])
        api_module._load_and_enrich_cache()

        with api_module._cache_lock:
            assert "p1" in api_module._readings_cache
            assert "p2" not in api_module._readings_cache, "Ghost patient must be evicted"

    def test_corrupt_json_clears_cache(self, tmp_cache):
        """A file with invalid JSON must result in an empty cache."""
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "A", "value": 100, "trend_arrow": "→"},
        ])
        api_module._load_and_enrich_cache()

        # Corrupt the file
        tmp_cache.write_text("not valid json{{{")
        api_module._last_mtime = 0.0
        api_module._load_and_enrich_cache()

        with api_module._cache_lock:
            assert api_module._readings_cache == {}

